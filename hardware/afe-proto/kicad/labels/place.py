"""place.py BOARD OUT.json: one place for every designator, parts and copper untouched (owner, 2026-11-17; D30 amended).

Rule 1: above its part, 0 degrees. Rule 2: else beside it (east or west), 0 or 90 degrees, under the tested reading (pcbtools.silkread: the nearest
courtyard to the text is its own by >= 0.25 mm, on no pad and no other courtyard). Never under its own body. 1.0 mm text. A designator with no such place
comes OFF the silk (to F.Fab); no exceptions, no keys. Anchors (every U and every J) are placed FIRST, from the most constrained; passives take what is left.
Board silk that is not a designator (block outlines and names, connector and pin labels, identity) stays where it is and is an obstacle.
Prints the plan; writes {ref: [x, y, angle] | null} (Due mm)."""
import sys, json, math, collections, os
sys.path.insert(0, '.'); sys.path.append('/usr/lib/python3/dist-packages')
import numpy as np
import pcbnew
from pcbtools import boardio, silkread
from pcbtools.boards import v1 as C
path, out = sys.argv[1], sys.argv[2]
b = boardio.read_board(path)
refs = list(b.fp_ref); n = len(refs)
ADV, INK = C.DESIGNATOR_ADVANCE, C.DESIGNATOR_INK_H       # box along the text per character / across the text, x text height
GAPL = 0.6          # label to label (v1.DESIGNATOR_GAP_ONE_LABEL)
CLR = 0.10          # label to pads, vias, other silk
EDGE = 0.4
cour = {r: (float(b.fp_cx0[i]), float(b.fp_cy0[i]), float(b.fp_cx1[i]), float(b.fp_cy1[i])) for i, r in enumerate(refs) if not np.isnan(b.fp_cx0[i]) and int(b.fp_side[i]) == 0}
# ---- obstacles
pads = np.column_stack([b.p_bx0, b.p_by0, b.p_bx1, b.p_by1]).astype(float)
vias = np.column_stack([b.v_x - b.v_dia / 2, b.v_y - b.v_dia / 2, b.v_x + b.v_dia / 2, b.v_y + b.v_dia / 2]).astype(float) if len(b.v_x) else np.zeros((0, 4))
bd = pcbnew.LoadBoard(path); mm = pcbnew.ToMM
def tobox(bb):
    x0, y0 = boardio.to_due(mm(bb.GetX()), mm(bb.GetY())); x1, y1 = boardio.to_due(mm(bb.GetRight()), mm(bb.GetBottom()))
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
def ovl(a, A, m=0.0):                              # box a against an array of boxes
    if not len(A): return np.zeros(0, bool)
    return (a[0] - m < A[:, 2]) & (A[:, 0] - m < a[2]) & (a[1] - m < A[:, 3]) & (A[:, 1] - m < a[3])
cr_refs = list(cour); cr = np.array([cour[r] for r in cr_refs])
NAMES = ('CH1', 'CH2', 'AWG', 'POWER', 'REF/CAL')
pl = []
for fp in bd.GetFootprints():
    for pd in fp.Pads(): pl.append(tobox(pd.GetBoundingBox()))
pads = np.array(pl).reshape(-1, 4)
silk = []; silk_ref = []
for fp in bd.GetFootprints():
    for it in fp.GraphicalItems():
        if it.GetLayer() == pcbnew.F_SilkS: silk.append(tobox(it.GetBoundingBox())); silk_ref.append(fp.GetReference())
fixed_lab = {}                                    # designators left exactly as they are (the BNC frames)
for d in bd.GetDrawings():
    if d.GetLayer() != pcbnew.F_SilkS: continue
    if d.GetClass() == 'PCB_SHAPE':               # block outlines: the four edges, not the inside
        x0, y0, x1, y1 = tobox(d.GetBoundingBox()); w = 0.1
        silk += [(x0 - w, y0 - w, x1 + w, y0 + w), (x0 - w, y1 - w, x1 + w, y1 + w), (x0 - w, y0 - w, x0 + w, y1 + w), (x1 - w, y0 - w, x1 + w, y1 + w)]
    elif d.GetClass() == 'PCB_TEXT' and d.GetText() in NAMES: continue
    else: silk.append(tobox(d.GetBoundingBox()))
