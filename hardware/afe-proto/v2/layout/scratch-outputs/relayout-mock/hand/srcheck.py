"""python3 srcheck.py BOARD [extra beside refs ...]: the D30 reading of tests/pcbtools/test_silkread.py on a board (OPEN list, with the named exceptions)"""
import sys, re
sys.path.insert(0, '/work/hardware/afe-proto'); sys.path.insert(0, '/work/hardware/afe-proto/tests/pcbtools')
from pcbtools import boardio, silkread
src = open('/work/hardware/afe-proto/tests/pcbtools/test_silkread.py').read()
ns = {}
LABELS = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}
EDGE = {'J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607'}
m = re.search(r"BESIDE = (\{.*?\})\n", src, re.S); BES = eval(m.group(1))['v2/layout/integrated/afe-v2-integrated.kicad_pcb']
m = re.search(r"EAST_END = (\{.*?\})\n", src, re.S); EAST = eval(m.group(1))['v2/layout/integrated/afe-v2-integrated.kicad_pcb']
extra = set(sys.argv[2:])
p = sys.argv[1]; text = open(p).read()
f = silkread.findings(boardio.read_board(p), LABELS, edge_headers=EDGE, silk=silkread.read_silk(text), east_end=EAST, beside=BES | extra)
print('silkread findings (beside set %d + %d extra): %d' % (len(BES), len(extra), len(f)))
for x in f: print('  ', x[:200])
