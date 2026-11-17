"""place3.py BOARD OUT.json: designators, block outlines and block names on main's board, parts and copper untouched (owner, 2026-11-17, round 4).

Order: (1) the edge connectors' labels (J601-J607); (2) the BNC labels outside the bodies; (3) each block's outline as a rectilinear polygon (regions.py: its members'
courtyards grown, closed across gaps that hold nothing of another block, minus foreign courtyards, disjoint from the other blocks); (4) anchors inside the blocks
(every U, J501, every TP), strict test first, then the body-and-pad test; (5) the block names, one size, each at a corner of its region; (6) the passives.
A label sits wholly inside its own block's outline, and its nearest other label is farther from it than its own part is (both ways). No place: it comes off the silk."""
import sys, json, math, collections, os, re
sys.path.insert(0, '.'); sys.path.insert(0, 'kicad/labels'); sys.path.append('/usr/lib/python3/dist-packages')
import numpy as np
from scipy import ndimage
import pcbnew
from pcbtools import boardio, silkread
from pcbtools.boards import v1 as C
import regions as RG
path, out = sys.argv[1], sys.argv[2]
HALO = float(os.environ.get('HALO', '1.8')); LANE = float(os.environ.get('LANE', '0.4'))
b = boardio.read_board(path)
refs = list(b.fp_ref); n = len(refs)
ADV, INK = C.DESIGNATOR_ADVANCE, C.DESIGNATOR_INK_H
GAPL, CLR, EDGE, SMARG = 0.6, 0.10, 0.4, 0.15
cour = {r: (float(b.fp_cx0[i]), float(b.fp_cy0[i]), float(b.fp_cx1[i]), float(b.fp_cy1[i])) for i, r in enumerate(refs) if not np.isnan(b.fp_cx0[i]) and int(b.fp_side[i]) == 0}
vias = np.column_stack([b.v_x - b.v_dia / 2, b.v_y - b.v_dia / 2, b.v_x + b.v_dia / 2, b.v_y + b.v_dia / 2]).astype(float) if len(b.v_x) else np.zeros((0, 4))
bd = pcbnew.LoadBoard(path); mm = pcbnew.ToMM
def tobox(bb):
    x0, y0 = boardio.to_due(mm(bb.GetX()), mm(bb.GetY())); x1, y1 = boardio.to_due(mm(bb.GetRight()), mm(bb.GetBottom()))
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
def ovl(a, A, m=0.0):
    if not len(A): return np.zeros(0, bool)
    return (a[0] - m < A[:, 2]) & (A[:, 0] - m < a[2]) & (a[1] - m < A[:, 3]) & (A[:, 1] - m < a[3])
def gap(a, c): return float(np.hypot(max(c[0] - a[2], 0, a[0] - c[2]), max(c[1] - a[3], 0, a[1] - c[3])))
cr_refs = list(cour); cr = np.array([cour[r] for r in cr_refs])
NAMES = ('CH1', 'CH2', 'AWG', 'POWER', 'REF/CAL')
pads = np.array([tobox(pd.GetBoundingBox()) for fp in bd.GetFootprints() for pd in fp.Pads()]).reshape(-1, 4)
silk_fp = [tobox(it.GetBoundingBox()) for fp in bd.GetFootprints() for it in fp.GraphicalItems() if it.GetLayer() == pcbnew.F_SilkS]
body = {}
for fp in bd.GetFootprints():
    bs = [tobox(it.GetBoundingBox()) for it in fp.GraphicalItems() if it.GetLayer() == pcbnew.F_Fab and it.GetClass() == 'PCB_SHAPE']
    if bs: body[fp.GetReference()] = (min(x[0] for x in bs), min(x[1] for x in bs), max(x[2] for x in bs), max(x[3] for x in bs))
own_solid = {}
for fp in bd.GetFootprints():
    bx = [tobox(pd.GetBoundingBox()) for pd in fp.Pads()] + ([body[fp.GetReference()]] if fp.GetReference() in body else [])
    if bx: own_solid[fp.GetReference()] = (min(q[0] for q in bx), min(q[1] for q in bx), max(q[2] for q in bx), max(q[3] for q in bx))
