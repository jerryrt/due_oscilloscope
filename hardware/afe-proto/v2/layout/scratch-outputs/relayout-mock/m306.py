import json
D = json.load(open('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/dump_all.json'))
P = {p['ref']: p for p in D['parts']}
pad = lambda r, n: [q for q in P[r]['pads'] if q['n'] == n][0]
for r in ('R306', 'R301', 'R302'): print(r, [(q['n'], q['net'], [round(v, 2) for v in q['c']]) for q in P[r]['pads']], P[r]['x'], P[r]['y'])
print('J603.5', pad('J603', '5')['net'], pad('J603', '5')['c'])
a = pad('R306', '1')['c']; b = pad('J603', '5')['c']; print('main manhattan', abs(a[0] - b[0]) + abs(a[1] - b[1]))
a = pad('R306', '2')['c']; print('pad2 manhattan', abs(a[0] - b[0]) + abs(a[1] - b[1]))
