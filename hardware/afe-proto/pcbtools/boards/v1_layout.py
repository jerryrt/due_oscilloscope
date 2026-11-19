"""BoardConfig of the v1 LAYOUT OF RECORD (kicad/afe-proto.kicad_pcb): boards/v1 with the block outlines the layout actually has, as v2_layout is to v2.
`--config v1_layout`. boards/v1 stays as it is, because its rules tests and arms run on the frozen v1-34b2e51 board whose parts the approved rectangles do not hold;
every other field comes from it unchanged.

OUTLINE: the block rectangles AS APPROVED AND DRAWN on the v1 board's silk (afe1-labels, the owner's approval; read off the board's F.SilkS lines and equal to kvm_01's V1_RECTS):
one rectangle per block, CH1 and CH2 being two rectangles of the one SCOPE block, and the three BNC boxes (J101 and J201 in SCOPE, J301 in AWG).
OUTLINE_STRAYS: the nine parts the approved layout puts outside their own block's rectangle (accepted by montreal5): the corridor bridges R411-R413, the wall bridges R515, R516, R111, R309, R310
and the diode D201.
"""
from .v1 import *  # noqa: F401,F403
from . import v1 as _v1

OUTLINE = {'POWER': [(18.1, 4.05, 44.3, 22.9)],
           'REFCAL': [(44.7, 4.8, 64.55, 31.3)],
           'SCOPE': [(64.3, 33.9, 92.0, 46.4), (75.5, 22.4, 92.0, 32.0), (98.51, 17.78, 116.09, 35.56), (98.51, 35.56, 116.09, 53.34)],
           'AWG': [(69.8, 4.15, 92.0, 19.4), (98.51, -1.49, 116.09, 16.29)]}
OUTLINE_STRAYS = ('R411', 'R412', 'R413', 'R515', 'R516', 'D201', 'R111', 'R309', 'R310')


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
TOP_POUR_RECTS = [(154.0, 97.5, 166.5, 148.5), (68.0, 112.0, 87.5, 129.0)]   # KiCad mm (x0, y0, x1, y1): the top GND pour is these plain rectangles and nothing else (BNC column; logo area); one zone each, no carved keep-outs
FILL_LAYERS = ('F', 'B')
FILL_MIN_WIDTH = {'F': 1.0, 'B': 0.5}                  # the owner's fill standard: top 1.0 mm, bottom plane 0.5 mm
FILL_DEAD_END_WIDTH = 1.6
FILL_LENGTH_FACTOR = 2.0
FILL_RASTER = 40.0
FILL_MIN_AREA = 0.02
FILL_SHELL_PREFIXES = ('J',)                           # every connector's through-hole GND pins (BNC shells, Due headers) stay in the top pour
FILL_GNDPAD_MIN = 0.2
FILL_SHELL_EXCEPTIONS = [('J606', '7', "the Due header row: a 2.54 mm pitch leaves a 0.24 mm web between two pins, under the 1.0 mm minimum width of the top pour. On 1dae3dc9 the pin was in the 0.2 mm pour and the owner's 1.0 standard removed it; the pin is on the bottom plane through its hole"), ('J601', '6', "the Due header row: a 2.54 mm pitch leaves a 0.24 mm web between two pins, under the 1.0 mm minimum width of the top pour. On 1dae3dc9 the pin was in the 0.2 mm pour and the owner's 1.0 standard removed it; the pin is on the bottom plane through its hole"), ('J601', '7', "the Due header row: a 2.54 mm pitch leaves a 0.24 mm web between two pins, under the 1.0 mm minimum width of the top pour. On 1dae3dc9 the pin was in the 0.2 mm pour and the owner's 1.0 standard removed it; the pin is on the bottom plane through its hole"), ('J607', '35', "the Due header row: a 2.54 mm pitch leaves a 0.24 mm web between two pins, under the 1.0 mm minimum width of the top pour. On 1dae3dc9 the pin was in the 0.2 mm pour and the owner's 1.0 standard removed it; the pin is on the bottom plane through its hole"),
    ('J607', '36', "the Due header row, outside the top pour's rectangles (TOP_POUR_RECTS): the pin is on the bottom plane through its hole"),
    ('J101', '2', "the BNC shell leg beside the signal pin (x = 102 mm, the signal pin 2.5 mm from it on the same line): no plain rectangle reaches it without carrying the signal pin's clearance inside it, so it is outside the top pour and on the bottom plane through its hole; the two legs on the far side of the BNC are in the rectangle"),
    ('J201', '2', "the BNC shell leg beside the signal pin: as J101 pin 2"),
    ('J301', '2', "the BNC shell leg beside the signal pin: as J101 pin 2")]
