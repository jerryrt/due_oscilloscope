import sys
from pcbtools import boardio, rules
from pcbtools.boards import v1 as cfg
b=boardio.read_board(sys.argv[1])
r=rules.lr11(b,cfg)
print(r.ok)
import re
for part in r.detail.split('; '): 
    if re.search(r'\b[RCDUJT][P]?[12]\d\d\b|CH1|CH2|SCOPE',part): print(part)
print(len(r.detail.split('; ')))
