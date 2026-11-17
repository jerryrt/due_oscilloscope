"""PathFinder (negotiated congestion) router for a scratch KiCad 10 board: one copper layer, 0.1 mm grid, pcbnew from the PCB image.

USAGE (in the image, cwd = this folder):   [PF_CFG=<module>] python3 pf.py BOARD.kicad_pcb OUT_SPEC.py [ITER] [SECONDS]
    BOARD      a .kicad_pcb that already carries the copper to keep (every track and via on it is FIXED), e.g. spliced by hr.py
    OUT_SPEC   a Python file with ROUTES = [(net, 'F', [(x, y), ...], width)] and VIAS = [(net, x, y)] in user mm (hr.py splices it back)
    ITER, SECONDS   negotiation rounds (default 25) and wall-clock stop (default 900 s)
    PF_CFG     the board's data module (default pf_cfg_afe2, next to this file): frame origin, grid box, edge box, clearances, high-impedance and
               sensitive nets, digital nets and the courtyards they avoid, supply stars with their consumer groups, Kelvin nets. pf.py itself
               knows no board: another board writes its own module with the same names.

WHAT IT DOES: every net with pads not yet joined by the fixed copper is a job (a supply star or Kelvin branch is a separate pseudo net that
may touch only its star / source pads). Each round every job is ripped up and re-routed by A* (8 directions) with a soft penalty on cells
within reach of other jobs' copper that grows each round, plus a history cost on cells that stayed in conflict; fixed copper, pads of other
nets, the edge box, the sensitive-net keep-away and the DIGITAL courtyards are hard blocks. A GND SMD pad that the rule (greedy, a via of its own
within 3 mm) leaves without one gets a stub and a via first, as fixed copper.

OUTPUT: the spec file, and on stdout one line per round (jobs routed, jobs still conflicting), then
    METRIC conflict_segments N distinct_clusters K     N = pairs of segments (different jobs, or a job and fixed copper) closer than the clearance
                                                        (0.37 mm centre to centre, 0.9 to a hi-Z track); K = those pairs grouped within 2 mm.
                                                        K is the number of distinct places where a bridge, hop or move is still needed.
    CLUSTER (x, y) [jobs]                              one per distinct place.
LIMITS: single layer (no vias but the GND ones), one track width, 45-degree grid, no length rules (fix A0/A1, outputs and feedback nodes first), the
count is geometric, so verify the spliced board with KiCad DRC (tracks_crossing, shorting_items, clearance, unconnected_items)."""
import sys, math, heapq, time, json, os, importlib
sys.path.append('/usr/lib/python3/dist-packages')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pcbnew

cfg = importlib.import_module(os.environ.get('PF_CFG', 'pf_cfg_afe2'))      # all board knowledge lives in this module
BOARD, OUT = sys.argv[1], sys.argv[2]
ITER = int(sys.argv[3]) if len(sys.argv) > 3 else 25
SECS = float(sys.argv[4]) if len(sys.argv) > 4 else 900
RES = 0.1
X0, Y0, X1, Y1 = cfg.GRID
NX, NY = int(round((X1 - X0) / RES)), int(round((Y1 - Y0) / RES))
INFL, INFL_PAD, INFL_HIZ = cfg.INFL, cfg.INFL_PAD, cfg.INFL_HIZ
ORIGIN_X, ORIGIN_Y = cfg.ORIGIN_X, cfg.ORIGIN_Y
mm = pcbnew.ToMM
HIZ, SENS, DIGITAL, STAR, GROUPS = cfg.HIZ, cfg.SENS, cfg.DIGITAL, cfg.STAR, cfg.GROUPS
KELVIN = cfg.KELVIN
GND = cfg.GND_NET

b = pcbnew.LoadBoard(BOARD)
ANALOG_BOX = {}                       # courtyard boxes (user mm) of the parts the DIGITAL nets keep out of
for _f in b.GetFootprints():
    if _f.GetReference() in set(cfg.ANALOG_REFS):
        try:
            _bb = _f.GetCourtyard(pcbnew.F_CrtYd).BBox()
        except Exception:
            _bb = _f.GetBoundingBox()
        ANALOG_BOX[_f.GetReference()] = (mm(_bb.GetX()) - ORIGIN_X, ORIGIN_Y - mm(_bb.GetBottom()), mm(_bb.GetRight()) - ORIGIN_X, ORIGIN_Y - mm(_bb.GetY()))


