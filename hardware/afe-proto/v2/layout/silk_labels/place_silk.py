"""place_silk.py IN.kicad_pcb OUT.kicad_pcb PLAN.json [SECONDS]    (in the PCB image; the checkers are silk-above's pcbtools, read-only)

Silk-only designator pass on the AFE-2 board. Parts and copper do not move: the only text this writes is each footprint's Reference property (its offset, its
angle, and `(hide yes)` for a part that loses its label).

ONE SEARCH ORDER FOR EVERY LABEL (owner): above, east/west at 0 degrees, below, east/west at 90 degrees; the first place that passes. Passing, for a passive,
is the strict test: silkread's rules (silk-above: a place 0 to 0.6 mm off the courtyard, centred to 0.3, on no courtyard, pad, via drill or silk line, the 3b
reading for every place but above), LR-11's legibility (box to box DESIGNATOR_GAP_MIN, clear of pads, within DESIGNATOR_DIST_MAX of its part, not in another
block's outline) and D31's one label line per row. ANCHORS (every U, J and TP) are placed first and keep a label by a relaxed test where the strict one fails:
not on another part's body (its F.Fab outline), not on a pad, nearest body its own by 0.25 mm (and, because it must stay readable: on no silk line or board
text, clear of other labels). A passive that finds no place loses its label (hidden). Mounting holes carry no designator (hidden). The BNCs are handled by
bnc.py. No exceptions, no keys, no waivers."""
import sys, re, math, json, collections, random, time
sys.path.insert(0, '/work/hardware/afe-proto'); sys.path.append('/usr/lib/python3/dist-packages')
import numpy as np
import pcbnew
from pcbtools import boardio, silkread as S, rules
from pcbtools.boards import v2_layout as C

inp, out, plan_out = sys.argv[1:4]
SECS = float(sys.argv[4]) if len(sys.argv) > 4 else 150.0
txt = open(inp).read()
b = boardio.read_board(inp)
pb = pcbnew.LoadBoard(inp)
mm = pcbnew.ToMM
silk = S.read_silk(txt)
def footprint_silk(pb):
    """every footprint's F.SilkS graphics as ('seg', x0, y0, x1, y1, width) in Due mm: a line as it is, a rectangle by its four edges, anything else (arc, circle) by its box"""
    out = []
    f_ = lambda v: (pcbnew.ToMM(v.x) - 50.0, 150.0 - pcbnew.ToMM(v.y))
    for f in pb.GetFootprints():
        for g in f.GraphicalItems():
            if g.GetLayer() != pcbnew.F_SilkS or not hasattr(g, 'GetShape'): continue
            w = pcbnew.ToMM(g.GetWidth()); sh = g.GetShape()
            if sh == pcbnew.SHAPE_T_SEGMENT:
                (x0, y0), (x1, y1) = f_(g.GetStart()), f_(g.GetEnd()); out.append(('seg', x0, y0, x1, y1, w))
            else:
                bx = g.GetBoundingBox(); x0, y1 = f_(bx.GetOrigin()); x1, y0 = f_(pcbnew.VECTOR2I(bx.GetRight(), bx.GetBottom()))
                for a, c in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))): out.append(('seg', *a, *c, w))
    return out
SILK_CLEAR = 0.2
def on_silk(sb, shapes):
    g = (sb[0] - SILK_CLEAR, sb[1] - SILK_CLEAR, sb[2] + SILK_CLEAR, sb[3] + SILK_CLEAR)
    return any(S._on_shape(g, sh) for sh in shapes)

silk = silk + footprint_silk(pb)
refs = list(b.fp_ref)
row = {int(k): i for i, k in enumerate(b.fp_idx)}
fi = {r: i for i, r in enumerate(refs)}
top = [int(s) == 0 for s in b.fp_side]
cour = {refs[i]: S._box(b.fp_cx0[i], b.fp_cy0[i], b.fp_cx1[i], b.fp_cy1[i]) for i in range(len(refs)) if top[i] and not np.isnan(b.fp_cx0[i])}
body = {}
for f in pb.GetFootprints():                                     # the F.Fab outline of each part: its body
    bx = pcbnew.BOX2I(); n = 0
    for g in f.GraphicalItems():
        if g.GetLayer() == pcbnew.F_Fab: bx.Merge(g.GetBoundingBox()); n += 1
    r = f.GetReference()
    body[r] = (mm(bx.GetX()) - 50.0, 150.0 - mm(bx.GetBottom()), mm(bx.GetRight()) - 50.0, 150.0 - mm(bx.GetY())) if n else cour.get(r)
