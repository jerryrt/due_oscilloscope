"""fin_d.py IN OUT : own vias for D501.1/D502.1 (drop the router's GND link between them), 1.0 mm designators and the two words on silk"""
import sys, math
import numpy as np
from pcbtools import boardio
from pcbtools.editor import edit
src, out = sys.argv[1:3]
F = (44.5, 4.6, 64.5, 36.0)
b = boardio.read_board(src)
kill = [int(b.s_idx[i]) for i in range(len(b.s_idx)) if b.nets[b.s_net[i]] == '/GND' and 63.2 <= b.s_x0[i] <= 64.5 and 63.2 <= b.s_x1[i] <= 64.5 and 22.0 < b.s_y0[i] < 27.0]
print('router GND link tracks dropped', len(kill))
# --- obstacles for silk
pads = [(b.p_bx0[j], b.p_by0[j], b.p_bx1[j], b.p_by1[j]) for j in range(len(b.p_x))]
boxes = [(a - 0.2, c - 0.2, d + 0.2, e + 0.2) for a, c, d, e in pads]
boxes += [(b.fp_cx0[i], b.fp_cy0[i], b.fp_cx1[i], b.fp_cy1[i]) for i in range(len(b.fp_ref)) if not np.isnan(b.fp_cx0[i]) and b.fp_cx1[i] > F[0] - 3 and b.fp_cx0[i] < F[2] + 3 and b.fp_cy1[i] > F[1] - 3 and b.fp_cy0[i] < F[3] + 3]
new_vias = [(63.25, 23.6), (63.25, 27.65)]
boxes += [(x - 0.5, y - 0.5, x + 0.5, y + 0.5) for x, y in new_vias]
boxes += [(b.v_x[i] - 0.5, b.v_y[i] - 0.5, b.v_x[i] + 0.5, b.v_y[i] + 0.5) for i in range(len(b.v_idx))]
keep = np.ones(len(b.s_idx), bool); keep[[np.flatnonzero(b.s_idx == k)[0] for k in kill]] = False
pts = []
for i in np.flatnonzero(keep):
    L = math.hypot(b.s_x1[i] - b.s_x0[i], b.s_y1[i] - b.s_y0[i]); k = max(int(L / 0.1), 1)
    t = np.arange(k + 1) / k
    pts.append(np.column_stack([b.s_x0[i] + (b.s_x1[i] - b.s_x0[i]) * t, b.s_y0[i] + (b.s_y1[i] - b.s_y0[i]) * t]))
segpts = np.vstack(pts)
TW, TH = 0.8, 1.0
def tbox(cx, cy, n, ang):
    w = n * TW * 0.95 + 0.2; h = TH * 1.15
    if ang: w, h = h, w
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
def hit(p, q): return p[0] < q[2] and q[0] < p[2] and p[1] < q[3] and q[1] < p[3]
placed = []
def free(bx, tight=True):
    if not (F[0] + 0.3 <= bx[0] and bx[2] <= F[2] - 0.3 and F[1] + 0.3 <= bx[1] and bx[3] <= F[3] - 0.3): return False
    if any(hit(bx, o) for o in boxes + placed): return False
    m = (segpts[:, 0] > bx[0] - 0.2) & (segpts[:, 0] < bx[2] + 0.2) & (segpts[:, 1] > bx[1] - 0.2) & (segpts[:, 1] < bx[3] + 0.2)
    return not m.any()
refs = []
for i, r in enumerate(b.fp_ref):
    d = ''.join(c for c in r if c.isdigit())
    if len(d) == 3 and d[0] == '5' and r not in ('R515', 'R516'): refs.append((i, r))
cen = {}
for j in range(len(b.p_x)): cen.setdefault(b.fp_ref[b.p_fp[j]], []).append((b.p_x[j], b.p_y[j]))
res, fail = [], []
for i, r in sorted(refs, key=lambda t: t[1]):
    pc = np.mean(cen[r], axis=0); ok = False
    for dist in np.arange(0.9, 30.0, 0.2):
        for k in range(32):
            a = 2 * math.pi * k / 32
            for ang in (0, 90):
                bx = tbox(pc[0] + dist * math.cos(a), pc[1] + dist * math.sin(a), len(r), ang)
                if free(bx):
                    placed.append(bx); res.append((r, (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2, ang)); ok = True; break
            if ok: break
        if ok: break
    if not ok: fail.append(r)
print('designators placed', len(res), 'failed', fail)
words = []
for word, tgt in (('ON', (59.7, 12.0)), ('REF/CAL', (54.5, 33.0))):
    ok = False
    for dist in np.arange(0.0, 6.0, 0.15):
        for k in range(24):
            a = 2 * math.pi * k / 24; c = (tgt[0] + dist * math.cos(a), tgt[1] + dist * math.sin(a))
            for ang in ((0,) if word == 'ON' else (0, 90)):
                bx = tbox(c[0], c[1], len(word), ang)
                if free(bx):
                    placed.append(bx); words.append((word, c[0], c[1], dist, ang)); ok = True; break
            if ok: break
        if ok: break
    if not ok: print('WORD FAILED', word)
print('words', [(w, round(x, 2), round(y, 2), round(d, 2), ang) for w, x, y, d, ang in words])
with edit(src, out) as e:
    e.remove_tracks(kill)
    e.stub_via('GND', 'D501', '1', 0, 0.96, w=0.2)
    e.stub_via('GND', 'D502', '1', 0, 0.91, w=0.2)
    for r, x, y, ang in res:
        e.set_ref(r, x, y, h=1.0, w=0.8); e.set_ref_pose(r, x, y, ang)
    for w, x, y, d, ang in words:
        e.add_text(w, x, y, h=1.0)
        if ang:
            for dd in e.b.GetDrawings():
                if dd.GetClass() == 'PCB_TEXT' and dd.GetText() == w and dd.GetLayer() == e.pcb.F_SilkS:
                    dd.SetTextAngleDegrees(90.0)
    e.fill_zones()
