import json, runpy, os
runpy.run_path('kicad/relayout/variant_p33.py')
p = 'kicad/design.py'; s = open(p).read()
if 'R521' not in s:
    s = s.replace("two('R511', '4.7k', 'SCL1_A', 'P33_R',", "two('R511', '4.7k', 'SCL1_B', 'P33_R',")
    s = s.replace("two('R517', '0Rb'", "two('R521', '0Rb', 'SCL1_A', 'SCL1_B', 'cal', 'bridge on SCL1 at the ADS: the pull-up R511 behind it (scratch what-if)')\ntwo('R517', '0Rb'", 1)
    open(p, 'w').write(s)
p = 'kicad/floorplan.py'; s = open(p).read()
if 'R521' not in s:
    s = s.replace("    ('BR4 (R309)'", "    ('BR11 (R521)', 'SCL1_A / SCL1_B', (55.0, 25.25), 'the P33_R branch under the ADS'),\n    ('BR4 (R309)'")
    open(p, 'w').write(s)
J = json.load(open('whatif/_scratch/pos_keep.json')); J['R521'] = [55.0, 25.25]; json.dump(J, open('whatif/_scratch/pos_keep.json', 'w'), indent=1)
R = json.load(open('whatif/_scratch/rot.json')); R['R521'] = 0.0; json.dump(R, open('whatif/_scratch/rot.json', 'w'), indent=1)
