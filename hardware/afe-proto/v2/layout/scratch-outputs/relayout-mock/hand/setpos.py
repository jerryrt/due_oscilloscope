"""python3 setpos.py IN OUT MAIN.json REF [REF...]: put the named parts at main's origin and rotation (main_vs_cur.json 'main': ref -> [x, y, rot], Due mm). Labels keep their own offsets (scratch)."""
import json, re, sys
inp, out, mj, *refs = sys.argv[1:]
M = json.load(open(mj))['main']
t = open(inp).read()
for ref in refs:
    x, y, rot = M[ref]
    i = t.index('(property "Reference" "%s"' % ref); s = t.rfind('\n\t(footprint ', 0, i)
    m = re.compile(r'\(at ([\d.\-]+) ([\d.\-]+)(?: ([\d.\-]+))?\)').search(t, s)
    t = t[:m.start()] + '(at %.4f %.4f %d)' % (x + 50, 150 - y, rot) + t[m.end():]
open(out, 'w').write(t)
print('placed', len(refs), 'parts at main')
