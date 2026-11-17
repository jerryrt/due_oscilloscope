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
open(out, 'w').write(t)
print('turned', refs)
