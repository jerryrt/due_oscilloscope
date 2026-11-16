import os
import json, re, ast
pos = json.load(open('relay_pos_base.json')); rotov = json.load(open('rotov_base.json')); lab = json.load(open('labmode_base.json')); rot0 = json.load(open('rot.json'))
import json as _j
REST = {'1': {'C105': (83.9, 39.3), 'R102': (88.15, 39.3), 'R101': (89.9, 42.3)}, '2': _j.loads(os.environ.get('REST2', '{"C203": [86.4, 30.9], "R202": [87.4, 27.9], "R201": [83.15, 27.9]}'))}
import os
K1 = int(os.environ.get('K1', '7')); K2 = int(os.environ.get('K2', '0'))
for ch, k in (('1', K1), ('2', K2)):
    l = [x for x in open(f'tm_{ch}.txt') if x.startswith('RES ')][k]
    spec = ast.literal_eval(re.match(r"RES (\S+) (\S+) (\S+) (\S+) (\[.*\])", l).group(5))
    for ref, x, y, d, mode in spec:
        pos[ref] = [x, y]
        if d: rotov[ref] = int((rotov.get(ref, rot0[ref]) + d) % 360)
        lab[ref] = 'W' if mode == 2 else 'E'
    for ref, (x, y) in REST[ch].items(): pos[ref] = [x, y]
json.dump(pos, open('relay_pos.json', 'w')); json.dump(rotov, open('rotov.json', 'w'))
for f in ('labmode.json', 'labmode_E.json', 'labmode_W.json'): json.dump(lab, open(f, 'w'))
print({r: pos[r] for r in ('C101','C102','R101','R102','R103','R104','R105','R106','C105','C201','C202','C203','R201','R202','R203','R204','R205','R206')})
