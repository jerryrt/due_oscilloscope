"""place.py BOARD OUT.json: one place for every designator, parts and copper untouched (owner, 2026-11-17; D30 amended).

Rule 1: above its part, 0 degrees. Rule 2: else beside it (east or west), 0 or 90 degrees, under the tested reading (pcbtools.silkread: the nearest
courtyard to the text is its own by >= 0.25 mm, on no pad and no other courtyard). Never under its own body. 1.0 mm text. A designator with no such place
comes OFF the silk (to F.Fab); no exceptions, no keys. Anchors (every U and every J) are placed FIRST, from the most constrained; passives take what is left.
Board silk that is not a designator (block outlines and names, connector and pin labels, identity) stays where it is and is an obstacle.
Prints the plan; writes {ref: [x, y, angle] | null} (Due mm)."""
import sys, json, math, collections
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
silk = []
for fp in bd.GetFootprints():
    for it in fp.GraphicalItems():
        if it.GetLayer() == pcbnew.F_SilkS: silk.append(tobox(it.GetBoundingBox()))
fixed_lab = {}                                    # designators left exactly as they are (the BNC frames)
for d in bd.GetDrawings():
    if d.GetLayer() != pcbnew.F_SilkS: continue
    if d.GetClass() == 'PCB_SHAPE':               # block outlines: the four edges, not the inside
        x0, y0, x1, y1 = tobox(d.GetBoundingBox()); w = 0.1
        silk += [(x0 - w, y0 - w, x1 + w, y0 + w), (x0 - w, y1 - w, x1 + w, y1 + w), (x0 - w, y0 - w, x0 + w, y1 + w), (x1 - w, y0 - w, x1 + w, y1 + w)]
    else: silk.append(tobox(d.GetBoundingBox()))
silk = np.array(silk).reshape(-1, 4)
body = {}
for fp in bd.GetFootprints():
    bs = [tobox(it.GetBoundingBox()) for it in fp.GraphicalItems() if it.GetLayer() == pcbnew.F_Fab and it.GetClass() == 'PCB_SHAPE']
    if bs: body[fp.GetReference()] = (min(x[0] for x in bs), min(x[1] for x in bs), max(x[2] for x in bs), max(x[3] for x in bs))
RELAX = False
BNC = ('J101', 'J201', 'J301')
def ovl(a, A, m=0.0):                              # box a against an array of boxes
    if not len(A): return np.zeros(0, bool)
    return (a[0] - m < A[:, 2]) & (A[:, 0] - m < a[2]) & (a[1] - m < A[:, 3]) & (A[:, 1] - m < a[3])
cr_refs = list(cour); cr = np.array([cour[r] for r in cr_refs])
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
anchors = [r for r in cr_refs if r.startswith(('U', 'J')) and r not in BNC]
MH = [r for r in cr_refs if r.startswith('MH')]
rest = [r for r in cr_refs if r not in anchors and r not in BNC and r not in MH]
# BNC designators stay as they are (identical frames, D30 2)
js = [j for j in range(len(b.r_fp))]
for j in js:
    r = refs[int(b.r_fp[j])]
    if r in BNC:
        if b.r_on_silk[j]: placed[r] = (lab_box(r, b.r_x[j], b.r_y[j], int(round(b.r_ang[j])) % 180), float(b.r_x[j]), float(b.r_y[j]), float(b.r_ang[j]))
def feasibility(r): return sum(1 for k in cands(r) if ok(r, k[2], k[3], k[4]))
plan = {}; kind = {}
def run(order, tag):
    for r in order:
        k = first_ok(r)
        if k:
            placed[r] = (lab_box(r, k[2], k[3], k[4]), k[2], k[3], k[4]); plan[r] = [round(k[2], 3), round(k[3], 3), k[4]]; kind[r] = k[1]
        else:
            plan[r] = None; kind[r] = 'OFF'
for r in MH: plan[r] = None; kind[r] = 'OFF'
# anchors: most constrained first
anchors_set.update(anchors)
anchors.sort(key=feasibility)
run(anchors, 'anchors')
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
            if len(hit) != 1 or hit[0] in fixed_ref: continue
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