# block outlines (round 3): each block's full outline on the silk, drawn here from the rectangles below; the BNC ends are cut at the BNC labels
BASE = {'POWER': [(18.1, 4.15, 43.95, 22.9)], 'REFCAL': [(44.45, 4.8, 64.55, 31.3), (64.55, 10.6, 67.0, 13.5)],
        'AWG': [(69.8, 4.15, 92.0, 19.4)],
        'CH2': [(70.3, 22.4, 78.2, 32.5), (78.2, 22.4, 87.3, 30.4), (87.3, 22.4, 92.0, 27.0)],
        'CH1': [(64.3, 33.9, 92.0, 46.4), (78.65, 30.4, 84.7, 33.9)]}
BNCEND = {'AWG': (98.5, -0.5, 116.4, 17.4), 'CH2': (98.5, 17.9, 116.4, 36.3), 'CH1': (98.5, 36.8, 116.4, 54.1)}
PCX = np.array([(float(b.fp_x[i]), float(b.fp_y[i])) for i in range(n)])
def seg_box(x0, y0, x1, y1): return (min(x0, x1) - 0.075, min(y0, y1) - 0.075, max(x0, x1) + 0.075, max(y0, y1) + 0.075)
ANCHOR_BOX = np.zeros((0, 4))
def nudge_rects(rects, inside_all, outside_idx):
    """move each edge (within 1.5 mm) to the position with the fewest conflicts: a pad (0.25 clear) or a designator label of an anchor is a hard conflict, a footprint's silk
    a soft one, a foreign courtyard softer; every part that was inside stays inside (its courtyard too) and every part that was outside stays outside"""
    out = []
    for (x0, y0, x1, y1) in rects:
        cur = [x0, y0, x1, y1]
        inside_idx = [i for i in inside_all if x0 <= PCX[i][0] <= x1 and y0 <= PCX[i][1] <= y1]
        for e in (2, 0, 3, 1):
            best = None
            for d in sorted(np.arange(-3.0, 3.01, 0.05), key=abs):
                c = list(cur); c[e] += d
                if c[2] - c[0] < 1 or c[3] - c[1] < 1: continue
                seg = {0: (c[0], c[1], c[0], c[3]), 1: (c[0], c[1], c[2], c[1]), 2: (c[2], c[1], c[2], c[3]), 3: (c[0], c[3], c[2], c[3])}[e]
                sb = seg_box(*seg)
                okc = True
                for i in inside_idx:
                    ri = cr_refs.index(refs[i]) if refs[i] in cour else None
                    if ri is None: continue
                    q = cr[ri]
                    if not (c[0] + 0.05 <= q[0] and q[2] <= c[2] - 0.05 and c[1] + 0.05 <= q[1] and q[3] <= c[3] - 0.05): okc = False; break
                if not okc: continue
                if any(c[0] <= PCX[i][0] <= c[2] and c[1] <= PCX[i][1] <= c[3] for i in outside_idx): continue
                hard = int(ovl(sb, pads, 0.25).sum()) + (int(ovl(sb, ANCHOR_BOX, 0.2).sum()) if len(ANCHOR_BOX) else 0)
                soft = int(ovl(sb, silk, 0.12).sum())
                cour_hit = sum(1 for k in np.flatnonzero(ovl(sb, cr, 0.0)) if refs.index(cr_refs[k]) in outside_idx)
                score = 1000 * hard + 10 * soft + 2 * cour_hit + abs(d)
                if best is None or score < best[0]: best = (score, c, hard, soft)
            if best:
                cur = best[1]
                if best[2]: print('OUTLINE EDGE WITH A HARD CONFLICT', e, [round(float(v), 2) for v in cur])
                elif best[3]: print('outline edge over footprint silk', e, [round(float(v), 2) for v in cur], best[3])
        out.append(tuple(round(float(v), 2) for v in cur))
    return out
