import json
p = 'kicad/design.py'; s = open(p).read()
if 'R520' not in s:
    s = s.replace("part('D502', 'BAV99', {'1': G, '3': 'SNS_TI', '2': 'P33_R'}", "part('D502', 'BAV99', {'1': G, '3': 'SNS_TI', '2': 'P33_C'}")
    s = s.replace("part('D501', 'BAV99', {'1': G, '3': 'SNS_BI', '2': 'P33_R'}", "part('D501', 'BAV99', {'1': G, '3': 'SNS_BI', '2': 'P33_C'}")
    s = s.replace("two('R517', '0Rb'", "two('R520', '0Rb', 'P33_R', 'P33_C', 'cal', 'bridge on the ADS supply branch: the two input clamps D501/D502 behind it (scratch what-if)')\ntwo('R517', '0Rb'", 1)
    open(p, 'w').write(s)
p = 'kicad/floorplan.py'; s = open(p).read()
if 'R520' not in s:
    s = s.replace("    ('BR4 (R309)'", "    ('BR10 (R520)', 'P33_R / P33_C', (58.25, 28.75), 'the SNS legs under the ADS'),\n    ('BR4 (R309)'")
    open(p, 'w').write(s)
J = json.load(open('whatif/_scratch/pos_keep.json')); J['R520'] = [58.25, 28.75]; json.dump(J, open('whatif/_scratch/pos_keep.json', 'w'), indent=1)
R = json.load(open('whatif/_scratch/rot.json')); R['R520'] = 0.0; json.dump(R, open('whatif/_scratch/rot.json', 'w'), indent=1)
