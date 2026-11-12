"""Route the placed AFE board: a two-layer grid router, then the GND planes.

    python3 -I hardware/afe-proto/kicad/route.py        (a Python 3.14 with numpy; pcbnew is added from the system)

Rules (JLC 2-layer, standard): track 0.20 mm (0.30 mm on supply nets), clearance 0.20 mm, via 0.6 / 0.3 mm.
F.Cu carries the signals; B.Cu is the GND plane and takes a signal only where F.Cu is blocked (its cost is 2x).
GND is not routed: every GND pad gets a short stub and a via to the B.Cu plane, and both layers are poured with
GND.  The router works on a 0.05 mm grid; a cell is legal for a net when nothing of another net lies within
clearance + half the track width + half a cell diagonal, so a route the grid accepts holds the real clearance.
KiCad's DRC (check.py P2) is the judge.  Deterministic: same input, same board.

Own work, CC BY-SA 4.0.
"""
import heapq
import math
import os
import sys

sys.path.append('/usr/lib/python3/dist-packages')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np    # noqa: E402
import pcbnew as pcb  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BOARD = os.environ.get('AFE_BOARD') or os.path.join(HERE, 'afe-proto.kicad_pcb')

RES = 0.05                     # mm per cell
CLR = 0.20                     # copper clearance
TOL = RES * math.sqrt(2) / 2   # rasterisation allowance
W_SIG, W_PWR = 0.20, 0.30
VIA_D, VIA_DRILL = 0.60, 0.30
VIA_HOLE_PITCH = 0.60           # via centres at least this far apart (hole to hole 0.30 >= KiCad's 0.25)
EDGE_CLR = 0.30
POWER = {'+3V3A', 'VNEG', '+5V_DUE', '+5V_F', 'LM_CP', 'LM_C1P', 'LM_C1N', 'AWG_VCC', 'AWG_VEE', 'AWG_VPX',
         'AWG_VNX', 'AWG_BV', 'AWG_MV', 'CH1_VCC', 'CH2_VCC', '+3V3_DUE'}
B_COST = 2.0                   # B.Cu cost factor with the no-bottom zones off (and the historical value)
B_COST_ZONED = 3.0             # with zones on: a bottom run outside them should be a short hop, so F.Cu is preferred
ZONE_BLOCKS = ('ch1', 'ch2', 'vmid', 'awg', 'cal')   # layout rule LR-1: no signal trace on B.Cu under these
ZONE_PAD = 0.3
USE_ZONES = os.environ.get('AFE_NOZONES') != '1'     # AFE_NOZONES=1 disables the mechanism (to test lr_check.py)
ESCAPE = 0.8                   # mm of channel reserved straight out from each signal pad, before anything routes
VIA_COST = 30.0                # in cells (1.5 mm of track)
TURN_COST = 2.0
WINDOW = 8.0                   # mm around a connection's endpoints; widened on failure
LAYERS = (pcb.F_Cu, pcb.B_Cu)
DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


def nobottom_rects(board):
    """The no-bottom-track zones as KiCad-mm rectangles (x0, y0, x1, y1): layout.NOBOTTOM (Due coordinates, x right,
    Yup up: KiCad (x, y) = (50 + x, 150 - Yup)) when present, else the courtyards of the parts of ZONE_BLOCKS
    inflated by ZONE_PAD."""
    if not USE_ZONES:
        return []
    import layout
    nb = getattr(layout, 'NOBOTTOM', None)
    if nb is not None:
        return [(50.0 + min(r[0], r[2]), 150.0 - max(r[1], r[3]), 50.0 + max(r[0], r[2]), 150.0 - min(r[1], r[3]))
                for r in nb]
    import design
    blk = {p['ref']: p['block'] for p in design.PARTS}
    out = []
    for f in board.GetFootprints():
        if blk.get(f.GetReference()) in ZONE_BLOCKS:
            f.BuildCourtyardCaches()
            c = f.GetCourtyard(pcb.F_CrtYd).BBox()
            if c.GetWidth():
                out.append((mm(c.GetLeft()) - ZONE_PAD, mm(c.GetTop()) - ZONE_PAD,
                            mm(c.GetRight()) + ZONE_PAD, mm(c.GetBottom()) + ZONE_PAD))
    return out


def mm(v):
    return pcb.ToMM(v)


def _integral(m):
    s = np.zeros((m.shape[0] + 1, m.shape[1] + 1), np.int32)
    s[1:, 1:] = np.cumsum(np.cumsum(m.astype(np.int32), 0), 1)
    return s