FILL_GNDPAD_EXCEPTIONS = [
    ('U502', '3', 'VSSOP pin 3: a via whose annulus touches the pad edge needs 0.16 mm to the corners of the pads either side (U502.2, U502.4), not the 0.2 mm; the 0.225 mm track to the via at (59.8, 16.6) is the copper that fits (measured by hand, 2x crop sent to montreal5)'),
]

FILL_RECT_LAYERS = ('F',)                              # the top GND pour is TOP_POUR_RECTS: plain rectangles, each >= 3 mm a side and >= 100 mm2, >= 1 mm apart, clear of other copper, a GND via or pad in each
FILL_NOTCH_WIDTH = 1.05                                # no bare inlet in the top pour no wider than its 1.0 mm minimum width (and the raster tolerance)
FILL_ROUGH_LAYERS = ('F',)                             # no row of clearance arcs along the top pour's edge
FILL_ROUGH_TOL = 0.15
FILL_ROUGH_LINK = 2.0
FILL_THERMAL_LAYERS = ('F',)                           # thermal reliefs on the top pour's SMD GND pads
FILL_SOLID_LAYERS = ('B',)                             # the bottom plane is solid
GEOMETRY_EXCEPTIONS = [            # (rule, net, pad_or_ref, reason): each waives exactly one finding; one that matches none fails the check
    ('over_pad', 'AWG_INV', 'R302.1', 'LR-4: the AWG_INV node is limited to 5.0 mm of track; routing round R302.1 makes it 5.7 mm (montreal5, for the owner)'),
    ('over_pad', 'AWG_INV', 'R303.2', 'LR-4: the AWG_INV node is limited to 5.0 mm of track; routing round R303.2 makes it 5.7 mm (montreal5, for the owner)'),
    ('over_pad', 'A0', 'D201.3', 'A0 is a length-limited sensitive net: it connects the clamp D201 and test point TP201 of its own net in a daisy chain, which avoids a stub (montreal5)'),
    ('over_pad', 'A0', 'TP201.1', 'the same, A0 through TP201 (montreal5)'),
    ('over_pad', 'A1', 'D101.3', 'the same, A1 through D101 (montreal5)'),
    ('over_pad', 'A1', 'TP101.1', 'the same, A1 through TP101 (montreal5)'),
    ('detour', 'VREF', (52.07, 1.39), 'the VREF branch from U501.2 to R515 runs south under the TAP1-5 row (y 3.25-7.85 verticals and the TAP pads) and back up: 37.7 mm against a 22.2 mm octilinear shortest path (1.7x); the shorter path crosses the five TAP tracks, which it may not (montreal5: a named exception, not a shorter wrong route)'),
    ('jog', 'VREF', (57.4, 14.375), 'VREF into U502.4: between the R520/R514 pads (track y 14.32-14.58) and the channel under U502 above R502.2 (y 14.18-14.32) the step is 0.39 mm, a 45 degree leg of 0.55 mm; no leg of 0.6 fits without moving a part'),
]


def __getattr__(name):          # names that start with an underscore or are not star-exported (sch_cfg, pcb_cfg, ...)
    return getattr(_v1, name)