def union_edges(rects):
    xs = sorted({v for r in rects for v in (r[0], r[2])}); ys = sorted({v for r in rects for v in (r[1], r[3])})
    inside = lambda i, j: 0 <= i < len(xs) - 1 and 0 <= j < len(ys) - 1 and any(r[0] <= xs[i] and xs[i + 1] <= r[2] and r[1] <= ys[j] and ys[j + 1] <= r[3] for r in rects)
    segs = []
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            if not inside(i, j): continue
            if not inside(i - 1, j): segs.append((xs[i], ys[j], xs[i], ys[j + 1]))
            if not inside(i + 1, j): segs.append((xs[i + 1], ys[j], xs[i + 1], ys[j + 1]))
            if not inside(i, j - 1): segs.append((xs[i], ys[j], xs[i + 1], ys[j]))
            if not inside(i, j + 1): segs.append((xs[i], ys[j + 1], xs[i + 1], ys[j + 1]))
    # merge collinear touching pieces
    segs.sort(); out = []
    for a in segs:
        for k, o in enumerate(out):
            if a[0] == a[2] == o[0] == o[2] and a[1] <= o[3] and o[1] <= a[3]: out[k] = (o[0], min(o[1], a[1]), o[2], max(o[3], a[3])); break
            if a[1] == a[3] == o[1] == o[3] and a[0] <= o[2] and o[0] <= a[2]: out[k] = (min(o[0], a[0]), o[1], max(o[2], a[2]), o[3]); break
        else: out.append(a)
    return out
silk = np.array(silk).reshape(-1, 4)
body = {}
for fp in bd.GetFootprints():
    bs = [tobox(it.GetBoundingBox()) for it in fp.GraphicalItems() if it.GetLayer() == pcbnew.F_Fab and it.GetClass() == 'PCB_SHAPE']
    if bs: body[fp.GetReference()] = (min(x[0] for x in bs), min(x[1] for x in bs), max(x[2] for x in bs), max(x[3] for x in bs))
RELAX = False
BNC = ('J101', 'J201', 'J301')
placed = {}           # ref -> (box, x, y, ang)
def lab_box(r, x, y, ang, scale=True):
    L = len(r) * ADV; W = INK
    return (x - W / 2, y - L / 2, x + W / 2, y + L / 2) if ang == 90 else (x - L / 2, y - W / 2, x + L / 2, y + W / 2)
RECTS = {blk: list(v) for blk, v in C.OUTLINE.items()}
def in_rects(x, y, rects): return any(a <= x <= c and d <= y <= e for a, d, c, e in rects)
def home(r): return C.BLOCK.get(r)
def gap(a, c): return float(np.hypot(max(c[0] - a[2], 0, a[0] - c[2]), max(c[1] - a[3], 0, a[1] - c[3])))
REASON = collections.Counter()
def lab_clash(L, B):
    # two labels on a common baseline (vertical extents overlap by more than half of the smaller) must be GAPL apart horizontally (they read as one word);
    # otherwise 0.2 mm of clear silk
    vo = min(L[3], B[3]) - max(L[1], B[1]); sm = min(L[3] - L[1], B[3] - B[1])
    m = GAPL if vo > 0.5 * sm else 0.2
    mx = GAPL if vo > 0.5 * sm else 0.2
    return (B[0] - mx < L[2] and L[0] < B[2] + mx and B[1] - 0.2 < L[3] and L[1] < B[3] + 0.2)
def ok(r, x, y, ang, allow_placed=True):
    v = ok_(r, x, y, ang)
    return v if isinstance(v, bool) else (REASON.update([v]) or False)
def ok_(r, x, y, ang):
    L = lab_box(r, x, y, ang)
    if L[0] < C.DUE_RECT[0] + EDGE or L[2] > C.DUE_RECT[2] - EDGE or L[1] < C.DUE_RECT[1] + EDGE or L[3] > C.DUE_RECT[3] - EDGE: return 'edge'
    own = cour[r]
    if gap(L, own) < 0.05 or (L[0] < own[2] and own[0] < L[2] and L[1] < own[3] and own[1] < L[3]): return 'body'          # never under its own body
    # the tested reading, on silkread's own box (0.9 per character, 1.0 high)
    t = silkread.text_box(r, x, y, 1.0, 1.0, ang)
    g_own = gap(t, own)
    if RELAX:        # anchors only: on no other part's BODY (F.Fab outline) and on no pad; the nearest body is its own by OWN_MARGIN
        bk = [q for q in body if q != r]; BA = np.array([body[q] for q in bk])
        if ovl(t, BA).any(): return 'otherbody'
        gb = gap(t, body.get(r, cour[r]))
        if min(gap(t, body[q]) for q in bk) - gb < silkread.OWN_MARGIN: return 'ownmargin'
    else:
        m = ovl(t, cr); m[cr_refs.index(r)] = False
        if m.any(): return 'othercourt'
        others = [gap(t, cr[k]) for k in range(len(cr_refs)) if cr_refs[k] != r]
        if min(others) - g_own < silkread.OWN_MARGIN: return 'ownmargin'
    if ovl(L, pads, CLR).any() or ovl(L, vias, CLR).any(): return 'padvia'
    if ovl(L, silk, CLR).any(): return 'silk'
    for q, (B, *_r) in placed.items():
        if q != r and lab_clash(L, B): return 'label'
    h = home(r)
    if h and h != C.EDGE_BLOCK:
        for blk, rects in RECTS.items():
            if blk != h and in_rects(x, y, rects): return 'foreign'
    return True
