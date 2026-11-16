import sys, shutil, numpy as np, itertools
from pcbtools import boardio
from pcbtools.editor import edit
src = 'whatif/_scratch/relaid/afe-proto.kicad_pcb'; dst = 'whatif/_scratch/probe/afe-proto.kicad_pcb'
import os; os.makedirs('whatif/_scratch/probe', exist_ok=True)
for ext in ('kicad_pcb', 'kicad_pro', 'kicad_prl', 'kicad_sch'): 
    if os.path.exists(src.replace('kicad_pcb', ext)): shutil.copy(src.replace('kicad_pcb', ext), dst.replace('kicad_pcb', ext))
b = boardio.read_board(src)
nid = b.nets.index('/AWG_INV')
pads = []
for j in range(len(b.p_fp)):
    if int(b.p_net[j]) == nid:
        pads.append((f"{b.fp_ref[int(b.p_fp[j])]}.{b.p_pin[j]}", float(b.p_x[j]), float(b.p_y[j]), (float(b.p_bx0[j]), float(b.p_by0[j]), float(b.p_bx1[j]), float(b.p_by1[j]))))
for p in pads: print('PAD', p[0], round(p[1], 3), round(p[2], 3), [round(v, 3) for v in p[3]])
# Prim MST on centre distances
n = len(pads); used = [0]; edges = []
while len(used) < n:
    best = None
    for i in used:
        for k in range(n):
            if k in used: continue
            d = np.hypot(pads[i][1] - pads[k][1], pads[i][2] - pads[k][2])
            if best is None or d < best[0]: best = (d, i, k)
    edges.append((best[1], best[2])); used.append(best[2])
def clip(A, B):
    """the part of the centre line A -> B outside both pad boxes: returns (p0, p1) or None"""
    a = np.array(A[1:3]); c = np.array(B[1:3]); v = c - a; L = np.hypot(*v)
    ts = np.linspace(0, 1, 2001)
    pts = a[None, :] + ts[:, None] * v[None, :]
    def inside(box, P): return (P[:, 0] > box[0]) & (P[:, 0] < box[2]) & (P[:, 1] > box[1]) & (P[:, 1] < box[3])
    free = ~(inside(A[3], pts) | inside(B[3], pts))
    if not free.any(): return None
    i0 = np.argmax(free); i1 = len(free) - 1 - np.argmax(free[::-1])
    return pts[i0], pts[i1]
W = float(os.environ.get('TW', '0.25'))
segs = []
for i, k in edges:
    s = clip(pads[i], pads[k])
    print('EDGE', pads[i][0], pads[k][0], 'centre', round(float(np.hypot(pads[i][1] - pads[k][1], pads[i][2] - pads[k][2])), 3), 'track', None if s is None else round(float(np.hypot(*(s[1] - s[0]))), 3))
    if s is not None:
        # extend by half the track width into the pad copper so that the track touches both pads
        d = (s[1] - s[0]); L = np.hypot(*d); u = d / L if L > 1e-9 else d
        segs.append((s[0] - u * 0.1, s[1] + u * 0.1))
with edit(dst) as e:
    for p0, p1 in segs:
        e.add_tracks('/AWG_INV', 'F.Cu', p0[0], p0[1], p1[0], p1[1], W)
print('routed segments', len(segs), 'total length (incl. 0.1 mm stubs)', round(sum(float(np.hypot(*(b_ - a_))) for a_, b_ in segs), 3))
