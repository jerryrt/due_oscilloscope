import sys
from pcbtools import boardio, silkread
from pcbtools.boards import v1 as C
p = sys.argv[1]
b = boardio.read_board(p)
txt = open(p).read()
f = silkread.findings(b, {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}, edge_headers=('J601','J602','J603','J604','J605','J606','J607'), silk=silkread.read_silk(txt), east_end={'U301','U101'}, beside={'R302','R303','C301','R305','C302','C405','C401','C409','C402','C101','C102','R103','R104','R105','R106','C201','C202','R203','R204','R205','R206'})
print(len(f))
for x in f[:int(sys.argv[2]) if len(sys.argv) > 2 else 40]: print(x[:170])
