import sys, re, collections
sys.path.insert(0, '/work/hardware/afe-proto')
from pcbtools import boardio, silkread, align
b = boardio.read_board_retry(sys.argv[1])
BNC = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}
H = {'J601','J602','J603','J604','J605','J606','J607'}
f = silkread.findings(b, BNC, edge_headers=H, silk=silkread.read_silk(open(sys.argv[1]).read()))
print('silkread', len(f))
for x in f: print('  ', x)
a = align.findings(b)
cnt = collections.Counter()
for x in a:
    m = re.match(r'([A-Z]+)(\d)\d\d', x)
    cnt[m.group(2) if m else '?'] += 1
print('align', len(a), dict(cnt))
for x in a: print('  ', x)
