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
BNC_X = _t.BNC_X                                                                     # the three BNCs share one x (Due mm)
BNC_Y = dict(_t.BNC_Y)                                                               # {ref: y of pin 1, Due mm}: the owner's ruling of 2026-11-13
AWG_EXTRA_GAP = _t.AWG_EXTRA_GAP                                                     # AWG to CH2 is at least SCOPE_PITCH + this
SCOPE_PITCH = _t.SCOPE_PITCH                                                         # CH1 to CH2; AWG to CH2 is at least this
# J605's designator sat at (100.0, 51.75), where CH1's BNC box and the BNC's own silk now reach (the BNC moved north 2.54 mm). It moves above the
# socket, into the strip between the socket's own silk (top edge 52.13) and the Due's edge, beside the owner's pin labels' band and not in it
# (silk only; v2/layout/place_bncs.py). {ref: (x, y) Due mm, centre of the label}
DESIGNATOR_AT = {'J605': (96.2, 53.0)}
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

# The Due's own pin names, printed on top silk in the bands beside each edge-row socket (LR-11, owner 2026-11-13: the shield covers the
# Due's silkscreen). pcbtools/pinlabels.py builds them from this config and the table; no name is typed here. EDGE_SOCKETS: which sockets
# are edge rows -> the Due header whose table gives their pins (J605, the XIO socket, is on the short edge and is not one).
EDGE_SOCKETS = {'J601': 'POWER0', 'J602': 'ADCL0', 'J603': 'ADCH0', 'J604': 'PWMH0', 'J606': 'PWML0', 'J607': 'COMMUNICATION0'}
PIN_TABLE = 'hardware/afe-proto/docs/due-header-table.md'     # repo relative; names are its "Arduino" / "Due label" column
PIN_LABEL_ALIASES = {'3.3 V': '3V3', '5 V': '5V'}             # a whole table cell -> the name the Due prints (the cells spell them with a space)
PIN_LABEL_FUNCTION_HEADERS = ('COMMUNICATION0',)              # the Due prints the function there (TX3, RX3 ... SDA, SCL): the table cell's word that is not the Dnn number
# Every label is exactly this high and this wide (the stroke font's default width at that height), turned 90 degrees, on both bands. Nothing is
# narrowed or shrunk: the OVERHANG is sized to fit the longest name.
PIN_LABEL_H = 1.0                # the board house's minimum silk text height (docs/jlcpcb.md)
PIN_LABEL_W = 1.0
PIN_LABEL_THICK = 0.15           # stroke
PIN_LABEL_EDGE_MARGIN = 0.35     # the ink starts this far inside the board edge
PIN_LABEL_PAD_GAP = 0.7          # and ends at least this far from a socket pad box: the socket footprint's silk outline sits 0.4 mm outside its pads (it is
                                 # not in the board arrays), so the label stops 0.3 mm short of that line *(check against DRC silk_overlap)*
PIN_LABEL_POS_TOL = 0.05         # the checker finds a label within this of its planned place
OVERHANG_STEP = 0.5              # the overhang is rounded UP to this
from .. import pinlabels as _pl  # noqa: E402
_ink = _pl.load_ink()            # measured in the PCB image by `python3 -m pcbtools.pinlabels --measure` (a test re-measures it)
assert (_ink['h'], _ink['w'], _ink['thick']) == (PIN_LABEL_H, PIN_LABEL_W, PIN_LABEL_THICK), 'pinlabel_ink.json was measured at another size: re-measure'
PIN_LABEL_INK = dict(_ink['ink'])                               # {name: ink length along the baseline, mm}
PIN_LABEL_INK_H = _ink['ink_h']                                 # ink across the baseline
PIN_PAD_EDGE = _ink['pad_edge']                                 # socket pad box to the Due's own edge, mm
PIN_LABEL_NAMES = _pl.label_names(os.path.join(_pl.REPO, PIN_TABLE), sorted(set(EDGE_SOCKETS.values())), PIN_LABEL_ALIASES, PIN_LABEL_FUNCTION_HEADERS)
PIN_LABEL_LONGEST = max(PIN_LABEL_NAMES, key=lambda n: PIN_LABEL_INK[n])

