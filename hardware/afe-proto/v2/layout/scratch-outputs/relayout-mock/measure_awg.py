import json, math
D = json.load(open('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/dump_new.json'))
P = {p['ref']: p for p in D['parts']}
pad = lambda r, n: [q['c'] for q in P[r]['pads'] if q['n'] == n][0]
d = lambda a, b: math.hypot(a[0] - b[0], a[1] - b[1])
print('C305.1-U301.8 %.2f' % d(pad('C305', '1'), pad('U301', '8')), ' C306.1-U301.4 %.2f' % d(pad('C306', '1'), pad('U301', '4')))
J = P['J301']; print('J301 origin', J['x'], J['y'])
for r in ('R301', 'R302'): print(r, 'origin-to-(102.0,8.89) %.2f' % d((P[r]['x'], P[r]['y']), (102.0, 8.89)))
a = pad('R306', '1'); b = pad('J603', '5'); print('R306.1 to J603.5 manhattan %.2f' % (abs(a[0] - b[0]) + abs(a[1] - b[1])))
