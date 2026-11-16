import json, re, sys
sys.path.insert(0, 'kicad')
J = json.load(open('whatif/_scratch/relay_pos.json'))
ROT = json.load(open('whatif/_scratch/rot.json'))
import os
if os.path.exists('whatif/_scratch/rotov.json'): ROT.update(json.load(open('whatif/_scratch/rotov.json')))
src = open('kicad/layout.py').read()
src = src.split('\n# ----- D30 relayout')[0].rstrip('\n') + '\n'
import importlib.util
import types
m = types.ModuleType('lay0'); exec(compile(src, 'layout0', 'exec'), m.__dict__)
anch = {'J601','J602','J603','J604','J605','J606','J607','J101','J201','J301','MH601','MH602','R411'}
rows = []
for r in sorted(J, key=lambda s: (re.sub(r'\d', '', s), int(re.sub(r'\D', '', s)))):
    if r in m.PLACE and r not in anch:
        x, y = J[r]
        if abs(x - m.PLACE[r][0]) > 1e-6 or abs(y - m.PLACE[r][1]) > 1e-6 or abs(ROT[r] - m.PLACE[r][2]) > 1e-6:
            rows.append((r, round(x, 3), round(y, 3), round(ROT[r]) % 360))
body = '\n# ----- D30 relayout (pcbtools/labelplace.py): label room above every part; rotations from the landed board. Hand-routed fan-outs above no longer apply.\nRELAID = {\n'
body += ''.join(f"    '{r}': ({x}, {y}, {a}),\n" for r, x, y, a in rows) + '}\nfor _ref, (_x, _y, _a) in RELAID.items():\n    put(_ref, _x, _y, _a)\nPREROUTE = []\nPREVIA = []\n'
open('kicad/layout.py', 'w').write(src + body)
print(len(rows), 'parts moved')
