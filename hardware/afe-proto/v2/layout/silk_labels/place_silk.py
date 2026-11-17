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
import os
if os.environ.get('RECTS_JSON'): C.OUTLINE = {k: [tuple(r) for r in v] for k, v in json.load(open(os.environ['RECTS_JSON'])).items()}
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
def on_silk(sb, shapes, clr=None):
    c_ = SILK_CLEAR if clr is None else clr
    g = (sb[0] - c_, sb[1] - c_, sb[2] + c_, sb[3] + c_)
    return any(S._on_shape(g, sh) for sh in shapes)

board_silk = list(silk)                                          # the outline lines and other board-level silk, without the footprints' own
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
solid_items = collections.defaultdict(list)                       # a part's solid: its body outline box (F.Fab) and each of its pad boxes
for p_, o_ in zip(pads, owner): solid_items[o_].append(p_)
for r_, bd_ in body.items():
    if bd_ is not None: solid_items[r_].append(bd_)
vias = [(x - d / 2 - S.VIA_CLEAR, y - d / 2 - S.VIA_CLEAR, x + d / 2 + S.VIA_CLEAR, y + d / 2 + S.VIA_CLEAR) for x, y, d in zip(b.v_x, b.v_y, b.v_drill)]
LEFT_JUSTIFIED = {m_.group(1) for m_ in re.finditer(r'\(gr_text "([^"]+)"(?:(?!\n\t\)).)*?\(justify left\)', txt, re.S)}       # a left-justified text starts at its position
texts = [(lambda L, xc: (xc - L / 2, y - L / 2, xc + L / 2, y + L / 2))(max(len(t.decode() if isinstance(t, bytes) else t) * 0.95 * h, h), x + (max(len(t.decode() if isinstance(t, bytes) else t) * 0.95 * h, h) / 2 if (t.decode() if isinstance(t, bytes) else t) in LEFT_JUSTIFIED else 0.0)) for t, x, y, h in zip(b.t_text, b.t_x, b.t_y, b.t_h)]   # pin labels may be turned: a square of the longer side
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


def slide_cands(r, kind):
    """every place along the side of the part: the sliding coordinate in 0.1 mm steps on an absolute grid (so two parts of one row can share a label line), the label keeping at least
    0.3 mm of its length beside the part; nearest the centre first, then nearest the part"""
    c = cour[r]; cx, cy = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2; ang = ang_of(kind); Lt = len(r) * S.CHAR_ADV
    gs = (0.03, 0.3, 0.57); o = []
    if kind in ('above', 'below'):
        lo, hi = c[0] + 0.3 - Lt / 2, c[2] - 0.3 + Lt / 2
        ylo, yhi = ((c[3] + 0.03 + H / 2, c[3] + 0.57 + H / 2) if kind == 'above' else (c[1] - 0.57 - H / 2, c[1] - 0.03 - H / 2))
        for xv in ygrid(lo, hi):
            for yv in ygrid(ylo, yhi): o.append((abs(xv - cx), abs(yv - (ylo if kind == 'above' else yhi)), xv, yv))
    else:
        w = Lt if ang == 0.0 else H; hh = H if ang == 0.0 else Lt
        lo, hi = c[1] + 0.3 - hh / 2, c[3] - 0.3 + hh / 2
        for yv in ygrid(lo, hi):
            for g in gs:
                o.append((abs(yv - cy), g, ((c[2] + g + w / 2) if kind.startswith('east') else (c[0] - g - w / 2)), yv))
    return [(x, y) for _, _, x, y in sorted(o, key=lambda t: (round(t[0], 3), t[1]))]


def in_rects(p, rs): return any(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for x0, y0, x1, y1 in rs)


def dsolid(r, box):
    return min(lgap(box, it) for it in solid_items[r]) if solid_items.get(r) else 9e9


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


def strict_static(r, kind, x, y, passive=False):
    ang = ang_of(kind); sb, lb = sbox(r, x, y, ang), lbox(r, x, y, ang)
    if passive:                                                  # AFE-1's fix: keep off part BODIES (F.Fab), not whole courtyards; nearer to the own body than to any other by 0.25 mm
        if any(S._overlap(sb, bd) for bd in body.values() if bd is not None): return False
        own_ = lgap(sb, body[r]) if body.get(r) else 0.0
        if any(lgap(sb, bd) < own_ + 0.25 for k, bd in body.items() if k != r and bd is not None): return False
    elif any(S._overlap(sb, c) for c in cour.values()): return False
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


