import sys, pickle, json
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
D0, P0 = RP.load(R + 'dump_all.json')
d = json.load(open(R + 'rc_final_place.json'))['st']
C = pickle.load(open(R + 'rc_sel_m2.pkl', 'rb'))
for r in ('R503', 'R511', 'R504', 'R510'):
    x, y, rot, ls = d[r]; k = int(round((rot - P0[r]['rot']) / 90.0)) % 4
    m = [c for c in C[r] if abs(c[3] - x) < 1e-6 and abs(c[4] - y) < 1e-6]
    gg = RP.part_geom(P0[r], k, ls)
    print(r, 'rot', rot, 'main rot', P0[r]['rot'], 'k', k, 'cand k', [c[1] for c in m], 'cy model', [tuple(round(v, 2) for v in c[5]) for c in m][:1], 'cy recomputed', [round(v + o, 2) for v, o in zip(gg['cy'], (x, y, x, y))])