pads = [(x0, y0, x1, y1) for x0, y0, x1, y1 in zip(b.p_bx0, b.p_by0, b.p_bx1, b.p_by1)]
owner = [refs[int(f)] for f in b.p_fp]
vias = [(x - d / 2 - S.VIA_CLEAR, y - d / 2 - S.VIA_CLEAR, x + d / 2 + S.VIA_CLEAR, y + d / 2 + S.VIA_CLEAR) for x, y, d in zip(b.v_x, b.v_y, b.v_drill)]
texts = [(lambda L: (x - L / 2, y - L / 2, x + L / 2, y + L / 2))(max(len(t.decode() if isinstance(t, bytes) else t) * 0.95 * h, h)) for t, x, y, h in zip(b.t_text, b.t_x, b.t_y, b.t_h)]   # pin labels may be turned: a square of the longer side
BNC = ('J101', 'J201', 'J301')
H = 1.0
ADV_L, H_L = C.DESIGNATOR_ADVANCE, C.DESIGNATOR_INK_H
GAP_MIN, DIST_MAX = C.DESIGNATOR_GAP_MIN, C.DESIGNATOR_DIST_MAX
ORDER = ['above', 'east0', 'west0', 'below', 'east90', 'west90']
BES = ('east0', 'west0', 'below', 'east90', 'west90')          # every place but above is read under 3b


def ang_of(kind): return 90.0 if kind.endswith('90') else 0.0
def sbox(r, x, y, ang=0.0): return S.text_box(r, x, y, 1.0, H, ang)
def lbox(r, x, y, ang=0.0):
    L = len(r) * ADV_L
    return (x - L / 2, y - H_L / 2, x + L / 2, y + H_L / 2) if ang == 0.0 else (x - H_L / 2, y - L / 2, x + H_L / 2, y + L / 2)


def ygrid(lo, hi):
    k = math.ceil(lo / 0.1 - 1e-9); o = []
    while k * 0.1 <= hi + 1e-9: o.append(round(k * 0.1, 3)); k += 1
    return o


def cands(r, kind, c=None):
    """places on an absolute 0.1 mm grid in y (two parts of one row share a label line); x steps for the centring tolerance"""
    c = c or cour[r]; cx, cy = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2
    ang = ang_of(kind); w = len(r) * S.CHAR_ADV if ang == 0.0 else H; hh = H if ang == 0.0 else len(r) * S.CHAR_ADV
    dxs = (0.0, 0.12, -0.12, 0.25, -0.25); gs = (0.03, 0.2, 0.4, 0.57); o = []
    if kind == 'above':
        for y in ygrid(c[3] + 0.03 + hh / 2, c[3] + 0.57 + hh / 2): o += [(cx + d, y) for d in dxs]
    elif kind == 'below':
        for y in ygrid(c[1] - 0.57 - hh / 2, c[1] - 0.03 - hh / 2): o += [(cx + d, y) for d in dxs]
    else:
        for y in ygrid(cy - 0.25, cy + 0.25):
            for g in gs: o.append(((c[2] + g + w / 2) if kind.startswith('east') else (c[0] - g - w / 2), y))
    return o


def in_rects(p, rs): return any(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for x0, y0, x1, y1 in rs)


def lgap(a, c):
    dx = max(c[0] - a[2], 0.0, a[0] - c[2]); dy = max(c[1] - a[3], 0.0, a[1] - c[3])
    return math.hypot(dx, dy)


def blk_rects(r):
    home = C.SHARED_PARTS.get(r) or C.BLOCK.get(r)
    return C.OUTLINE.get(home) if home and home != C.EDGE_BLOCK else None


