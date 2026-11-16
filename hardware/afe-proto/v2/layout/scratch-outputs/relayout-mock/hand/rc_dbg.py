"""Placement checks for the relayout (phase 1), in the PCB image:  python3 relayout_check.py NEW.kicad_pcb OLD.kicad_pcb
  silk clearance : every top designator and top text (true ink box from pcbnew) at least 0.3 mm from every top silk line (drawn lines, the outline
                   lines, every footprint's own silk lines), 0.3 mm from arcs, circles and rects (their box: conservative), and 0.5 mm from every other
                   text; a text on its own part's silk counts
  courtyards     : no two overlap (every part)
  board          : every courtyard inside the board outline and, for parts other than the edge headers, outside the two top keep-out bands
  fixed          : J601-J607, J101, J201, J301, MH601, MH602 and U101 at their old origin and rotation
Prints every finding and a count."""
import math, sys
import pcbnew
mm = pcbnew.ToMM
BOARD = (17.0, -4.5, 117.0, 57.84); BANDS = [(17.0, -4.5, 117.0, 0.0), (17.0, 53.34, 117.0, 57.84)]
FIXED = ['J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607', 'J101', 'J201', 'J301', 'MH601', 'MH602', 'U101']
EDGE = {'J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607'}


def X(v): return mm(v) - 50.0
def Y(v): return 150.0 - mm(v)
def box(bb): return (X(bb.GetLeft()), Y(bb.GetBottom()), X(bb.GetRight()), Y(bb.GetTop()))
def rect_gap(a, b):
    dx = max(b[0] - a[2], 0, a[0] - b[2]); dy = max(b[1] - a[3], 0, a[1] - b[3]); return math.hypot(dx, dy)
def seg_box_dist(a, b, r):
    """distance from segment a-b to rectangle r (0 when they touch)"""
    if min(max(a[0], b[0]), r[2]) >= max(min(a[0], b[0]), r[0]) and min(max(a[1], b[1]), r[3]) >= max(min(a[1], b[1]), r[1]):
        n = 200
        best = 1e9
        for k in range(n + 1):
            p = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n); best = min(best, rect_gap((p[0], p[1], p[0], p[1]), r))
        if best < 1e-6: return 0.0
    n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.05))
    best = 1e9
    for k in range(n + 1):
        p = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n); best = min(best, rect_gap((p[0], p[1], p[0], p[1]), r))
    return best


def read(path):
    b = pcbnew.LoadBoard(path)
    parts, lines, boxes, texts = {}, [], [], []
    for f in b.GetFootprints():
        r = f.Reference()
        sh = r.GetEffectiveTextShape().BBox()
        c = f.GetCourtyard(pcbnew.F_CrtYd)
        parts[f.GetReference()] = dict(x=X(f.GetPosition().x), y=Y(f.GetPosition().y), rot=f.GetOrientationDegrees(), cy=box(c.BBox()) if c.OutlineCount() else None,
                                       ink=box(sh) if r.IsVisible() and b.GetLayerName(r.GetLayer()) == 'F.Silkscreen' else None)
        for g in f.GraphicalItems():
            if g.GetLayer() == pcbnew.F_SilkS and not hasattr(g, 'GetText'):
                (lines if g.GetShapeStr() == 'Line' else boxes).append((f.GetReference(), (X(g.GetStart().x), Y(g.GetStart().y)), (X(g.GetEnd().x), Y(g.GetEnd().y)), box(g.GetBoundingBox())))
    for d in b.GetDrawings():
        if d.GetLayer() != pcbnew.F_SilkS: continue
        if hasattr(d, 'GetText'):
            texts.append(('text ' + d.GetText(), box(d.GetEffectiveTextShape().BBox())))
        elif d.GetShapeStr() == 'Line':
            lines.append(('board', (X(d.GetStart().x), Y(d.GetStart().y)), (X(d.GetEnd().x), Y(d.GetEnd().y)), box(d.GetBoundingBox())))
        else:
            boxes.append(('board', None, None, box(d.GetBoundingBox())))
    return parts, lines, boxes, texts


def main(new, old):
    P, lines, boxes, texts = read(new)
    P0 = read(old)[0]
    bad = 0
    def say(s):
        nonlocal bad; bad += 1; print(s)
    labels = {r: p['ink'] for r, p in P.items() if p['ink']}
    for r, ink in sorted(labels.items()):
        for own, a, b, bb in lines:
            d = seg_box_dist(a, b, ink)
            if d < 0.3 - 1e-6: say('silk line: %s label %.2f mm from a line of %s ink=%s line=%s-%s' % (r, d, own, ink, a, b))
        for own, a, b, bb in boxes:
            d = rect_gap(ink, bb)
            if d < 0.3 - 1e-6: say('silk shape: %s label %.2f mm from a shape of %s (box)' % (r, d, own))
        for name, tb in texts:
            d = rect_gap(ink, tb)
            if d < 0.5 - 1e-6: say('silk text: %s label %.2f mm from %s' % (r, d, name))
    L = sorted(labels.items())
    for i in range(len(L)):
        for j in range(i + 1, len(L)):
            d = rect_gap(L[i][1], L[j][1])
            if d < 0.5 - 1e-6: say('label gap: %s and %s %.2f mm' % (L[i][0], L[j][0], d))
    cy = {r: p['cy'] for r, p in P.items() if p['cy']}
    ks = sorted(cy)
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            a, c = cy[ks[i]], cy[ks[j]]
            if min(a[2], c[2]) - max(a[0], c[0]) > 1e-6 and min(a[3], c[3]) - max(a[1], c[1]) > 1e-6:
                say('courtyards overlap: %s %s' % (ks[i], ks[j]))
    for r, c in cy.items():
        if c[0] < BOARD[0] or c[1] < BOARD[1] or c[2] > BOARD[2] or c[3] > BOARD[3]: say('outside the board: ' + r)
        if r not in EDGE and not r.startswith('MH') and r not in ('J101', 'J201', 'J301'):
            for k in BANDS:
                if min(c[2], k[2]) > max(c[0], k[0]) and min(c[3], k[3]) > max(c[1], k[1]): say('in a keep-out band: ' + r)
    for r in FIXED:
        a, o = P[r], P0[r]
        if abs(a['x'] - o['x']) > 1e-4 or abs(a['y'] - o['y']) > 1e-4 or abs(a['rot'] - o['rot']) > 1e-4: say('fixed part moved: ' + r)
    print('findings:', bad)


main(sys.argv[1], sys.argv[2])