def box_any(m, k):
    """True where any cell of the (2k+1)^2 square around it is True (outside the array counts as False)."""
    if k <= 0:
        return m.copy()
    H, W = m.shape
    s = _integral(m)
    y = np.arange(H); x = np.arange(W)
    y1 = np.clip(y - k, 0, H); y2 = np.clip(y + k + 1, 0, H)
    x1 = np.clip(x - k, 0, W); x2 = np.clip(x + k + 1, 0, W)
    tot = s[y2][:, x2] - s[y1][:, x2] - s[y2][:, x1] + s[y1][:, x1]
    return tot > 0


def box_all(m, k):
    """True where every cell of the (2k+1)^2 square is True; a square reaching outside the window is not all."""
    if k <= 0:
        return m.copy()
    out = ~box_any(~m, k)
    out[:k, :] = False; out[-k:, :] = False; out[:, :k] = False; out[:, -k:] = False
    return out


class Grid:
    def __init__(self, board):
        bb = board.GetBoardEdgesBoundingBox()
        self.x0 = math.floor(mm(bb.GetLeft()) / RES) * RES - 1.0
        self.y0 = math.floor(mm(bb.GetTop()) / RES) * RES - 1.0
        self.nx = int(round((mm(bb.GetRight()) - self.x0 + 1.0) / RES)) + 1
        self.ny = int(round((mm(bb.GetBottom()) - self.y0 + 1.0) / RES)) + 1
        n = self.nx * self.ny
        self.halo = [np.zeros(n, np.int32) for _ in LAYERS]     # 0 free, k net k's clearance zone, -1 two nets'
        self.cu = [np.zeros(n, np.int32) for _ in LAYERS]       # exact copper owner
        self.padcu = [np.zeros(n, np.bool_) for _ in LAYERS]    # pad copper (no via there)
        self.viablk = np.zeros(n, np.bool_)                       # within hole-to-hole distance of a via
        self.bx = (mm(bb.GetLeft()), mm(bb.GetRight()), mm(bb.GetTop()), mm(bb.GetBottom()))

    def idx(self, x, y):
        return int(round((y - self.y0) / RES)) * self.nx + int(round((x - self.x0) / RES))

    def xy(self, i):
        return self.x0 + (i % self.nx) * RES, self.y0 + (i // self.nx) * RES

    def disk(self, r):
        k = int(math.ceil(r / RES))
        return np.array([dy * self.nx + dx for dy in range(-k, k + 1) for dx in range(-k, k + 1)
                         if (dx * dx + dy * dy) * RES * RES <= r * r + 1e-12], np.int64)

    def claim(self, L, cells, net):
        """mark cells as net's clearance zone on layer index L"""
        cells = np.unique(cells)
        cells = cells[(cells >= 0) & (cells < self.halo[L].size)]
        v = self.halo[L][cells]
        self.halo[L][cells] = np.where((v == 0) | (v == net), net, -1)

    def rect_cells(self, x1, y1, x2, y2):
        ix1, ix2 = int(math.ceil((x1 - self.x0) / RES - 1e-9)), int(math.floor((x2 - self.x0) / RES + 1e-9))
        iy1, iy2 = int(math.ceil((y1 - self.y0) / RES - 1e-9)), int(math.floor((y2 - self.y0) / RES + 1e-9))
        if ix2 < ix1 or iy2 < iy1:
            return np.zeros(0, np.int64)
        xs = np.arange(ix1, ix2 + 1); ys = np.arange(iy1, iy2 + 1)
        return (ys[:, None] * self.nx + xs[None, :]).ravel()

    def circle_cells(self, cx, cy, r):
        c = self.idx(cx, cy)
        return c + self.disk(r)


def build_obstacles(board, g, netid):
    """Pads, holes and the board edge into the grid."""
    halo_sig = CLR + W_SIG / 2 + TOL
    pads = []
    for f in board.GetFootprints():
        for p in f.Pads():
            n = netid.get(p.GetNetname(), 0)
            nid = n if n else -1                     # an unconnected pad blocks everyone's clearance
            pos = p.GetPosition(); cx, cy = mm(pos.x), mm(pos.y)
            bb = p.GetBoundingBox()
            x1, y1, x2, y2 = mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())
            circ = p.GetShape(pcb.F_Cu) == pcb.PAD_SHAPE_CIRCLE
            on = [L for L, lay in enumerate(LAYERS) if p.IsOnLayer(lay)]
            if p.GetAttribute() == pcb.PAD_ATTRIB_NPTH:
                r = mm(p.GetDrillSize().x) / 2
                for L in (0, 1):
                    g.claim(L, g.circle_cells(cx, cy, r + EDGE_CLR + W_SIG / 2), -1)
                continue
            for L in on:
                if circ:
                    r = (x2 - x1) / 2
                    cu = g.circle_cells(cx, cy, r)
                    hz = g.circle_cells(cx, cy, r + halo_sig)
                else:
                    cu = g.rect_cells(x1, y1, x2, y2)
                    hz = np.unique((cu[:, None] + g.disk(halo_sig)[None, :]).ravel()) if cu.size else cu
                g.claim(L, hz, nid)
                if n:
                    g.cu[L][cu] = n
                g.padcu[L][cu] = True
            if p.GetAttribute() == pcb.PAD_ATTRIB_PTH:      # drill: blocks vias of anything nearby on both layers
                pass
            pads.append((f.GetReference(), p.GetNumber(), n, cx, cy, on, p))
    # board edge
    xl, xr, yt, yb = g.bx
    m = EDGE_CLR + W_SIG / 2 + TOL
    ix = (np.arange(g.nx) * RES + g.x0)[None, :]
    iy = (np.arange(g.ny) * RES + g.y0)[:, None]
    out = ((ix < xl + m) | (ix > xr - m) | (iy < yt + m) | (iy > yb - m)).ravel()
    for L in (0, 1):
        g.halo[L][out] = -1
    return pads


