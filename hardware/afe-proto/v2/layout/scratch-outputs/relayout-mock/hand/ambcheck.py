import sys, json
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
st = json.load(open(sys.argv[1]))['st']; D = {p['ref']: p for p in json.load(open(sys.argv[2]))['parts']}
bes = sorted(r for r, v in st.items() if v[3] >= 10 and r != 'U301')
bad = []
for r in bes:
    p = D[r]; w, h = RP.LAB_W * len(r), RP.LAB_H
    lb = (p['tx'] - w / 2, p['ty'] - 0.5, p['tx'] + w / 2, p['ty'] + 0.5)        # ink 1.0 high
    for q, c in D.items():
        if q == r: continue
        cy = c['cy']
        if not cy: continue
        xo = min(lb[2], cy[2]) - max(lb[0], cy[0]) > 1e-6
        up = 0 <= lb[1] - cy[3] <= 0.6; dn = 0 <= cy[1] - lb[3] <= 0.6
        if xo and (up or (dn and __import__('os').environ.get('AMBBOTH','1')=='1')): bad.append((r, q, 'above' if up else 'below'))
print('beside', len(bes), 'CH1', sum(1 for r in bes if r[1] == '1'), 'CH2', sum(1 for r in bes if r[1] == '2'), 'ambiguous', bad)
