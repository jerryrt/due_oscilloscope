import sys
from pcbtools import boardio, align
for p in sys.argv[1:]:
    b = boardio.read_board(p); f = align.findings(b)
    print(p, len(f)); print('\n'.join(x[:100] for x in f[:12]))