silk_board = []
for d in bd.GetDrawings():
    if d.GetLayer() != pcbnew.F_SilkS or (d.GetClass() == 'PCB_TEXT' and d.GetText() in NAMES): continue
    if d.GetClass() == 'PCB_SHAPE':
        x0, y0, x1, y1 = tobox(d.GetBoundingBox()); w = 0.1
        silk_board += [(x0 - w, y0 - w, x1 + w, y0 + w), (x0 - w, y1 - w, x1 + w, y1 + w), (x0 - w, y0 - w, x0 + w, y1 + w), (x1 - w, y0 - w, x1 + w, y1 + w)]
    elif d.GetClass() == 'PCB_TEXT' and d.GetText() == 'ON': ON_BOX = tobox(d.GetBoundingBox()); silk_board.append(ON_BOX)
    else: silk_board.append(tobox(d.GetBoundingBox()))
silk = np.array(silk_fp + silk_board).reshape(-1, 4)
def blk(r):
    m = re.fullmatch(r'[A-Z]+(\d)\d\d', r)
    return {'1': 'CH1', '2': 'CH2', '3': 'AWG', '4': 'POWER', '5': 'REFCAL'}.get(m.group(1)) if m else None
BNC = ('J101', 'J201', 'J301'); BNCBLK = {'J101': 'CH1', 'J201': 'CH2', 'J301': 'AWG'}
BNCFN = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}
BNCEND = {'AWG': (98.5, -0.5, 115.8, 17.4), 'CH2': (98.5, 17.9, 116.4, 36.3), 'CH1': (98.5, 36.8, 115.8, 54.0)}
DUE = C.DUE_RECT
def part_block(r): return BNCBLK.get(r) or blk(r)
RECT_MODE = bool(os.environ.get('RECT'))
_rj = json.load(open(os.environ.get('RJSON', 'kicad/labels/rects.json'))) if os.path.exists(os.environ.get('RJSON', 'kicad/labels/rects.json')) else {}
if os.environ.get('PX1') and 'POWER' in _rj: _rj['POWER'][2] = float(os.environ['PX1'])
RECTS = {B: [tuple(_rj[B])] for B in ('POWER', 'REFCAL', 'AWG', 'CH2', 'CH1')}
RECTS['AWG'].append((98.5, -0.5, 116.4, 17.4)); RECTS['CH2'].append((98.5, 17.9, 116.4, 36.3)); RECTS['CH1'].append((98.5, 36.8, 116.4, 54.0))
placed = {}; own_of = {}; plan = {}; kind = {}; relaxed = set(); RELAX = False; FALLBACK = False; SAMEKIND = False; fallback_used = set(); samekind_used = set(); FALLBACK = False; fallback_used = set()
REGION_IN = {}; REGION_ANY = None; SAT = {}
def lab_box(r, x, y, ang):
    L = len(r) * ADV
    return (x - INK / 2, y - L / 2, x + INK / 2, y + L / 2) if ang == 90 else (x - L / 2, y - INK / 2, x + L / 2, y + INK / 2)
def lab_clash(L, B):
    vo = min(L[3], B[3]) - max(L[1], B[1]); sm = min(L[3] - L[1], B[3] - B[1])
    mx = GAPL if vo > 0.5 * sm else 0.2
    return (B[0] - mx < L[2] and L[0] < B[2] + mx and B[1] - 0.2 < L[3] and L[1] < B[3] + 0.2)
def sat_inside(B, box):
    S = SAT[B]; i0, i1 = int(math.floor((box[0] - RG.X0) / RG.RES)), int(math.ceil((box[2] - RG.X0) / RG.RES)); j0, j1 = int(math.floor((box[1] - RG.Y0) / RG.RES)), int(math.ceil((box[3] - RG.Y0) / RG.RES))
    if i0 < 0 or j0 < 0 or i1 > RG.NX or j1 > RG.NY: return False
    return (S[i1, j1] - S[i0, j1] - S[i1, j0] + S[i0, j0]) == 0
