"""python3 _work/verify.py BOARD [PLAN.json]  (in the image, cwd the checker checkout): silkread (silk-above) with the plan's beside / east_end sets, align, LR-11's legibility terms."""
import sys, json, re, collections
sys.path.insert(0, '/work/hardware/afe-proto'); sys.path.append('/usr/lib/python3/dist-packages')
from pcbtools import boardio, silkread, align, rules
from pcbtools.boards import v2_layout as C
LABELS = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}
EDGE = {'J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607'}
path = sys.argv[1]; plan = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else {'beside': [], 'east_end': []}
b = boardio.read_board(path); silk = silkread.read_silk(open(path).read())
f = silkread.findings(b, LABELS, edge_headers=EDGE, silk=silk, east_end=set(plan['east_end']), beside=set(plan['beside']))
print('silkread findings', len(f)); [print('  ', s[:160]) for s in f[:40]]
a = align.findings(b); print('align findings', len(a)); [print('  ', s[:160]) for s in a[:10]]
close, over, far, n = rules.designator_findings(b, C)
print('LR-11 terms: pairs under %.1f mm: %d, over a pad: %d, too far: %d, judged %d, one-label %d, foreign %d' % (C.DESIGNATOR_GAP_MIN, len(close), len(over), len(far), n, len(rules.one_label_pairs(b, C)), len(rules.foreign_labels(b, C))))
shown = {b.fp_ref[list(b.fp_idx).index(int(b.r_fp[j]))] for j in range(len(b.r_fp)) if b.r_on_silk[j]}
print('visible top designators', len(shown), 'of', len(b.fp_ref))
