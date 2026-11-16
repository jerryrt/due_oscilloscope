"""THE table of the integrated v2 board's block outlines: one source for the silkscreen and for the LR-11 config.

Rectangles are (x0, y0, x1, y1) in Due mm (x right, y up, origin the Due's lower-left corner: KiCad sheet x - 50, 150 - y).
A block is outlined by one or more rectangles (its main area, a small box beside it, its BNC). Two things read this table and
nothing else holds a copy:
  - v2/layout/draw_outlines.py draws a rectangle that the board's F.Silkscreen lacks (the dashed outlines of the main areas were
    drawn by the block scripts; v2/layout/outlines_from_silk.py recovers them from the board and the test compares);
  - pcbtools/boards/v2_layout.py takes OUTLINE (and the analog fence, LR-1) and SHARED_PARTS from it.
"""
# The three BNCs, Due mm. One x for all three; y is the centre of pin 1 (the footprint origin). The pitches are the owner's ruling of
# 2026-11-13: CH1 to CH2 is SCOPE_PITCH (17.78, a multiple of the Due's 2.54 mm grid), and AWG to CH2 is at least SCOPE_PITCH + AWG_EXTRA_GAP.
# Each input run crosses the XIO socket J605 in its old corridor, between two rows of its pins, and jogs to its BNC east of the socket. The AWG BNC did not move.
BNC_X = 102.0
SCOPE_PITCH = 17.78
BNC_Y = {'J101': 45.60, 'J201': 27.82, 'J301': 8.89}
# Spec lead's ruling after the first move: the scope pair sits closer to each other than to the AWG, so AWG to CH2 is at least SCOPE_PITCH + AWG_EXTRA_GAP.
# CH1's y is as far north as the Due edge allows (its courtyard top, y + 7.645, must stay inside 53.34); the AWG BNC and its run did not move.
AWG_EXTRA_GAP = 1.0
# the silk box of a BNC, as offsets of its y: (below, above). The two scope boxes keep the offsets they had; the AWG box is its own table
# entry below and its top edge is the line CH2's box used to share.
BNC_BOX = {'CH1': (-7.91, 8.09), 'CH2': (-7.63, 7.87)}
_BNC_OF = {'CH1': 'J101', 'CH2': 'J201'}


def _box(block):
    lo, hi = BNC_BOX[block]
    y = BNC_Y[_BNC_OF[block]]
    return (98.5, round(y + lo, 3), 116.4, round(y + hi, 3))


RECTS = {
    'POWER': [(17.9, 4.6, 34.5, 26.0), (34.5, 6.2, 39.2, 26.0), (39.2, 4.6, 43.6, 26.0), (17.9, 26.0, 34.0, 37.0)],
    'REFCAL': [(44.2, 4.6, 57.4, 27.8), (44.2, 27.8, 62.0, 38.0), (44.2, 38.0, 57.4, 47.1), (34.6, 26.6, 44.2, 48.9)],
    'CH1': [(62.4, 33.0, 74.9, 49.0), (74.9, 33.0, 80.1, 47.1), (80.1, 33.0, 92.25, 49.0), (58.0, 38.6, 62.4, 49.0), _box('CH1')],
    'CH2': [(69.0, 19.75, 92.25, 32.9), _box('CH2')],
    'AWG': [(59.0, 6.2, 62.2, 18.4), (62.2, 4.55, 80.0, 18.4), (80.0, 6.2, 84.9, 18.4), (84.9, 4.55, 92.25, 18.4), (70.4, 18.4, 92.25, 19.25), (59.0, 18.4, 65.0, 27.4), (98.55, 0.75, 116.4, 16.5)],
}
# Phase 1 of the relayout: the same rectangles as relayout_place.py REGIONS (one table there, for the placer; here for the silk and LR-11).

# The AWG's BNC outline (the last AWG rectangle) was a bracket on the board, a left side with two stubs; its right side and bottom
# are drawn from this table (draw_outlines.py). Its top is the CH2 BNC outline's bottom edge (sheet y 133.5), shared, 0.15 mm
# clear of the J301 footprint's own silk.

# U101 is ONE dual op-amp serving both channels, so it straddles the fence between the CH1 and CH2 outlines. Its designator
# says CH1 (1xx) and the board labels both halves; it is held to the CH1 outline (within SHARED_MARGIN mm of it, because its
# centre sits on the outline's edge) and is not counted as an extra part in any other outline.
SHARED_PARTS = {'U101': 'CH1'}
SHARED_MARGIN = 0.25


def all_rects():
    return [r for rs in RECTS.values() for r in rs]


# The outline is the boundary of the union of a block's rectangles, drawn solid (owner, 2026-11-16): an edge two rectangles of one block share is not drawn.
# GAP_BOXES: where no outline is drawn by design (the boundary between CH1 and CH2 round U101 and its designator beside its east end, open toward J605).
GAP_BOXES = [(73.9, 32.0, 93.6, 34.0)]


def boundary(rects):
    """the boundary of a union of rectangles as axis-aligned segments (x0, y0, x1, y1): each rectangle edge less the stretches that border another rectangle of the union"""
    segs = []
    for r in rects:
        for side in range(4):
            horiz = side < 2
            c = (r[1] if side == 0 else r[3]) if horiz else (r[0] if side == 2 else r[2])
            iv = [(r[0], r[2])] if horiz else [(r[1], r[3])]
            for q in rects:
                if q is r:
                    continue
                if horiz and abs((q[3] if side == 0 else q[1]) - c) < 1e-9:
                    lo, hi = max(r[0], q[0]), min(r[2], q[2])
                elif (not horiz) and abs((q[2] if side == 2 else q[0]) - c) < 1e-9:
                    lo, hi = max(r[1], q[1]), min(r[3], q[3])
                else:
                    continue
                iv = [p for a, b in iv for p in ([(a, b)] if hi <= a or lo >= b else [(a, lo)] * (lo > a) + [(hi, b)] * (hi < b))]
            segs += [(a, c, b, c) if horiz else (c, a, c, b) for a, b in iv if b - a > 1e-9]
    return segs


def clip_boxes(segs, boxes):
    """axis-aligned segments less the stretches inside `boxes` (x0, y0, x1, y1)"""
    out = []
    for (a, b, c, d) in segs:
        pieces = [(a, b, c, d)]
        for (x0, y0, x1, y1) in boxes:
            nxt = []
            for (p, q, r, t) in pieces:
                if abs(q - t) < 1e-9 and y0 < q < y1:                       # horizontal line through the box's rows
                    lo, hi = sorted((p, r))
                    for u, v in ((lo, min(hi, x0)), (max(lo, x1), hi)):
                        if v - u > 1e-9: nxt.append((u, q, v, q))
                elif abs(p - r) < 1e-9 and x0 < p < x1:
                    lo, hi = sorted((q, t))
                    for u, v in ((lo, min(hi, y0)), (max(lo, y1), hi)):
                        if v - u > 1e-9: nxt.append((p, u, p, v))
                else:
                    nxt.append((p, q, r, t))
            pieces = nxt
        out += pieces
    return out
