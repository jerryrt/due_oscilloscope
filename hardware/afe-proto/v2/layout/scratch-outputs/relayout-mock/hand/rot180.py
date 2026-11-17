"""python3 rot180.py IN OUT REF [REF...]: turn two-pad parts 180 degrees in place (scratch). Text splice of the footprint's (at x y rot)."""
import re, sys
inp, out, *refs = sys.argv[1:]
t = open(inp).read()
for ref in refs:
    i = t.index('(property "Reference" "%s"' % ref); s = t.rfind('\n\t(footprint ', 0, i)
    m = re.compile(r'\(at ([\d.\-]+) ([\d.\-]+)(?: ([\d.\-]+))?\)').search(t, s)
    x, y, r = m.group(1), m.group(2), float(m.group(3) or 0)
    new = '(at %s %s %g)' % (x, y, (r + 180) % 360)
    t = t[:m.start()] + new + t[m.end():]
    pm = re.compile(r'\(property "Reference" "%s"\s+\(at ([\-\d.]+) ([\-\d.]+)' % ref).search(t, s)
    t = t[:pm.start(1)] + '%g %g' % (-float(pm.group(1)), -float(pm.group(2))) + t[pm.end(2):]      # the label stays where it was: its offset turns with the part
open(out, 'w').write(t)
print('turned', refs)