def inside_blk(sb, r):
    """rule (b): a label sits inside its own block's outline (a part of no block, or of the edge block, has no outline to sit in)"""
    rs = blk_rects(r)
    return True if not rs else any(x0 - 0.005 <= sb[0] and sb[2] <= x1 + 0.005 and y0 - 0.005 <= sb[1] and sb[3] <= y1 + 0.005 for x0, y0, x1, y1 in rs)


def strict_static(r, kind, x, y):
    ang = ang_of(kind); sb, lb = sbox(r, x, y, ang), lbox(r, x, y, ang)
    if any(S._overlap(sb, c) for c in cour.values()): return False
    if any(lgap(lb, p) < 0.02 for p in pads): return False
    if any(S._overlap(sb, v) for v in vias): return False
    if on_silk(sb, silk): return False
    if any(lgap(lb, t) < 0.4 for t in texts): return False
    mine = [p for p, o in zip(pads, owner) if o == r]
    if mine and min(lgap(lb, p) for p in mine) > DIST_MAX: return False
    hm = C.BLOCK.get(r)
    if hm is not None and hm != C.EDGE_BLOCK and r not in C.SHARED_PARTS and r not in C.BLOCK_OVERRIDE:
        ctr = ((lb[0] + lb[2]) / 2, (lb[1] + lb[3]) / 2)
        for blk, rs in C.OUTLINE.items():
            if blk != hm and in_rects(ctr, rs) and C.DESIGNATOR_FOREIGN_WAIVED.get(r) != blk: return False
    if not inside_blk(sb, r): return False
    if kind in BES and any('above' in S._places(sb, c) for k, c in cour.items() if k != r): return False
    return True


def relaxed_static(r, kind, x, y, need_inside=True):
    """anchors only: not on another part's body, not on a pad, nearest body its own by 0.25 mm; plus readability: no silk line, no board text"""
    ang = ang_of(kind); sb = sbox(r, x, y, ang)
    if need_inside and not inside_blk(sb, r): return False
    if any(S._overlap(sb, bd) for k, bd in body.items() if k != r and bd is not None): return False
    if any(S._overlap(sb, p) for p in pads): return False
    if any(S._overlap(sb, v) for v in vias): return False
    own = lgap(sb, body[r]) if body.get(r) else 0.0
    if any(lgap(sb, bd) < own + 0.25 for k, bd in body.items() if k != r and bd is not None): return False
    if on_silk(sb, silk): return False
    if any(lgap(sb, t) < 0.2 for t in texts): return False
    return True


class Cand:
    __slots__ = ('kind', 'x', 'y', 'lb', 'pl', 'rank', 'relaxed')
    def __init__(s, kind, x, y, lb, pl, rank, relaxed=False): s.kind, s.x, s.y, s.lb, s.pl, s.rank, s.relaxed = kind, x, y, lb, pl, rank, relaxed


def make(r, kind, x, y, relaxed=False):
    ang = ang_of(kind)
    return Cand(kind, x, y, lbox(r, x, y, ang), frozenset(o for o, c in cour.items() if o != r and S._places(sbox(r, x, y, ang), c)), ORDER.index(kind), relaxed)


PASSIVE = re.compile(r'(?:R|C|BR|L|FB)(\d)\d\d$')
def orient(rot): return round(float(rot) % 180.0) % 180
rowmates = collections.defaultdict(set)
pl_ = [r for r in refs if top[fi[r]] and PASSIVE.fullmatch(r)]
for a_ in pl_:
    for c_ in pl_:
        if a_ < c_ and PASSIVE.fullmatch(a_).group(1) == PASSIVE.fullmatch(c_).group(1) and orient(b.fp_rot[fi[a_]]) == orient(b.fp_rot[fi[c_]]) \
                and math.hypot(b.fp_x[fi[a_]] - b.fp_x[fi[c_]], b.fp_y[fi[a_]] - b.fp_y[fi[c_]]) <= 8.0 and abs(b.fp_y[fi[a_]] - b.fp_y[fi[c_]]) <= 0.05:
            rowmates[a_].add(c_); rowmates[c_].add(a_)


