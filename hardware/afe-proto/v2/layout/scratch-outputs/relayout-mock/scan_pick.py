import sys, os, pickle, math, json
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock')
import relayout_place as RP
BLK = os.environ['BLK']
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
S = pickle.load(open(R + 'scan_%s.pkl' % BLK, 'rb'))
D0, P0 = RP.load(R + 'dump_all.json'); DN, PN = RP.load(R + 'dump_new.json')
npart, upin = ('R107', '5') if BLK == 'CH1' else ('R207', '3')
u = [q for q in P0['U101']['pads'] if q['n'] == upin][0]['c']
BASE = {'CH1': (['R107', 'R105', 'C102'], ['R103', 'R102', 'C101']), 'CH2': (['R207', 'R205', 'C202'], ['R203', 'R202', 'C201'])}[BLK]
def variants():
    L0, R0 = BASE; out = {}
    for swap in (0, 1):
        for flip in (0, 1):
            Lc, Rc = (R0, L0) if swap else (L0, R0)
            out['swap%d_flip%d' % (swap, flip)] = ((Lc[::-1] if flip else Lc), (Rc[::-1] if flip else Rc))
    return out
PITCH = 1.8; picks = []
for var, (Lc, Rc) in variants().items():
    west = npart in Lc; col = Lc if west else Rc; row = col.index(npart)
    p = P0[npart]; npad = [q for q in p['pads'] if q['net'].endswith('_NP')][0]; off = npad['c'][0] - p['x']
    # outer NP pad at the column's outer end: west column -> -0.825 ; east column -> +0.825
    px_off = (-0.825 if west else 0.825) + (0.0 if west else 3.05)
    cand = []
    for (xl, yb) in S[var]:
        px = xl + px_off; py = yb + row * PITCH
        base = abs(px - u[0]) + abs(py - u[1])
        cand.append((base, xl, yb))
    cand = [c for c in cand if 6.0 <= c[0] <= float(os.environ.get('NPMAX', 9.0))]
    cand.sort()
    pick = []
    for c in cand:
        if all(abs(c[1] - q[1]) > float(os.environ.get('PX', 1.0)) or abs(c[2] - q[2]) > float(os.environ.get('PY', 0.8)) for q in pick): pick.append(c)
        if len(pick) >= int(os.environ.get('NPICK', 4)): break
    print(var, 'row', row, 'west', west, 'legal', len(S[var]), 'with NP base 6-9:', len(cand), 'picked', [(round(a, 2), round(b, 2), round(c, 2)) for a, b, c in pick])
    picks += [(var, b, c, a) for a, b, c in pick]
json.dump(picks, open(R + os.environ.get('PICKFILE', 'picks_%s.json') % BLK, 'w'))
