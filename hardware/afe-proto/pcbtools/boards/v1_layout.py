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


def __getattr__(name):          # names that start with an underscore or are not star-exported (sch_cfg, pcb_cfg, ...)
    return getattr(_v1, name)
