"""python3 _work/final_report.py MAIN.kicad_pcb NEW.kicad_pcb PLAN.json   (in the image, cwd the checker checkout)"""
import sys, json, re, collections
sys.path.insert(0, '/work/hardware/afe-proto'); sys.path.append('/usr/lib/python3/dist-packages')
import numpy as np
from pcbtools import boardio, silkread, align, rules
from pcbtools.boards import v2_layout as C
import os
if os.environ.get('RECTS_JSON'): C.OUTLINE = {k: [tuple(r) for r in v] for k, v in json.load(open(os.environ['RECTS_JSON'])).items()}
LABELS = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}
EDGE = {'J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607'}
main, new, planp = sys.argv[1:4]
plan = json.load(open(planp))
bm, bn = boardio.read_board(main), boardio.read_board(new)
def shown(b):
    out = {}
    for j in range(len(b.r_fp)):
        r = b.fp_ref[list(b.fp_idx).index(int(b.r_fp[j]))]
        if b.r_on_silk[j] and int(b.r_layer[j]) == boardio.R_LAYERS['F.SilkS']: out[r] = (float(b.r_x[j]), float(b.r_y[j]), float(b.r_ang[j]))
    return out
sm, sn = shown(bm), shown(bn)
refs = list(bn.fp_ref)
def block(r):
    v = C.BLOCK.get(r)
    if v: return v
    return 'EDGE' if r in EDGE else ('MH' if r.startswith('MH') else 'other')
print('BLOCK       parts  with-label(new)  without(new)   with-label(main)')
tot = collections.Counter()
for blk in ('POWER', 'CH1', 'CH2', 'AWG', 'REFCAL', 'EDGE', 'MH', 'other'):
    rs = [r for r in refs if block(r) == blk]
    if not rs: continue
    w = sum(1 for r in rs if r in sn); wm = sum(1 for r in rs if r in sm)
    print('%-10s %6d %10d %14d %14d' % (blk, len(rs), w, len(rs) - w, wm)); tot['p'] += len(rs); tot['w'] += w; tot['m'] += wm
print('TOTAL      %6d %10d %14d %14d' % (tot['p'], tot['w'], tot['p'] - tot['w'], tot['m']))
print('without a label (new):', sorted(r for r in refs if r not in sn))
print('beside set (east/west at 0 degrees):', plan['beside'])
kinds = collections.Counter(v[0] for v in plan['placed'].values()); print('places used by passives and anchors:', dict(kinds))
anch = [r for r in refs if r[0] in 'UJ' and not r.startswith('MH') or r.startswith('TP')]
bnc = ('J101', 'J201', 'J301')
print('ANCHORS (U, J, TP):')
allok = True
for r in sorted(anch, key=lambda r: (r[0], int(re.sub(r'\D', '', r)))):
    state = plan['anchors'].get(r)
    ok = (r in sn)
    if not state: allok = False
    print('   %-5s visible=%s  %s' % (r, 'yes' if ok else 'NO', state or 'NO PLACE (kept as on main)'))
print('ALL ANCHORS LABELLED BY A PLACE THE TEST ACCEPTS:', 'yes' if allok else 'NO')
f0 = silkread.findings(bm, LABELS, edge_headers=EDGE, silk=silkread.read_silk(open(main).read()))
f1 = silkread.findings(bn, LABELS, edge_headers=EDGE, silk=silkread.read_silk(open(new).read()), beside=set(plan['beside']))
print('silkread (silk-above) findings: main', len(f0), ' new', len(f1))
byref = collections.Counter(s.split(':')[0] for s in f1)
nolabel = {s.split(':')[0] for s in f1 if 'no designator' in s}
new_places = {r for r, v in plan['placed'].items() if v[0] in ('below', 'east90', 'west90')}
print('  of the new findings: %d are "no designator" (the part lost its label), %d name a part placed below or at 90 degrees (the owner\'s order, not in silk-above\'s rules), rest %d' %
      (len(nolabel), len({r for r in byref if r in new_places and r not in nolabel}), len({r for r in byref if r not in nolabel and r not in new_places})))
print('  rest:', [s[:120] for s in f1 if s.split(':')[0] not in nolabel and s.split(':')[0] not in new_places][:25])
a0, a1 = align.findings(bm), align.findings(bn); print('align findings: main', len(a0), ' new', len(a1))
for tag, b in (('main', bm), ('new', bn)):
    close, over, far, n = rules.designator_findings(b, C)
    print('LR-11 terms %-4s: pairs under %.1f mm %d, over a pad %d, too far %d, designators judged %d, one-label %d, foreign %d' % (tag, C.DESIGNATOR_GAP_MIN, len(close), len(over), len(far), n, len(rules.one_label_pairs(b, C)), len(rules.foreign_labels(b, C))))
# labels outside the board outline
ring = [tuple(p) for p in bn.outline]
def inside(px, py):
    c = False
    for i in range(len(ring)):
        (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % len(ring)]
        if (y0 > py) != (y1 > py) and px < (x1 - x0) * (py - y0) / (y1 - y0) + x0: c = not c
    return c
out = [r for r, (x, y, a) in sn.items() if not inside(x, y)]
print('labels whose centre is outside the board outline:', out)
# ---- rules (b) and (c)
def lgap(a, c): return float(np.hypot(max(c[0] - a[2], 0.0, a[0] - c[2]), max(c[1] - a[3], 0.0, a[1] - c[3])))
courts = {bn.fp_ref[i]: silkread._box(bn.fp_cx0[i], bn.fp_cy0[i], bn.fp_cx1[i], bn.fp_cy1[i]) for i in range(len(bn.fp_ref)) if not np.isnan(bn.fp_cx0[i])}
sb = {}
for j in range(len(bn.r_fp)):
    r = bn.fp_ref[list(bn.fp_idx).index(int(bn.r_fp[j]))]
    if bn.r_on_silk[j] and int(bn.r_layer[j]) == boardio.R_LAYERS['F.SilkS']: sb[r] = silkread.text_box(r, bn.r_x[j], bn.r_y[j], bn.r_w[j], bn.r_h[j], bn.r_ang[j])
stack = []
for r, box in sb.items():
    d_own = lgap(box, courts[r]); d_oth, who = min((lgap(box, o), q) for q, o in sb.items() if q != r)
    if d_oth <= d_own: stack.append((r, who, round(d_oth, 2), round(d_own, 2)))
print('(c) labels whose nearest other label is not farther than their own part:', stack)
bad_in = []
for r, box in sb.items():
    home = C.SHARED_PARTS.get(r) or C.BLOCK.get(r)
    rs = C.OUTLINE.get(home) if home and home != C.EDGE_BLOCK else None
    if rs and not any(x0 - 0.005 <= box[0] and box[2] <= x1 + 0.005 and y0 - 0.005 <= box[1] and box[3] <= y1 + 0.005 for x0, y0, x1, y1 in rs): bad_in.append(r)
print('(b) labels not inside their own block outline:', bad_in)