GAPS = (0.15, 0.25, 0.35, 0.5, 0.7, 0.9)
def cands(r):
    c = cour[r]; cx, cy = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2; w, h = c[2] - c[0], c[3] - c[1]
    L = len(r) * ADV
    out = []
    for g in GAPS:
        for dx in sorted([0.0] + [s * k * 0.25 for k in range(1, int((w / 2 + 1.0 + L / 2) / 0.25) + 2) for s in (1, -1)], key=abs):
            if abs(dx) <= w / 2 + 1.0 + L / 2: out.append((0, 'above', cx + dx, c[3] + g + INK / 2, 0, g, abs(dx)))
    for g in GAPS:
        for dy in sorted([0.0] + [s * k * 0.25 for k in range(1, int((h / 2 + 1.0) / 0.25) + 2) for s in (1, -1)], key=abs):
            if abs(dy) <= h / 2 + 0.5:
                out.append((1, 'east', c[2] + g + L / 2, cy + dy, 0, g, abs(dy))); out.append((1, 'west', c[0] - g - L / 2, cy + dy, 0, g, abs(dy)))
    for g in GAPS:
        for dx in sorted([0.0] + [s * k * 0.25 for k in range(1, int((w / 2 + 1.0 + L / 2) / 0.25) + 2) for s in (1, -1)], key=abs):
            if abs(dx) <= w / 2 + 1.0 + L / 2: out.append((1.5, 'below', cx + dx, c[1] - g - INK / 2, 0, g, abs(dx)))
    for g in GAPS:
        for dy in sorted([0.0] + [s * k * 0.25 for k in range(1, int((h / 2 + 1.0 + L / 2) / 0.25) + 2) for s in (1, -1)], key=abs):
            if abs(dy) <= h / 2 + 1.0 + L / 2:
                out.append((2, 'east90', c[2] + g + INK / 2, cy + dy, 90, g, abs(dy))); out.append((2, 'west90', c[0] - g - INK / 2, cy + dy, 90, g, abs(dy)))
    return sorted(out, key=lambda t: (t[0], t[5], t[6]))
def first_ok(r, only=None):
    global RELAX
    RELAX = False
    k = first_ok_(r, only)
    if k or r not in anchors_set: return k
    RELAX = True
    k = first_ok_(r, only); RELAX = False
    if k: relaxed.add(r)
    return k
relaxed = set(); anchors_set = set()
def first_ok_(r, only=None):
    for k in cands(r):
        if only and k[1] not in only: continue
        if ok(r, k[2], k[3], k[4]): return k
    return None
# ---- order: anchors first
anchors = [r for r in cr_refs if r.startswith(('U', 'J', 'TP')) and r not in BNC]
MH = [r for r in cr_refs if r.startswith('MH')]
rest = [r for r in cr_refs if r not in anchors and r not in BNC and r not in MH]
# BNC designators stay as they are (identical frames, D30 2)
BNCFN = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}
BNC_OFF = 8.6; BNC_DX = (2.0, 9.0)           # the offset of each BNC's designator and function label from its centre, the same in every frame (all three are at -90)
plan = {}; kind = {}; fnpos = {}
for r in BNC:
    i = ix_ = refs.index(r); cx, cy = float(b.fp_x[i]), float(b.fp_y[i])
    xd, yd = cx + BNC_DX[0], cy + BNC_OFF; xl = cx + 7.0          # the function label is LEFT-justified, so its offset in the BNC's frame is the same for all three
    L1 = lab_box(r, xd, yd, 0); L2 = (xl, yd - INK / 2, xl + len(BNCFN[r]) * ADV, yd + INK / 2)
    plan[r] = [round(xd, 3), round(yd, 3), 0]; kind[r] = 'bnc'; placed[r] = (L1, xd, yd, 0)
    fnpos[BNCFN[r]] = [round(xl, 3), round(yd, 3)]
    placed['fn_' + r] = (L2, 0, 0, 0)
    for q in (L1, L2):
        hits = [bool(ovl(q, pads, 0.05).any()), bool(ovl(q, silk, 0.05).any())]
        print('BNC label', r, [round(v, 2) for v in q], 'on pad' if hits[0] else '', 'on silk' if hits[1] else '')