def cx(v): return mm(v) - ORIGIN_X
def cy(v): return ORIGIN_Y - mm(v)


def cell(x, y): return int(round((x - X0) / RES)), int(round((y - Y0) / RES))
def xy(i, j): return X0 + i * RES, Y0 + j * RES


def rect_mask(x0, y0, x1, y1, m):
    i0, j0 = cell(x0 - m, y0 - m); i1, j1 = cell(x1 + m, y1 + m)
    i0, j0 = max(i0, 0), max(j0, 0); i1, j1 = min(i1, NX - 1), min(j1, NY - 1)
    return i0, j0, i1, j1


def stamp_rect(g, x0, y0, x1, y1, m, val=True):
    i0, j0, i1, j1 = rect_mask(x0, y0, x1, y1, m)
    if i0 <= i1 and j0 <= j1:
        ii, jj = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1), indexing='ij')
        gx_, gy_ = X0 + ii * RES, Y0 + jj * RES
        dx = np.maximum(np.maximum(x0 - gx_, gx_ - x1), 0); dy = np.maximum(np.maximum(y0 - gy_, gy_ - y1), 0)
        g[i0:i1 + 1, j0:j1 + 1] |= np.hypot(dx, dy) <= m


_DISK = {}
def disk(m):
    k = round(m, 3)
    if k not in _DISK:
        r = int(math.ceil((m + RES * 0.35) / RES))
        ii, jj = np.meshgrid(np.arange(-r, r + 1), np.arange(-r, r + 1), indexing='ij')
        sel = np.hypot(ii, jj) * RES <= m + RES * 0.35
        _DISK[k] = np.stack([ii[sel], jj[sel]], 1)
    return _DISK[k]


def stamp_cells(g, cells, m):
    c = np.asarray(cells, int).reshape(-1, 2)
    off = disk(m)
    idx = (c[:, None, :] + off[None, :, :]).reshape(-1, 2)
    ok = (idx[:, 0] >= 0) & (idx[:, 0] < NX) & (idx[:, 1] >= 0) & (idx[:, 1] < NY)
    idx = idx[ok]
    g[idx[:, 0], idx[:, 1]] = True


def stamp_seg(g, ax, ay, bx, by, m):
    n = max(2, int(math.hypot(bx - ax, by - ay) / (RES / 2)) + 1)
    pts = [cell(ax + (bx - ax) * t, ay + (by - ay) * t) for t in np.linspace(0, 1, n)]
    stamp_cells(g, sorted(set(pts)), m)


# ------------------------------------------------------------------------------------------------ read the board
pads = []          # dict(ref, pin, net, bb)
for f in b.GetFootprints():
    for p in f.Pads():
        bb = p.GetBoundingBox()
        pads.append(dict(ref=f.GetReference(), pin=p.GetNumber(), net=p.GetNetname(), bb=(cx(bb.GetX()), cy(bb.GetBottom()), cx(bb.GetRight()), cy(bb.GetY())),
                         th=(p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD)))
key = {(p['ref'], p['pin']): p for p in pads}
tracks = []        # (net, ax, ay, bx, by, w)
vias = []          # (net, x, y, d)
for t in b.GetTracks():
    if t.GetClass() == 'PCB_VIA':
        vias.append((t.GetNetname(), cx(t.GetPosition().x), cy(t.GetPosition().y), mm(t.GetWidth(pcbnew.F_Cu))))
    else:
        tracks.append((t.GetNetname(), cx(t.GetStart().x), cy(t.GetStart().y), cx(t.GetEnd().x), cy(t.GetEnd().y), mm(t.GetWidth())))

names = sorted({p['net'] for p in pads if p['net']} | {t[0] for t in tracks})
nid = {n: i for i, n in enumerate(names)}

# ------------------------------------------------------------------------------------------------ fixed obstacles per net
net_mask = {n: np.zeros((NX, NY), bool) for n in names}
for p in pads:
    if p['net']:
        stamp_rect(net_mask[p['net']], *p['bb'], INFL_PAD)
for n, ax, ay, bx, by, w in tracks:
    stamp_seg(net_mask[n], ax, ay, bx, by, INFL_HIZ if n in HIZ else INFL)
