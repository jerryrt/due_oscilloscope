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
TRACK_ENTRY_EDGE_TOL = 0.001      # a track enters a pad through an edge, not across a corner, to this tolerance
TRACK_OVERLAP_TOL = 0.001
FILL_LAYERS = ('F', 'B')
FILL_MIN_WIDTH = {'F': 1.0, 'B': 0.5}                  # the owner's fill standard: top 1.0 mm, bottom plane 0.5 mm
FILL_DEAD_END_WIDTH = 1.6
FILL_LENGTH_FACTOR = 2.0
FILL_RASTER = 40.0
FILL_MIN_AREA = 0.02
FILL_THERMAL_LAYERS = ('F',)                           # thermal reliefs on the top pour's SMD GND pads
FILL_SOLID_LAYERS = ('B',)                             # the bottom plane is solid
GEOMETRY_EXCEPTIONS = [            # (rule, net, pad_or_ref, reason): each waives exactly one finding; one that matches none fails the check
    ('over_pad', 'AWG_INV', 'R302.1', 'LR-4: the AWG_INV node is limited to 5.0 mm of track; routing round R302.1 makes it 5.7 mm (montreal5, for the owner)'),
    ('over_pad', 'AWG_INV', 'R303.2', 'LR-4: the AWG_INV node is limited to 5.0 mm of track; routing round R303.2 makes it 5.7 mm (montreal5, for the owner)'),
    ('over_pad', 'A0', 'D201.3', 'A0 is a length-limited sensitive net: it connects the clamp D201 and test point TP201 of its own net in a daisy chain, which avoids a stub (montreal5)'),
    ('over_pad', 'A0', 'TP201.1', 'the same, A0 through TP201 (montreal5)'),
    ('over_pad', 'A1', 'D101.3', 'the same, A1 through D101 (montreal5)'),
    ('over_pad', 'A1', 'TP101.1', 'the same, A1 through TP101 (montreal5)'),
]


def __getattr__(name):          # names that start with an underscore or are not star-exported (sch_cfg, pcb_cfg, ...)
    return getattr(_v1, name)