def pair_ok(r, c, o, oc, gap=GAP_MIN):
    if lgap(c.lb, oc.lb) < gap - 1e-9: return False
    if c.kind in BES and r in oc.pl: return False                 # 3b: another label where this part's own would be read
    if oc.kind in BES and o in c.pl: return False
    if o in rowmates.get(r, ()) and abs(c.y - oc.y) > 0.04: return False          # D31: one label line per row
    return True


def is_mh(r): return re.fullmatch(r'MH\d+', r) is not None
labelled = [r for r in cour if not is_mh(r) and r not in BNC]
anchors = sorted([r for r in labelled if r[0] in 'UJ' or r.startswith('TP')], key=lambda r: (r[:1] if not r.startswith('TP') else 'T', int(re.sub(r'\D', '', r))))
passives = [r for r in labelled if r not in anchors]

fixed = {}                                                       # the BNCs' labels stay as main has them here (bnc.py moves them afterwards)
for j in range(len(b.r_fp)):
    r = refs[row[int(b.r_fp[j])]]
    if r in BNC and b.r_on_silk[j]:
        fixed[r] = Cand('above', float(b.r_x[j]), float(b.r_y[j]), lbox(r, float(b.r_x[j]), float(b.r_y[j])), frozenset(), 0)
P = {}                                                           # ref -> Cand

# ---- anchors first
anchor_note = {}
for r in anchors:
    done = None; how = None
    for mode in ('strict', 'relaxed_in', 'relaxed_free'):
        for kind in ORDER:
            for x, y in cands(r, kind):
                if mode == 'strict': okp = strict_static(r, kind, x, y)
                else: okp = relaxed_static(r, kind, x, y, need_inside=(mode == 'relaxed_in'))
                if not okp: continue
                c = make(r, kind, x, y, mode != 'strict')
                others = list(P.values()) + list(fixed.values())
                if mode == 'strict':
                    good = all(pair_ok(r, c, o, oc) for o, oc in list(P.items()) + list(fixed.items()))
                else:                                                          # (c): the nearest other label is farther than the part itself
                    d_own = lgap(sbox(r, x, y, ang_of(kind)), cour[r])
                    good = all(lgap(c.lb, oc.lb) >= 0.3 - 1e-9 and lgap(c.lb, oc.lb) > d_own for oc in others)
                if good: done = c; how = mode; break
            if done: break
        if done: break
    if done: P[r] = done; anchor_note[r] = how + ' ' + done.kind
    else: anchor_note[r] = None

blocked = {}
for r in [q for q, v in anchor_note.items() if v is None]:
    j = [jj for jj in range(len(b.r_fp)) if refs[row[int(b.r_fp[jj])]] == r][0]
    x0, y0 = float(b.r_x[j]), float(b.r_y[j])
    fixed[r] = Cand('above', x0, y0, lbox(r, x0, y0, float(b.r_ang[j])), frozenset(), 0)
    why = {}
    for kind in ORDER:
        hit = collections.Counter(); n = 0
        for x, y in cands(r, kind):
            n += 1; ang = ang_of(kind); sb = sbox(r, x, y, ang); w = set()
            if not inside_blk(sb, r): w.add('outside its block outline')
            for k, bd in body.items():
                if k != r and bd is not None and S._overlap(sb, bd): w.add('body of ' + k)
            for p, o in zip(pads, owner):
                if S._overlap(sb, p): w.add('pad of ' + o)
            if any(S._overlap(sb, v) for v in vias): w.add('via')
            if on_silk(sb, silk): w.add('silk line')
            if any(lgap(sb, t) < 0.2 for t in texts): w.add('board text')
            own = lgap(sb, body[r]) if body.get(r) else 0.0
            for k, bd in body.items():
                if k != r and bd is not None and lgap(sb, bd) < own + 0.25 and ('body of ' + k) not in w: w.add('nearer to ' + k + ' than 0.25 mm beyond its own body')
            for o, oc in list(P.items()) + list(fixed.items()):
                if o != r and lgap(lbox(r, x, y, ang), oc.lb) < 0.3: w.add('label of ' + o)
            for q in w: hit[q] += 1
        why[kind] = (n, hit.most_common(4))
    blocked[r] = why