def mk_sat(mask): return np.pad(np.cumsum(np.cumsum(~mask, 0), 1), ((1, 0), (1, 0))).astype(np.int64)
def region_ok(r, L):
    B = part_block(r)
    if B is None or not REGION_IN: return True
    if B in SAT: return sat_inside(B, L)
    return True
def outside_regions(L):
    if REGION_ANY is None: return True
    i0, i1 = RG.ci(L[0]), RG.ci(L[2]); j0, j1 = RG.cj(L[1]), RG.cj(L[3])
    return not REGION_ANY[max(0, i0):i1, max(0, j0):j1].any()
def ok_(r, x, y, ang):
    L = lab_box(r, x, y, ang)
    if L[0] < DUE[0] + EDGE or L[2] > DUE[2] - EDGE or L[1] < DUE[1] + EDGE or L[3] > DUE[3] - EDGE: return 'edge'
    own = cour[r]; sol = own_solid.get(r, own)
    if gap(L, sol) < 0.05 or (L[0] < sol[2] and sol[0] < L[2] and L[1] < sol[3] and sol[1] < L[3]): return 'body'
    t = silkread.text_box(r, x, y, 1.0, 1.0, ang)
    if RELAX:
        bk = [q for q in body if q != r]; BA = np.array([body[q] for q in bk])
        if ovl(t, BA).any(): return 'otherbody'
        if SAMEKIND:                      # anchors only: the own-part-nearer test against parts of the same kind (J against J, U against U, TP against TP)
            kd = 'TP' if r.startswith('TP') else r[0]
            sk = [q for q in bk if (q.startswith('TP') if kd == 'TP' else (q[0] == kd and not q.startswith('TP')))]
            if sk and min(gap(t, body[q]) for q in sk) - gap(t, body.get(r, own)) < silkread.OWN_MARGIN: return 'ownmargin'
        elif min(gap(t, body[q]) for q in bk) - gap(t, body.get(r, own)) < silkread.OWN_MARGIN: return 'ownmargin'
    else:
        m = ovl(t, cr); m[cr_refs.index(r)] = False
        if m.any(): return 'othercourt'
        if min(gap(t, cr[k]) for k in range(len(cr_refs)) if cr_refs[k] != r) - gap(t, own) < silkread.OWN_MARGIN: return 'ownmargin'
    if ovl(L, pads, CLR).any() or ovl(L, vias, CLR).any(): return 'padvia'
    if ovl(L, silk, CLR).any(): return 'silk'
    g_own = gap(L, own)
    for q, B in placed.items():
        if q == r: continue
        if lab_clash(L, B): return 'label'
        d = gap(L, B)
        if d <= g_own + SMARG: return 'stack'
        if q in own_of and d <= gap(B, own_of[q]) + SMARG: return 'stack2'
    if RECT_MODE:
        pb = part_block(r); i = refs.index(r); pc = (float(b.fp_x[i]), float(b.fp_y[i]))
        own_in = pb in RECTS and any(q[0] <= pc[0] <= q[2] and q[1] <= pc[1] <= q[3] for q in RECTS[pb])
        if own_in and FALLBACK:
            lc = ((L[0] + L[2]) / 2, (L[1] + L[3]) / 2)
            for B2, rs in RECTS.items():
                if any(q[0] <= lc[0] <= q[2] and q[1] <= lc[1] <= q[3] for q in rs): return 'foreign'
        elif own_in:
            if not sat_inside(pb, L): return 'region'
        else:
            lc = ((L[0] + L[2]) / 2, (L[1] + L[3]) / 2)
            for B2, rs in RECTS.items():
                if any(q[0] <= lc[0] <= q[2] and q[1] <= lc[1] <= q[3] for q in rs): return 'foreign'
        return True
    if part_block(r) is None: return True if REGION_ANY is None or outside_regions((L[0] - 0.3, L[1] - 0.3, L[2] + 0.3, L[3] + 0.3)) else 'inregion'
    if not region_ok(r, L): return 'region'
    return True
