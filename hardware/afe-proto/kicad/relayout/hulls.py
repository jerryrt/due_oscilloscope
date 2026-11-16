import numpy as np, sys
from pcbtools import boardio, silkread
from pcbtools.boards import v1 as C
b = boardio.read_board('whatif/_scratch/relaid/afe-proto.kicad_pcb')
refs = list(b.fp_ref)
blk = {r: C.BLOCK.get(r) for r in refs}
print('EDGE_BLOCK', C.EDGE_BLOCK, 'override', sorted(C.BLOCK_OVERRIDE)[:10])
import collections
groups = collections.defaultdict(list)
for i, r in enumerate(refs):
    if np.isnan(b.fp_cx0[i]) or r.startswith('MH'): continue
    bl = C.BLOCK.get(r)
    if bl and (bl != C.EDGE_BLOCK or r in C.BLOCK_OVERRIDE): groups[bl].append(i)
# label boxes
shown = {}
for j in range(len(b.r_fp)):
    i = int(b.r_fp[j])
    if b.r_on_silk[j] and int(b.r_layer[j]) == boardio.R_LAYERS['F.SilkS']:
        shown[i] = silkread.text_box(refs[i], b.r_x[j], b.r_y[j], b.r_w[j], b.r_h[j], b.r_ang[j])
for g, idx in sorted(groups.items()):
    x0 = min(min(b.fp_cx0[i], shown[i][0] if i in shown else 1e9) for i in idx); y0 = min(min(b.fp_cy0[i], shown[i][1] if i in shown else 1e9) for i in idx)
    x1 = max(max(b.fp_cx1[i], shown[i][2] if i in shown else -1e9) for i in idx); y1 = max(max(b.fp_cy1[i], shown[i][3] if i in shown else -1e9) for i in idx)
    print(g, len(idx), 'bbox', [round(float(v), 2) for v in (x0, y0, x1, y1)])
    # parts of other blocks whose centre is inside the bbox
    inside = [refs[k] for k in range(len(refs)) if not np.isnan(b.fp_cx0[k]) and x0 <= b.fp_x[k] <= x1 and y0 <= b.fp_y[k] <= y1 and k not in idx and (C.BLOCK.get(refs[k]) not in (None, C.EDGE_BLOCK))]
    print('   foreign centres inside bbox:', inside)
print('OLD OUTLINE', {k: [tuple(round(v, 1) for v in r) for r in rs] for k, rs in C.OUTLINE.items()})

print('--- clusters')
BRIDGE_REFS = {'R515', 'R516', 'R310', 'R309', 'R110', 'R411', 'R412', 'R413'}
M = 0.3
def padded(i):
    x0, y0, x1, y1 = b.fp_cx0[i], b.fp_cy0[i], b.fp_cx1[i], b.fp_cy1[i]
    if i in shown:
        s = shown[i]; x0, y0, x1, y1 = min(x0, s[0]), min(y0, s[1]), max(x1, s[2]), max(y1, s[3])
    return [float(x0 - M), float(y0 - M), float(x1 + M), float(y1 + M)]
for g, idx in sorted(groups.items()):
    boxes = [padded(i) for i in idx if refs[i] not in BRIDGE_REFS and not refs[i].startswith(('J1', 'J2', 'J3'))]
    # merge boxes closer than 1.0 mm
    merged = True
    while merged:
        merged = False
        for a in range(len(boxes)):
            for c in range(a + 1, len(boxes)):
                A, B = boxes[a], boxes[c]
                if min(A[2], B[2]) - max(A[0], B[0]) > -1.0 and min(A[3], B[3]) - max(A[1], B[1]) > -1.0:
                    boxes[a] = [min(A[0], B[0]), min(A[1], B[1]), max(A[2], B[2]), max(A[3], B[3])]; del boxes[c]; merged = True; break
            if merged: break
    print(g, [[round(v, 1) for v in bx] for bx in boxes])
    for bx in boxes:
        fi = [refs[k] for k in range(len(refs)) if not np.isnan(b.fp_cx0[k]) and bx[0] <= b.fp_x[k] <= bx[2] and bx[1] <= b.fp_y[k] <= bx[3] and k not in idx and C.BLOCK.get(refs[k]) not in (None, C.EDGE_BLOCK)]
        if fi: print('   foreign inside', [round(v, 1) for v in bx], fi)
print('BRIDGE/BNC positions', {r: (round(float(b.fp_x[b.ref_index(r)]), 2), round(float(b.fp_y[b.ref_index(r)]), 2)) for r in sorted(BRIDGE_REFS | {'J101', 'J201', 'J301'})})

print('--- scope split')
idx = groups['SCOPE']
for nm, sel in (('S1 y>=27.5', lambda i: b.fp_y[i] >= 27.5), ('S2 y<27.5', lambda i: b.fp_y[i] < 27.5)):
    boxes = [padded(i) for i in idx if refs[i] not in BRIDGE_REFS and not refs[i].startswith(('J1', 'J2', 'J3')) and sel(i)]
    bx = [min(v[0] for v in boxes), min(v[1] for v in boxes), max(v[2] for v in boxes), max(v[3] for v in boxes)]
    fi = [refs[k] for k in range(len(refs)) if not np.isnan(b.fp_cx0[k]) and bx[0] <= b.fp_x[k] <= bx[2] and bx[1] <= b.fp_y[k] <= bx[3] and k not in idx and C.BLOCK.get(refs[k]) not in (None, C.EDGE_BLOCK)]
    print(nm, [round(v, 2) for v in bx], 'foreign', fi, 'members', len(boxes))

print('--- extremes')
def ext(grp, side, sel=lambda i: True):
    best=None
    for i in groups[grp]:
        if refs[i] in BRIDGE_REFS or refs[i].startswith(('J1','J2','J3')) or not sel(i): continue
        bx = padded(i)
        v = bx[2] if side == 'x1' else bx[0]
        if best is None or (side=='x1' and v > best[0]) or (side=='x0' and v < best[0]): best=(v, refs[i], [round(t,2) for t in bx])
    return best
print('REFCAL x1', ext('REFCAL','x1')); print('SCOPE S1 x0', ext('SCOPE','x0', lambda i: b.fp_y[i]>=27.5))
print('AWG y1', ext_y if False else max(((padded(i)[3], refs[i]) for i in groups['AWG'] if refs[i] not in BRIDGE_REFS and not refs[i].startswith('J')), key=lambda t:t[0]))
print('SCOPE S2 y0', min(((padded(i)[1], refs[i]) for i in groups['SCOPE'] if refs[i] not in BRIDGE_REFS and not refs[i].startswith('J') and b.fp_y[i] < 27.5), key=lambda t:t[0]))

print('--- refcal upper')
up=[(padded(i), refs[i]) for i in groups['REFCAL'] if b.fp_y[i] >= 26.0 and refs[i] not in BRIDGE_REFS]
print('upper bbox', [round(min(v[0][0] for v in up),2), round(min(v[0][1] for v in up),2), round(max(v[0][2] for v in up),2), round(max(v[0][3] for v in up),2)], max(up, key=lambda v:v[0][2])[1])
lo=[(padded(i), refs[i]) for i in groups['REFCAL'] if b.fp_y[i] < 26.0 and refs[i] not in BRIDGE_REFS]
print('lower bbox', [round(min(v[0][0] for v in lo),2), round(min(v[0][1] for v in lo),2), round(max(v[0][2] for v in lo),2), round(max(v[0][3] for v in lo),2)])