def feasibility(r): return sum(1 for k in cands(r) if ok(r, k[2], k[3], k[4]))
def run(order, tag):
    for r in order:
        k = first_ok(r)
        if k:
            placed[r] = (lab_box(r, k[2], k[3], k[4]), k[2], k[3], k[4]); plan[r] = [round(k[2], 3), round(k[3], 3), k[4]]; kind[r] = k[1]
        else:
            plan[r] = None; kind[r] = 'OFF'
for r in MH: plan[r] = None; kind[r] = 'OFF'
def build_outlines():
    global OUTL, OUTSEG, silk, ANCHOR_BOX
    ANCHOR_BOX = np.array([placed[q][0] for q in placed if q in anchors_set or q in BNC or q.startswith('fn_')]).reshape(-1, 4)
    OUTL = {}
    for B, rects in BASE.items():
        ins = {i for i in range(n) if any(r[0] <= PCX[i][0] <= r[2] and r[1] <= PCX[i][1] <= r[3] for r in rects)}
        outs = set(range(n)) - ins
        OUTL[B] = [tuple(r) for r in rects]
        if B in BNCEND: OUTL[B].append(BNCEND[B])
    print('OUTL', {k: [tuple(round(float(x), 2) for x in r) for r in v] for k, v in OUTL.items()})
    OUTSEG = {k: union_edges(v) for k, v in OUTL.items()}
    seen = set()
    for k in OUTSEG:
        keep = []
        for sg in OUTSEG[k]:
            key = tuple(round(float(v), 3) for v in sg)
            if key not in seen: seen.add(key); keep.append(sg)
        OUTSEG[k] = keep
    prefs = [refs[int(f)] for f in b.p_fp]; nb = len(silk_ref)
    for k, sg in OUTSEG.items():
        for x0, y0, x1, y1 in sg:
            sb = seg_box(x0, y0, x1, y1)
            ph = sorted({prefs[i] for i in np.flatnonzero(ovl(sb, pads, 0.08))}); sh = sorted({silk_ref[i] for i in np.flatnonzero(ovl(sb, silk[:nb], 0.12))})
            lh = [q for q in placed if (q in anchors_set or q in BNC or q.startswith('fn_')) and ovl(sb, np.array([placed[q][0]]), 0.2).any()]
            if ph or sh or lh: print('SEG', k, tuple(round(float(v), 2) for v in (x0, y0, x1, y1)), 'pads', ph, 'footprint silk', sh, 'labels', lh)
    add = [(x0 - 0.075, y0 - 0.075, x1 + 0.075, y1 + 0.075) for sg in OUTSEG.values() for x0, y0, x1, y1 in sg]
    silk = np.vstack([silk, np.array(add).reshape(-1, 4)])
anchors_set.update(anchors)
build_outlines()
anchors.sort(key=feasibility)
run(anchors, 'anchors')
# ---- block names: one size, each in the same corner of its block wherever it fits (inside the outline, clear of courtyards, pads and silk)
SIZE = 1.2; NAMETXT = {'POWER': 'POWER', 'REFCAL': 'REF/CAL', 'AWG': 'AWG', 'CH1': 'CH1', 'CH2': 'CH2'}
def name_box(t, x, y): return (x - len(t) * ADV * SIZE / 2, y - INK * SIZE / 2, x + len(t) * ADV * SIZE / 2, y + INK * SIZE / 2)
def name_ok(B, x, y):
    t = name_box(NAMETXT[B], x, y)
    if ovl(t, cr, 0.1).any() or ovl(t, pads, CLR).any() or ovl(t, vias, CLR).any() or ovl(t, silk, 0.15).any(): return False
    return not any(lab_clash(t, bx) for q, (bx, *_r) in placed.items())