def relaxed_static(r, kind, x, y, need_inside=True, clean=True):
    """anchors only (owner): on no part's body (F.Fab) and no exposed pad (tented vias may lie under the text), across no outline line, and nearer to its own body than to any
    body of the SAME KIND (U against U, J against J, TP against TP) by 0.25 mm. `need_inside` keeps it inside the block's own outline; `clean` also keeps it off the footprints'
    silk and board text; the later modes drop them"""
    ang = ang_of(kind); sb = sbox(r, x, y, ang)
    if need_inside and not inside_blk(sb, r): return False
    if any(S._overlap(sb, bd) for k, bd in body.items() if k != r and bd is not None): return False
    lb_ = lbox(r, x, y, ang)
    if any(lgap(lb_, p) < 0.05 for p in pads): return False                                    # an exposed pad: with the LR-11 box (1.2 mm high), 0.05 clear
    if on_silk(sb, board_silk): return False
    pre = 'TP' if r.startswith('TP') else r[0]
    own = lgap(sb, body[r]) if body.get(r) else 0.0
    if any(lgap(sb, bd) < own + 0.25 for k, bd in body.items() if k != r and bd is not None and (('TP' if k.startswith('TP') else k[0]) == pre)): return False
    if clean and on_silk(sb, silk): return False
    if clean and any(lgap(sb, t) < 0.2 for t in texts): return False
    return True


class Cand:
    __slots__ = ('kind', 'x', 'y', 'lb', 'pl', 'rank', 'relaxed', 'gown')
    def __init__(s, kind, x, y, lb, pl, rank, relaxed=False, gown=0.0): s.kind, s.x, s.y, s.lb, s.pl, s.rank, s.relaxed, s.gown = kind, x, y, lb, pl, rank, relaxed, gown


def make(r, kind, x, y, relaxed=False):
    ang = ang_of(kind); lb_ = lbox(r, x, y, ang)
    return Cand(kind, x, y, lb_, frozenset(o for o, c in cour.items() if o != r and S._places(sbox(r, x, y, ang), c)), ORDER.index(kind), relaxed, dsolid(r, lb_) if r in cour else 0.0)


PASSIVE = re.compile(r'(?:R|C|BR|L|FB)(\d)\d\d$')
def orient(rot): return round(float(rot) % 180.0) % 180
rowmates = collections.defaultdict(set)
pl_ = [r for r in refs if top[fi[r]] and PASSIVE.fullmatch(r)]
for a_ in pl_:
    for c_ in pl_:
        if a_ < c_ and PASSIVE.fullmatch(a_).group(1) == PASSIVE.fullmatch(c_).group(1) and orient(b.fp_rot[fi[a_]]) == orient(b.fp_rot[fi[c_]]) \
                and math.hypot(b.fp_x[fi[a_]] - b.fp_x[fi[c_]], b.fp_y[fi[a_]] - b.fp_y[fi[c_]]) <= 8.0 and abs(b.fp_y[fi[a_]] - b.fp_y[fi[c_]]) <= 0.05:
            rowmates[a_].add(c_); rowmates[c_].add(a_)


def lab_clash(L, B):
    """AFE-1's label spacing: 0.6 mm between two labels that share a baseline, 0.2 mm otherwise"""
    vo = min(L[3], B[3]) - max(L[1], B[1]); sm = min(L[3] - L[1], B[3] - B[1])
    mx = 0.6 if vo > 0.5 * sm else 0.2
    return B[0] - mx < L[2] and L[0] < B[2] + mx and B[1] - 0.2 < L[3] and L[1] < B[3] + 0.2


def kind_of(p): return 'TP' if p.startswith('TP') else (p[0] if p[0] in 'UJD' else 'P')
def part_of(n): return n[4:] if n.startswith('fun:') else n


def own_nearer(r, lb):
    """FROM THE LABEL (owner's two-way test, margin 0.15 plus 0.01 for the text's rounding): its own part, body and pads, is nearer than any other part; an anchor compares only against parts of its own kind"""
    d_own = dsolid(r, lb); kr = kind_of(r)
    for q in solid_items:
        if q == r or (kr != 'P' and kind_of(q) != kr): continue
        if d_own + 0.16 > dsolid(q, lb): return False
    return True


