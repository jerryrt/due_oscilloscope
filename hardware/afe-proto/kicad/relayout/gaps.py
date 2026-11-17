"""gaps.py DRC_JSON : unconnected items by block (outline membership of the first item), with hop/bridge need."""
import json, re, sys
from collections import defaultdict
from pcbtools.boards import v1 as C
d = json.load(open(sys.argv[1]))
def block(x, y):
    for blk in ('POWER', 'AWG', 'REFCAL', 'SCOPE'):
        for (x0, y0, x1, y1) in C.OUTLINE[blk]:
            if x0 <= x <= x1 and y0 <= y <= y1: return blk
    return 'OTHER'
by = defaultdict(lambda: defaultdict(list))
for u in d['unconnected_items']:
    it = u['items']; net = re.search(r'\[(/[^\]]*)\]', it[0]['description']).group(1)
    if net == '/GND': by['GND'][net].append(1); continue
    x = it[0]['pos']['x'] - 50; y = 150 - it[0]['pos']['y']
    by[block(x, y)][net].append((round(x, 1), round(y, 1)))
tot = 0
for blk, nets in sorted(by.items()):
    n = sum(len(v) for v in nets.values()); tot += n
    need = 'hop (<= 3 mm, outside fences)' if blk in ('POWER', 'OTHER') else ('GND via position' if blk == 'GND' else 'bridge')
    print('GAPS', blk, n, '->', need, {k: len(v) for k, v in sorted(nets.items())})
print('GAPS total', tot)