for n, x, y, d in vias:
    stamp_seg(net_mask[n], x, y, x, y, d / 2 + INFL - 0.1)
for p in pads:                                           # an unconnected pad (no net) is an obstacle for everybody
    if not p['net']:
        for n in names:
            pass
static = np.zeros((NX, NY), bool)
for p in pads:
    if not p['net']:
        stamp_rect(static, *p['bb'], INFL_PAD)
# board edge, far-edge band
ex0, ey0, ex1, ey1 = cfg.EDGE_BOX
i, j = np.meshgrid(np.arange(NX), np.arange(NY), indexing='ij')
gx, gy = X0 + i * RES, Y0 + j * RES
static |= (gx < ex0) | (gx > ex1) | (gy < ey0) | (gy > ey1)
total = np.zeros((NX, NY), np.int16)
for n in names:
    total += net_mask[n]

# fixed copper connectivity: which pads are already joined
parent = {}
def find(a):
    while parent.setdefault(a, a) != a:
        parent[a] = parent[parent[a]]; a = parent[a]
    return a
def union(a, c): parent[find(a)] = find(c)
for n, ax, ay, bx, by, w in tracks:
    for k, p in key.items():
        if p['net'] != n: continue
        x0, y0, x1, y1 = p['bb']
        for (qx, qy) in ((ax, ay), (bx, by)):
            if x0 - w / 2 - 0.02 <= qx <= x1 + w / 2 + 0.02 and y0 - w / 2 - 0.02 <= qy <= y1 + w / 2 + 0.02:
                union(('pad',) + k, ('t', n, round(ax, 3), round(ay, 3), round(bx, 3), round(by, 3)))
    for m, a2, c2, d2, e2, w2 in tracks:
        if m != n: continue
        for q in ((ax, ay), (bx, by)):
            dxx, dyy = d2 - a2, e2 - c2; LL = dxx * dxx + dyy * dyy
            tt = 0 if LL == 0 else max(0, min(1, ((q[0] - a2) * dxx + (q[1] - c2) * dyy) / LL))
            if math.hypot(q[0] - a2 - tt * dxx, q[1] - c2 - tt * dyy) < 0.02:       # end on the other track's body (a T junction) joins too
                union(('t', n, round(ax, 3), round(ay, 3), round(bx, 3), round(by, 3)), ('t', m, round(a2, 3), round(c2, 3), round(d2, 3), round(e2, 3)))
    for m, vx, vy, vd in vias:
        if m == n and (math.hypot(ax - vx, ay - vy) < 0.05 or math.hypot(bx - vx, by - vy) < 0.05):
            union(('t', n, round(ax, 3), round(ay, 3), round(bx, 3), round(by, 3)), ('v', m, vx, vy))

# ------------------------------------------------------------------------------------------------ nets and terminals
jobs = []          # dict(name, own (net whose fixed mask is the job's own), comps: list of list of pad keys, goals alt)
def comps_of(padkeys):
    c = {}
    for k in padkeys:
        c.setdefault(find(('pad',) + k), []).append(k)
    return list(c.values())

bynet = {}
for p in pads:
    if p['net'] and p['net'] not in cfg.SKIP_NETS:
        bynet.setdefault(p['net'], []).append((p['ref'], p['pin']))
for n, ks in bynet.items():
    if n in STAR or n in KELVIN:
        continue
    comps = comps_of(ks)
    if len(comps) > 1:
        jobs.append(dict(name=n, own=n, comps=comps, star=None))
for n, groups in GROUPS.items():
    stars = [tuple(s.split('.')) for s in STAR[n]]
    jobs.append(dict(name=n + '#star', own=n, comps=[[k] for k in stars if k in key], star=None))
    for gname, gp in groups.items():
        ks = [tuple(s.split('.')) for s in gp if tuple(s.split('.')) in key and key[tuple(s.split('.'))]['net'] == n]
        if not ks: continue
        jobs.append(dict(name=n + '#' + gname, own=n, comps=[ks], star=stars))
