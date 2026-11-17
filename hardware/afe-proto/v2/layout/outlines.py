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
    # AFE-1's way (afe1-labels, kicad/labels/rects.py): ONE plain rectangle per block around its main group, no extra small boxes, strays sit outside; the BNC boxes keep one margin
    # on all four sides of the BNC's footprint silk, (input pitch - silk height)/2, the two inputs sharing one line. No two rectangles overlap.
    'POWER': [(17.9, 4.6, 43.6, 26.0)],
    'REFCAL': [(44.2, 4.6, 64.8, 27.8)],                    # its small second rectangle is gone: BR501-BR504 are strays outside
    'CH1': [(63.9, 33.0, 92.3, 49.0), (98.51, 36.71, 116.09, 54.49)],      # the small BR box is gone (BR102 is a stray); east edge 92.3 and north edge 49.0 stand clear of the J605 / J606 / J607 pads
    'CH2': [(69.0, 19.75, 92.3, 32.9), (98.51, 18.93, 116.09, 36.71)],
    'AWG': [(70.4, 4.3, 92.3, 19.25), (98.51, 0.0, 116.09, 17.78)],
}

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