def corner_spots(B, c):
    x0, y0, x1, y1 = OUTL[B][0]; t = NAMETXT[B]; L = len(t) * ADV * SIZE; Wd = INK * SIZE; m = 0.35
    base = {'TL': (x0 + m + L / 2, y1 - m - Wd / 2, 1, -1), 'TR': (x1 - m - L / 2, y1 - m - Wd / 2, -1, -1),
            'BL': (x0 + m + L / 2, y0 + m + Wd / 2, 1, 1), 'BR': (x1 - m - L / 2, y0 + m + Wd / 2, -1, 1)}[c]
    return sorted([(base[0] + base[2] * dx, base[1] + base[3] * dy, dx + dy) for dx in np.arange(0, 3.01, 0.25) for dy in np.arange(0, 3.01, 0.25)], key=lambda v: v[2])
feas = {B: {c: next(((x, y) for x, y, _ in corner_spots(B, c) if name_ok(B, x, y)), None) for c in ('TL', 'TR', 'BL', 'BR')} for B in NAMETXT}
print('NAME corners', {B: [c for c, v in f.items() if v] for B, f in feas.items()})
cnt = {c: sum(1 for B in feas if feas[B][c]) for c in ('TL', 'TR', 'BL', 'BR')}
best = max(('TL', 'TR', 'BL', 'BR'), key=lambda c: (cnt[c], -('TL', 'TR', 'BL', 'BR').index(c)))
names_plan = {}
for B in NAMETXT:
    order = [best] + [c for c in ('TL', 'TR', 'BL', 'BR') if c != best]
    c = next((c for c in order if feas[B][c]), None)
    if c is None: print('NAME OFF-CORNER', B); names_plan[NAMETXT[B]] = None; continue
    x, y = feas[B][c]; names_plan[NAMETXT[B]] = [round(x, 3), round(y, 3), SIZE]
    placed['name_' + B] = (name_box(NAMETXT[B], x, y), x, y, 0); print('NAME', B, c, round(x, 2), round(y, 2))
rest.sort(key=feasibility)
run(rest, 'rest')
# repair: a part with no place takes the only spot blocked by one movable passive's label if that passive has another place
def blockers(r, k):
    L = lab_box(r, k[2], k[3], k[4]); hit = []
    for q, (B, *_r) in placed.items():
        if q != r and lab_clash(L, B): hit.append(q)
    return hit
fixed_ref = set(anchors) | set(BNC)
for rnd in range(6):
    moved = 0
    for r in [q for q in plan if plan[q] is None and q not in BNC and q not in MH]:
        done = False
        for k in cands(r):
            saved = dict(placed)
            hit = blockers(r, k)
            if len(hit) != 1 or hit[0] in fixed_ref or hit[0].startswith(('fn_', 'name_')): continue
            q = hit[0]; old_q = placed.pop(q)
            if not ok(r, k[2], k[3], k[4]): placed[q] = old_q; continue
            placed[r] = (lab_box(r, k[2], k[3], k[4]), k[2], k[3], k[4])
            k2 = first_ok(q)
            if k2:
                placed[q] = (lab_box(q, k2[2], k2[3], k2[4]), k2[2], k2[3], k2[4]); plan[q] = [round(k2[2], 3), round(k2[3], 3), k2[4]]; kind[q] = k2[1]
                plan[r] = [round(k[2], 3), round(k[3], 3), k[4]]; kind[r] = k[1]; moved += 1; done = True; break
            placed.clear(); placed.update(saved)
    print('repair round', rnd, 'moved', moved)
    if not moved: break
json.dump(plan, open(out, 'w'))
json.dump(dict(names=names_plan, bncfn=fnpos, outline={k: [list(x) for x in v] for k, v in OUTSEG.items()}), open(out.replace('.json', '_extra.json'), 'w'))
byb = collections.defaultdict(lambda: [0, 0])
for r in cr_refs:
    if r in BNC: continue
    bl = C.BLOCK.get(r, '?'); byb[bl][0] += 1; byb[bl][1] += plan.get(r) is not None
print('placed', sum(1 for r in plan if plan[r]), 'of', len(plan), 'off', [r for r in plan if plan[r] is None])
print('by block (parts, labelled):', dict(byb))
print('kinds', collections.Counter(kind.values()))
import os
for r in os.environ.get('DBG','').split(','):
    if r:
        REASON.clear(); [ok(r, k[2], k[3], k[4]) for k in cands(r)]; print('DBG', r, dict(REASON))
for r in anchors:
    print('FEAS', r, sorted({k[1] for k in cands(r) if ok(r, k[2], k[3], k[4])}))
print('relaxed anchors', sorted(relaxed))
print('anchors OFF', [r for r in anchors if plan[r] is None])
for r in anchors: print('  ', r, kind[r], plan[r])
