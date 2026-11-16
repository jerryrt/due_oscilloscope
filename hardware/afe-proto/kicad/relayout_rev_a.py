"""AFE-1 relayout step 1 (D30, the owner's convention of 2026-11-15): positions with room for a designator above every part.

    python3 kicad/relayout_rev_a.py FLIPS SEED NSEEDS ANNEAL_ITERS      (in the PCB image; PYTHONPATH=hardware/afe-proto; run from hardware/afe-proto)

Starts from the landed board (kicad/afe-proto.kicad_pcb: origins and courtyards, rotations kept), solves with pcbtools/labelplace.py (a linear programme for
least movement, restarts with jittered targets, a hill-climb and an anneal on the violation count) inside the fence rectangles below, and writes the
origins to kicad/relayout_pos.json. HAND holds the positions chosen by hand (REF/CAL's ladder zone, J501, the wall bridges) and ANCH the parts that
never move. The result goes into kicad/layout.py's RELAID table (rotations from the landed board).
"""
import re, sys, json
import numpy as np
from pcbtools import boardio, labelplace as LP, silkread
from pcbtools.boards import v1 as C
b = boardio.read_board('kicad/afe-proto.kicad_pcb')
FENCE = {
 '1': [(64.4, 32.0, 92.0, 48.7)],
 '2': [(70.4, 21.6, 92.0, 31.6)],
 '3': [(70.4, 4.6, 92.0, 21.2)],
 '4': [(17.5, 4.6, 43.6, 33.0)],
 '5': [(45.0, 4.6, 64.2, 40.0)],
}
WALL = [(64.4, 13.0, 70.2, 30.8)]
R412 = [(38.6, 34.5, 45.0, 47.5)]
WALLREFS = {'R309', 'R310', 'R515', 'R516'}
LADDER = {'R503', 'R504', 'R505', 'R506', 'R507', 'R508'}
HAND = {'R508': (52.07, 5.4), 'R506': (57.15, 5.4), 'R504': (62.23, 5.4), 'R507': (54.61, 8.35), 'R505': (59.69, 8.35),
        'R503': (63.05, 9.2), 
        'R501': (63.35, 17.3), 'R513': (53.9, 19.6), 'U502': (58.1, 20.1), 'D501': (62.2, 25.5), 'TP501': (51.2, 9.9), 'R502': (62.3, 21.2), 'R514': (53.7, 14.15), 'R520': (51.3, 14.15), 'R515': (66.04, 24.0), 'R516': (68.58, 27.3), 'D201': (72.6, 28.4), 'C503': (46.8, 9.2), 'J501': (56.54, 13.75)}
ANCH = set(C.ANCHORS) | {'R411'} | set(HAND)
LOCKX = WALLREFS | {'R110', 'J501'}
NOLAB = ['J601','J602','J603','J604','J605','J606','J607','J101','J201','J301']
refs, rel, target, fence = [], {}, {}, {}
big = [(-1e3, -1e3, 1e3, 1e3)]
for k, r in enumerate(b.fp_ref):
    if np.isnan(b.fp_cx0[k]) or int(b.fp_side[k]) != 0: continue
    refs.append(r)
    ox, oy = float(b.fp_x[k]), float(b.fp_y[k])
    rel[r] = (float(b.fp_cx0[k]) - ox, float(b.fp_cy0[k]) - oy, float(b.fp_cx1[k]) - ox, float(b.fp_cy1[k]) - oy)
    x, y = ox, oy
    m = re.fullmatch(r'[A-Z]+(\d)\d\d', r)
    d = m.group(1) if m else '6'
    if r in ANCH or d == '6':
        fence[r] = big
    elif r == 'J501': fence[r] = FENCE['5']
    elif r in WALLREFS: fence[r] = [(62.2, 13.0, 71.0, 30.8)]
    elif r == 'R110': fence[r] = [(62.2, 32.0, 69.4, 48.7)]
    elif r in ('R412', 'R413'): fence[r] = R412; y = 40.0
    else:
        fence[r] = FENCE[d]
        if d == '4': y = 4.6 + (y - 4.6) * 1.55
    target[r] = HAND.get(r, (x, y))
ANCH |= {r for r in refs if re.fullmatch(r'[A-Z]+6\d\d', r)}
# obstacles: headers' end labels, the identity strip
obst = [(17.5, 34.0, 38.5, 47.0)]
for r in ('J601','J602','J603','J604','J605','J606','J607'):
    k = b.ref_index(r); c = (b.fp_cx0[k], b.fp_cy0[k], b.fp_cx1[k], b.fp_cy1[k]); w = len(r) * 0.9
    if (c[2]-c[0]) > (c[3]-c[1]): obst.append((c[0]-0.3-w, (c[1]+c[3])/2-0.5, c[0]-0.3, (c[1]+c[3])/2+0.5))
    else: obst.append(((c[0]+c[2])/2-w/2, c[3]+0.3, (c[0]+c[2])/2+w/2, c[3]+1.3))
best = None
rng = np.random.default_rng(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
T0 = dict(target)
for seed in range(int(sys.argv[3]) if len(sys.argv) > 3 else 1):
    target = {r: ((T0[r][0] + (rng.normal(0, 0.4) if seed and r not in ANCH else 0) * (r not in LOCKX), T0[r][1] + (rng.normal(0, 0.4) if seed and r not in ANCH else 0))) for r in refs}
    pos, bad = LP.solve(refs, rel, target, fence, ANCH, LOCKX, obst, verbose=False, nolabel=set(NOLAB), flips=int(sys.argv[1]) if len(sys.argv) > 1 else 25)
    if best is None or len(bad) < len(best[1]): best = (pos, bad, dict(target))
    print('seed', seed, len(bad), flush=True)
pos, bad, target = best
print('before polish', len(bad))
pos, bad = LP.polish(refs, rel, pos, fence, ANCH, LOCKX, obst, nolabel=set(NOLAB), rounds=12)
print('after polish', len(bad))
pos, bad = LP.anneal(refs, rel, pos, target, fence, ANCH, LOCKX, obst, nolabel=set(NOLAB), iters=int(sys.argv[4]) if len(sys.argv) > 4 else 30000)
print('parts', len(refs), 'violations', len(bad))
for x in bad[:60]: print(' ', x)
disp = {r: ((pos[r][0]-target[r][0])**2 + (pos[r][1]-target[r][1])**2) ** .5 for r in refs}
print('max displacement from target', max(disp.values()), sorted(disp, key=disp.get)[-5:])
json.dump({r: [*pos[r]] for r in refs}, open('kicad/relayout_pos.json', 'w'))
