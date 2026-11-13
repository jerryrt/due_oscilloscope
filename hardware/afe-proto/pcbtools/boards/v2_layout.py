"""BoardConfig of the v2 LAYOUT OF RECORD (v2/layout/integrated/afe-v2-integrated.kicad_pcb): boards/v2 with the block outlines
the layout actually has. `--config v2_layout`. boards/v2 itself stays frozen (it reads the PASS-2 fixture table, whose SCOPE
rectangles the east re-placement made stale); every other field is imported from it unchanged.

The outlines come from v2/layout/outlines.py, the one table the silkscreen is drawn from too, and
v2/layout/outlines_from_silk.py recovers them from the board so a test can hold the two equal.
"""
import importlib.util
import os

from .v2 import *  # noqa: F401,F403  every public name of the frozen config

_TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'v2', 'layout', 'outlines.py')
_spec = importlib.util.spec_from_file_location('_pcbtools_v2_layout_outlines', _TABLE)
_t = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_t)

OUTLINE = {k: list(v) for k, v in _t.RECTS.items()}                                  # LR-11, and LR-1's fence below
SHARED_PARTS = dict(_t.SHARED_PARTS)
SHARED_MARGIN = _t.SHARED_MARGIN
# the designator legibility check of LR-11 (rules.py): thresholds, all mm
# The text box. Measured in pcbnew 10.x on this board (GetEffectiveTextShape, the ink of the 112 reference fields, size 1.0 mm,
# thickness 0.15): 4-character designators are 3.44-3.67 mm long, 5-character ones 4.48-4.77 mm (0.86-0.95 of the height per
# character, worst case taken), 1.15-1.20 mm across, centred within 0.07 mm of the text position. The first guess, 0.65 per
# character, was short by a third and the DRC said so (silk_over_copper on labels judged clear).
DESIGNATOR_ADVANCE = 0.95        # length of the box per character, as a fraction of the text height
DESIGNATOR_INK_H = 1.2           # width of the box across the text, as a fraction of the text height (ink plus stroke)
DESIGNATOR_GAP_MIN = 1.0         # two designators are at least this far apart, edge to edge: one character height (1.0 mm text, the project's
                                 # DRC minimum text height)
DESIGNATOR_GAP_ONE_LABEL = 0.6   # two labels on one baseline (vertical extents overlapping by more than half a box height) closer than this read as one
                                 # label (C401C402): they fail whatever DESIGNATOR_GAP_WAIVED says, a waiver can never cover them
DESIGNATOR_DIST_MAX = 3.0        # a designator is at most this far from the nearest pad of its own part
# A label whose centre lies in another block's outline fails LR-11. These two cannot be moved home by any silk-only change, which was
# searched exhaustively (every 0.1 mm place and both turns, clear of pads, vias, silk and its own part, within DESIGNATOR_DIST_MAX of
# the part's pads): BR501 and BR504 sit against the REFCAL box's east side with CH2 beyond it. Closing them needs a part to move (a
# human decision). R203 and R204 were waived too until CH2's resistor-capacitor array (R201-R207, C201-C203) moved 1.3 mm north,
# which put the bottom row's labels inside CH2 under the row. {ref: the block whose outline the label sits in}, an exact match.
DESIGNATOR_FOREIGN_WAIVED = {'BR501': 'CH2', 'BR504': 'CH2'}
# The pairs the room does not allow. The CH2 and AWG passives sit on a 1.5-3 mm grid and a 1 mm designator is 3.4-4.8 mm long, so
# with every part where it is, no placement keeps every pair 1.0 mm apart: the placement search (v2/layout/place_designators.py)
# got 74 pairs under 1.0 mm down to these 20 (none touching: closest 0.30 mm) and not lower, from several starts and with the
# distance to the part relaxed to 3.5 and 4.5 mm. Each is recorded at the gap it reached, rounded down to 0.05; the check holds a
# pair to its floor, so it still catches a label that moves toward its neighbour. Closing them means moving a part or shortening a
# label (a human decision); the board house's minimum text height is the project's 1.0 mm, so a smaller label is not an option.
DESIGNATOR_GAP_WAIVED = {('BR502', 'R507'): 0.60, ('BR508', 'J501'): 0.30, ('C201', 'R201'): 0.80, ('C306', 'R301'): 0.80,
                         ('J501', 'R509'): 0.40, ('R206', 'R207'): 0.75, ('R304', 'R306'): 0.65, ('R307', 'U301'): 0.40}