REASON = collections.Counter()
def ok(r, x, y, ang):
    v = ok_(r, x, y, ang)
    if v is True: return True
    REASON.update([v]); return False
GAPS0 = (0.15, 0.25, 0.35, 0.5, 0.7, 0.9, -0.1, -0.2, -0.3, -0.4)
def cands(r):
    GAPS = GAPS0 + ((1.2, 1.6, 2.0, 2.5, 3.0) if FALLBACK else ())
    c = cour[r]; cx, cy = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2; w, h = c[2] - c[0], c[3] - c[1]; L = len(r) * ADV; out = []
    sl = lambda half: sorted([0.0] + [s * k * 0.1 for k in range(1, int(half / 0.1) + 2) for s in (1, -1)], key=abs)
    for g in GAPS:
        for dx in sl(w / 2 + 1.0 + L / 2):
            if abs(dx) <= w / 2 + 1.0 + L / 2: out.append((0, 'above', cx + dx, c[3] + g + INK / 2, 0, g, abs(dx)))
    for g in GAPS:
        for dy in sl(h / 2 + 1.0):
            if abs(dy) <= h / 2 + 0.5: out.append((1, 'east', c[2] + g + L / 2, cy + dy, 0, g, abs(dy))); out.append((1, 'west', c[0] - g - L / 2, cy + dy, 0, g, abs(dy)))
    for g in GAPS:
        for dx in sl(w / 2 + 1.0 + L / 2):
            if abs(dx) <= w / 2 + 1.0 + L / 2: out.append((1.5, 'below', cx + dx, c[1] - g - INK / 2, 0, g, abs(dx)))
    for g in GAPS:
        for dy in sl(h / 2 + 1.0 + L / 2):
            if abs(dy) <= h / 2 + 1.0 + L / 2: out.append((2, 'east90', c[2] + g + INK / 2, cy + dy, 90, g, abs(dy))); out.append((2, 'west90', c[0] - g - INK / 2, cy + dy, 90, g, abs(dy)))
    return sorted(out, key=lambda t: (t[0], t[5] if t[5] >= 0 else 5 + abs(t[5]), t[6]))
def first_ok(r, anchor=False):
    global RELAX
    RELAX = False
    for k in cands(r):
        if ok(r, k[2], k[3], k[4]): return k
    if not anchor: return None
    RELAX = True
    try:
        for k in cands(r):
            if ok(r, k[2], k[3], k[4]): relaxed.add(r); return k
    finally: RELAX = False
    if RECT_MODE and r.startswith(('U', 'J', 'TP')):   # an IC, a connector or a test point with no place inside its rectangle: outside it, in no other block's
        global FALLBACK
        for rl in (False, True):
            RELAX = rl; FALLBACK = True
            try:
                for k in cands(r):
                    if ok(r, k[2], k[3], k[4]):
                        fallback_used.add(r)
                        if rl: relaxed.add(r)
                        return k
            finally: RELAX = False; FALLBACK = False
        global SAMEKIND
        for fb in (False, True):                       # the same-kind own-part-nearer rule (round 7), inside the rectangle then just past it
            RELAX = True; FALLBACK = fb; SAMEKIND = True
            try:
                for k in cands(r):
                    if ok(r, k[2], k[3], k[4]):
                        samekind_used.add(r); relaxed.add(r)
                        if fb: fallback_used.add(r)
                        return k
            finally: RELAX = False; FALLBACK = False; SAMEKIND = False
    return None
def put(r, k):
    L = lab_box(r, k[2], k[3], k[4]); placed[r] = L; own_of[r] = cour[r]; plan[r] = [round(k[2], 3), round(k[3], 3), k[4]]; kind[r] = k[1]
def feas(r): return sum(1 for k in cands(r) if ok(r, k[2], k[3], k[4]))
def run(order):
    for r in order:
        k = first_ok(r, anchor=r in ANCH)
        if k: put(r, k)
        else: plan[r] = None; kind[r] = 'OFF'