def pair_ok(r, c, o, oc, gap=None):
    """AFE-1's spacing (0.6 mm on a shared baseline, 0.2 mm otherwise) and the owner's two-way nearest test, margin 0.15 mm. From the label (its own part nearer than any other part) is
    the static body test. From the PART: its own label is nearer than any other label, measured to body and pads. An anchor compares only against labels of its own kind; a passive
    against all. A BNC's designator and function text are one label"""
    pr, po = part_of(r), part_of(o)
    if pr == po: return True
    if lab_clash(c.lb, oc.lb): return False
    kr, ko = kind_of(pr), kind_of(po)
    if (kr == 'P' or kr == ko) and c.gown + 0.16 > dsolid(pr, oc.lb): return False
    if (ko == 'P' or ko == kr) and oc.gown + 0.16 > dsolid(po, c.lb): return False
    return True


def is_mh(r): return re.fullmatch(r'MH\d+', r) is not None
labelled = [r for r in cour if not is_mh(r) and r not in BNC]
anchors = sorted([r for r in labelled if r[0] in 'UJD' or r.startswith('TP')], key=lambda r: (r[:1] if not r.startswith('TP') else 'T', int(re.sub(r'\D', '', r))))
passives = [r for r in labelled if r not in anchors]

fixed = {}                                                       # no fixed labels: the BNCs' labels move into their own rectangles (bnc.py), the holes carry none
P = {}                                                           # ref -> Cand

# ---- anchors first
anchor_note = {}

# ---- BNCs (owner, round 6): designator then function label VERTICAL (90 degrees, reading bottom to top) in the LEFT margin of each BNC's own box, between the box's west line and the
# body; one offset from each footprint origin for all three; the function text bottom-aligned (left-justified in its own direction) so the gap after the designator is identical
BNC_FUN = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}
RING = [tuple(p) for p in b.outline]
def inside_board(px, py):
    c = False; n = len(RING)
    for i in range(n):
        (x0, y0), (x1, y1) = RING[i], RING[(i + 1) % n]
        if (y0 > py) != (y1 > py) and px < (x1 - x0) * (py - y0) / (y1 - y0) + x0: c = not c
    return c
bods = {r: body[r] for r in BNC}
bnc_info = {'found': None, 'margins': {}, 'angle': 90.0}
def bnc_rect(r):
    ox_, oy_ = float(b.fp_x[fi[r]]), float(b.fp_y[fi[r]])
    for q in C.OUTLINE.get(C.BLOCK.get(r), []):
        if q[0] >= 98.0 and q[0] <= ox_ <= q[2] and q[1] <= oy_ <= q[3]: return q
    return None
fp_silk_x0 = {}
for f in pb.GetFootprints():
    if f.GetReference() in BNC:
        xs_ = [mm(g.GetBoundingBox().GetX()) - 50.0 for g in f.GraphicalItems() if g.GetLayer() == pcbnew.F_SilkS]
        fp_silk_x0[f.GetReference()] = min(xs_) if xs_ else None
for r in BNC:
    rc = bnc_rect(r); hi_ = min([bods[r][0]] + ([fp_silk_x0[r]] if fp_silk_x0.get(r) is not None else []))
    bnc_info['margins'][r] = {'box west line x': rc[0], 'body west x': round(bods[r][0], 3), 'footprint silk west x': (round(fp_silk_x0[r], 3) if fp_silk_x0.get(r) is not None else None),
                              'clear width between the line and the silk (line half-width 0.075 each)': round(hi_ - 0.075 - (rc[0] + 0.075), 3), 'text height (box) 1.0 / LR-11 box 1.2': 1.0}
DES_DY, FN_DY = -3.35, -0.45                                  # AFE-1's offsets (round 10/11): the designator's centre and the function text's bottom end, from each footprint origin
_r0 = 'J101'; _rc = bnc_rect(_r0); _sx0 = fp_silk_x0[_r0]
BNC_DX = (_rc[0] + 0.075 + _sx0) / 2 - float(b.fp_x[fi[_r0]])  # the centre of the clear width in the left margin
bnc_info['dx'] = round(BNC_DX, 4); bnc_info['des_dy'] = DES_DY; bnc_info['fn_dy'] = FN_DY
def bnc_geom(r, lab):
    ox, oy = float(b.fp_x[fi[r]]), float(b.fp_y[fi[r]]); x = ox + BNC_DX; Lf = len(lab) * S.CHAR_ADV
    return x, oy + DES_DY, oy + FN_DY, Lf
