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
extra_p = plan_p.replace('.json', '_extra.json')
if os.path.exists(extra_p):
    import uuid
    ex = json.load(open(extra_p)); kx = lambda x: round(x + 50.0, 4); ky = lambda y: round(150.0 - y, 4)
    for name, v in ex['names'].items():                    # block names: one size, moved to their corner
        if v is None: continue
        m = re.search(r'\(gr_text "%s"\s*\(at [-\d.]+ [-\d.]+ [-\d.]+\)' % re.escape(name), res)
        assert m, name
        end = res.index('\n\t)\n', m.start())
        blk = res[m.start():end]
        blk = re.sub(r'\(at [-\d.]+ [-\d.]+ ([-\d.]+)\)', lambda q: '(at %s %s %s)' % (kx(v[0]), ky(v[1]), q.group(1)), blk, 1)
        blk = re.sub(r'\(size [-\d.]+ [-\d.]+\)', '(size %g %g)' % (v[2], v[2]), blk, 1)
        blk = re.sub(r'\(thickness [-\d.]+\)', '(thickness 0.2)', blk, 1)
        res = res[:m.start()] + blk + res[end:]
    add = ''
    for text, (x, y) in ex['bncfn'].items():               # the BNC function labels, outside the bodies
        add += '\t(gr_text "%s"\n\t\t(at %s %s %d)\n\t\t(layer "F.SilkS")\n\t\t(uuid "%s")\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1 1)\n\t\t\t\t(thickness 0.15)\n\t\t\t)\n\t\t\t(justify left)\n\t\t)\n\t)\n' % (text, kx(x), ky(y), ex.get('bncfn_angle', 0), uuid.uuid4())
    for blk, segs in ex['outline'].items():                # each block's full outline
        for x0, y0, x1, y1 in segs:
            add += '\t(gr_line\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(stroke\n\t\t\t(width 0.15)\n\t\t\t(type default)\n\t\t)\n\t\t(layer "F.SilkS")\n\t\t(uuid "%s")\n\t)\n' % (kx(x0), ky(y0), kx(x1), ky(y1), uuid.uuid4())
    k = res.rindex('\t(embedded_fonts')
    res = res[:k] + add + res[k:]
open(out, 'w').write(res)
print('spliced', sum(1 for m in pat.finditer(src) if m.group(2) in plan), 'designators')