ANCH = {r for r in cour if r.startswith(('U', 'J', 'TP')) and r not in BNC}
MH = [r for r in cour if r.startswith('MH')]
for r in MH: plan[r] = None; kind[r] = 'OFF'
EDGEJ = os.environ.get('EDGEJSON', 'kicad/labels/edge.json')
if RECT_MODE and not os.path.exists(EDGEJ) and not os.environ.get('EDGEONLY'): sys.exit('run with EDGEONLY=1 first')
if RECT_MODE:
    R = {B: RG.union_rects(rs) for B, rs in RECTS.items()}
    er0 = int(round(0.2 / RG.RES)) * 2 + 1
    for B, m in R.items(): REGION_IN[B] = ndimage.binary_erosion(m, structure=np.ones((er0, er0), bool)); SAT[B] = mk_sat(REGION_IN[B])
    OUTSEG = {B: [(q[0], q[1], q[2], q[1]), (q[2], q[1], q[2], q[3]), (q[0], q[3], q[2], q[3]), (q[0], q[1], q[0], q[3])] for B, rs in RECTS.items() for q in rs[:1]}
    for B, rs in RECTS.items():
        if len(rs) > 1: OUTSEG[B] = OUTSEG[B] + [(q[0], q[1], q[2], q[1]) for q in rs[1:]] + [(q[2], q[1], q[2], q[3]) for q in rs[1:]] + [(q[0], q[3], q[2], q[3]) for q in rs[1:]] + [(q[0], q[1], q[0], q[3]) for q in rs[1:]]
    def cut(sg):
        out = []
        fb = []
        for f in [q for q in os.environ.get('FORCE', '').split(',') if q]:      # a forced label breaks any edge it touches (0.2 clear each side)
            rr_, fx_, fy_, fa_ = f.split(':'); fx_, fy_ = float(fx_), float(fy_); hl = len(rr_) * 0.45 + 0.2
            fb.append((fx_ - 0.8, fy_ - hl, fx_ + 0.8, fy_ + hl) if int(fa_) == 90 else (fx_ - hl, fy_ - 0.8, fx_ + hl, fy_ + 0.8))
        obs = np.vstack([np.array(silk_fp).reshape(-1, 4), pads] + ([np.array(fb)] if fb else []))
        for (a, d_, c, e) in sg:
            horiz = abs(d_ - e) < 1e-9; lo, hi = (min(a, c), max(a, c)) if horiz else (min(d_, e), max(d_, e)); fixed = d_ if horiz else a
            ivs = []
            for ob in obs:
                if horiz: hit = ob[1] - 0.03 < fixed + 0.075 and fixed - 0.075 < ob[3] + 0.03 and ob[0] - 0.03 < hi and lo < ob[2] + 0.03; iv = (ob[0] - 0.2, ob[2] + 0.2)
                else: hit = ob[0] - 0.03 < fixed + 0.075 and fixed - 0.075 < ob[2] + 0.03 and ob[1] - 0.03 < hi and lo < ob[3] + 0.03; iv = (ob[1] - 0.2, ob[3] + 0.2)
                if hit: ivs.append(iv)
            ivs.sort(); cur = lo; pieces = []
            for (p0, p1) in ivs:
                if p0 > cur: pieces.append((cur, min(p0, hi)))
                cur = max(cur, p1)
            if cur < hi: pieces.append((cur, hi))
            for (p0, p1) in pieces:
                if p1 - p0 > 0.05: out.append((p0, fixed, p1, fixed) if horiz else (fixed, p0, fixed, p1))
        return out
    OUTSEG = {B: cut(sg) for B, sg in OUTSEG.items()}
    print('OUTLINE pieces', {B: len(v) for B, v in OUTSEG.items()})
    lines = np.array([(min(a, c) - 0.075, min(d, e) - 0.075, max(a, c) + 0.075, max(d, e) + 0.075) for sg in OUTSEG.values() for a, d, c, e in sg]).reshape(-1, 4)
    silk = np.vstack([silk, lines])
