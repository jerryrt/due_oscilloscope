"""python3 permute.py IN.kicad_pcb OUT.kicad_pcb 'R501=S505:1,R502=S503:1,...'  slot swap of the ladder resistors: part=SLOT:TURN (TURN 1 = rot 180), the label goes to the slot's label place."""
import re, sys
inp, out, spec = sys.argv[1:4]
SL = {'S501': (47.35, 11.25, 47.1, 13.1), 'S502': (47.1, 15.25, 46.85, 17.1), 'S503': (50.85, 27.5, 50.6, 29.35), 'S504': (53.55, 5.525, 53.8, 7.38),
      'S505': (54.93, 27.5, 54.93, 29.35), 'S506': (49.67, 5.625, 49.42, 7.47)}          # origin x, y and label x, y, Due mm: the slots as the committed board has them
t = open(inp).read()
for item in spec.split(','):
    ref, v = item.split('='); slot, turn = v.split(':'); ox, oy, lx, ly = SL[slot]; turn = int(turn)
    i = t.index('(property "Reference" "%s"' % ref); s = t.rfind('\n\t(footprint ', 0, i)
    m = re.compile(r'\(at ([\d.\-]+) ([\d.\-]+)(?: ([\d.\-]+))?\)').search(t, s)
    t = t[:m.start()] + '(at %.4f %.4f %d)' % (ox + 50, 150 - oy, 180 if turn else 0) + t[m.end():]
    i = t.index('(property "Reference" "%s"' % ref, s)
    pm = re.compile(r'\(property "Reference" "%s"\s+\(at ([\-\d.]+) ([\-\d.]+)' % ref).search(t, s)
    dx, dy = lx - ox, -(ly - oy)
    if turn: dx, dy = -dx, -dy
    t = t[:pm.start(1)] + '%g %g' % (round(dx, 3), round(dy, 3)) + t[pm.end(2):]
open(out, 'w').write(t)
print('permuted', spec)