class Router:
    def __init__(self, board, g, netid):
        self.b, self.g, self.netid = board, g, netid
        self.names = {v: k for k, v in netid.items()}
        self.via_cache = {}
        self.zone = np.zeros((g.ny, g.nx), np.bool_)       # B.Cu cells where a signal track may not go (LR-1)
        for (x0, y0, x1, y1) in nobottom_rects(board):      # grown by half the widest track: its edge counts too
            x0 -= W_PWR / 2; y0 -= W_PWR / 2; x1 += W_PWR / 2; y1 += W_PWR / 2
            ix0 = max(int(math.floor((x0 - g.x0) / RES)), 0); ix1 = min(int(math.ceil((x1 - g.x0) / RES)), g.nx - 1)
            iy0 = max(int(math.floor((y0 - g.y0) / RES)), 0); iy1 = min(int(math.ceil((y1 - g.y0) / RES)), g.ny - 1)
            self.zone[iy0:iy1 + 1, ix0:ix1 + 1] = True
        self.track_n = 0; self.via_n = 0
        self.netinfo = {n.GetNetname(): n for n in board.GetNetInfo().NetsByName().values()} \
            if hasattr(board.GetNetInfo(), 'NetsByName') else None

    narrow = False      # set while retrying a supply connection at signal width

    def width(self, net):
        return W_PWR if (self.names[net].lstrip('/') in POWER and not self.narrow) else W_SIG

    def extra(self, net):
        """extra disk to check for a wider track"""
        w = self.width(net)
        return self.g.disk((w - W_SIG) / 2) if w > W_SIG else np.zeros(1, np.int64)

    def legal(self, L, i, net, ext):
        h = self.g.halo[L]
        if ext.size == 1:
            v = h[i]
            return v == 0 or v == net
        v = h[i + ext]
        return bool(np.all((v == 0) | (v == net)))

    def via_ok(self, i, net):
        key = (i, net)
        if key in self.via_cache:
            return self.via_cache[key]
        g = self.g
        d = self.vdisk
        ok = True
        for L in (0, 1):
            v = g.halo[L][i + d]
            if not np.all((v == 0) | (v == net)) or np.any(g.padcu[L][i + self.vpad]):
                ok = False; break
        self.via_cache[key] = ok
        return ok

    def search(self, starts, targets, net, box, gnd=False):
        """A* from start cells [(L, i)] to target cells (set of (L, i)), or, gnd, to the first cell a via may take.
        Legality and via masks are computed once for the window (numpy), the search runs over plain bytes."""
        g = self.g
        nx = g.nx
        ix1 = max(int((box[0] - g.x0) / RES), 1); iy1 = max(int((box[1] - g.y0) / RES), 1)
        ix2 = min(int((box[2] - g.x0) / RES), nx - 2); iy2 = min(int((box[3] - g.y0) / RES), g.ny - 2)
        W, H = ix2 - ix1 + 1, iy2 - iy1 + 1
        kw = int(round((self.width(net) - W_SIG) / 2 / RES))
        kv = int(math.ceil((VIA_D / 2 + CLR + TOL - W_SIG / 2) / RES))
        kp = int(math.ceil((VIA_D / 2 + 0.05) / RES))
        leg, via = [], None
        gndnet = self.names[net] == '/GND'
        bcost = B_COST_ZONED if self.zone.any() else B_COST
        for L in (0, 1):
            h = g.halo[L].reshape(g.ny, nx)[iy1:iy2 + 1, ix1:ix2 + 1]
            ok = (h == 0) | (h == net)
            lg = box_all(ok, kw) if kw else ok
            if L == 1 and not gndnet:
                # LR-1: no signal track on B.Cu inside a zone; the via mask below uses the unrestricted `ok`
                lg = lg & ~self.zone[iy1:iy2 + 1, ix1:ix2 + 1]
            leg.append(bytes(lg.ravel().astype(np.uint8)))
            pc = g.padcu[L].reshape(g.ny, nx)[iy1:iy2 + 1, ix1:ix2 + 1]
            v = box_all(ok, kv) & ~box_any(pc, kp)
            via = v if via is None else via & v
        via &= ~g.viablk.reshape(g.ny, nx)[iy1:iy2 + 1, ix1:ix2 + 1]
        viab = bytes(via.ravel().astype(np.uint8))

        def loc(i):
            x, y = i % nx - ix1, i // nx - iy1
            return y * W + x if 0 <= x < W and 0 <= y < H else -1
        tl = set()
        for (L, i) in targets:
            li = loc(i)
            if li >= 0:
                tl.add((L, li))
        if targets and not tl:
            return None
        if tl:
            txs = [t[1] % W for t in tl]; tys = [t[1] // W for t in tl]
            bx1, bx2, by1, by2 = min(txs), max(txs), min(tys), max(tys)

            def hf(li):
                x, y = li % W, li // W
                dx = bx1 - x if x < bx1 else (x - bx2 if x > bx2 else 0)
                dy = by1 - y if y < by1 else (y - by2 if y > by2 else 0)
                return 1.2 * (max(dx, dy) + 0.414 * min(dx, dy))
        else:
            def hf(li):
                return 0.0
        nb = [(1, 1.0, 0), (-1, 1.0, 1), (W, 1.0, 2), (-W, 1.0, 3),
              (W + 1, 1.414, 4), (W - 1, 1.414, 5), (-W + 1, 1.414, 6), (-W - 1, 1.414, 7)]
        dxs = [1, -1, 0, 0, 1, -1, 1, -1]
        best = {}; came = {}; dirn = {}
        q = []
        for (L, i) in starts:
            li = loc(i)
            if li < 0:
                continue
            key = L * W * H + li
            best[key] = 0.0; came[key] = -1; dirn[key] = -1
            heapq.heappush(q, (hf(li), 0.0, key))
        WH = W * H
        pops = 0
        cap = min(1500000, 3 * W * H)          # a failing search costs at most a few visits per window cell
        while q and pops < cap:
            f, gc, key = heapq.heappop(q)
            if gc > best.get(key, 1e18) + 1e-9:
                continue
            pops += 1
            L, li = divmod(key, WH)
            if (tl and (L, li) in tl) or (gnd and L == 0 and gc > 0 and viab[li]):
                out = []
                k = key
                while k != -1:
                    LL, ll = divmod(k, WH)
                    out.append((LL, (ll // W + iy1) * nx + (ll % W + ix1)))
                    k = came[k]
                return out[::-1]
            x = li % W
            lb = leg[L]
            mult = bcost if L else 1.0
            d0 = dirn[key]
            for k, (off, c, dk) in enumerate(nb):
                xx = x + dxs[k]
                if xx < 0 or xx >= W:
                    continue
                lj = li + off
                if lj < 0 or lj >= WH or not lb[lj]:
                    continue
                ng = gc + c * mult + (TURN_COST if (d0 != -1 and d0 != dk) else 0.0)
                k2 = L * WH + lj
                if ng < best.get(k2, 1e18) - 1e-9:
                    best[k2] = ng; came[k2] = key; dirn[k2] = dk
                    heapq.heappush(q, (ng + hf(lj), ng, k2))
            if not gnd and viab[li]:
                k2 = (1 - L) * WH + li
                ng = gc + VIA_COST
                if ng < best.get(k2, 1e18) - 1e-9:
                    best[k2] = ng; came[k2] = key; dirn[k2] = -1
                    heapq.heappush(q, (ng + hf(li), ng, k2))
        return None

    # ------------------------------------------------------------------ committing a path
    def paint(self, net, path, w, gnd_via):
        """paint a route into the grid (copper and clearance zone)"""
        g = self.g
        rcu = g.disk(w / 2)
        rhz = g.disk(w / 2 + CLR + W_SIG / 2 + TOL)
        vcu = g.disk(VIA_D / 2)
        vhz = g.disk(VIA_D / 2 + CLR + W_SIG / 2 + TOL)
        for L, run, vias in split(path, gnd_via):
            if len(run) > 1:
                cells = np.array(run, np.int64)
                g.claim(L, (cells[:, None] + rhz[None, :]).ravel(), net)
                g.cu[L][(cells[:, None] + rcu[None, :]).ravel()] = net
            for v in vias:
                for LL in (0, 1):
                    g.claim(LL, v + vhz, net); g.cu[LL][v + vcu] = net
                g.viablk[v + g.disk(VIA_HOLE_PITCH)] = True

    def commit(self, path, net, gnd_via=False):
        w = self.width(net)
        self.routes.append((net, path, w, gnd_via))
        self.paint(net, path, w, gnd_via)


def split(path, gnd_via):
    """[(layer, [cells of one run], [via cells after the run])]"""
    out = []
    cur = [path[0][1]]; L = path[0][0]
    for a, b in zip(path, path[1:]):
        if a[0] != b[0]:
            out.append((L, cur, [a[1]])); cur = [b[1]]; L = b[0]
        else:
            cur.append(b[1])
    out.append((L, cur, [path[-1][1]] if gnd_via else []))
    return out


def write_board(board, g, names, routes):
    """turn the kept routes into KiCad tracks and vias"""
    nt = nv = 0
    for net, path, w, gnd_via in routes:
        ni = board.FindNet(names[net])
        for L, run, vias in split(path, gnd_via):
            if len(run) > 1:
                corners = [run[0]]
                for k in range(1, len(run) - 1):
                    if (run[k] - run[k - 1]) != (run[k + 1] - run[k]):
                        corners.append(run[k])
                corners.append(run[-1])
                for a, b in zip(corners, corners[1:]):
                    xa, ya = g.xy(a); xb, yb = g.xy(b)
                    t = pcb.PCB_TRACK(board)
                    t.SetStart(pcb.VECTOR2I(pcb.FromMM(xa), pcb.FromMM(ya)))
                    t.SetEnd(pcb.VECTOR2I(pcb.FromMM(xb), pcb.FromMM(yb)))
                    t.SetWidth(pcb.FromMM(w)); t.SetLayer(LAYERS[L]); t.SetNet(ni)
                    board.Add(t); nt += 1
            for v in vias:
                x, y = g.xy(v)
                via = pcb.PCB_VIA(board)
                via.SetPosition(pcb.VECTOR2I(pcb.FromMM(x), pcb.FromMM(y)))
                via.SetWidth(pcb.FromMM(VIA_D)); via.SetDrill(pcb.FromMM(VIA_DRILL)); via.SetNet(ni)
                board.Add(via); nv += 1
    return nt, nv


def pad_cells(g, net, pad):
    """every grid cell of the pad's own copper, per layer (a route may start or end anywhere on it)"""
    ref, num, n, cx, cy, on, p = pad
    bb = p.GetBoundingBox()
    out = []
    for L in on:
        cells = g.rect_cells(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))
        out += [(L, int(c)) for c in cells[g.cu[L][cells] == net]]
    return out


class Job:
    """The whole routing state: the grid is rebuilt from the pads, the escape channels and the kept routes."""

    def __init__(self, board):
        self.board = board
        self.netid = {}
        for name in sorted({p.GetNetname() for f in board.GetFootprints() for p in f.Pads()}):
            if name and not name.startswith('unconnected-'):
                self.netid[name] = len(self.netid) + 1
        self.names = {v: k for k, v in self.netid.items()}
        self.gnd = self.netid.get('/GND')
        self.routes = []
        self.fixed = []          # hand pre-routes (layout.PREROUTE / PREVIA): painted first, never ripped up
        self.g = Grid(board)
        self.fixed = self.preroutes()
        self.rebuild()
        self.bynet = {}
        for pd in self.pads:
            if pd[2]:
                self.bynet.setdefault(pd[2], []).append(pd)

    def rebuild(self):
        g = Grid(self.board)
        self.pads = build_obstacles(self.board, g, self.netid)
        self.escapes(g)
        self.g = g
        self.r = Router(self.board, g, self.netid)
        self.r.routes = self.routes
        for net, path, w, gv in self.fixed + self.routes:
            self.r.paint(net, path, w, gv)

    def preroutes(self):
        """layout.PREROUTE: (net, 'F' | 'B', [(x, Yup), ...], width) polylines in Due coordinates; layout.PREVIA:
        (net, x, Yup).  Turned into grid paths on this job's grid; the router treats them as copper of their net."""
        import layout
        g = self.g
        out = []
        cell = lambda x, y: g.idx(50.0 + x, 150.0 - y)

        def line(a, b):
            ia, ib = cell(*a), cell(*b)
            ax, ay, bx, by = ia % g.nx, ia // g.nx, ib % g.nx, ib // g.nx
            n = max(abs(bx - ax), abs(by - ay), 1)
            return [int(round(ay + (by - ay) * k / n)) * g.nx + int(round(ax + (bx - ax) * k / n)) for k in range(n + 1)]
        zr = nobottom_rects(self.board)

        def resolve(p):
            """a waypoint is (x, Yup) or ('pad', ref, number[, dx, dy]): the centre of that pad (plus an offset)"""
            if isinstance(p[0], str):
                f = self.board.FindFootprintByReference(p[1])
                pd = f.FindPadByNumber(str(p[2]))
                q = pd.GetPosition()
                return (mm(q.x) - 50.0 + (p[3] if len(p) > 3 else 0.0), 150.0 - mm(q.y) + (p[4] if len(p) > 4 else 0.0))
            return p
        for net, lay, pts, w in getattr(layout, 'PREROUTE', []):
            pts = [resolve(p) for p in pts]
            if lay != 'F' and net != 'GND':
                for a, b in zip(pts, pts[1:]):
                    if any(z[0] <= 50.0 + a[0] + (b[0] - a[0]) * t / 40 <= z[2] and
                           z[1] <= 150.0 - (a[1] + (b[1] - a[1]) * t / 40) <= z[3] for z in zr for t in range(41)):
                        print(f'WARNING: B-layer pre-route of {net} enters a no-bottom zone at Due {a}-{b} '
                              f'(kept as drawn)', flush=True)
                        break
            L = 0 if lay == 'F' else 1
            cells = []
            for a, b in zip(pts, pts[1:]):
                seg = line(a, b)
                cells += seg if not cells else seg[1:]
            out.append((self.netid['/' + net], [(L, c) for c in cells], w, False))
        for net, x, y in getattr(layout, 'PREVIA', []):
            c = cell(x, y)
            out.append((self.netid['/' + net], [(0, c), (1, c)], W_SIG, False))
        return out

    def escapes(self, g):
        """a pad-wide strip ESCAPE long straight out of every SMD signal pad (away from its part's centre, along the
        pad's long side), claimed for the pad's net with its clearance, so no via or other net closes a fine-pitch
        pin in before its own net routes"""
        hz = CLR + W_SIG / 2 + TOL
        for f in self.board.GetFootprints():
            fc = f.GetPosition()
            for p in f.Pads():
                n = self.netid.get(p.GetNetname(), 0)
                if not n or n == self.gnd or p.GetAttribute() != pcb.PAD_ATTRIB_SMD:
                    continue
                bb = p.GetBoundingBox()
                x1, y1, x2, y2 = mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                w = W_SIG / 2
                if (x2 - x1) >= (y2 - y1):
                    rx = (x2, cy - w, x2 + ESCAPE, cy + w) if cx >= mm(fc.x) else (x1 - ESCAPE, cy - w, x1, cy + w)
                else:
                    rx = (cx - w, y2, cx + w, y2 + ESCAPE) if cy >= mm(fc.y) else (cx - w, y1 - ESCAPE, cx + w, y1)
                cells = g.rect_cells(*rx)
                if cells.size:
                    g.claim(0, np.unique((cells[:, None] + g.disk(hz)[None, :]).ravel()), n)

    def span(self, n):
        xs = [p[3] for p in self.bynet[n]]; ys = [p[4] for p in self.bynet[n]]
        return (max(xs) - min(xs)) + (max(ys) - min(ys))

    def route_net(self, n):
        """route net n on the current grid; returns its failures [(net name, ref, pad)]"""
        g, r = self.g, self.r
        failed = []
        if n == self.gnd:
            for pd in self.bynet[n]:
                if 1 in pd[5]:
                    continue                    # through-hole: on the plane already
                starts = pad_cells(g, n, pd)
                path = None
                for win in (2.0, 5.0):
                    box = (pd[3] - win, pd[4] - win, pd[3] + win, pd[4] + win)
                    path = r.search(starts, set(), n, box, gnd=True) if starts else None
                    if path:
                        break
                if path:
                    r.commit(path, n, gnd_via=True)
                else:
                    failed.append(('/GND', pd[0], pd[1]))
            return failed
        pl = sorted(self.bynet[n], key=lambda p: (p[3], p[4]))
        cx = sum(p[3] for p in pl) / len(pl); cy = sum(p[4] for p in pl) / len(pl)
        first = min(pl, key=lambda p: (p[3] - cx) ** 2 + (p[4] - cy) ** 2)
        own = [set(path) for (m, path, w, gv) in self.fixed + self.routes if m == n]   # copper already down

        def close(t):
            # add every piece of this net's existing copper that touches the tree (8-neighbour or the same cell),
            # repeatedly: a pre-route counts as connected only through copper that reaches the tree
            nb = (0, 1, -1, g.nx, -g.nx, g.nx + 1, g.nx - 1, -g.nx + 1, -g.nx - 1)
            grown = True
            while grown:
                grown = False
                for s in own:
                    if s and not s <= t and any((L, i + d) in t for (L, i) in s for d in nb):
                        t |= s; grown = True
            return t
        tree = close(set(pad_cells(g, n, first)))
        tree_pts = [(first[3], first[4])]
        rest = [p for p in pl if p is not first]
        power = self.names[n].lstrip('/') in POWER
        while rest:
            nxt = min(rest, key=lambda p: min((p[3] - a) ** 2 + (p[4] - b) ** 2 for a, b in tree_pts))
            rest.remove(nxt)
            starts = pad_cells(g, n, nxt)
            near = min(tree_pts, key=lambda q: (q[0] - nxt[3]) ** 2 + (q[1] - nxt[4]) ** 2)
            path = None
            tries = [(False, WINDOW), (False, 2.5 * WINDOW)]
            if power:
                tries += [(True, 2.5 * WINDOW)]     # neck down to signal width
            for narrow, win in tries:
                r.narrow = narrow
                box = (min(nxt[3], near[0]) - win, min(nxt[4], near[1]) - win,
                       max(nxt[3], near[0]) + win, max(nxt[4], near[1]) + win)
                tgt = {t for t in tree if box[0] <= g.xy(t[1])[0] <= box[2] and box[1] <= g.xy(t[1])[1] <= box[3]}
                if not starts or not tgt:
                    continue
                path = r.search(starts, tgt, n, box)
                if path:
                    break
            if not path:
                r.narrow = False
                failed.append((self.names[n], nxt[0], nxt[1]))
                continue
            r.commit(path, n)
            r.narrow = False
            tree.update(path); tree.update(starts)
            tree = close(tree)
            tree_pts.append((nxt[3], nxt[4]))
            for (L, i) in path[::8]:
                tree_pts.append(g.xy(i))
        # a pad that failed early may have been joined since (by a pre-route that the tree reached later)
        nb = (0, 1, -1, g.nx, -g.nx)
        byref = {(p[0], p[1]): p for p in pl}
        still = []
        for f in failed:
            pd = byref.get((f[1], f[2]))
            cells = pad_cells(g, n, pd) if pd else []
            if not any((L, i + d) in tree for (L, i) in cells for d in nb):
                still.append(f)
        return still


EARLY = ('VREF', '+3V3A', 'VNEG', 'AWG_BNC')      # board-crossing nets: routed first, while the lanes are free


def route(board):
    """GND vias, then supplies, then signals (shortest first); then rip-up and reroute of whatever failed."""
    import time
    t0 = time.time()
    job = Job(board)
    nets = [job.gnd] + sorted((n for n in job.bynet if n != job.gnd and len(job.bynet[n]) > 1),
                              key=lambda n: (job.names[n].lstrip('/') not in EARLY, job.names[n].lstrip('/') not in POWER, job.span(n), job.names[n]))
    fails = {}
    for k, n in enumerate(nets):
        tn = time.time()
        f = job.route_net(n)
        if time.time() - tn > 5 or f:
            print(f'[{time.time() - t0:7.1f}s] {k + 1}/{len(nets)} {job.names[n]}: {time.time() - tn:.1f} s, '
                  f'{len(f)} failed', flush=True)
        if f:
            fails[n] = f
    print(f'[{time.time() - t0:7.1f}s] first pass: {sum(map(len, fails.values()))} connections not routed', flush=True)

    # rip-up and reroute: for a failed net, tear out the nets whose copper crowds its pads' box, route the failed
    # net first and the torn-out ones after; keep the change only if the failures among them go down
    for it in range(int(os.environ.get('RIPUP_ROUNDS', '6'))):
        if not fails:
            break
        before_total = sum(map(len, fails.values()))
        for n in sorted(fails, key=lambda k: job.names[k]):
            if n not in fails:
                continue
            g = job.g
            pts = [(p[3], p[4]) for p in job.bynet[n]]
            grow = 1.5 + it
            x1 = min(p[0] for p in pts) - grow; x2 = max(p[0] for p in pts) + grow
            y1 = min(p[1] for p in pts) - grow; y2 = max(p[1] for p in pts) + grow
            score = {}
            for (m, path, w, gv) in job.routes:
                if m in (n,):
                    continue
                c = sum(1 for (L, i) in path if x1 <= g.xy(i)[0] <= x2 and y1 <= g.xy(i)[1] <= y2)
                if c:
                    score[m] = score.get(m, 0) + c
            victims = [m for m, _ in sorted(score.items(), key=lambda kv: -kv[1])[:4 + it]]
            group = [n] + victims
            old_routes = list(job.routes)
            old_f = {m: fails.get(m, []) for m in group}
            job.routes[:] = [rt for rt in job.routes if rt[0] not in group]
            job.rebuild()
            new_f = {}
            for m in group:
                f = job.route_net(m)
                if f:
                    new_f[m] = f
            if sum(map(len, new_f.values())) < sum(map(len, old_f.values())):
                for m in group:
                    fails.pop(m, None)
                fails.update(new_f)
            else:
                job.routes[:] = old_routes
                job.rebuild()
        after = sum(map(len, fails.values()))
        print(f'[{time.time() - t0:7.1f}s] rip-up round {it + 1}: {after} connections not routed', flush=True)
        if after >= before_total and it >= 2:
            break
    failed = [x for f in fails.values() for x in f]
    return job, failed


def pour(board):
    """GND on both layers over the whole board, filled."""
    bb = board.GetBoardEdgesBoundingBox()
    gnd = board.FindNet('/GND')
    zones = []
    for lay, prio in ((pcb.B_Cu, 0), (pcb.F_Cu, 0)):
        z = pcb.ZONE(board)
        z.SetLayer(lay); z.SetNet(gnd); z.SetAssignedPriority(prio)
        o = z.Outline(); o.NewOutline()
        for x, y in ((bb.GetLeft(), bb.GetTop()), (bb.GetRight(), bb.GetTop()),
                     (bb.GetRight(), bb.GetBottom()), (bb.GetLeft(), bb.GetBottom())):
            o.Append(x, y)
        z.SetLocalClearance(pcb.FromMM(0.25)); z.SetMinThickness(pcb.FromMM(0.2))
        z.SetPadConnection(pcb.ZONE_CONNECTION_FULL)   # solid to pads: the small fine-pitch GND pads starve on spokes
        z.SetThermalReliefGap(pcb.FromMM(0.25)); z.SetThermalReliefSpokeWidth(pcb.FromMM(0.3))
        z.SetIslandRemovalMode(pcb.ISLAND_REMOVAL_MODE_ALWAYS)
        board.Add(z); zones.append(z)
    pcb.ZONE_FILLER(board).Fill(board.Zones())


def main():
    board = pcb.LoadBoard(BOARD)
    if len(board.GetTracks()) or len(board.Zones()):
        raise SystemExit('the board already carries copper: run build_pcb.py first (route.py routes a placed board)')
    ds = board.GetDesignSettings()
    ds.m_TrackMinWidth = pcb.FromMM(0.15); ds.m_MinClearance = pcb.FromMM(CLR)
    ds.m_ViasMinSize = pcb.FromMM(0.5); ds.m_MinThroughDrill = pcb.FromMM(0.3)
    job, failed = route(board)
    nt, nv = write_board(board, job.g, job.names, job.fixed + job.routes)
    pour(board)
    board.Save(BOARD)
    print(f'saved: {nt} track segments, {nv} vias, {len(failed)} connections not routed')
    for f in failed:
        print('  unrouted:', *f)
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
