import sys, os
os.environ['BLK'] = 'CH2'
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock')
import cspfit as C
t = C.T.template('swap0_flip1', 83.1, 23.0)       # the old CH2 base template: R207 top row at y 26.6
print('template', {r: (round(v[0], 2), round(v[1], 2), v[2], v[3]) for r, v in t.items()})
res, info = C.solve(t, tl=40)
print('all obstacles:', 'FIT' if res else info)
ob = C.fixed_obstacles(t)
near = [k for k, d in ob.items() if d['cy'] is not None and (d['cy'][2] > 60 and d['cy'][0] < 95 and d['cy'][3] > 15 and d['cy'][1] < 40)]
near += [k for k in ob if k.startswith('_')]
for k in sorted(set(near)):
    res, info = C.solve(t, skip=(k,), tl=25)
    print('skip', k, '->', 'FIT' if res else info[0])