bnc_conflicts = {}
for r, lab in BNC_FUN.items():
    x, yd, yb, Lf = bnc_geom(r, lab); db = S.text_box(r, x, yd, 1.0, H, 90.0); fb = S.text_box(lab, x, yb + Lf / 2, 1.0, H, 90.0); why = []
    for nm, bx in (('designator', db), ('function', fb)):
        if any(S._overlap(bx, bd) for k, bd in body.items() if bd is not None and k != 'zzz'): why.append(nm + ' on a body')
        if any(lgap((bx[0] - 0.1, bx[1], bx[2] + 0.1, bx[3]), p) < 0.02 for p in pads): why.append(nm + ' on a pad')
        rc = bnc_rect(r)
        if bx[0] < rc[0] + 0.075 or bx[2] > fp_silk_x0[r] or bx[1] < rc[1] or bx[3] > rc[3]: why.append(nm + ' not inside the margin / box')
    bnc_conflicts[r] = why
bnc_info['conflicts'] = bnc_conflicts
bnc_info['found'] = (BNC_DX, DES_DY, FN_DY)
for r, lab in BNC_FUN.items():
    x, yd, yb, Lf = bnc_geom(r, lab)
    P[r] = Cand('bnc90', x, yd, lbox(r, x, yd, 90.0), frozenset(), 0, False, dsolid(r, lbox(r, x, yd, 90.0)))
    fixed['fun:' + r] = Cand('bnc90', x, yb + Lf / 2, (x - 0.85, yb, x + 0.85, yb + Lf + 0.1), frozenset(), 0, False, P[r].gown)          # pcbnew's own box of the turned text is 1.7 mm wide
    bnc_info.setdefault('function_at', {})[r] = (round(x, 3), round(yb, 3))
anchor_note.update({r: 'bnc vertical, left margin of its box (AFE-1 offsets)' for r in BNC})

for r in anchors:
    done = None; how = None
    for mode in ('strict', 'relaxed_in_clean', 'relaxed_clean', 'relaxed_in', 'relaxed_bare'):
        for kind in ORDER:
            for x, y in (cands(r, kind) if mode == 'strict' else slide_cands(r, kind)):
                if mode == 'strict': okp = strict_static(r, kind, x, y)
                else: okp = relaxed_static(r, kind, x, y, need_inside=('_in' in mode), clean=('clean' in mode))
                if okp and mode in ('strict', 'relaxed_in_clean', 'relaxed_clean') and not own_nearer(r, lbox(r, x, y, ang_of(kind))): okp = False
                if not okp: continue
                c = make(r, kind, x, y, mode != 'strict')
                others = list(P.values()) + list(fixed.values())
                if mode == 'strict':
                    good = all(pair_ok(r, c, o, oc) for o, oc in list(P.items()) + list(fixed.items()))
                else:                                                          # (c): the nearest other label is farther than the part itself
                    d_own = lgap(sbox(r, x, y, ang_of(kind)), cour[r])
                    good = all(lgap(c.lb, oc.lb) >= 0.3 - 1e-9 and lgap(c.lb, oc.lb) > d_own for oc in others)
                    if good and mode in ('relaxed_in_clean', 'relaxed_clean'): good = all(pair_ok(r, c, o, oc) for o, oc in list(P.items()) + list(fixed.items()))      # the two-way test first; the later modes drop it
                if good: done = c; how = mode; break
            if done: break
        if done: break
    if done: P[r] = done; anchor_note[r] = how + ' ' + done.kind
    else: anchor_note[r] = None

blocked = {}
for r in [q for q, v in anchor_note.items() if v is None]:
    j0 = [jj for jj in range(len(b.r_fp)) if refs[row[int(b.r_fp[jj])]] == r][0]               # not a place: it stays visible where main had it, and passives keep clear of it
    fixed[r] = Cand('above', float(b.r_x[j0]), float(b.r_y[j0]), lbox(r, float(b.r_x[j0]), float(b.r_y[j0]), float(b.r_ang[j0])), frozenset(), 0)
    why = {}
    for kind in ORDER:
        hit = collections.Counter(); n = 0
        for x, y in slide_cands(r, kind):
            n += 1; ang = ang_of(kind); sb = sbox(r, x, y, ang); w = set()
            for k, bd in body.items():
                if k != r and bd is not None and S._overlap(sb, bd): w.add('body of ' + k)
            for p, o in zip(pads, owner):
                if S._overlap(sb, p): w.add('pad of ' + o)
            if on_silk(sb, board_silk): w.add('outline line')
            own = lgap(sb, body[r]) if body.get(r) else 0.0
            pre = 'TP' if r.startswith('TP') else r[0]
            for k, bd in body.items():
                if k != r and bd is not None and (('TP' if k.startswith('TP') else k[0]) == pre) and lgap(sb, bd) < own + 0.25 and ('body of ' + k) not in w: w.add('nearer to ' + k + ' than 0.25 mm beyond its own body')
            for q in w: hit[q] += 1
        why[kind] = (n, hit.most_common(4))
    blocked[r] = why

