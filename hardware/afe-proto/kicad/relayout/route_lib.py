"""two-layer grid router for hand-routing a list of nets on a scratch board: A* over (layer, i, j), per-net layer and via permission,
clearances from distance transforms of the copper that is not the net's own. Writes tracks and vias with pcbtools.editor."""
import heapq, math, os, shutil
import numpy as np
from scipy import ndimage
from pcbtools import boardio
from pcbtools.boards import v1 as C
from pcbtools.editor import edit
H = 0.1
X0, Y0, X1, Y1 = C.BOARD_RECT
X0 += 0.4; Y0 += 0.4; X1 -= 0.4; Y1 -= 0.4
NX = int((X1 - X0) / H) + 1; NY = int((Y1 - Y0) / H) + 1
GX = X0 + H * np.arange(NX); GY = Y0 + H * np.arange(NY)
CLR = 0.2           # copper clearance, mm
VIA_D, VIA_DRILL = 0.6, 0.3
class Board:
    def __init__(self, path):
        self.path = path
        self.b = boardio.read_board(path)
        self.relax = set()
        self.tracks = []   # (net, layer, p0, p1, w) added
        self.vias = []     # (net, x, y)
    def pad_layers(self, j):
        m = int(self.b.p_layer_mask[j])
        return (m & 1 != 0, m & 2 != 0) if m else ((True, not bool(self.b.p_smd[j])))
    def copper_masks(self, net_id, extra_tracks, extra_vias, tag=None, pad_subset=None, net_courtyards=None):
        """boolean (NX, NY) masks per layer of foreign copper (pads, existing tracks, vias, our new ones), in cells"""
        b = self.b
        masks = [np.zeros((NX, NY), bool), np.zeros((NX, NY), bool)]
        def box(mask, x0, y0, x1, y1):
            i0 = max(0, int((x0 - X0) / H) - 1); i1 = min(NX, int((x1 - X0) / H) + 2); j0 = max(0, int((y0 - Y0) / H) - 1); j1 = min(NY, int((y1 - Y0) / H) + 2)
            if i1 <= i0 or j1 <= j0: return
            sub = (GX[i0:i1, None] >= x0 - 0.001) & (GX[i0:i1, None] <= x1 + 0.001) & (GY[None, j0:j1] >= y0 - 0.001) & (GY[None, j0:j1] <= y1 + 0.001)
            mask[i0:i1, j0:j1] |= sub
        for j in range(len(b.p_fp)):
            if int(b.p_net[j]) == net_id and (pad_subset is None or j in pad_subset): continue
            f, bt = self.pad_layers(j)
            for L, on in ((0, f), (1, bt)):
                if on: box(masks[L], b.p_bx0[j], b.p_by0[j], b.p_bx1[j], b.p_by1[j])
        hiz_ids = {b.nets.index(n_) for n_ in C.HIZ if n_ in b.nets}
        mine_hiz = net_id in hiz_ids
        def seg(mask, p0, p1, w, hiz=False):
            n = max(2, int(math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / (H / 2)) + 1)
            r = 0.52 if (hiz and 'hiz' not in self.relax) else w / 2          # a HIZ track keeps 0.85 mm between centre lines (LR-3: 0.6 + the widths, and the checker's rounding)
            for t in np.linspace(0, 1, n):
                x = p0[0] + t * (p1[0] - p0[0]); y = p0[1] + t * (p1[1] - p0[1])
                box(mask, x - r, y - r, x + r, y + r)
        for k in range(len(b.s_idx)):
            if int(b.s_net[k]) == net_id and tag is None: continue
            seg(masks[int(b.s_layer[k])], (b.s_x0[k], b.s_y0[k]), (b.s_x1[k], b.s_y1[k]), b.s_w[k], hiz=(int(b.s_net[k]) in hiz_ids) or mine_hiz)
        for tr in extra_tracks:
            net, layer, p0, p1, w = tr[:5]; ttag = tr[5] if len(tr) > 5 else None
            if b.nets.index(net) == net_id and ttag == tag: continue
            seg(masks[layer], p0, p1, w, hiz=(b.nets.index(net) in hiz_ids) or mine_hiz)
        for k in range(len(b.v_idx)):
            if int(b.v_net[k]) == net_id: continue
            for L in (0, 1): box(masks[L], b.v_x[k] - VIA_D / 2, b.v_y[k] - VIA_D / 2, b.v_x[k] + VIA_D / 2, b.v_y[k] + VIA_D / 2)
        for vv in extra_vias:
            net, x, y = vv[:3]; vtag = vv[3] if len(vv) > 3 else None
            if b.nets.index(net) == net_id and vtag == tag: continue
            for L in (0, 1): box(masks[L], x - VIA_D / 2, y - VIA_D / 2, x + VIA_D / 2, y + VIA_D / 2)
        # LR-1: no bottom copper under an analog part (courtyards of the analog fences' parts block the bottom layer and every via) ; LR-9 per net
        gnd_id = b.nets.index(C.GND)
        self._court_bottom = np.zeros((NX, NY), bool)
        if net_id != gnd_id and 'court' not in self.relax:
            for i_, r_ in enumerate(b.fp_ref):
                if np.isnan(b.fp_cx0[i_]): continue
                if C.BLOCK.get(r_) in ('AWG', 'SCOPE', 'REFCAL') and not r_.startswith(('J', 'MH')):
                    box(self._court_bottom, b.fp_cx0[i_] - 0.45, b.fp_cy0[i_] - 0.45, b.fp_cx1[i_] + 0.45, b.fp_cy1[i_] + 0.45)   # LR-1: ZONE_PAD 0.3 + half the track width (bottom segments only, vias are not counted)
        self._keep_top = np.zeros((NX, NY), bool)
        if any(b.nets[net_id].startswith(p_) for p_ in C.SENSITIVE):          # LR-5: sensitive copper stays 10 mm from the generator's courtyards
            for r_ in C.GEN:
                i_ = b.ref_index(r_); box(self._keep_top, b.fp_cx0[i_] - C.KEEPOUT - 0.1, b.fp_cy0[i_] - C.KEEPOUT - 0.1, b.fp_cx1[i_] + C.KEEPOUT + 0.1, b.fp_cy1[i_] + C.KEEPOUT + 0.1)
        for r_ in (net_courtyards or []):
            i_ = b.ref_index(r_); box(masks[0], b.fp_cx0[i_], b.fp_cy0[i_], b.fp_cx1[i_], b.fp_cy1[i_])
        # the top-layer keepout bands
        for name, (kx0, ky0, kx1, ky1) in C.KEEPOUTS: box(masks[0], kx0 - 0.05, ky0 - 0.05, kx1 + 0.05, ky1 + 0.05)
        return masks
    def route(self, net, width=0.2, bottom=False, vias=False, extra_margin=0.0, via_cost=1.5, bottom_cost=1.6, max_bottom=3.0, pads_subset=None, tag=None, net_courtyards=None, extra_goal_pads=None):
        """route all pads of `net` together; returns (segments, vias, failures)"""
        b = self.b; nid = b.nets.index(net)
        self._tag = tag
        pads = [j for j in range(len(b.p_fp)) if int(b.p_net[j]) == nid and (pads_subset is None or j in pads_subset)]
        masks = self.copper_masks(nid, self.tracks, self.vias, tag=tag, pad_subset=set(pads), net_courtyards=net_courtyards)
        # clearance maps (distance from foreign copper)
        dist = [ndimage.distance_transform_edt(~m) * H for m in masks]
        trk_ok = [d >= CLR + width / 2 + 0.03 + extra_margin for d in dist]
        via_ok = [d >= CLR + VIA_D / 2 + 0.03 + extra_margin for d in dist]
        via_ok = via_ok[0] & via_ok[1]
        trk_ok[1] = trk_ok[1] & ~self._court_bottom
        trk_ok[0] = trk_ok[0] & ~self._keep_top
        own = [np.zeros((NX, NY), bool), np.zeros((NX, NY), bool)]
        def pad_cells(j):
            f, bt = self.pad_layers(j)
            out = []
            x0, y0, x1, y1 = b.p_bx0[j], b.p_by0[j], b.p_bx1[j], b.p_by1[j]
            i0 = max(0, int((x0 - X0) / H)); i1 = min(NX - 1, int((x1 - X0) / H) + 1); j0 = max(0, int((y0 - Y0) / H)); j1 = min(NY - 1, int((y1 - Y0) / H) + 1)
            for i in range(i0, i1 + 1):
                for k in range(j0, j1 + 1):
                    if x0 <= GX[i] <= x1 and y0 <= GY[k] <= y1:
                        if f: out.append((0, i, k))
                        if bt: out.append((1, i, k))
            if not out:      # a pad smaller than the grid: the nearest cell
                i = int(round((b.p_x[j] - X0) / H)); k = int(round((b.p_y[j] - Y0) / H)); out.append((0, i, k))
            return out
        tree = set(pad_cells(pads[0])); done = {pads[0]}
        def seg_cells(L_, p0, p1):
            n_ = max(2, int(math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / (H / 2)) + 1)
            out_ = set()
            for t_ in np.linspace(0, 1, n_):
                x_ = p0[0] + t_ * (p1[0] - p0[0]); y_ = p0[1] + t_ * (p1[1] - p0[1])
                i_ = int(round((x_ - X0) / H)); k_ = int(round((y_ - Y0) / H))
                if 0 <= i_ < NX and 0 <= k_ < NY: out_.add((L_, i_, k_))
            return out_
        own_cells = set()
        for tr in self.tracks:
            if tr[0] == net and (tr[5] if len(tr) > 5 else None) == tag: own_cells |= seg_cells(tr[1], tr[2], tr[3])
        if tag is None:
            for k_ in range(len(b.s_idx)):
                if int(b.s_net[k_]) == nid: own_cells |= seg_cells(int(b.s_layer[k_]), (b.s_x0[k_], b.s_y0[k_]), (b.s_x1[k_], b.s_y1[k_]))
        for c_ in own_cells: trk_ok[c_[0]][c_[1], c_[2]] = True
        # an own track that touches the first pad is already part of the tree
        tree |= own_cells
        segs = []; vs = []; fails = []
        for L, i, k in tree: trk_ok[L][i, k] = True
        while len(done) < len(pads):
            cand = [j for j in pads if j not in done]
            j = min(cand, key=lambda q: min(math.hypot(b.p_x[q] - b.p_x[d], b.p_y[q] - b.p_y[d]) for d in done))
            start = pad_cells(j)
            for L, i, k in start: trk_ok[L][i, k] = True
            tx = np.array([[b.p_x[d], b.p_y[d]] for d in done])
            def hf(i, k): return float(np.min(np.hypot(GX[i] - tx[:, 0], GY[k] - tx[:, 1]))) 
            pq = []; g = {}; came = {}
            for s in start: g[s] = 0.0; heapq.heappush(pq, (hf(s[1], s[2]), 0.0, s))
            end = None; steps = 0
            while pq:
                f, gc, cur = heapq.heappop(pq)
                if gc > g.get(cur, 1e18) + 1e-9: continue
                if cur in tree and cur not in start: end = cur; break
                steps += 1
                if steps > 2_500_000: break
                L, i, k = cur
                for di, dk in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    ni, nk = i + di, k + dk
                    if not (0 <= ni < NX and 0 <= nk < NY) or not trk_ok[L][ni, nk]: continue
                    if di and dk and not (trk_ok[L][i + di, k] and trk_ok[L][i, k + dk]): continue
                    step = H * (1.4142 if di and dk else 1.0) * (bottom_cost if L == 1 else 1.0)
                    nb = (L, ni, nk); ng = gc + step
                    if ng < g.get(nb, 1e18): g[nb] = ng; came[nb] = cur; heapq.heappush(pq, (ng + hf(ni, nk) * 0.999, ng, nb))
                if vias and bottom and via_ok[i, k] and trk_ok[1 - L][i, k]:
                    nb = (1 - L, i, k); ng = gc + via_cost
                    if ng < g.get(nb, 1e18): g[nb] = ng; came[nb] = cur; heapq.heappush(pq, (ng + hf(i, k) * 0.999, ng, nb))
            if end is None:
                fails.append(f'{b.fp_ref[int(b.p_fp[j])]}.{b.p_pin[j]}'); done.add(j); tree |= set(start); continue
            path = [end]
            while path[-1] in came: path.append(came[path[-1]])
            # split into per-layer runs, vias at layer changes
            run = [path[0]]
            for a in range(1, len(path)):
                if path[a][0] != run[-1][0]:
                    vs.append((net, float(GX[path[a][1]]), float(GY[path[a][2]]), tag))
                    segs += self._runs(net, run, width); run = [path[a]]
                else: run.append(path[a])
            segs += self._runs(net, run, width)
            tree |= set(path) | set(start); done.add(j)
        return segs, vs, fails

    def escape(self, net, j, ref, dist=1.3, width=0.2, extra_margin=0.0):
        """a short stub from pad j out of the courtyard of `ref` (fine-pitch IC): returns (segments, vias, ok)"""
        b = self.b; nid = b.nets.index(net)
        self._tag = None
        masks = self.copper_masks(nid, self.tracks, self.vias, tag=None, pad_subset={j})
        dist_m = [ndimage.distance_transform_edt(~m) * H for m in masks]
        ok = (dist_m[0] >= CLR + width / 2 + 0.03 + extra_margin) & ~self._keep_top
        i_ = b.ref_index(ref); bx = (b.fp_cx0[i_], b.fp_cy0[i_], b.fp_cx1[i_], b.fp_cy1[i_])
        # distance from the courtyard box
        dx = np.maximum(np.maximum(bx[0] - GX[:, None], 0), GX[:, None] - bx[2]); dy = np.maximum(np.maximum(bx[1] - GY[None, :], 0), GY[None, :] - bx[3])
        dbox = np.hypot(dx, dy)
        x0, y0, x1, y1 = b.p_bx0[j], b.p_by0[j], b.p_bx1[j], b.p_by1[j]
        start = [(i, k) for i in range(NX) for k in range(NY) if False]
        i0 = max(0, int((x0 - X0) / H)); i1 = min(NX - 1, int((x1 - X0) / H) + 1); j0 = max(0, int((y0 - Y0) / H)); j1 = min(NY - 1, int((y1 - Y0) / H) + 1)
        start = [(i, k) for i in range(i0, i1 + 1) for k in range(j0, j1 + 1) if x0 <= GX[i] <= x1 and y0 <= GY[k] <= y1]
        if not start: start = [(int(round((b.p_x[j] - X0) / H)), int(round((b.p_y[j] - Y0) / H)))]
        for c in start: ok[c] = True
        g = {c: 0.0 for c in start}; came = {}; pq = [(0.0, c) for c in start]; heapq.heapify(pq); end = None
        while pq:
            gc, cur = heapq.heappop(pq)
            if gc > g.get(cur, 1e18) + 1e-9: continue
            if cur not in start and dbox[cur] >= dist: end = cur; break
            if gc > 6.0: break
            for di, dk in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nb = (cur[0] + di, cur[1] + dk)
                if not (0 <= nb[0] < NX and 0 <= nb[1] < NY) or not ok[nb]: continue
                if di and dk and not (ok[cur[0] + di, cur[1]] and ok[cur[0], cur[1] + dk]): continue
                ng = gc + H * (1.4142 if di and dk else 1.0)
                if ng < g.get(nb, 1e18): g[nb] = ng; came[nb] = cur; heapq.heappush(pq, (ng, nb))
        if end is None: return [], [], False
        path = [end]
        while path[-1] in came: path.append(came[path[-1]])
        return self._runs(net, [(0, i, k) for i, k in path], width), [], True
    def _runs(self, net, run, width):
        if len(run) < 2: return []
        L = run[0][0]; pts = [(float(GX[i]), float(GY[k])) for _, i, k in run]
        simp = [pts[0]]
        for a in range(1, len(pts) - 1):
            d0 = (pts[a][0] - pts[a - 1][0], pts[a][1] - pts[a - 1][1]); d1 = (pts[a + 1][0] - pts[a][0], pts[a + 1][1] - pts[a][1])
            if abs(d0[0] * d1[1] - d0[1] * d1[0]) > 1e-9: simp.append(pts[a])
        simp.append(pts[-1])
        return [(net, L, simp[a], simp[a + 1], width, self._tag) for a in range(len(simp) - 1)]
    def add(self, segs, vs):
        self.tracks += segs; self.vias += vs
    def save(self, dst):
        shutil.copy(self.path, dst)
        for ext in ('kicad_pro', 'kicad_prl', 'kicad_sch'):
            s_ = self.path.replace('kicad_pcb', ext)
            if os.path.exists(s_): shutil.copy(s_, dst.replace('kicad_pcb', ext))
        with edit(dst) as e:
            for net in sorted({t[0] for t in self.tracks}):
                for layer in (0, 1):
                    S = [t for t in self.tracks if t[0] == net and t[1] == layer]
                    if S: e.add_tracks(net, 'F.Cu' if layer == 0 else 'B.Cu', [t[2][0] for t in S], [t[2][1] for t in S], [t[3][0] for t in S], [t[3][1] for t in S], [t[4] for t in S])
            for net in sorted({v[0] for v in self.vias}):
                V = [v for v in self.vias if v[0] == net]
                e.add_vias(net, [v[1] for v in V], [v[2] for v in V], VIA_D, VIA_DRILL)