for kn, kspec in KELVIN.items():
    ksrc = [tuple(s.split('.')) for s in kspec['src']]
    jobs.append(dict(name=kn + '#src', own=kn, comps=[[k] for k in ksrc if k in key], star=None))
    for gi, gp in enumerate(kspec['groups']):
        ks = [tuple(s.split('.')) for s in gp if tuple(s.split('.')) in key and key[tuple(s.split('.'))]['net'] == kn]
        if ks:
            jobs.append(dict(name='%s#%d' % (kn, gi), own=kn, comps=[ks], star=ksrc))
if os.environ.get('PF_ONLY'):
    import re as _re
    jobs = [j for j in jobs if _re.search(os.environ['PF_ONLY'], j['name'])]            # a subset of the jobs (a cluster what-if): the others stay unrouted and are no obstacle
print('jobs', len(jobs), [j['name'] for j in jobs])

# per-job static mask: other nets' fixed copper (own net's removed), star pads of the same family are neutral
def job_block(job):
    blk = (total - net_mask[job['own']].astype(np.int16)) > 0
    blk |= static
    nm = job['own']
    for comp in job['comps']:
        for k in comp:
            for c in pad_cells(k):
                blk[c] = False
    for k in (job['star'] or []):
        if k in key:
            for c in pad_cells(k):
                blk[c] = False
    if nm.startswith(SENS):
        for ref in cfg.SENS_FROM:
            for p in pads:
                if p['ref'] == ref:
                    x0, y0, x1, y1 = p['bb']
                    cxm, cym = (x0 + x1) / 2, (y0 + y1) / 2
                    blk |= np.hypot(gx - cxm, gy - cym) < 10.0
    if nm in DIGITAL:
        own_refs = {p['ref'] for p in pads if p['net'] == nm}
        for ref, (bx0, by0, bx1, by1) in ANALOG_BOX.items():
            if ref in own_refs: continue
            m = 0.3 + 0.1 + 0.15        # LR-9: box + 0.3 + half the track, and a cell of margin
            blk |= (gx >= bx0 - m) & (gx <= bx1 + m) & (gy >= by0 - m) & (gy <= by1 + m)
    return blk

occ = np.zeros((NX, NY), np.int16)         # dynamic: other jobs' routed copper
hist = np.zeros((NX, NY), np.float32)
routed = {}                                # job name -> (cells array, polylines)
OWNMASK = {}


def pad_cells(k):
    x0, y0, x1, y1 = key[k]['bb']
    i0, j0 = cell(x0, y0); i1, j1 = cell(x1, y1)
    return [(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1) if x0 - 1e-6 <= X0 + i * RES <= x1 + 1e-6 and y0 - 1e-6 <= Y0 + j * RES <= y1 + 1e-6]


DIRS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]


def astar(starts, goals, blk, pres, win):
    """starts, goals: sets of (i,j); returns path list or None. win = (i0, j0, i1, j1)"""
    i0, j0, i1, j1 = win
    gi0 = min(g[0] for g in goals); gi1 = max(g[0] for g in goals); gj0 = min(g[1] for g in goals); gj1 = max(g[1] for g in goals)
    def h(i, j):
        dx = max(gi0 - i, 0, i - gi1); dy = max(gj0 - j, 0, j - gj1)
        return (max(dx, dy) + 0.414 * min(dx, dy))
    pq = []
    best = {}
    prev = {}
    for s in starts:
        best[s] = 0.0
        heapq.heappush(pq, (h(*s), 0.0, s))
    while pq:
        f, g0, c = heapq.heappop(pq)
        if g0 > best.get(c, 1e18) + 1e-9:
            continue
        if c in goals:
            path = [c]
            while c in prev:
                c = prev[c]; path.append(c)
            return path[::-1]
        ci, cj = c
        for di, dj, w in DIRS:
            ni, nj = ci + di, cj + dj
            if ni < i0 or ni > i1 or nj < j0 or nj > j1:
                continue
            if blk[ni, nj] and (ni, nj) not in goals:
                continue
            cost = w * (1.0 + hist[ni, nj]) + (pres * w if occ[ni, nj] else 0.0)
            if (di, dj) != prev.get(c, (None, None)) and False:
                cost += 0.0
            ng = g0 + cost
            if ng < best.get((ni, nj), 1e18) - 1e-9:
                best[(ni, nj)] = ng; prev[(ni, nj)] = c
                heapq.heappush(pq, (ng + h(ni, nj), ng, (ni, nj)))
    return None