# 8 pairs after the CH2 array moved north (17 before it, 20 at first): v2/layout/refine_designators.py (silk only, after place_designators.py) turned and moved labels until none
# reads as one label (DESIGNATOR_GAP_ONE_LABEL: no same-baseline pair is under 0.65 mm, and the rule below is not waivable). Three
# pairs are still under 0.6 mm and are NOT one word - BR508/J501 and R307/U301 are stacked lines, J501/R509 a horizontal and a vertical
# label - and none could be improved by any silk-only move (each label sits at its best admissible place with the others fixed).

# The board outline and the analog-edge band (owner's ruling 2026-11-13, MC-1 amended; v1 does the same in boards/v1.py). The shield's
# rectangle in Due mm (y up). It overhangs the Due by 5 mm on the analog-header edge only (the south edge, y 0, the strip with the
# J601/J602/J603 sockets), and that band is a copper keep-out (one rule area: no tracks, vias or pour, on every copper layer). The other
# edges keep the Due's outline, so the board is 100 x 58.34 mm, and the strip lanes (VNEG, +3V3A, VREF-C at y 0.55 / 0.95 / 1.35) stay
# where they are and are 5.55 mm or more from the cut. v2/layout/outline_overhang.py applies it to the board file.
OVERHANG = 5.0
BOARD_RECT = (17.0, -OVERHANG, 117.0, 53.34)
BOARD_MAX_MM = (100.0, 58.34)                                   # MC-1: the board fits in this
KEEPOUTS = [('analog edge band', (17.0, -OVERHANG, 117.0, 0.0))]
BAND_NAME = 'analog edge band'
# The design rules the project file carries and DRC judges the board against (v2/layout/v2-integration build RULES: clearance 0.15,
# track 0.15, via 0.6 / 0.3, hole-to-hole 0.25). min_copper_edge_clearance 0.45 mm: the fabricator's minimum is 0.2 mm *(check)* and the
# outline tolerance +-0.2 mm, so 0.45 leaves 0.25 mm worst case (spec team's ruling, as v1).
BOARD_SETUP = {
    'board': {'design_settings': {'rules': {"max_error": 0.005, "min_clearance": 0.15, "min_connection": 0.0, "min_copper_edge_clearance": 0.45, "min_groove_width": 0.0, "min_hole_clearance": 0.25, "min_hole_to_hole": 0.25, "min_microvia_diameter": 0.2, "min_microvia_drill": 0.1, "min_resolved_spokes": 2, "min_silk_clearance": 0.0, "min_text_height": 1.0, "min_text_thickness": 0.12, "min_through_hole_diameter": 0.3, "min_track_width": 0.15, "min_via_annular_width": 0.15, "min_via_diameter": 0.5, "solder_mask_to_copper_clearance": 0.0, "use_height_for_length_calcs": True}}},
    'net_settings': {'classes': [{"bus_width": 12, "clearance": 0.15, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25, "diff_pair_width": 0.15, "line_style": 0, "microvia_diameter": 0.3, "microvia_drill": 0.1, "name": "Default", "pcb_color": "rgba(0, 0, 0, 0.000)", "priority": 2147483647, "schematic_color": "rgba(0, 0, 0, 0.000)", "track_width": 0.15, "tuning_profile": "", "via_diameter": 0.6, "via_drill": 0.3, "wire_width": 6}], 'meta': {'version': 5}, 'net_colors': {}, 'netclass_assignments': {}, 'netclass_patterns': []},
}