# The board outline and the two edge bands (owner's ruling 2026-11-13, MC-1 amended; v1 does the same in boards/v1.py). The shield's
# rectangle in Due mm (y up) overhangs the Due by OVERHANG on each long edge: the analog-header edge (the south edge, y 0, the strip with the
# J601/J602/J603 sockets) and the opposite one (north, y 53.34), so the board is centred over the Due. OVERHANG is COMPUTED: the longest pin
# name's measured ink at PIN_LABEL_H, after the pad edge and PIN_LABEL_PAD_GAP and before PIN_LABEL_EDGE_MARGIN, rounded up to OVERHANG_STEP
# (pinlabels.required_overhang); nothing here is a typed figure. Each band is a TOP-layer keep-out only (one rule area per band: no tracks,
# vias or pour on KEEPOUT_LAYERS); the bottom ground plane fills both bands back to the copper-to-edge clearance, and its zone outline is
# the board rectangle grown by ZONE_MARGIN. The strip lanes (VNEG, +3V3A, VREF-C at y 0.55 / 0.95 / 1.35) stay where they are.
# v2/layout/outline_overhang.py applies it to the board file.
DUE_RECT = (17.0, 0.0, 117.0, 53.34)                            # the Due's own outline in Due mm, where the shield sits over it
OVERHANG = _pl.required_overhang(PIN_LABEL_INK[PIN_LABEL_LONGEST], PIN_PAD_EDGE, PIN_LABEL_PAD_GAP, PIN_LABEL_EDGE_MARGIN, OVERHANG_STEP)
BOARD_RECT = (DUE_RECT[0], DUE_RECT[1] - OVERHANG, DUE_RECT[2], DUE_RECT[3] + OVERHANG)
BOARD_MAX_MM = (100.0, 100.0)                                   # MC-1: the board fits the board house's 100 x 100 mm price tier
BAND_NAME = 'analog edge band'                                  # the first band (the second is FAR_BAND_NAME)
FAR_BAND_NAME = 'far edge band'
KEEPOUTS = [(BAND_NAME, (DUE_RECT[0], BOARD_RECT[1], DUE_RECT[2], DUE_RECT[1])),
            (FAR_BAND_NAME, (DUE_RECT[0], DUE_RECT[3], DUE_RECT[2], BOARD_RECT[3]))]
KEEPOUT_LAYERS = ('F.Cu',)                                      # top only: the bottom ground plane fills the bands
ZONE_MARGIN = 0.05                                              # the bottom GND zone outline is BOARD_RECT grown by this; its fill is held back by the edge clearance

# The design rules the project file carries and DRC judges the board against (v2/layout/v2-integration build RULES: clearance 0.15,
# track 0.15, via 0.6 / 0.3, hole-to-hole 0.25). min_copper_edge_clearance 0.45 mm: the fabricator's minimum is 0.2 mm *(check)* and the
# outline tolerance +-0.2 mm, so 0.45 leaves 0.25 mm worst case (spec team's ruling, as v1).
BOARD_SETUP = {
    'board': {'design_settings': {'rules': {"max_error": 0.005, "min_clearance": 0.15, "min_connection": 0.0, "min_copper_edge_clearance": 0.45, "min_groove_width": 0.0, "min_hole_clearance": 0.25, "min_hole_to_hole": 0.25, "min_microvia_diameter": 0.2, "min_microvia_drill": 0.1, "min_resolved_spokes": 2, "min_silk_clearance": 0.0, "min_text_height": 1.0, "min_text_thickness": 0.12, "min_through_hole_diameter": 0.3, "min_track_width": 0.15, "min_via_annular_width": 0.15, "min_via_diameter": 0.5, "solder_mask_to_copper_clearance": 0.0, "use_height_for_length_calcs": True}}},
    'net_settings': {'classes': [{"bus_width": 12, "clearance": 0.15, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25, "diff_pair_width": 0.15, "line_style": 0, "microvia_diameter": 0.3, "microvia_drill": 0.1, "name": "Default", "pcb_color": "rgba(0, 0, 0, 0.000)", "priority": 2147483647, "schematic_color": "rgba(0, 0, 0, 0.000)", "track_width": 0.15, "tuning_profile": "", "via_diameter": 0.6, "via_drill": 0.3, "wire_width": 6}], 'meta': {'version': 5}, 'net_colors': {}, 'netclass_assignments': {}, 'netclass_patterns': []},
}

# LR-11 on the committed board adds the identity block (pcbtools/identity.py) and the no-arrow rule; the frozen fixtures and the old-tool
# comparisons read boards/v2.py, which carries the fields but not this switch, because their boards predate the identity.
IDENTITY_CHECK = True
SILK_WORDS = tuple(SILK_WORDS) + (NAME, ID_LINE, SN_LABEL)    # top silk words; the bottom marker is held by identity.findings (boardio reads F.SilkS texts only)
