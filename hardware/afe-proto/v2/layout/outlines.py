"""THE table of the integrated v2 board's block outlines: one source for the silkscreen and for the LR-11 config.

Rectangles are (x0, y0, x1, y1) in Due mm (x right, y up, origin the Due's lower-left corner: KiCad sheet x - 50, 150 - y).
A block is outlined by one or more rectangles (its main area, a small box beside it, its BNC). Two things read this table and
nothing else holds a copy:
  - v2/layout/draw_outlines.py draws a rectangle that the board's F.Silkscreen lacks (the dashed outlines of the main areas were
    drawn by the block scripts; v2/layout/outlines_from_silk.py recovers them from the board and the test compares);
  - pcbtools/boards/v2_layout.py takes OUTLINE (and the analog fence, LR-1) and SHARED_PARTS from it.
"""
RECTS = {
    'POWER': [(17.9, 4.6, 43.6, 26.0)],
    'REFCAL': [(44.2, 4.6, 64.4, 27.8), (64.6, 18.6, 70.2, 26.0)],
    'CH1': [(63.9, 33.0, 93.0, 50.0), (60.4, 34.6, 64.0, 36.8), (98.5, 34.0, 116.4, 50.0)],
    'CH2': [(69.0, 19.75, 93.0, 32.9), (98.5, 16.5, 116.4, 32.0)],
    'AWG': [(70.4, 4.55, 92.3, 19.25), (98.55, 0.75, 116.4, 16.5)],
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
