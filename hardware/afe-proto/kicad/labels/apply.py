"""apply.py BOARD PLAN.json OUT: write the plan into the board as a TEXT SPLICE of the Reference properties only (position and layer), so the diff is those lines and
nothing else. The new positions come from pcbnew (editor.set_ref / set_ref_pose, which know the footprint frame) on a scratch copy; a designator with no place goes to F.Fab."""
import sys, json, re, tempfile, os
sys.path.insert(0, '.'); sys.path.append('/usr/lib/python3/dist-packages')
from pcbtools.editor import edit
board, plan_p, out = sys.argv[1:4]
plan = json.load(open(plan_p))
tmp = out + '.tmp'
with edit(board, tmp) as e:
    for r, v in plan.items():
        if v is None: e.set_ref(r, 0, 0, on_silk=False)
        else:
            e.set_ref(r, v[0], v[1], h=1.0); e.set_ref_pose(r, v[0], v[1], v[2])
new = open(tmp).read(); os.remove(tmp)
pat = re.compile(r'(\(property "Reference" "([^"]+)"\s*)\(at ([^)]*)\)(\s*)\(layer "([^"]*)"\)')
info = {m.group(2): (m.group(3), m.group(5)) for m in pat.finditer(new)}
src = open(board).read()
def sub(m):
    r = m.group(2)
    if r not in plan or r not in info: return m.group(0)
    at, layer = info[r]
    if plan[r] is None:
        # off the silk: keep the position, change the layer only
        return f'{m.group(1)}(at {m.group(3)}){m.group(4)}(layer "{layer}")'
    return f'{m.group(1)}(at {at}){m.group(4)}(layer "{layer}")'
res = pat.sub(sub, src)
open(out, 'w').write(res)
print('spliced', sum(1 for m in pat.finditer(src) if m.group(2) in plan), 'designators')
