import sys, json, collections
sys.path.insert(0, '.')
from pcbtools import boardio, silkread
from pcbtools.boards import v1 as C
path, plan_p = sys.argv[1], sys.argv[2]
plan = json.load(open(plan_p)); off = {r for r, v in plan.items() if v is None}
b = boardio.read_board(path)
f = silkread.findings(b, (), {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}, {r: 'no place' for r in off}, {})
print('silkread findings (labelled parts judged, no-place parts exempt):', len(f))
for x in f[:15]: print('  ', x[:160])
