"""hand-route (grid A*, top layer only, no via) every HIZ net on a scratch copy of the assembled board; report lengths and the LR-3 / LR-4 rows"""
import os, shutil, heapq, sys
import numpy as np
from pcbtools import boardio
from pcbtools.boards import v1 as C
from pcbtools.editor import edit
src = 'whatif/_scratch/final/afe-proto.kicad_pcb'; dst = 'whatif/_scratch/hizroute/afe-proto.kicad_pcb'
os.makedirs('whatif/_scratch/hizroute', exist_ok=True)
for ext in ('kicad_pcb', 'kicad_pro', 'kicad_prl', 'kicad_sch'):
    if os.path.exists(src.replace('kicad_pcb', ext)): shutil.copy(src.replace('kicad_pcb', ext), dst.replace('kicad_pcb', ext))
b = boardio.read_board(src)
W = 0.2; CL = 0.3          # track width, clearance to other copper
H = 0.05
def pads_of(nid): return [j for j in range(len(b.p_fp)) if int(b.p_net[j]) == nid]
allboxes = np.column_stack([b.p_bx0, b.p_by0, b.p_bx1, b.p_by1])
nets = sorted(C.HIZ, key=lambda n: (0 if n.endswith('_N') else 1 if n.endswith('R2A') else 2 if n.endswith('R1A') else 3, n))
def route_order(order):
    routed = []     # segments already routed: (net, p0, p1)
    total = {}
    segs_out = []
    fails = []
    for n in order:
        nid = b.nets.index(n); mine = pads_of(nid)
        xs = b.p_x[mine]; ys = b.p_y[mine]
        X0, X1 = xs.min() - 4.0, xs.max() + 4.0; Y0, Y1 = ys.min() - 4.0, ys.max() + 4.0
        nx = int((X1 - X0) / H) + 1; ny = int((Y1 - Y0) / H) + 1
        gx = X0 + H * np.arange(nx); gy = Y0 + H * np.arange(ny)
        blocked = np.zeros((nx, ny), bool)
        def block_box(x0, y0, x1, y1, m):
            i0 = max(0, int((x0 - m - X0) / H)); i1 = min(nx, int((x1 + m - X0) / H) + 2)
            j0 = max(0, int((y0 - m - Y0) / H)); j1 = min(ny, int((y1 + m - Y0) / H) + 2)
            sub = (gx[i0:i1, None] > x0 - m) & (gx[i0:i1, None] < x1 + m) & (gy[None, j0:j1] > y0 - m) & (gy[None, j0:j1] < y1 + m)
            blocked[i0:i1, j0:j1] |= sub
        for j in range(len(b.p_fp)):
            if int(b.p_net[j]) == nid: continue
            bx = allboxes[j]
            if bx[2] < X0 or bx[0] > X1 or bx[3] < Y0 or bx[1] > Y1: continue
            block_box(bx[0], bx[1], bx[2], bx[3], CL + W / 2)
        for (n2, p0, p1) in routed:        # other nets' tracks: the LR-3 limit is 0.6 mm between a HIZ track and another net's track
            if n2 == n: continue
            for t in np.linspace(0, 1, int(np.hypot(*(np.array(p1) - np.array(p0))) / H) + 2):
                q = np.array(p0) + t * (np.array(p1) - np.array(p0))
                block_box(q[0], q[1], q[0], q[1], 0.6 + W + 0.06)
        tree = [(mine[0], 'pad')]
        tree_cells = set()
        def cells_of_pad(j):
            bx = allboxes[j]
            i0 = int((bx[0] - X0) / H); i1 = int((bx[2] - X0) / H) + 1; j0 = int((bx[1] - Y0) / H); j1 = int((bx[3] - Y0) / H) + 1
            return {(i, k) for i in range(max(0, i0), min(nx, i1 + 1)) for k in range(max(0, j0), min(ny, j1 + 1)) if bx[0] <= gx[i] <= bx[2] and bx[1] <= gy[k] <= bx[3]}
        tree_cells |= cells_of_pad(mine[0])
        length = 0.0
        done = {mine[0]}
        while len(done) < len(mine):
            # pick the nearest undone pad to the tree
            best = None
            for j in mine:
                if j in done: continue
                d = min(np.hypot(b.p_x[j] - b.p_x[k], b.p_y[j] - b.p_y[k]) for k in done)
                if best is None or d < best[0]: best = (d, j)
            j = best[1]
            goal = tree_cells
            start = cells_of_pad(j)
            # A* from the pad's cells to any tree cell, own pads free
            free = blocked.copy()
            for k in mine:
                for (i, kk) in cells_of_pad(k): free[i, kk] = False
            gxy = np.array([(b.p_x[k], b.p_y[k]) for k in done])
            def hfun(i, k): return float(np.min(np.hypot(gx[i] - gxy[:, 0], gy[k] - gxy[:, 1])))
            pq = []; g = {}; came = {}
            for s in start:
                g[s] = 0.0; heapq.heappush(pq, (hfun(*s), 0.0, s))
            end = None
            while pq:
                f, gc, cur = heapq.heappop(pq)
                if gc > g.get(cur, 1e18) + 1e-9: continue
                if cur in goal and cur not in start:
                    end = cur; break
                for di, dk in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    nb = (cur[0] + di, cur[1] + dk)
                    if not (0 <= nb[0] < nx and 0 <= nb[1] < ny) or free[nb]: continue
                    step = H * (1.4142 if di and dk else 1.0)
                    ng = gc + step
                    if ng < g.get(nb, 1e18):
                        g[nb] = ng; came[nb] = cur; heapq.heappush(pq, (ng + hfun(*nb) * 0.999, ng, nb))
            if end is None:
                print('NET', n, 'NO ROUTE for pad', b.fp_ref[int(b.p_fp[j])], b.p_pin[j]); fails.append(n); done.add(j); continue
            path = [end]
            while path[-1] in came: path.append(came[path[-1]])
            pts = [(gx[i], gy[k]) for i, k in path]
            # simplify to straight runs
            simp = [pts[0]]
            for a in range(1, len(pts) - 1):
                d0 = (pts[a][0] - pts[a - 1][0], pts[a][1] - pts[a - 1][1]); d1 = (pts[a + 1][0] - pts[a][0], pts[a + 1][1] - pts[a][1])
                if abs(d0[0] * d1[1] - d0[1] * d1[0]) > 1e-9: simp.append(pts[a])
            simp.append(pts[-1])
            # trim the parts inside own pad boxes (keep 0.1 mm of overlap into a pad)
            def inside_any(p):
                for k in mine:
                    bx = allboxes[k]
                    if bx[0] < p[0] < bx[2] and bx[1] < p[1] < bx[3]: return True
                return False
            for a in range(len(simp) - 1):
                p0 = np.array(simp[a]); p1 = np.array(simp[a + 1]); L = np.hypot(*(p1 - p0))
                if L < 1e-9: continue
                ts = np.linspace(0, 1, max(2, int(L / 0.01)))
                pt = p0[None, :] + ts[:, None] * (p1 - p0)[None, :]
                ins = np.array([inside_any(q) for q in pt])
                if ins.all(): continue
                i0 = int(np.argmax(~ins)); i1 = len(ins) - 1 - int(np.argmax(~ins[::-1]))
                u = (p1 - p0) / L
                q0 = pt[i0] - (u * 0.1 if i0 > 0 else 0); q1 = pt[i1] + (u * 0.1 if i1 < len(ins) - 1 else 0)
                if np.hypot(*(q1 - q0)) < 1e-6: continue
                segs_out.append((n, tuple(q0), tuple(q1))); routed.append((n, tuple(q0), tuple(q1))); length += float(np.hypot(*(q1 - q0)))
            tree_cells |= {c for c in path} | cells_of_pad(j)
            done.add(j)
        total[n] = length
        print('ROUTED', n, 'pads', len(mine), 'track', round(length, 2), 'mm')

    return segs_out, total, fails
import itertools, io, contextlib
best_all = []
for ch in os.environ.get('CHANNELS', '/CH1,/CH2').split(','):
    chan = [n for n in C.HIZ if n.startswith(ch)]
    best = None
    for perm in itertools.permutations(chan):
        with contextlib.redirect_stdout(io.StringIO()):
            sg, tot, fl = route_order(list(perm))
        score = (len(set(fl)), sum(tot.values()))
        if best is None or score < best[0]: best = (score, perm, sg, tot, fl)
    print('CHANNEL', ch, 'best order', [p[len(ch) + 1:] for p in best[1]], 'fails', sorted(set(best[4])), 'lengths', {k[1:]: round(v, 2) for k, v in best[3].items()})
    best_all += best[2]
with edit(dst) as e:
    for n, p0, p1 in best_all:
        e.add_tracks(n, 'F.Cu', p0[0], p0[1], p1[0], p1[1], W)
print('segments', len(best_all))