# (1) the edge connectors
edge_anch = sorted([r for r in ANCH if blk(r) is None], key=feas)
if RECT_MODE and not os.environ.get('EDGEONLY'):
    ej = json.load(open(EDGEJ))
    for r in edge_anch:
        v = ej.get(r)
        if v: k = (0, v[3], v[0], v[1], v[2], 0, 0); put(r, k); plan[r] = [round(v[0], 3), round(v[1], 3), v[2]]
        else: plan[r] = None; kind[r] = 'OFF'
else:
    run(edge_anch)
if os.environ.get('EDGEONLY'):
    json.dump({r: ([plan[r][0], plan[r][1], plan[r][2], kind[r]] if plan.get(r) else None) for r in edge_anch}, open(EDGEJ, 'w')); print('EDGE labels', {r: plan.get(r) for r in edge_anch}); sys.exit(0)
# (2) the BNC labels, the same offset in every frame
BNC_OFF, BNC_DX = 8.6, 2.0; fnpos = {}
for r in BNC:
    i = refs.index(r); cx, cy = float(b.fp_x[i]), float(b.fp_y[i]); xd, yd = cx + BNC_DX, cy + BNC_OFF; xl = cx + 7.0
    L1 = lab_box(r, xd, yd, 0); L2 = (xl, yd - INK / 2, xl + len(BNCFN[r]) * ADV, yd + INK / 2)
    plan[r] = [round(xd, 3), round(yd, 3), 0]; kind[r] = 'bnc'; placed[r] = L1; placed['fn_' + r] = L2; fnpos[BNCFN[r]] = [round(xl, 3), round(yd, 3)]
# (2b) anchors inside the blocks (U, J501, TP): placed before the regions, which then take their labels in
PRIO = [q for q in os.environ.get('PRIO', 'TP405').split(',') if q]
blk_anch = sorted([r for r in ANCH if blk(r) is not None], key=lambda r: (0 if r in PRIO else 1, feas(r)))
for f in [q for q in os.environ.get('FORCE', '').split(',') if q]:      # FORCE=REF:x:y:angle puts a label at a stated place the candidate grid cannot reach
    rr, fx, fy, fa = f.split(':'); put(rr, (0, 'forced', float(fx), float(fy), int(fa), 0, 0)); blk_anch = [q for q in blk_anch if q != rr]
run(blk_anch)
# (2c) block names: one size, each at a corner of its block (the corners of its members' bounding box), the same corner wherever it fits
SIZE = 1.2; NAMETXT = {'POWER': 'POWER', 'REFCAL': 'REF/CAL', 'AWG': 'AWG', 'CH1': 'CH1', 'CH2': 'CH2'}
def name_box(t, x, y): return (x - len(t) * ADV * SIZE / 2, y - INK * SIZE / 2, x + len(t) * ADV * SIZE / 2, y + INK * SIZE / 2)
def name_ok(B, x, y):
    t = name_box(NAMETXT[B], x, y)
    if RECT_MODE and not sat_inside(B, t): return False
    if t[0] < DUE[0] + EDGE or t[2] > 98.0 or t[1] < DUE[1] + EDGE or t[3] > DUE[3] - EDGE: return False
    BA = np.array([body[q] for q in body]).reshape(-1, 4)
    if ovl(t, BA, 0.05).any() or ovl(t, pads, CLR).any() or ovl(t, vias, CLR).any() or ovl(t, silk, 0.08).any(): return False
    return not any(lab_clash(t, bx) for bx in placed.values())
CORN = ('TL', 'TR', 'BL', 'BR')
mem0 = {B: [] for B in NAMETXT}
for r, c in cour.items():
    B = blk(r)
    if B and r not in BNC: mem0[B].append(c)
