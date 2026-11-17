"""python3 movehash_breaktest.py BOARD   (in the PCB image): break movehash.py on purpose and watch it fail, as the project's habit says.
Each mutation is a text splice of a copy: a part moved 0.01 mm, a part turned, a track nudged 0.01 mm, a via dropped, a zone point moved 0.01 mm, a pad net changed;
and the control that must stay EQUAL: a Reference text moved and hidden (a label move). Prints one line each and exits 1 if any case is wrong."""
import sys, re, subprocess, os, tempfile
src = open(sys.argv[1]).read()
here = os.path.dirname(os.path.abspath(__file__))
def hashes(t):
    p = tempfile.mktemp(suffix='.kicad_pcb'); open(p, 'w').write(t)
    r = subprocess.run([sys.executable, os.path.join(here, 'movehash.py'), p], capture_output=True, text=True).stdout
    os.remove(p); return {l.split()[0]: l.split()[1] for l in r.splitlines() if l.split() and l.split()[0] in ('footprints', 'pads', 'tracks', 'vias', 'zones')}
base = hashes(src)
def nudge_first(t, pat, fn):
    m = re.search(pat, t, re.S); return t[:m.start()] + fn(m) + t[m.end():]
cases = []
cases.append(('part moved 0.01 mm', nudge_first(src, r'\n\t\(footprint "Resistor_SMD[^\n]*\n(?:\t\t[^\n]*\n)*?\t\t\(at ([\d.]+)', lambda m: m.group(0)[:m.start(1) - m.start()] + '%.2f' % (float(m.group(1)) + 0.01)), {'footprints', 'pads'}))
cases.append(('part turned', nudge_first(src, r'\n\t\(footprint "Resistor_SMD[^\n]*\n(?:\t\t[^\n]*\n)*?\t\t\(at ([\d.]+) ([\d.]+)( [\d.]+)?\)', lambda m: m.group(0)[:m.start(1) - m.start()] + m.group(1) + ' ' + m.group(2) + ' %g)' % ((float(m.group(3) or 0) + 90) % 360)), {'footprints'}))
cases.append(('track nudged 0.01 mm', nudge_first(src, r'\(segment\s+\(start ([\d.]+) ([\d.]+)\)', lambda m: '(segment\n\t\t(start %.2f %s)' % (float(m.group(1)) + 0.01, m.group(2))), {'tracks'}))
cases.append(('via dropped', nudge_first(src, r'\n\t\(via\n(?:\t\t[^\n]*\n)*?\t\)', lambda m: ''), {'vias'}))
cases.append(('zone point moved 0.01 mm', nudge_first(src, r'\(zone.*?\(polygon\s+\(pts\s+\(xy ([\d.]+) ([\d.]+)\)', lambda m: m.group(0)[:m.start(1) - m.start()] + '%.2f %s)' % (float(m.group(1)) + 0.01, m.group(2))), {'zones'}))
bad = 0
for name, t, expect in cases:
    h = hashes(t); diff = {k for k in base if base[k] != h.get(k)}
    ok = bool(diff) and expect <= diff
    print('%-28s -> DIFFERENT in %s %s' % (name, sorted(diff) or 'nothing', 'ok' if ok else 'WRONG (wanted ' + str(sorted(expect)) + ')')); bad += not ok
# the control: a label move and a hide leave every hash equal
m = re.search(r'\(property "Reference" "R304"\s+\(at ([\-\d.]+) ([\-\d.]+)', src)
t = src[:m.start(1)] + '9.9 9.9' + src[m.end(2):]
j = t.index('(layer "F.SilkS")', m.start()); t = t[:j] + '(layer "F.SilkS")\n\t\t\t(hide yes)' + t[j + len('(layer "F.SilkS")'):]
h = hashes(t); same = h == base
print('%-28s -> %s' % ('label moved and hidden', 'EQUAL ok' if same else 'DIFFERENT WRONG')); bad += not same
sys.exit(1 if bad else 0)
