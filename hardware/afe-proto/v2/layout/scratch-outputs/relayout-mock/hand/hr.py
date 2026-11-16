"""hand-route splicer: python3 hr.py IN.kicad_pcb OUT.kicad_pcb routes.py
routes.py defines ROUTES = [(net, 'F'|'B', [(x, y), ...], width), ...] and VIAS = [(net, x, y), ...] in Due mm (y up).
Text splice only: segments/vias are inserted before the first (gr_circle after the existing segments; everything else is kept byte-for-byte."""
import sys, uuid, hashlib
inp, out, spec = sys.argv[1:4]
ns = {}
exec(open(spec).read(), ns)
s = open(inp).read()
def u(tag):
    h = hashlib.sha1(tag.encode()).hexdigest()
    return f'{h[:8]}-{h[8:12]}-5{h[13:16]}-a{h[17:20]}-{h[20:32]}'
txt = ''
k = 0
for net, lay, pts, w in ns.get('ROUTES', []):
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if (x0, y0) == (x1, y1): continue
        k += 1
        txt += f'\t(segment\n\t\t(start {x0 + 50:.4f} {150 - y0:.4f})\n\t\t(end {x1 + 50:.4f} {150 - y1:.4f})\n\t\t(width {w})\n\t\t(layer "{lay}.Cu")\n\t\t(net "{net}")\n\t\t(uuid "{u("seg%d%s%s" % (k, net, pts))}")\n\t)\n'
for net, x, y in ns.get('VIAS', []):
    k += 1
    txt += f'\t(via\n\t\t(at {x + 50:.4f} {150 - y:.4f})\n\t\t(size 0.6)\n\t\t(drill 0.3)\n\t\t(layers "F.Cu" "B.Cu")\n\t\t(net "{net}")\n\t\t(uuid "{u("via%d%s" % (k, net))}")\n\t)\n'
anchor = '\t(gr_circle\n\t\t(center 140.17 99.2)'
assert s.count(anchor) == 1
open(out, 'w').write(s.replace(anchor, txt + anchor, 1))
print('spliced', k)
