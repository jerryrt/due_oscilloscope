import sys, json
v = sys.argv[1]            # A: pad 1 (west) = R516 side, pad 2 = R204 side ; B: the other way
p = 'kicad/design.py'; s = open(p).read()
if 'R208' not in s:
    s = s.replace("'VREF' if ch == 'CH1' else 'VREF_P', B,", "'VREF' if ch == 'CH1' else 'VREF_T', B,")
    s = s.replace("two('R516', '0Rb', 'VREF_M', 'VREF_P', 'cal',", "two('R516', '0Rb', 'VREF_M', 'VREF_P', 'cal',")
    a, b2 = ('VREF_P', 'VREF_T') if v == 'A' else ('VREF_T', 'VREF_P')
    s = s.replace("two('C303',", "two('R208', '0Rb', '%s', '%s', 'ch2', 'bridge over CH2_IN: the CH2 centring leg of VREF (D24, a reference line)')\ntwo('C303'," % (a, b2), 1)
    open(p, 'w').write(s)
p = 'kicad/floorplan.py'; s = open(p).read()
if 'R208' not in s:
    s = s.replace("    ('BR4 (R309)'", "    ('BR10 (R208)', 'VREF_P / VREF_T', (87.5, 29.5), 'the CH2_IN approach to R202.1'),\n    ('BR4 (R309)'")
    open(p, 'w').write(s)
J = json.load(open('whatif/_scratch/pos_keep.json')); J['R208'] = [87.5, 29.5]
json.dump(J, open('whatif/_scratch/pos_keep.json', 'w'), indent=1)
