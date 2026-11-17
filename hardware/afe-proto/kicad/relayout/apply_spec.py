"""apply_spec.py SPEC: make a ref:dx:dy:rot move list permanent in pos_keep.json / rotov_keep2.json (the live placement files)"""
import json, sys
J = json.load(open('whatif/_scratch/pos_keep.json')); R = json.load(open('whatif/_scratch/rotov_keep2.json'))
for it in [s for s in sys.argv[1].split(';') if s]:
    r, dx, dy, rot = it.split(':')
    J[r] = [round(J[r][0] + float(dx), 3), round(J[r][1] + float(dy), 3)]
    if rot != '-': R[r] = int(rot)
json.dump(J, open('whatif/_scratch/pos_keep.json', 'w'), indent=1); json.dump(R, open('whatif/_scratch/rotov_keep2.json', 'w'), indent=1)
print('applied', len([s for s in sys.argv[1].split(';') if s]))
