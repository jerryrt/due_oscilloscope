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
DESIGNATOR_AT = {'J605': (95.2, 53.2)}
# 3D models the board names by reference instead of the footprint's own (KiCad 10 ships none for the LM27762's WSON-12 package: the library's
# link dangles). ${KIPRJMOD} is the board's folder (v2/layout/integrated); the file is the project's own VRML stand-in, render only (a KiCad
# STEP export leaves it out). v2/layout/set_models.py applies it by text splice.
MODEL_BY_REF = {'U401': '${KIPRJMOD}/../../../kicad/lib/afe.3dshapes/WSON-12-1EP_3x2mm_P0.5mm_standin.wrl'}
SHARED_PARTS = dict(_t.SHARED_PARTS)
SHARED_MARGIN = _t.SHARED_MARGIN
# the designator legibility check of LR-11 (rules.py): thresholds, all mm
# The text box. Measured in pcbnew 10.x on this board (GetEffectiveTextShape, the ink of the 112 reference fields, size 1.0 mm,
# thickness 0.15): 4-character designators are 3.44-3.67 mm long, 5-character ones 4.48-4.77 mm (0.86-0.95 of the height per
# character, worst case taken), 1.15-1.20 mm across, centred within 0.07 mm of the text position. The first guess, 0.65 per
# character, was short by a third and the DRC said so (silk_over_copper on labels judged clear).
DESIGNATOR_ADVANCE = 0.95        # length of the box per character, as a fraction of the text height
DESIGNATOR_INK_H = 1.2           # width of the box across the text, as a fraction of the text height (ink plus stroke)
DESIGNATOR_GAP_MIN = 0.2         # D30 (1c), owner 2026-11-17: readability is judged by the two-way nearest test the placement ran (own part
                                 # and own label nearer by 0.15 mm); this floor is only the spacing that placement kept off a shared baseline
DESIGNATOR_GAP_ONE_LABEL = 0.6   # two labels on one baseline (vertical extents overlapping by more than half a box height) closer than this read as one
                                 # label (C401C402): they fail whatever DESIGNATOR_GAP_WAIVED says, a waiver can never cover them
DESIGNATOR_DIST_MAX = 3.0        # a designator is at most this far from the nearest pad of its own part
# A label whose centre lies in another block's outline fails LR-11. These two cannot be moved home by any silk-only change, which was
# searched exhaustively (every 0.1 mm place and both turns, clear of pads, vias, silk and its own part, within DESIGNATOR_DIST_MAX of
# the part's pads): BR501 and BR504 sit against the REFCAL box's east side with CH2 beyond it. Closing them needs a part to move (a
# human decision). R203 and R204 were waived too until CH2's resistor-capacitor array (R201-R207, C201-C203) moved 1.3 mm north,
# which put the bottom row's labels inside CH2 under the row. {ref: the block whose outline the label sits in}, an exact match.
DESIGNATOR_FOREIGN_WAIVED = {'BR501': 'CH2', 'BR504': 'CH2'}
DESIGNATOR_GAP_WAIVED = {}       # D30 (1c) replaced the 1.0 mm gap and its recorded floors

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

# Cluster keys (D30 1b, pcbtools/keys.py): where parts are held tight on purpose their designators come off and one outlined key in free area
# carries them in the parts' rows and columns. `parts` is the residue the silk-only placer could not place beside the part; until the placer has
# run, CH2's whole input network stands in (no key is applied to the board before the placer has run).
KEYS = {'CH2': dict(parts=('R201', 'R202', 'R203', 'R204', 'R205', 'R206', 'R207', 'R208', 'C201', 'C202', 'C203'))}
KEY_TEXT_H = 1.0                  # mm, the board house's minimum silk text height
KEY_ADVANCE = DESIGNATOR_ADVANCE  # as the designators (stroke font advance per character, fraction of the height)
KEY_INK_H = DESIGNATOR_INK_H
KEY_COL_GAP = 0.7                 # mm between two designators of a row
KEY_ROW_PITCH = 1.6               # mm centre to centre of two rows (ink 1.2 high)
KEY_MARGIN = 0.5                  # mm inside the box all round
KEY_ROW_TOL = 0.5                 # mm: parts within this span in y are one row, in x one column: silkread's ORDER_MIN, past which two texts must be ordered, not tied
KEY_CLEAR = 0.15                  # mm: pads, vias, silk and courtyards are grown by this when free area is measured
KEY_ADJOIN_MAX = 2.0              # mm: the key box lies this close to its cluster's extent at most (spec lead's ruling: "adjoins" = 2 mm)
KEY_STROKE = 0.15
KEY_GAP = 1.0                     # mm between two keys of a legend
KEY_BLOCKS = {'CH1': '1', 'CH2': '2', 'AWG': '3', 'POWER': '4', 'REF / CAL': '5'}     # heading -> the hundreds digit of its designators (LR-11)

