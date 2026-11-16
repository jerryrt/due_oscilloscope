import json, sys
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
D = json.load(open((sys.argv[1] if len(sys.argv) > 1 else R + 'dump_new.json'))); P = {p['ref']: p for p in D['parts']}
def ov(a, b): return min(a[2], b[2]) - max(a[0], b[0]) > 1e-6 and min(a[3], b[3]) - max(a[1], b[1]) > 1e-6
print('lanes (Due mm, x0 y0 x1 y1): A1 lane', RP.LANES[0], ' A0 lane', RP.LANES[1])
bad = 0
for r, p in P.items():
    c = p['cy']; e = list(c)
    if p['silk']: e = [min(e[0], p['silk'][0]), min(e[1], p['silk'][1]), max(e[2], p['silk'][2]), max(e[3], p['silk'][3])]
    n = len(r); w = RP.LAB_W * n
    lab = (p['tx'] - w / 2 - RP.ZONE, p['ty'] - RP.LAB_H / 2 - RP.ZONE, p['tx'] + w / 2 + RP.ZONE, p['ty'] + RP.LAB_H / 2 + RP.ZONE)
    for i, l in enumerate(RP.LANES):
        if ov(e, l): print('PART in lane', i, r); bad += 1
        if ov(lab, l): print('LABEL ZONE in lane', i, r); bad += 1
print('lane check:', 'PASS, no part and no label zone stands in either lane' if not bad else 'FAIL %d' % bad)