# ---- passives (round 4): AFE-1's tests (kicad/labels/place3.py), first fit in AFE-1's candidate order, most constrained first, random restarts
GAPS0 = (0.15, 0.25, 0.35, 0.5, 0.7, 0.9, -0.1, -0.2, -0.3, -0.4)               # label to own courtyard; negative = over its own courtyard's edge
bx0b, by0b, bx1b, by1b = float(b.outline[:, 0].min()), float(b.outline[:, 1].min()), float(b.outline[:, 0].max()), float(b.outline[:, 1].max())
own_solid = {}
for r in passives:
    bxs = [p for p, o in zip(pads, owner) if o == r] + ([body[r]] if body.get(r) else [])
    own_solid[r] = (min(q[0] for q in bxs), min(q[1] for q in bxs), max(q[2] for q in bxs), max(q[3] for q in bxs))
oth_bodies = {r: [(k, bd) for k, bd in body.items() if k != r and bd is not None] for r in passives}
pad_arr = np.array(pads).reshape(-1, 4); via_arr = np.array(vias).reshape(-1, 4) if vias else np.zeros((0, 4))


def pcands(r):
    c = cour[r]; cx, cy = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2; w_, h_ = c[2] - c[0], c[3] - c[1]; L = len(r) * ADV_L; out = []
    sl = lambda half: sorted([0.0] + [sg * k * 0.1 for k in range(1, int(half / 0.1) + 2) for sg in (1, -1)], key=abs)
    for g in GAPS0:
        for dx in sl(w_ / 2 + 1.0 + L / 2):
            if abs(dx) <= w_ / 2 + 1.0 + L / 2: out.append((0, 'above', cx + dx, c[3] + g + H_L / 2, g, abs(dx)))
    for g in GAPS0:
        for dy in sl(h_ / 2 + 1.0):
            if abs(dy) <= h_ / 2 + 0.5: out.append((1, 'east0', c[2] + g + L / 2, cy + dy, g, abs(dy))); out.append((1, 'west0', c[0] - g - L / 2, cy + dy, g, abs(dy)))
    for g in GAPS0:
        for dx in sl(w_ / 2 + 1.0 + L / 2):
            if abs(dx) <= w_ / 2 + 1.0 + L / 2: out.append((1.5, 'below', cx + dx, c[1] - g - H_L / 2, g, abs(dx)))
    for g in GAPS0:
        for dy in sl(h_ / 2 + 1.0 + L / 2):
            if abs(dy) <= h_ / 2 + 1.0 + L / 2: out.append((2, 'east90', c[2] + g + H_L / 2, cy + dy, g, abs(dy))); out.append((2, 'west90', c[0] - g - H_L / 2, cy + dy, g, abs(dy)))
    return [(k, x, y) for _, k, x, y, _, _ in sorted(out, key=lambda t: (t[0], t[4] if t[4] >= 0 else 5 + abs(t[4]), t[5]))]


def ovl_any(L, A, m):
    return bool(len(A)) and bool(((L[0] - m < A[:, 2]) & (A[:, 0] - m < L[2]) & (L[1] - m < A[:, 3]) & (A[:, 1] - m < L[3])).any())


def passive_fails(r, kind, x, y, stop=2):
    """the static tests (AFE-1's) a place fails, by name; stops after `stop` failures"""
    ang = ang_of(kind); L = lbox(r, x, y, ang); t = sbox(r, x, y, ang); f = []
    if L[0] < bx0b + 0.4 or L[2] > bx1b - 0.4 or L[1] < by0b + 0.4 or L[3] > by1b - 0.4: f.append('board edge')
    sol = own_solid[r]
    if lgap(L, sol) < 0.05: f.append('own part body/pads')
    if len(f) < stop and any(S._overlap(t, bd) for _, bd in oth_bodies[r]): f.append('on another part body')
    if len(f) < stop:
        own_ = lgap(t, body[r]) if body.get(r) else 0.0
        if any(lgap(t, bd) - own_ < 0.25 for _, bd in oth_bodies[r]): f.append('own body not nearer by 0.25 mm')
    if len(f) < stop and (ovl_any(L, pad_arr, 0.10) or ovl_any(L, via_arr, 0.10)): f.append('pad or via')
    if len(f) < stop and on_silk(t, silk, 0.15): f.append('silk line or outline')
    if len(f) < stop and any(lgap(L, tx) < 0.4 for tx in texts): f.append('board text / pin label')
    if len(f) < stop and not inside_blk(t, r): f.append('outside own block outline')
    if len(f) < stop and not f and not own_nearer(r, L): f.append('own part (body and pads) not nearer than another part by 0.15 mm')
    return f