def cover(path):
    """cells within INFL of the path centre line (the copper this route denies to others)"""
    g = np.zeros((NX, NY), bool)
    stamp_cells(g, path, INFL)
    return g


def route_job(job, pres):
    blk = job_block(job)
    comps = job['comps']
    star = job['star']
    cells = set(); paths = []
    comp_cells = [set(c for k in comp for c in pad_cells(k)) for comp in comps]
    if star:
        goalsets = [set(c for s in star if s in key for c in pad_cells(s))]
        tree = comp_cells[0]
        targets = goalsets[0]
        remaining = []
        order = [(tree, targets)]
    else:
        order = None
    ok = True
    if star:
        steps = [(comp_cells[0], goalsets[0])]
    else:
        tree = set(comp_cells[0]); rest = comp_cells[1:]
        steps = []
    allc = []
    def run(starts, goals):
        pts = [c for c in starts] + [c for c in goals]
        bi0 = min(p[0] for p in pts); bi1 = max(p[0] for p in pts); bj0 = min(p[1] for p in pts); bj1 = max(p[1] for p in pts)
        for grow in (60, 150, 400):
            win = (max(bi0 - grow, 0), max(bj0 - grow, 0), min(bi1 + grow, NX - 1), min(bj1 + grow, NY - 1))
            p = astar(starts, goals, blk, pres, win)
            if p:
                return p
        return None
    res = []
    if star:
        p = run(comp_cells[0], goalsets[0])
        if p is None:
            return None
        res.append(p)
        # the other pads of the group join the group's own copper
        tree = set(comp_cells[0]) | set(p)
        for c in comp_cells[1:]:
            pass
        extra = [set(c for k in [kk] for c in pad_cells(kk)) for comp in comps for kk in comp][1:]
        for c in extra:
            p2 = run(tree, c)
            if p2 is None:
                return None
            res.append(p2); tree |= set(p2) | c
    else:
        tree = set(comp_cells[0])
        rest = comp_cells[1:]
        while rest:
            goals = set().union(*rest)
            p = run(tree, goals)
            if p is None:
                return None
            end = p[-1]
            k = [i for i, c in enumerate(rest) if end in c][0]
            tree |= set(p) | rest[k]
            rest.pop(k)
            res.append(p)
    return res


PADBOX = [(p['bb'], p) for p in pads]
def pad_at(pt, net):
    for (x0, y0, x1, y1), p in PADBOX:
        if p['net'] == net and x0 <= pt[0] <= x1 and y0 <= pt[1] <= y1:
            return p
    return None