# ---- passives: most constrained first, restarts
base = {}
for r in passives:
    cs = []
    for kind in ORDER:
        for x, y in cands(r, kind):
            if strict_static(r, kind, x, y): cs.append(make(r, kind, x, y))
    base[r] = cs
fixed_all = dict(P); fixed_all.update(fixed)
start = {r: [c for c in cs if all(pair_ok(r, c, o, oc) for o, oc in fixed_all.items())] for r, cs in base.items()}
rng = random.Random(7); best = None; t0 = time.time(); it = 0
while time.time() - t0 < SECS:
    it += 1
    live = {r: list(c) for r, c in start.items()}; got = {}
    noise = 0.0 if it == 1 else rng.random() * 2.0
    while live:
        r = min(live, key=lambda q: (len(live[q]) + rng.random() * noise, q))
        cs = live.pop(r)
        if not cs: continue
        pick = cs[0] if it == 1 or rng.random() < 0.5 else cs[min(len(cs) - 1, int(rng.random() ** 2 * len(cs)))]
        got[r] = pick
        for q in live: live[q] = [c for c in live[q] if pair_ok(q, c, r, pick)]
    score = (len(got), -sum(c.rank for c in got.values()))
    if best is None or score > best[0]: best = (score, got); print('restart', it, 'labelled', score[0], 'rank sum', -score[1], round(time.time() - t0), flush=True)
for r, c in best[1].items(): P[r] = c
dropped = sorted(set(passives) - set(best[1]))

beside = sorted(r for r, c in P.items() if c.kind in ('east0', 'west0'))
plan = {'placed': {r: [c.kind, c.x, c.y, 'relaxed' if c.relaxed else 'strict'] for r, c in P.items()}, 'dropped': dropped, 'beside': beside, 'east_end': [],
        'anchors': anchor_note, 'blocked': blocked, 'kinds': dict(collections.Counter(c.kind for c in P.values())), 'iterations': it}
json.dump(plan, open(plan_out, 'w'), indent=1)
print('anchors:', anchor_note)
print('passives labelled', len(best[1]), 'of', len(passives), '; dropped', len(dropped), dropped)
print('kinds', plan['kinds'])

# ---- write (the offsets by pcbnew's own conversion of an absolute place, spliced as text)
mh = [r for r in refs if is_mh(r)]
for f in pb.GetFootprints():
    r = f.GetReference()
    if r in P:
        c = P[r]; rf = f.Reference()
        rf.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(float(c.x) + 50.0), pcbnew.FromMM(150.0 - float(c.y)))); rf.SetTextAngleDegrees(ang_of(c.kind)); rf.SetVisible(True)
    elif r in dropped or r in mh:
        f.Reference().SetVisible(False)
pcbnew.SaveBoard('/tmp/scratch_labels.kicad_pcb', pb)
sc = open('/tmp/scratch_labels.kicad_pcb').read()
def refblock(t, r):
    i = t.index('(property "Reference" "%s"' % r)
    return i, re.compile(r'\(at ([\-\d.]+) ([\-\d.]+)(?: ([\-\d.]+))?\)').search(t, i)
t = txt
for r in list(P) + dropped + mh:
    i, m = refblock(t, r); _, ms = refblock(sc, r)
    t = t[:m.start()] + '(at %s %s %s)' % (ms.group(1), ms.group(2), ms.group(3) or '0') + t[m.end():]
    if r in dropped or r in mh:
        end = t.index('\n\t\t)', i)
        if '(hide yes)' not in t[i:end]:
            j = t.index('(layer "F.SilkS")', i); t = t[:j] + '(layer "F.SilkS")\n\t\t\t(hide yes)' + t[j + len('(layer "F.SilkS")'):]
open(out, 'w').write(t)
print('wrote', out)
