"""BoardConfig of the v2 LAYOUT OF RECORD (v2/layout/integrated/afe-v2-integrated.kicad_pcb): boards/v2 with the block outlines
the layout actually has. `--config v2_layout`. boards/v2 itself stays frozen (it reads the PASS-2 fixture table, whose SCOPE
rectangles the east re-placement made stale); every other field is imported from it unchanged.

The outlines come from v2/layout/outlines.py, the one table the silkscreen is drawn from too, and
v2/layout/outlines_from_silk.py recovers them from the board so a test can hold the two equal.
"""
import importlib.util
import os

from .v2 import *  # noqa: F401,F403  every public name of the frozen config

# The renumbering of 2026-11-15 (LR-11, the runs): old designator -> the one the board and the design have now. boards/v2.py is frozen on the old
# fixture and keeps the old names; every inherited field is carried to the new ones here, so a table written once (a channel's parts, the VREF
# branches, the groups) still names the same parts. Everything this file defines after the loop is written with the new names.
RENUMBER = {
    'BR101': 'BR102', 'BR102': 'BR101', 'BR507': 'BR508', 'BR508': 'BR507', 'BR510': 'BR511', 'BR511': 'BR510', 'C101': 'C102',
    'C102': 'C101', 'C201': 'C202', 'C202': 'C201', 'R101': 'R103', 'R103': 'R106', 'R104': 'R107', 'R106': 'R104', 'R107':
    'R101', 'R201': 'R203', 'R203': 'R206', 'R204': 'R207', 'R206': 'R204', 'R207': 'R201'}
RENUMBER_INVERSE = {v: k for k, v in RENUMBER.items()}


def _renamed(v):
    if isinstance(v, str):
        return RENUMBER.get(v, v)
    if isinstance(v, dict):
        return {_renamed(k): _renamed(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set, frozenset)):
        return type(v)(_renamed(x) for x in v)
    return v


for _k in [_k for _k in list(globals()) if _k.isupper()]:
    globals()[_k] = _renamed(globals()[_k])

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
DESIGNATOR_AT = {'J605': (96.2, 53.4)}
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
DESIGNATOR_GAP_MIN = 1.0         # two designators are at least this far apart, edge to edge: one character height (1.0 mm text, the project's
                                 # DRC minimum text height)
DESIGNATOR_GAP_ONE_LABEL = 0.6   # the gap the Due's pin-name labels keep from each other and from a designator (pcbtools/pinlabels.py)
# The legacy LR-11 label rules (pair gap, one label, foreign outline, distance to the part) and their waiver tables are retired: silkread (D30, docs/afe.md)
# judges where a label may sit, and SILK_TO_BOM below lists the parts left to the BOM.

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
SCH_NS = '6f1f0d3e-4a52-4c1b-9a4e-0ad5e0a1f001'     # the uuid namespace of the schematic and the footprints' paths (boards/v2_sch.py NS)
LABEL_IN_BLOCK = True        # a designator's centre lies in its own block's outline (LR-11); the placer looks only there
RUN_GRID_ROWS = False        # POWER's capacitor grid stays as it is until POWER is re-placed into rows and renumbered once
BNC_LABELS = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}      # the first one's label offset is every one's (D30 (2))
BNC_DESIGNATOR_OFFSET = (3.2, 0.0)    # board mm from each BNC's origin, all three: the designator on the bottom silk beside the pin, mirrored, clear of the pin ring and the two mounting holes
BNC_LABEL_OFFSET = (-2.75, 1.0)     # board mm from each BNC origin, all three (D30 (2)): the label centred, vertical, in the 1.4 mm strip between the BNC courtyard and J605, so it is not under the body
SAME_ORIENTATION = True      # a designator beside its part is turned as the part is: 0 for a horizontal part, 90 for a vertical one (LR-11, silkplace)
IDENTITY_CHECK = True
SILK_WORDS = tuple(SILK_WORDS) + (NAME, ID_LINE, SN_LABEL)    # top silk words; the bottom marker is held by identity.findings (boardio reads F.SilkS texts only)