def polyline(path, net=None):
    pts = [xy(*c) for c in path]
    if net:
        def inside_pad(p, pt):
            x0, y0, x1, y1 = p['bb']; sh = max(0.15, 0.25 * min(x1 - x0, y1 - y0))
            return (min(max(pt[0], x0 + sh), x1 - sh), min(max(pt[1], y0 + sh), y1 - sh))      # the nearest point of the pad's inner half: copper for round and rounded pads too
        p0, p1 = pad_at(pts[0], net), pad_at(pts[-1], net)
        if p0: pts = [inside_pad(p0, pts[0])] + pts
        if p1: pts = pts + [inside_pad(p1, pts[-1])]
    out = [pts[0]]
    for a, c, d in zip(pts, pts[1:], pts[2:]):
        if abs((c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (d[0] - c[0])) > 1e-9:
            out.append(c)
    out.append(pts[-1])
    return [(round(x, 3), round(y, 3)) for x, y in out]


# ------------------------------------------------------------------------------------------------ GND pads without a via (LR-1)
EXTRA_ROUTES, EXTRA_VIAS = [], []
_gv = [(vx, vy) for m, vx, vy, vd in vias if m == GND]
_used = [False] * len(_gv)
_nov = []
for k, p in sorted(key.items()):                # the rule (rules.lr1): greedy in (ref, pin) order, a via within 3 mm of the pad centre, each used once
    if p['net'] != GND or p['th']:
        continue
    pxc, pyc = (p['bb'][0] + p['bb'][2]) / 2, (p['bb'][1] + p['bb'][3]) / 2
    best, bi = 1e9, -1
    for i_, (vx, vy) in enumerate(_gv):
        d_ = math.hypot(vx - pxc, vy - pyc)
        if not _used[i_] and d_ < best:
            best, bi = d_, i_
    if bi >= 0 and best <= 3.0:
        _used[bi] = True
    else:
        _nov.append(k)
print('GND pads without their own via:', _nov)
for k in ([] if os.environ.get('PF_NOGND') else _nov):
    p = key[k]
    blkg = ((total - net_mask[GND].astype(np.int16)) > 0) | static
    pc = pad_cells(k)
    for c in pc:
        blkg[c] = False
    vblk = blkg.copy()
    for di in range(-2, 3):
        for dj in range(-2, 3):
            if di * di + dj * dj <= 5:
                vblk |= np.roll(np.roll(blkg, di, 0), dj, 1)
    cx0 = sum(c[0] for c in pc) / len(pc); cy0 = sum(c[1] for c in pc) / len(pc)
    R3 = int(cfg.GND_VIA_RADIUS_MM / RES) - 2          # the rule counts a via within GND_VIA_RADIUS_MM of the pad centre; no stub: the top pour joins the pad
    best, bc = 1e9, None
    free = (~blkg).astype(np.int32)
    csum = np.cumsum(np.cumsum((blkg).astype(np.int32), 0), 1)
    for i in range(int(cx0) - R3, int(cx0) + R3 + 1):
        for j in range(int(cy0) - R3, int(cy0) + R3 + 1):
            if not (0 <= i < NX and 0 <= j < NY) or vblk[i, j] or math.hypot(i - cx0, j - cy0) > R3 or math.hypot(i - cx0, j - cy0) < 3:
                continue
            i0, j0, i1, j1 = max(i - 10, 1), max(j - 10, 1), min(i + 10, NX - 1), min(j + 10, NY - 1)
            crowd = csum[i1, j1] - csum[i0 - 1, j1] - csum[i1, j0 - 1] + csum[i0 - 1, j0 - 1]
            sc = crowd + 5.0 * math.hypot(i - cx0, j - cy0) * RES
            if sc < best:
                best, bc = sc, (i, j)
    if bc is None:
        print('GNDVIA none for', k); continue
    vx, vy = xy(*bc)
    EXTRA_VIAS.append((GND, round(vx, 3), round(vy, 3)))
    gm = np.zeros((NX, NY), bool)
    stamp_seg(gm, vx, vy, vx, vy, 0.3 + INFL - 0.1)
    new = gm & ~net_mask[GND]
    total += new.astype(np.int16)
    net_mask[GND] |= gm
    print('GNDVIA', k, '->', (round(vx, 2), round(vy, 2)), 'crowd score', round(best, 1))

t0 = time.time()
paths_of = {}
cov_of = {}
pres = 0.5
order = sorted(jobs, key=lambda j: -len(j['comps'][0]))
for it in range(ITER):
    conflicts = 0
    failed = []
    for job in order:
        nm = job['name']
        if nm in cov_of:
            occ -= cov_of[nm]
        r = route_job(job, pres)
        if r is None:
            failed.append(nm); cov_of.pop(nm, None); paths_of.pop(nm, None)
            continue
        cv = np.zeros((NX, NY), bool)
        for p in r:
            cv |= cover(p)
        cvi = cv.astype(np.int16)
        pcs = np.array([c for p in r for c in p])
        hit = np.zeros((NX, NY), bool)
        hit[pcs[:, 0], pcs[:, 1]] = occ[pcs[:, 0], pcs[:, 1]] > 0
        if hit.any():
            conflicts += 1
            hist[hit] += 1.0
        occ += cvi
        cov_of[nm] = cvi; paths_of[nm] = r
    # conflicts among current routes
    bad = []
    for nm in paths_of:
        others = occ - cov_of[nm]
        pc = np.array([c for p in paths_of[nm] for c in p])
        if (others[pc[:, 0], pc[:, 1]] > 0).any():
            bad.append(nm)
    if it == 0 and os.environ.get('DIAG'):
        for nm in failed:
            job = [j for j in jobs if j['name'] == nm][0]
            blk = job_block(job)
            for comp in job['comps']:
                for k in comp:
                    pc = pad_cells(k)
                    ring = []
                    for (ci, cj) in pc[:1]:
                        pass
                    x0, y0, x1, y1 = key[k]['bb']
                    i0, j0 = cell(x0 - 1.5, y0 - 1.5); i1, j1 = cell(x1 + 1.5, y1 + 1.5)
                    sub = blk[i0:i1 + 1, j0:j1 + 1]
                    # who blocks around: nets whose mask covers cells right next to the pad
                    near = [n for n in names if n != job['own'] and net_mask[n][i0:i1 + 1, j0:j1 + 1].any()]
                    seen = set(pc); st = list(pc)
                    while st and len(seen) < 400000:
                        a, c = st.pop()
                        for di, dj, _w in DIRS:
                            q = (a + di, c + dj)
                            if 0 <= q[0] < NX and 0 <= q[1] < NY and q not in seen and not blk[q]:
                                seen.add(q); st.append(q)
                    xs = [xy(*q)[0] for q in seen]; ys = [xy(*q)[1] for q in seen]
                    if k == ('U502', '4'):
                        x0_, y0_, x1_, y1_ = key[k]['bb']; qi, qj = cell((x0_ + x1_) / 2, y1_ + 0.1)
                        qi2, qj2 = cell((x0_ + x1_) / 2, y0_ - 0.1)
                        for (a_, c_) in ((qi, qj), (qi, qj2)):
                            print('PROBE cell', xy(a_, c_), 'static', bool(static[a_, c_]), 'covered by', [n for n in names if net_mask[n][a_, c_]], 'own', job['own'])
                    print('FLOOD', nm, k, len(seen), 'x', round(min(xs), 1), round(max(xs), 1), 'y', round(min(ys), 1), round(max(ys), 1))
                    print('DIAG', nm, k, 'pad cells', len(pc), 'blocked pad cells', sum(1 for c in pc if blk[c]), 'free cells in 1.5mm box', int((~sub).sum()), 'nets near', near[:8])
    if it == 0 and os.environ.get('DUMP'):
        from PIL import Image
        nm, bx0, by0, bx1, by1 = os.environ['DUMP'].split(',')
        job = [j for j in jobs if j['name'] == nm][0]
        blk = job_block(job)
        i0, j0 = cell(float(bx0), float(by0)); i1, j1 = cell(float(bx1), float(by1))
        sub = blk[i0:i1, j0:j1]
        im = Image.new('RGB', (i1 - i0, j1 - j0))
        px = im.load()
        for a in range(i1 - i0):
            for c in range(j1 - j0):
                px[a, (j1 - j0 - 1) - c] = (180, 60, 60) if sub[a, c] else (30, 90, 60)
        for p in pads:
            x0, y0, x1, y1 = p['bb']
            for a in range(max(cell(x0, y0)[0], i0), min(cell(x1, y1)[0], i1)):
                for c in range(max(cell(x0, y0)[1], j0), min(cell(x1, y1)[1], j1)):
                    px[a - i0, (j1 - j0 - 1) - (c - j0)] = (230, 200, 60)
        im = im.resize(((i1 - i0) * 6, (j1 - j0) * 6), Image.NEAREST)
        im.save('dump.png'); print('dumped')
    print('iter %d: %.0fs  routed %d/%d  failed %s  conflicting %d' % (it, time.time() - t0, len(paths_of), len(jobs), failed, len(bad)), flush=True)
    if not failed and not bad:
        break
    if time.time() - t0 > SECS:
        break
    pres = min(pres * 1.8, 300)
    order = sorted(jobs, key=lambda j: (j['name'] not in bad and j['name'] not in failed, -len(j['comps'][0])))

pairs = []
for a in paths_of:
    pc = np.array([c for p in paths_of[a] for c in p])
    for c in paths_of:
        if c != a:
            n = int((cov_of[c][pc[:, 0], pc[:, 1]] > 0).sum())
            if n:
                pairs.append((a, c, n, tuple(np.round(xy(*pc[(cov_of[c][pc[:, 0], pc[:, 1]] > 0).argmax()]), 1))))
pairs.sort(key=lambda t: -t[2])
print('PAIRS', pairs[:40])
def seg_dist(a, b, c, d):
    def ccw(p, q, r): return (r[1] - p[1]) * (q[0] - p[0]) - (q[1] - p[1]) * (r[0] - p[0])
    if ccw(a, c, d) * ccw(b, c, d) < 0 and ccw(a, b, c) * ccw(a, b, d) < 0: return 0.0
    def pd(p, s0, s1):
        dx, dy = s1[0] - s0[0], s1[1] - s0[1]; L = dx * dx + dy * dy
        t = 0 if L == 0 else max(0, min(1, ((p[0] - s0[0]) * dx + (p[1] - s0[1]) * dy) / L))
        return math.hypot(p[0] - s0[0] - t * dx, p[1] - s0[1] - t * dy)
    return min(pd(a, c, d), pd(b, c, d), pd(c, a, b), pd(d, a, b))
SEGS = []
for nm, rs in paths_of.items():
    net_ = [j for j in jobs if j['name'] == nm][0]['own']
    for p in rs:
        pl = polyline(p, net_)
        for u, v in zip(pl, pl[1:]):
            SEGS.append((nm, net_, u, v))
for nm, net_, a, c, d, e in [(t[0], t[0], t[1], t[2], t[3], t[4]) for t in tracks]:
    pass
FIXSEGS = [(t[0], t[0], (t[1], t[2]), (t[3], t[4])) for t in tracks if t[0] != GND]
confl = []
for i, (n1, o1, a, b_) in enumerate(SEGS):
    for (n2, o2, c, d) in SEGS[i + 1:] + FIXSEGS:
        if n1 == n2 or (o1 == o2 and '#' not in n1 and '#' not in str(n2)): continue
        if o1 == o2 and n2 in ('%s' % o1,): continue
        if max(min(a[0], b_[0]), min(c[0], d[0])) - min(max(a[0], b_[0]), max(c[0], d[0])) > 0.45 or max(min(a[1], b_[1]), min(c[1], d[1])) - min(max(a[1], b_[1]), max(c[1], d[1])) > 0.45: continue
        if o1 == o2:                      # groups of one supply / Kelvin net meet legitimately at their star or source pads
            mx_, my_ = (a[0] + b_[0]) / 2, (a[1] + b_[1]) / 2
            sp = [key[tuple(q.split('.'))] for q in (STAR.get(o1, []) + KELVIN.get(o1, {}).get('src', [])) if tuple(q.split('.')) in key]
            if any(math.hypot(mx_ - (p_['bb'][0] + p_['bb'][2]) / 2, my_ - (p_['bb'][1] + p_['bb'][3]) / 2) < 1.5 for p_ in sp):
                continue
        lim = 0.9 if (o2 in HIZ or o1 in HIZ) else 0.37
        if seg_dist(a, b_, c, d) < lim:
            confl.append((((a[0] + b_[0]) / 2), ((a[1] + b_[1]) / 2), n1, n2))
clusters = []
for x, y, n1, n2 in confl:
    for cl in clusters:
        if math.hypot(cl[0] - x, cl[1] - y) < 2.0:
            cl[2].add(n1); cl[2].add(n2); break
    else:
        clusters.append([x, y, {n1, n2}])
print('METRIC conflict_segments', len(confl), 'distinct_clusters', len(clusters))
_agg = {}
for x_, y_, n1_, n2_ in confl:
    k_ = tuple(sorted((n1_, n2_)))
    e_ = _agg.setdefault(k_, [0, 0.0, 0.0]); e_[0] += 1; e_[1] += x_; e_[2] += y_
for k_, e_ in sorted(_agg.items(), key=lambda t: -t[1][0]):
    print('PAIRSUM', k_[0], k_[1], e_[0], round(e_[1] / e_[0], 2), round(e_[2] / e_[0], 2))
for cl in sorted(clusters, key=lambda c: (round(c[0]), round(c[1]))):
    print('CLUSTER (%.1f, %.1f)' % (cl[0], cl[1]), sorted(cl[2]))
R = []
for nm, rs in paths_of.items():
    net = [j for j in jobs if j['name'] == nm][0]['own']
    for p in rs:
        R.append((net, 'F', polyline(p, net), 0.2))
R += EXTRA_ROUTES
open(OUT, 'w').write('ROUTES = %r\nVIAS = %r\n' % (R, EXTRA_VIAS))
print('wrote', OUT, len(R), 'polylines; failed', [j['name'] for j in jobs if j['name'] not in paths_of], 'conflicting', bad)
