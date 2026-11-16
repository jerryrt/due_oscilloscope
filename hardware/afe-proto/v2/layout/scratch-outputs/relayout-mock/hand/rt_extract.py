"""extract the router's segments/vias from a pcbnew-saved board into a spec: python3 rt_extract.py IN OUT.py"""
import re, sys
s = open(sys.argv[1]).read()
segs, vias = [], []
for m in re.finditer(r'\n\t\(segment\n\t\t\(start ([\d.-]+) ([\d.-]+)\)\n\t\t\(end ([\d.-]+) ([\d.-]+)\)\n\t\t\(width ([\d.]+)\)\n\t\t\(layer "(\w)\.Cu"\)\n\t\t\(net "([^"]*)"\)', s):
    x0, y0, x1, y1, w, l, n = m.groups()
    segs.append((n, l, [(round(float(x0) - 50, 4), round(150 - float(y0), 4)), (round(float(x1) - 50, 4), round(150 - float(y1), 4))], float(w)))
for m in re.finditer(r'\n\t\(via\n\t\t\(at ([\d.-]+) ([\d.-]+)\)\n\t\t\(size [\d.]+\)\n\t\t\(drill [\d.]+\)\n\t\t\(layers "F.Cu" "B.Cu"\)\n\t\t\(net "([^"]*)"\)', s):
    x, y, n = m.groups(); vias.append((n, round(float(x) - 50, 4), round(150 - float(y), 4)))
open(sys.argv[2], 'w').write('ROUTES = %r\nVIAS = %r\n' % (segs, vias))
print(len(segs), len(vias))