CORE = {'POWER': (18.0, 4.6, 44.0, 22.0), 'REFCAL': (44.5, 4.6, 64.5, 36.0), 'AWG': (69.8, 4.4, 92.0, 19.4), 'CH2': (69.4, 19.9, 92.0, 33.0), 'CH1': (64.8, 33.5, 92.0, 50.3)}   # the main body of each block (cfg.OUTLINE's first rectangle)
def corner_spot(B, c):
    if RECT_MODE:
        rr = RECTS[B][0]; cx = rr[0] if c[1] == 'L' else rr[2]; cy = rr[3] if c[0] == 'T' else rr[1]; best = None
        for x in np.arange(cx - 12, cx + 12, 0.25):
            for y in np.arange(cy - 12, cy + 12, 0.25):
                d = abs(x - cx) + abs(y - cy)
                if d > 12 or (best and d >= best[0]): continue
                if name_ok(B, x, y): best = (d, x, y)
        return best
    core = [q for q in mem0[B] if CORE[B][0] <= (q[0] + q[2]) / 2 <= CORE[B][2] and CORE[B][1] <= (q[1] + q[3]) / 2 <= CORE[B][3]]
    xs = [q[0] for q in core] + [q[2] for q in core]; ys = [q[1] for q in core] + [q[3] for q in core]
    cx = min(xs) if c[1] == 'L' else max(xs); cy = max(ys) if c[0] == 'T' else min(ys); best = None
    for x in np.arange(cx - 14, cx + 14, 0.25):
        for y in np.arange(cy - 14, cy + 14, 0.25):
            d = abs(x - cx) + abs(y - cy)
            if d > 10 or (best and d >= best[0]): continue
            if name_ok(B, x, y): best = (d, x, y)
    return best
feas_c = {B: {c: corner_spot(B, c) for c in CORN} for B in NAMETXT}
print('NAME corners', {B: [c for c, v in f.items() if v] for B, f in feas_c.items()})
cnt = {c: sum(1 for B in feas_c if feas_c[B][c]) for c in CORN}
bestc = max(CORN, key=lambda c: (cnt[c], -CORN.index(c)))
names_plan = {}; name_boxes = {}
for B in NAMETXT:
    c = next((c for c in [bestc] + [q for q in CORN if q != bestc] if feas_c[B][c]), None)
    if c is None: print('NAME OFF-CORNER', B); names_plan[NAMETXT[B]] = None; continue
    d, x, y = feas_c[B][c]; names_plan[NAMETXT[B]] = [round(float(x), 3), round(float(y), 3), SIZE]; name_boxes[B] = name_box(NAMETXT[B], x, y); placed['name_' + B] = name_boxes[B]; print('NAME', B, c, round(float(x), 2), round(float(y), 2), 'd %.1f' % d)
# (3) the regions
members = {B: [] for B in ('CH1', 'CH2', 'AWG', 'POWER', 'REFCAL')}
for r, c in cour.items():
    B = blk(r)
    if B and r not in BNC: members[B].append(c)
for B, e in BNCEND.items(): members[B].append(e)
GROW = 0.3; obst = {}
for B in members:
    o = []
    for r, c in cour.items():
        if r in BNC: continue
        if blk(r) != B: o.append(c)
    for B2, e in BNCEND.items():
        if B2 != B: o.append(e)
    o += [placed[q] for q in edge_anch if q in placed]
    o += [placed[q] for q in blk_anch if q in placed and part_block(q) != B]
    o += [bx for B2, bx in name_boxes.items() if B2 != B]
    o += [q for q in silk_board if q != ON_BOX]
    o = [(c[0] - GROW, c[1] - GROW, c[2] + GROW, c[3] + GROW) for c in o]
    o += [(16.0, -2.0, 98.4, 0.3), (16.0, 53.1, 98.4, 56.0), (16.0, -2.0, 17.3, 56.0), (116.0, -2.0, 118.0, 56.0), (98.4, 54.2, 118.0, 56.0)]
    obst[B] = o
CLAIMS = {'POWER': [(41.3, 4.5, 44.3, 11.5)]}
keep = {B: [placed[q] for q in blk_anch if q in placed and part_block(q) == B] for B in members}
if RECT_MODE: keep = {B: [] for B in members}
for r in BNC:
    keep[BNCBLK[r]] += [placed[r], placed['fn_' + r]]