# LR-11 on the committed board adds the identity block (pcbtools/identity.py) and the no-arrow rule; the frozen fixtures and the old-tool
# comparisons read boards/v2.py, which carries the fields but not this switch, because their boards predate the identity.
IDENTITY_CHECK = True
SILK_WORDS = tuple(SILK_WORDS) + (NAME, ID_LINE, SN_LABEL)    # top silk words; the bottom marker is held by identity.findings (pcbkit.board reads F.SilkS texts only)

# The copper standard both AFE boards are judged by (pcbkit rules.track_geometry and rules.fill_quality; pcbkit/CONFIG.md says what each name does). Every value is set here, so the
# effective configuration printed by a check is this file's, not a default's.
TRACK_ANGLE_STEP = 45.0           # every segment along 0, 45, 90, 135 degrees
TRACK_ANGLE_TOL = 0.5
TRACK_MIN_LEG = 0.6               # no bend with a leg shorter than this, except a breakout from a fine-pitch pad
TRACK_FINE_PITCH = 0.65
TRACK_BREAKOUT_REACH = 0.8        # montreal5: the second short leg of a fan-out (a 0.5 mm WSON) is a breakout too
TRACK_MAX_TURN = 180.0            # a hook or U-turn changes the heading by 180 degrees or more within 3 mm, net
TRACK_KINK_OFFSET = 0.6           # a V kink or bump comes back to its heading within this offset
TRACK_TURN_WINDOW = 3.0
TRACK_DETOUR_RATIO = 1.5
TRACK_DETOUR_MIN_LEN = 1.0
TRACK_SPUR_MIN = 0.6              # a T spur is at least this long, joins at 90 or 45 degrees and is this far from a bend, another junction or a pad on its trunk
TRACK_SPUR_CLEAR = 0.6
TRACK_NET_WIDTHS = {'*': 0.25, 'GND': 0.25,                  # the width rule of each net: signals and ground 0.25 mm at most, supply and charge-pump nets 0.3
                    '+5V_F': 0.3, '+5V_DUE': 0.3, '+3V3A': 0.3, '+3V3A_K': 0.3, '+3V3A_U': 0.3, 'VNEG': 0.3, 'VNEG_G': 0.3, 'VNEG_O': 0.3,
                    'LM_CP': 0.3, 'LM_C1N': 0.3, 'LM_C1P': 0.3, 'P33_RN': 0.3}