# D30, option C (owner, 2026-11-15): REF / CAL, POWER and AWG keep their copper. A leftover passive keeps a label only inside its own block and nearer its own
# courtyard than any other; every other leftover is left off the silk and found through the BOM (SILK_TO_BOM, in silk_to_bom.py's table below).
import re as _re

SILK_BLOCKS = {{'CH1': '1', 'CH2': '2', 'AWG': '3', 'POWER': '4', 'REFCAL': '5'}[k]: [tuple(r) for r in v] for k, v in OUTLINE.items()}       # {hundreds digit as a string: [rects, Due mm]}
SILK_NEAR_OK = {r for r in BLOCK if _re.fullmatch(r'(?:R|C|BR)[345]\d\d', r)} | {'U301', 'U401', 'U501', 'U502', 'J501', 'TP201', 'TP501', 'TP401', 'TP402', 'TP403', 'TP404', 'R108', 'R208'}          # the dense blocks' passives: nearer its own courtyard than any other
# Named exceptions (spec lead, 2026-11-15): two CH1 run labels lie just outside CH1's outline but read; both stay visible, with no renumbering.
SILK_EXEMPT = {
    'U502': 'against its own body; reads as U502 by eye (2026-11-15 review); 0.12 mm nearer R514\'s courtyard, no nearer free place',
    'C104': 'run label of C104/C105, one character height outside CH1\'s outline below it; the dual\'s capacitors sit on the block edge; readable, kept',
    'BR101': 'run label of BR101/BR102, just outside the outline\'s west ear; readable, kept',
}
# Option C covers the leftover passives only (owner): every IC, connector, jumper header and test point, and the channels' R108 and R208, keeps a visible
# label, beside the part inside its block (the nearest-only rule of SILK_NEAR_OK); one with no such place is named, never dropped.
# Labels placed by hand where the placer's search could not (Due mm, centre and angle): each is against its own part and checked by the board test and the 3D render.
SILK_AT = {
    'U502': (50.98, 17.75, 0), 'U301': (86.73, 10.75, 90), 'R108': (80.66, 39.1, 90),
    'TP401': (22.85, 20.0, 90), 'TP403': (26.995, 18.95, 90), 'TP404': (30.8, 25.25, 0), 'TP402': (38.8, 13.45, 90),
}
SILK_MUST_LABEL = {'U301', 'U401', 'U501', 'U502', 'J501', 'TP201', 'TP501', 'TP404', 'R108'}
SILK_TO_BOM = {
    'R208': 'no free place beside it; the only candidate reads as C104\'s label',
    'BR401': 'passive with no place for a label inside its block nearer it than any other; its label would lie on its own body',
    'BR501': 'passive with no place for a label inside its block nearer it than any other; no clear place for it: it would lie on the courtyard of TP201',
    'BR506': 'passive with no place for a label inside its block nearer it than any other; no clear place for it: it would lie on the courtyard of J501, U502',
    'BR507': 'passive with no place for a label inside its block nearer it than any other; no clear place for it: it would lie on the courtyard of J501',
    'BR508': 'passive with no place for a label inside its block nearer it than any other; no place inside its block nearer it than J601 (dense block)',
    'BR510': 'passive with no place for a label inside its block nearer it than any other; its label would lie on its own body',
    'BR511': 'passive with no place for a label inside its block nearer it than any other; no clear place for it: it would lie on the courtyard of BR509',
    'C301': 'passive with no place for a label inside its block nearer it than any other; no place inside its block nearer it than R204 (dense block)',
    'C303': 'passive with no place for a label inside its block nearer it than any other; no place inside its block nearer it than J603 (dense block)',
    'C304': 'passive with no place for a label inside its block nearer it than any other; no clear place for it: it would lie on the courtyard of R308',
    'C305': 'passive with no place for a label inside its block nearer it than any other; no place inside its block where it reads along the part',
    'C306': 'passive with no place for a label inside its block nearer it than any other; no clear place for it: it would lie on the courtyard of R301',
    'C402': 'passive with no place for a label inside its block nearer it than any other; no place inside its block nearer it than R402 (dense block)',
    'C403': 'passive with no place for a label inside its block nearer it than any other; no place inside its block nearer it than R402 (dense block)',
    'C409': 'passive with no place for a label inside its block nearer it than any other; no place inside its block nearer it than C406 (dense block)',
    'C501': 'passive with no place for a label inside its block nearer it than any other; no place inside its block where it reads along the part',
    'C502': 'passive with no place for a label inside its block nearer it than any other; no clear place for it: it would lie on the courtyard of R506',
    'C503': 'passive with no place for a label inside its block nearer it than any other; no place inside its block nearer it than R511 (dense block)',
    'R302': 'passive with no place for a label inside its block nearer it than any other; its label would lie on its own body',
    'R303': 'passive with no place for a label inside its block nearer it than any other; no place inside its block nearer it than R206 (dense block)',
    'R306': 'passive with no place for a label inside its block nearer it than any other; no place inside its block nearer it than R304 (dense block)',
    'R307': 'passive with no place for a label inside its block nearer it than any other; no clear place for it: it would lie on the courtyard of U301',
    'R404': 'passive with no place for a label inside its block nearer it than any other; no clear place for it: it would lie on the courtyard of R403',
    'R405': 'passive with no place for a label inside its block nearer it than any other; no clear place for it: it would lie on the courtyard of C407, R403, R404',
    'R502': 'passive with no place for a label inside its block nearer it than any other; no place inside its block nearer it than R501 (dense block)',
    'R503': 'passive with no place for a label inside its block nearer it than any other; its label would lie on its own body',
    'R504': 'passive with no place for a label inside its block nearer it than any other; no clear place for it: it would lie on the courtyard of J501, R505',
    'R505': 'passive with no place for a label inside its block nearer it than any other; its label would lie on its own body',
    'R508': 'passive with no place for a label inside its block nearer it than any other; no clear place for it: it would lie on the courtyard of R507, R510',
    'R509': 'passive with no place for a label inside its block nearer it than any other; no clear place for it: it would lie on the courtyard of R507',
    'R510': 'passive with no place for a label inside its block nearer it than any other; its label would lie on its own body',
    'R511': 'passive with no place for a label inside its block nearer it than any other; no place inside its block where it reads along the part',
    'BR503': 'passive with no place for a label inside its block nearer it than any other (the best place the placer finds fails the checker)',
    'C407': 'passive with no place for a label inside its block nearer it than any other (the best place the placer finds fails the checker)',
    'R301': 'passive with no place for a label inside its block nearer it than any other (the best place the placer finds fails the checker)',
    'R304': 'passive with no place for a label inside its block nearer it than any other (the best place the placer finds fails the checker)',
    'R305': 'passive with no place for a label inside its block nearer it than any other (the best place the placer finds fails the checker)',
    'R402': 'passive with no place for a label inside its block nearer it than any other (the best place the placer finds fails the checker)',
    'R403': 'passive with no place for a label inside its block nearer it than any other (the best place the placer finds fails the checker)',
    'R506': 'passive with no place for a label inside its block nearer it than any other (the best place the placer finds fails the checker)',
    'R507': 'passive with no place for a label inside its block nearer it than any other (the best place the placer finds fails the checker)',
    'R512': 'passive with no place for a label inside its block nearer it than any other (the best place the placer finds fails the checker)',
    'R514': 'passive with no place for a label inside its block nearer it than any other (the best place the placer finds fails the checker)',
    'BR502': 'its label would lie outside its own block (the block outline), and no place inside it is nearer this part than any other',
    'BR504': 'its label would lie outside its own block (the block outline), and no place inside it is nearer this part than any other',
    'BR509': 'its label would lie outside its own block (the block outline), and no place inside it is nearer this part than any other',
    'R501': 'its label would lie outside its own block (the block outline), and no place inside it is nearer this part than any other',
}