REASON1 = collections.Counter(); SOLE = collections.defaultdict(collections.Counter)
base = {}
for r in passives:
    cs = []
    for kind, x, y in pcands(r):
        fl = passive_fails(r, kind, x, y)
        if not fl: cs.append(make(r, kind, x, y))
        else:
            REASON1[fl[0]] += 1
            if len(fl) == 1: SOLE[r][fl[0]] += 1
    base[r] = cs
fixed_all = dict(P); fixed_all.update(fixed)
start = {r: [c for c in cs if all(pair_ok(r, c, o, oc) for o, oc in fixed_all.items())] for r, cs in base.items()}
rng = random.Random(7); best = None; t0 = time.time(); it = 0
while time.time() - t0 < SECS:
    it += 1
    noise = 0.0 if it == 1 else rng.random() * 40.0
    order = sorted(passives, key=lambda q: (len(start[q]) + rng.random() * noise, q)); got = {}
    for r in order:
        for c in start[r]:
            if all(pair_ok(r, c, q, pc) for q, pc in got.items()): got[r] = c; break
    score = (len(got), -sum(c.rank for c in got.values()))
    if best is None or score > best[0]: best = (score, got); print('restart', it, 'labelled', score[0], 'rank sum', -score[1], round(time.time() - t0), flush=True)
for r, c in best[1].items(): P[r] = c
dropped = sorted(set(passives) - set(best[1]))
tests_report = {'candidates failing first at each test': dict(REASON1),
                'passives with no static place at all': sorted(r for r in passives if not base[r]),
                'dropped with static places but lost to label spacing or stacking': sorted(r for r in dropped if start[r]),
                'dropped with no static place, by the single test whose removal alone would give a place': dict(collections.Counter(t for r in dropped if not base[r] for t in SOLE[r])),
                'dropped passives for which that test alone is the blocker (any place)': {t: sum(1 for r in dropped if not base[r] and SOLE[r].get(t)) for t in set(t for r in dropped for t in SOLE[r])}}
print('TESTS', json.dumps(tests_report))

beside = sorted(r for r, c in P.items() if c.kind in ('east0', 'west0'))
plan = {'placed': {r: [c.kind, c.x, c.y, 'relaxed' if c.relaxed else 'strict'] for r, c in P.items()}, 'dropped': dropped, 'beside': beside, 'east_end': [],
        'anchors': anchor_note, 'blocked': blocked, 'bnc': bnc_info, 'tests': tests_report, 'kinds': dict(collections.Counter(c.kind for c in P.values())), 'iterations': it}
json.dump(plan, open(plan_out, 'w'), indent=1)
print('anchors:', anchor_note)
print('bnc:', bnc_info)
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
if bnc_info['found']:
    for r, lab in BNC_FUN.items():
        fx_, fy_ = bnc_info['function_at'][r]
        g = re.search(r'\(gr_text "%s"\s+\(at ([\-\d.]+) ([\-\d.]+)(?: ([\-\d.]+))?\)' % re.escape(lab), t)
        t = t[:g.start(1)] + '%.3f %.3f %g' % (fx_ + 50.0, 150.0 - fy_, bnc_info['angle']) + t[g.end(0) - 1:]
        g2 = re.search(r'\(gr_text "%s"(?:(?!\n\t\)).)*?\(effects\s+\(font\s+\(size [\d.]+ [\d.]+\)\s+\(thickness [\d.]+\)\s+\)' % re.escape(lab), t, re.S)
        blk_ = t[g2.start():t.index('\n\t)', g2.start())]
        if '(justify left)' not in blk_: t = t[:g2.end()] + '\n\t\t\t(justify left)' + t[g2.end():]                    # all three function labels left-justified
open(out, 'w').write(t)
print('wrote', out)
