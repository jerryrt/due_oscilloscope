"""Break each changed check once on purpose, show the failing output, restore the board. Host python; each run is one pytest in the PCB image."""
import re, subprocess, sys, shutil
B = 'hardware/afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pcb'
TD = 'hardware/afe-proto/tests/pcbtools/'
orig = open(B).read()
def run(k, files):
    r = subprocess.run(['docker/pcb/run.sh', '-m', '3G', '-t', '300', '-c', '2', 'python3', '-m', 'pytest', '-q', '-c', 'hardware/afe-proto/tests/pytest.ini', '-p', 'no:cacheprovider', '-k', k] + [TD + f for f in files],
                       capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if l.startswith(('FAILED', 'E  ')) or ' passed' in l or ' failed' in l]
    return '\n'.join(l[:230] for l in lines[:6])
def prop(ref):
    i = orig.index('(property "Reference" "%s"' % ref); return i
muts = []
# 1. an outline line shifted by 1 mm: the polygon test must fail
m = re.search(r'\n\t\(gr_line\n\t\t\(start 112.4 117.1\)', orig) or re.search(r'\n\t\(gr_line\n\t\t\(start ([-\d.]+) 117.1\)', orig)
def shift_outline(t):
    mm = re.search(r'(\n\t\(gr_line\n\t\t\(start )([-\d.]+) 11[67](?:\.\d+)?\)\n\t\t\(end ([-\d.]+) (11[67](?:\.\d+)?)\)', t)
    new = mm.group(0).replace('11' + mm.group(4)[2:] + ')', '')
    y = float(mm.group(4))
    new = re.sub(r'\(start ([-\d.]+) [-\d.]+\)', lambda q: '(start %s %.2f)' % (q.group(1), y + 1.0), mm.group(0), count=1)
    new = re.sub(r'\(end ([-\d.]+) [-\d.]+\)', lambda q: '(end %s %.2f)' % (q.group(1), y + 1.0), new, count=1)
    return t[:mm.start()] + new + t[mm.end():]
muts.append(('a horizontal outline line moved 1 mm across', shift_outline, 'board_silk_outlines', ['test_outlines_legibility.py']))
# 2. a BNC designator back on the top silk
def bnc_top(t):
    i = t.index('(property "Reference" "J101"'); j = t.index('\n\t\t)', i)
    blk = t[i:j].replace('(layer "B.SilkS")', '(layer "F.SilkS")').replace('\n\t\t\t\t(justify mirror)', '')
    return t[:i] + blk + t[j:]
muts.append(('J101 designator on the top silk', bnc_top, 'integrated_board_lr11', ['test_outlines_legibility.py']))
# 3. two labels 0.1 mm closer than 0.5: R105's label moved
def close_labels(t):
    i = t.index('(property "Reference" "R105"'); j = t.index('\n\t\t)', i)
    blk = re.sub(r'\(at ([-\d.]+) ([-\d.]+) 0\)', lambda m: '(at %.3f %s 0)' % (float(m.group(1)) + 0.12, m.group(2)), t[i:j], count=1)
    return t[:i] + blk + t[j:]
muts.append(('R105 label 0.12 mm toward its neighbour', close_labels, 'integrated_board_lr11', ['test_outlines_legibility.py']))
# 4. the J605 label off the config
def j605(t):
    i = t.index('(property "Reference" "J605"'); j = t.index('\n\t\t)', i)
    blk = re.sub(r'\(at ([-\d.]+) ([-\d.]+) 0\)', lambda m: '(at %.3f %.3f 0)' % (float(m.group(1)) + 0.3, float(m.group(2))), t[i:j], count=1)
    return t[:i] + blk + t[j:]
muts.append(('J605 label 0.3 mm off the config', j605, 'j605_label', ['test_v2_bnc_pitch.py']))
# 5. the BNC input stub removed
def nostub(t):
    return re.sub(r'\n\t\(segment\n\t\t\(start 152 122\.18\)\n\t\t\(end 151 122\.18\)\n.*?\n\t\)', '', t, count=1, flags=re.S)
muts.append(('the CH2 BNC input stub removed', nostub, 'leaves_its_bnc', ['test_v2_bnc_pitch.py']))
# 6. an outline line across a header's silk (DRC silk overlap)
def across(t):
    seg = '\n\t(gr_line\n\t\t(start 70 100.5)\n\t\t(end 120 100.5)\n\t\t(stroke\n\t\t\t(width 0.15)\n\t\t\t(type default)\n\t\t)\n\t\t(layer "F.SilkS")\n\t\t(uuid "00000000-0000-4000-8000-000000000001")\n\t)'
    k = t.index('\n\t(gr_line'); return t[:k] + seg + t[k:]
muts.append(('an outline line across the J607 silk', across, 'kicad_drc_has_no_silk', ['test_pinlabels.py']))
for name, fn, k, files in muts:
    new = fn(orig)
    print('MUTATION:', name, '(board text changed: %s)' % (new != orig))
    open(B, 'w').write(new)
    try:
        print(run(k, files))
    finally:
        open(B, 'w').write(orig)
    print()
print('restored:', open(B).read() == orig)
