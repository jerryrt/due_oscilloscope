import json
for fn in ('dump_all.json', 'dump_new.json'):
    D = json.load(open('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/' + fn))
    pts = [tuple(q['c']) for p in D['parts'] for q in p['pads'] if q['net'] == '/AWG_FB']
    n = len(pts); inT = {0}; L = 0
    while len(inT) < n:
        d, j = min((abs(pts[i][0] - pts[j][0]) + abs(pts[i][1] - pts[j][1]), j) for i in inT for j in range(n) if j not in inT); L += d; inT.add(j)
    print(fn, 'AWG_FB pad tree (Manhattan MST) %.2f mm' % L)