TRACK_ENTRY_EDGE_TOL = 0.001      # a track enters a pad through an edge, not across a corner, to this tolerance
TRACK_OVERLAP_TOL = 0.001
FILL_LAYERS = ('F', 'B')
FILL_MIN_WIDTH = {'F': 1.0, 'B': 0.5}                  # the owner's fill standard: top 1.0 mm, bottom plane 0.5 mm
FILL_DEAD_END_WIDTH = 1.6
FILL_LENGTH_FACTOR = 2.0
FILL_RASTER = 40.0
FILL_MIN_AREA = 0.02
FILL_SHELL_PREFIXES = ('J',)                           # every connector's through-hole GND pins (BNC shells, Due headers) stay in the top pour
FILL_GNDPAD_MIN = 0.2
FILL_SHELL_EXCEPTIONS = [                              # (ref, pin, reason): a connector GND pin kept on the bottom plane
    ('J604', '7', 'Due header GND pin: through-hole on the solid bottom plane; the 2.54 mm header pitch leaves a 0.24 mm web of top copper between it and the signal pins beside it, under the 1.0 mm standard of the top pour'),
    ('J601', '6', 'Due header GND pin: through-hole on the solid bottom plane; the 2.54 mm header pitch leaves a 0.24 mm web of top copper between it and the signal pins beside it, under the 1.0 mm standard of the top pour'),
    ('J601', '7', 'Due header GND pin: through-hole on the solid bottom plane; the 2.54 mm header pitch leaves a 0.24 mm web of top copper between it and the signal pins beside it, under the 1.0 mm standard of the top pour'),
]
FILL_GNDPAD_EXCEPTIONS = []                             # (ref, pin, reason): an SMD GND pad neither in the pour nor given a via at its edge; none on AFE-2: every pad has its via at the edge
FILL_NOTCH_WIDTH = 1.05                                # no bare inlet in the top pour no wider than its 1.0 mm minimum width (and the raster tolerance)
FILL_ROUGH_LAYERS = ('F',)                             # no row of clearance arcs along the top pour's edge
FILL_ROUGH_TOL = 0.15
FILL_ROUGH_LINK = 2.0
FILL_THERMAL_LAYERS = ('F',)                           # thermal reliefs on the top pour's SMD GND pads
FILL_SOLID_LAYERS = ('B',)                             # the bottom plane is solid
GEOMETRY_EXCEPTIONS = [            # (rule, net, pad_or_ref, reason), see v1_layout
    ('angle', '/AWG_FB', (83.19, 11.20), 'LR-4 INV_MAX 5.0 mm: AWG_FB is 4.9 mm of track from U301.2 to U301.6 and a perpendicular entry at both pins makes it 5.3 mm'),
    ('entry', '/AWG_FB', 'U301.2', 'same: U301.2 enters at 76 degrees; perpendicular entries would take AWG_FB past INV_MAX (5.3 against 5.0 mm)'),
    ('over_pad', '/AWG_FB', 'R303.2', 'the cleanup may not lengthen an INV_MAX net: ending the track on R303.2 and restarting it adds 0.03 mm to AWG_FB (4.947 mm), so the track keeps running over the pad'),
    ('entry', '/AWG_FB', 'U301.6', 'same: U301.6 enters at 76 degrees; perpendicular entries would take AWG_FB past INV_MAX (5.3 against 5.0 mm)'),
    ('detour', '/VNEG_G', (33.23, 6.63), 'R403.1 to BR401.1: R403.1 takes its track along x and BR401.1 along y, 3.325 mm apart in x and 0.6 mm in y; no octilinear path of three legs of 0.62 mm or more joins them without a hook (the candidate search returns none), and the route in the file is the least-bent one the grid search found (measured)'),
    ('detour', '/VREF', (49.0, 13.2), 'the VREF branch from the node at (50.8, 8.25) to U501.2: the direct paths (via (52.6, 10.05) or (52.6, 9.43)) run over the +3V3A_R tracks (52.6, 10.7)-(52.6, 11.3) and (51.32, 10.7)-(52.6, 10.7), gap -0.2 mm against 0.5 mm required beside VREF (measured); the 9.8 mm route goes round them'),
    ('detour', '/VREF', (64.77, 14.22), 'the VREF run from R305.1 at the AWG block to U501.2, 39 mm against a 23.5 mm shortest path: the direct paths (via (74.1, 6.65) or (59.15, 6.0)) cross the A0 vertical x = 68.58, the A1 vertical x = 66.05, the TAP4 and SNS_B verticals x = 55.88 and 58.42 and the TAP2/TAP3/TAP4 rows, gap -0.2 mm against 0.5 mm (measured); they may not be crossed'),
    ('entry', '/LM_FB3M', 'R403.2', 'R403 / R404 pad pair offset 1.65 mm in x and 1.7 mm in y: one 45 degree leg pad to pad (montreal5), not a stair of two 90 degree bends; an axial leg first (0.8 mm, then 45 degrees) cuts the corner of R404.2 by 0.07 mm of copper (measured)'),
    ('entry', '/LM_FB3M', 'R404.1', 'same: the other end of the 45 degree LM_FB3M leg between R403.2 and R404.1'),
    ('entry', '/LM_FBN', 'R404.2', 'R404 / R405 pad pair offset 1.65 mm in x and 1.7 mm in y: one 45 degree leg pad to pad, not a stair; an axial leg first cuts the corner of R405.2 (measured, as for R403.2 / R404.1)'),
    ('entry', '/LM_FBN', 'R405.1', 'same: the other end of the 45 degree LM_FBN leg between R404.2 and R405.1'),
    ('tspur', '/+5V_F', (32.9, 13.25), 'U401.8 breakout: a 0.20 mm stub off the 0.5 mm pitch pad into the 45 degree leg of the +5V_F feed; two segments end at this point in the board file, the check counts three tracks'),
    ('tspur', '/+3V3A', (32.9, 14.75), 'U401.11 breakout: a 0.20 mm stub off the 0.5 mm pitch pad into the 45 degree leg; two segments end at this point in the board file, the check counts three tracks'),
]
