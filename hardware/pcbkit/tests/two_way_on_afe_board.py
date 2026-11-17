"""Print the two-way nearest test of pcbkit.rules.two_way_test on one board, in the format of the AFE-2 label job's stackcheck.py, to compare the
two on the same file (run in the image from the repository root: python3 hardware/pcbkit/tests/two_way_on_afe_board.py BOARD.kicad_pcb)."""
import sys

sys.path.insert(0, 'hardware/pcbkit')
sys.path.append('/usr/lib/python3/dist-packages')
from pcbkit import board, rules   # noqa: E402

cfg = dict(SILK_REQUIRED_PREFIXES=('U', 'J', 'TP', 'D'), LABEL_TEXTS={'CH1 IN': 'J101', 'CH2 IN': 'J201', 'AWG OUT': 'J301'})
b = board.read_board(sys.argv[1], (50.0, 150.0))
out = rules.two_way_test(b, cfg)
bad = {p: v for p, v in out.items() if v[1] or v[2]}
print('parts with a label', len(out), '; failing either step', len(bad))
for p, (own, s1, s2) in sorted(bad.items()):
    print('  FAIL %-6s %s %s' % (p, ('step1(label: own part %.2f, but %s at %.2f)' % (s1[2], s1[1], s1[3])) if s1 else '',
                              ('step2(part: own label %.2f, other label of %s at %.2f)' % (s2[2], s2[1], s2[3])) if s2 else ''))
for p, (own, s1, s2) in sorted(out.items()):
    print('  %s own %.4f' % (p, own))