for B2, bx in name_boxes.items(): keep[B2].append(bx)
keep['REFCAL'].append(ON_BOX)
keep = {B2: [(q[0] - 0.3, q[1] - 0.3, q[2] + 0.3, q[3] + 0.3) for q in v] for B2, v in keep.items()}
if not RECT_MODE:
    R = RG.make_regions(members, obst, halo=HALO, lane=LANE, claims=None, keep=keep, lmax=float(os.environ.get('LMAX', '8')))
    er = int(round(0.2 / RG.RES)) * 2 + 1
    for B, m in R.items():
        REGION_IN[B] = ndimage.binary_erosion(m, structure=np.ones((er, er), bool)); SAT[B] = mk_sat(REGION_IN[B])
    REGION_ANY = ndimage.maximum_filter(np.any(np.stack(list(R.values())), 0), size=3)
    OUTSEG = {}
    for B, m in R.items(): OUTSEG[B] = [tuple(round(float(v), 3) for v in s) for s in RG.boundary_segments(m)]
ncomp = {B: ndimage.label(m)[1] for B, m in R.items()}
print('REGIONS components', ncomp, 'segments', {B: len(v) for B, v in OUTSEG.items()})
for B, m in R.items():
    outp = [r for r, c in cour.items() if part_block(r) == B and r not in BNC and not m[RG.ci((c[0] + c[2]) / 2), RG.cj((c[1] + c[3]) / 2)]]
    fin = [r for r, c in cour.items() if part_block(r) not in (B, None) and r not in BNC and m[RG.ci((c[0] + c[2]) / 2), RG.cj((c[1] + c[3]) / 2)]]
    print('REGION', B, 'members outside', outp, 'foreign parts inside', fin)
# (6) passives
rest = sorted([r for r in cour if r not in ANCH and r not in BNC and r not in MH], key=feas)
run(rest)
json.dump(plan, open(out, 'w'))
json.dump(dict(names=names_plan, bncfn=fnpos, outline={B: [list(s) for s in v] for B, v in OUTSEG.items()}), open(out.replace('.json', '_extra.json'), 'w'))
byb = collections.defaultdict(lambda: [0, 0, []])
for r in list(cour):
    B = part_block(r) or 'EDGE'; byb[B][0] += 1
    if plan.get(r): byb[B][1] += 1
    else: byb[B][2].append(r)
print('placed', sum(1 for r in plan if plan[r]), 'of', len(plan))
for B, (a, c, offl) in sorted(byb.items()): print('BLOCK', B, a, c, a - c, ' '.join(sorted(offl)))
print('relaxed anchors', sorted(relaxed)); print('anchors outside their rectangle', sorted(fallback_used)); print('anchors on the same-kind rule', sorted(samekind_used)); print('anchors OFF', [r for r in ANCH if plan.get(r) is None])
print('kinds', collections.Counter(kind.values()))
for r in [q for q in os.environ.get('DBG', '').split(',') if q]:
    for mode in (False, True):
        RELAX = mode; REASON.clear(); good = [k for k in cands(r) if ok(r, k[2], k[3], k[4])]; print('DBG', r, 'relaxed' if mode else 'strict', len(good), dict(REASON))
# ---- report: islands, and the stacking test redone from the final plan
for B, m in R.items():
    lab_, nn = ndimage.label(m)
    for k in range(1, nn + 1):
        ps = sorted(r for r, c in cour.items() if part_block(r) == B and r not in BNC and lab_[RG.ci((c[0] + c[2]) / 2), RG.cj((c[1] + c[3]) / 2)] == k)
        print('COMPONENT', B, k, 'area %.0f mm2' % ((lab_ == k).sum() * RG.RES ** 2), 'parts', len(ps), ' '.join(ps) if len(ps) < 6 else '')
allb = {q: bx for q, bx in placed.items()}
bad = []
for q, bx in allb.items():
    if q not in own_of: continue
    go = gap(bx, own_of[q]); dn = min((gap(bx, bo) for q2, bo in allb.items() if q2 != q), default=9e9)
    if dn <= go: bad.append((q, round(go, 2), round(dn, 2)))
print('STACK test failures', bad)
