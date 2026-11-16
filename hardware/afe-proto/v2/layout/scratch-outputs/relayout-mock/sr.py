import sys, re
sys.path.insert(0, '/work/hardware/afe-proto')
from pcbtools import boardio, silkread
b = boardio.read_board_retry(sys.argv[1])
BNC = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}
H = {'J601','J602','J603','J604','J605','J606','J607'}
f = silkread.findings(b, BNC, edge_headers=H, silk=silkread.read_silk(open(sys.argv[1]).read()))
print('total', len(f))
ch2 = re.compile(r'^(R20[1-8]|C20[1-3]|D201|TP201|J201):')
c = [x for x in f if ch2.match(x)]
print('CH2', len(c))
for x in (c if len(sys.argv) < 3 else f): print(x)
