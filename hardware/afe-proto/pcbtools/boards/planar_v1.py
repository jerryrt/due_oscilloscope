"""Inputs for `planar.check` on v1's REFCAL block: the acceptance case kvm_01's block agent derived by hand (a planar
obstruction in the frozen design, cured by the 0603 R520 that splits SNS_B). Data copied from its note
(whatif/blocks/REFCAL_obstruction.md, 2026-11-12) and from the frozen contract rows (tests/fixtures/v1-34b2e51/kicad/
floorplan_table.md); nothing here reads another worktree.

    inputs(b, r520=False, leg_order='ACBD', walls=...) -> kwargs of planar.check

b is the BoardArrays of the frozen v1 board (tests/pcbtools/planar_v1_34b2e51.npz). Pin ORDER around a body does not depend on
the placement (rotating a part keeps its cyclic order), so the frozen board's pads give the same rotation system as 'Option P';
only the mirror image could differ and the test is blind to it.
"""
from .. import planar

FENCE = (44.5, 4.6, 64.5, 36.0)
# (label, net, (x, y)): the contract rows. +3V3A is two nets because its two entries are one trunk OUTSIDE the fence (a tee):
# '/+3V3A' is the west entry (U501.1 and its caps), '/+3V3A#N' the north entry (R517.1). VREF's branches: A south (J602.1),
# C the strip lane at the south-east corner, D east.
EDGE_POINTS = [('VREF_A', '/VREF', (50.8, 4.6)), ('TAP5', '/TAP5', (53.34, 4.6)), ('TAP4', '/TAP4', (55.88, 4.6)),
               ('TAP3', '/TAP3', (58.42, 4.6)), ('TAP2', '/TAP2', (60.96, 4.6)), ('TAP1', '/TAP1', (63.5, 4.6)),
               ('VREF_C', '/VREF', (64.5, 4.7)), ('AWG_S', '/AWG_S', (64.5, 19.5)), ('VREF_D', '/VREF', (64.5, 22.8)),
               ('P33_N', '/+3V3A#N', (56.0, 36.0)), ('AREF', '/AREF', (48.4, 36.0)), ('SDA', '/SDA1', (47.4, 36.0)),
               ('SCL', '/SCL1', (46.4, 36.0)), ('P33_W', '/+3V3A', (44.5, 12.6))]
OUTSIDE = ('R515', 'R516')                   # the wall bridges: outside the fence, their net leaves at VREF_D
# VREF is a Kelvin star at U501.2 (LR-8): branch A = J602.1 and the ladder top R508.2; B = U502.4 and C503; C = the AWG lane;
# D = the sense tie R512.2, the AREF part R510.1 and the east exit
BRANCHES = {'A': [('@edge', 'VREF_A'), ('R508', '2')], 'B': [('U502', '4'), ('C503', '1')], 'C': [('@edge', 'VREF_C')],
            'D': [('@edge', 'VREF_D'), ('R512', '2'), ('R510', '1')]}
WALL_ICS = {'U501': 'wall', 'U502': 'wall'}                    # the two ICs: pins cannot be passed between
WALL_MORE = {**WALL_ICS, **{r: 'wall' for r in ('J501', 'D501', 'D502', 'R512', 'R514', 'R502', 'R513', 'R501')}}


def inputs(b, r520=False, leg_order='ACBD', walls=WALL_ICS):
    from . import v1
    d = planar.from_board(b, v1, 'REFCAL', edge_points=[(n, p) for _, n, p in EDGE_POINTS], exclude_refs=OUTSIDE)
    nets = d['block_nets']
    nets['/+3V3A#N'] = [('R517', '1')]
    nets['/+3V3A'] = [t for t in nets['/+3V3A'] if t != ('R517', '1')]
    pts = [p for _, _, p in EDGE_POINTS]
    d['boundary'] = [(EDGE_POINTS[i][0], EDGE_POINTS[i][1]) for i in planar.boundary_order(pts, [FENCE])]
    d['roots'] = {'/VREF': ('U501', '2')}
    d['branches'] = {'/VREF': [BRANCHES[k] for k in leg_order]}
    d['ordered_branches'] = ('/VREF',)
    d['body_overrides'] = dict(walls)
    d['body'] = 'auto'
    if r520:                                   # R520: pin 1 = SNS_B (J501.2, R502.2, R514.1), pin 2 = SNS_B_N (R512.1)
        nets['/SNS_B_N'] = [('R512', '1'), ('R520', '2')]
        nets['/SNS_B'] = [t for t in nets['/SNS_B'] if t != ('R512', '1')] + [('R520', '1')]
        d['passable'] = tuple(d['passable']) + ('R520',)
    return d
