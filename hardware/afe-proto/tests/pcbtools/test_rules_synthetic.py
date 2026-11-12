"""Every rule on hand-built boards whose answer is known: a minimal board that passes, one change that fails, and the
figure checked exactly (boundaries are tested on both sides). No pcbnew, no fixtures."""
import numpy as np
import pytest

from pcbtools import rules as R
from synth import Synth, cfg

SQ = lambda x0, y0, x1, y1: [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# ----------------------------------------------------------------------------- LR-1
def lr1_board(hop=2.0, hop_vias=((30, 30), (32, 30)), gnd_via=(11, 10), a0=None, layers=2, pour_rings=1, hop_net='/SCL'):
    s = Synth('/GND', '/SCL', '/A0', layers=layers)
    s.part('C1', 10, 10).p('C1', '1', 10, 10, '/GND')
    if gnd_via:
        s.v('/GND', *gnd_via)
    rings = [(SQ(0, 0, 50, 50), False)] + ([(SQ(60, 0, 70, 10), False)] if pour_rings == 2 else [])
    s.z('/GND', 'B', rings)
    s.s(hop_net, 'B', 30, 30, 30 + hop, 30)
    for v in hop_vias:
        s.v(hop_net, *v)
    if a0:
        s.s('/A0', 'F', *a0)
    return s.build()


C1 = cfg(ANALOG_REFS=frozenset(), ANALOG_FENCE=(), OUTLINE={}, XSENS=('/A0',))


def test_lr1_passes_with_exact_figures():
    r = R.lr1(lr1_board(), C1)
    assert r.ok, r.detail
    assert r.detail == '2 layers, one bottom plane, 1 bottom runs, 1 GND pads each with its own via'
    assert r.figures['max_run_mm'] == 2.0 and r.figures['max_run_vias'] == 2 and r.figures['gnd_pads'] == 1
    assert r.figures['bottom_pieces'] == 1


@pytest.mark.parametrize('hop, ok', [(3.0, True), (3.0001, False), (4.0, False)])
def test_lr1_hop_length_boundary(hop, ok):
    r = R.lr1(lr1_board(hop=hop, hop_vias=((30, 30), (30 + hop, 30))), C1)
    assert r.ok == ok
    if not ok:
        assert f'/SCL: bottom run {hop:.1f} mm, 2 vias (limit 3.0 mm, 2)' in r.detail


def test_lr1_three_vias_on_a_hop_fail():
    r = R.lr1(lr1_board(hop_vias=((30, 30), (32, 30), (30.02, 30.01))), C1)
    assert not r.ok and '3 vias' in r.detail and r.figures['max_run_vias'] == 3


def test_lr1_via_of_another_net_is_not_counted():
    b = lr1_board(hop_vias=((30, 30), (32, 30)))
    assert R.bottom_runs(b, C1)[0][0][2] == 2
    b = Synth('/GND', '/SCL').s('/SCL', 'B', 30, 30, 32, 30).v('/SCL', 30, 30).v('/SCL', 32, 30).v('/GND', 30.01, 30).build()
    assert R.bottom_runs(b, C1)[0][0][2] == 2                                  # the ground via at the end is another net's


def test_lr1_runs_join_by_endpoint_and_net():
    one = Synth('/GND', '/SCL').s('/SCL', 'B', 30, 30, 31, 30).s('/SCL', 'B', 31.005, 30, 32, 30).build()
    assert [(r[0], r[1]) for r in R.bottom_runs(one, C1)[0]] == [('/SCL', pytest.approx(1.995))]        # ends 0.005 apart: one run
    far = Synth('/GND', '/SCL').s('/SCL', 'B', 30, 30, 31, 30).s('/SCL', 'B', 31.02, 30, 32, 30).build()
    assert len(R.bottom_runs(far, C1)[0]) == 2                                  # 0.02 apart: two runs
    two = Synth('/GND', '/SCL', '/B2').s('/SCL', 'B', 30, 30, 31, 30).s('/B2', 'B', 31, 30, 32, 30).build()
    assert len(R.bottom_runs(two, C1)[0]) == 2                                  # touching but different nets


def test_lr1_layers_and_plane():
    assert 'layers' in R.lr1(lr1_board(layers=4), C1).detail and not R.lr1(lr1_board(layers=4), C1).ok
    r = R.lr1(lr1_board(pour_rings=2), C1)
    assert not r.ok and 'bottom plane is 2 pieces, not 1' in r.detail
    s = Synth('/GND').part('C1', 10, 10)
    assert 'no bottom GND zone' in R.lr1(s.build(), C1).detail


@pytest.mark.parametrize('via, ok', [((13.0, 10.0), True), ((13.01, 10.0), False), (None, False)])
def test_lr1_gnd_pad_via_within_3_mm(via, ok):
    r = R.lr1(lr1_board(gnd_via=via), C1)
    assert r.ok == ok
    if not ok:
        assert "1 SMD ground pads without a via of their own: ['C1.1']" in r.detail


def test_lr1_a_via_serves_one_pad_only():
    s = Synth('/GND').part('C1', 10, 10).p('C1', '1', 10, 10, '/GND').p('C1', '2', 11, 10, '/GND').v('/GND', 10.5, 10)
    s.z('/GND', 'B', [(SQ(0, 0, 50, 50), False)])
    r = R.lr1(s.build(), C1)
    assert not r.ok and 'C1.2' in r.detail and r.figures['pads_without_via'] == 1


def test_lr1_hop_under_a_sensitive_top_net_and_pad():
    r = R.lr1(lr1_board(a0=(31, 25, 31, 35)), C1)
    assert not r.ok and '/SCL: bottom segment under /A0 (a hop under a sensitive net; bridge it on top)' in r.detail
    assert R.lr1(lr1_board(a0=(31, 31, 31, 40)), C1).ok                         # ends 1 mm above the hop: clear
    s = Synth('/GND', '/SCL', '/A0').part('C1', 10, 10).p('C1', '1', 10, 10, '/GND').v('/GND', 11, 10)
    s.part('R1', 31, 30.5).p('R1', '1', 31, 30.5, '/A0')
    s.z('/GND', 'B', [(SQ(0, 0, 50, 50), False)]).s('/SCL', 'B', 30, 30, 32, 30).v('/SCL', 30, 30).v('/SCL', 32, 30)
    r = R.lr1(s.build(), C1)
    assert not r.ok and 'bottom segment under pad R1.1 of /A0' in r.detail


def test_lr1_hop_inside_a_fence_or_under_an_analog_part():
    c = cfg(ANALOG_REFS=frozenset({'U9'}), ANALOG_FENCE=('CH1',), OUTLINE={'CH1': [(29, 29, 33, 31)]}, XSENS=('/A0',))
    r = R.lr1(lr1_board(), c)
    assert not r.ok and 'bottom segment inside an analog fence (29.0, 29.0, 33.0, 31.0)' in r.detail
    b = lr1_board()
    s = Synth('/GND', '/SCL').part('C1', 10, 10).p('C1', '1', 10, 10, '/GND').v('/GND', 11, 10).z('/GND', 'B', [(SQ(0, 0, 50, 50), False)])
    s.part('U9', 31, 33, box=(30, 31.5, 32, 34.5))           # courtyard 1.5 above the hop: outside ZONE_PAD 0.3 + 0.1
    s.s('/SCL', 'B', 30, 30, 32, 30).v('/SCL', 30, 30).v('/SCL', 32, 30)
    c2 = cfg(ANALOG_REFS=frozenset({'U9'}), ANALOG_FENCE=(), OUTLINE={}, XSENS=())
    assert R.lr1(s.build(), c2).ok
    s2 = Synth('/GND', '/SCL').part('C1', 10, 10).p('C1', '1', 10, 10, '/GND').v('/GND', 11, 10).z('/GND', 'B', [(SQ(0, 0, 50, 50), False)])
    s2.part('U9', 31, 31, box=(30, 30.3, 32, 33)).s('/SCL', 'B', 30, 30, 32, 30).v('/SCL', 30, 30).v('/SCL', 32, 30)
    r = R.lr1(s2.build(), c2)
    assert not r.ok and "bottom copper under ['U9']" in r.detail             # 0.3 above the track centre line: within 0.3 + 0.1


def test_lr1_unfilled_plane_and_near_miss_distances():
    b = lr1_board()
    nf = b.replace(z_filled=np.array([False]), z_ring_off=np.array([0, 0]), z_vert_off=np.array([0]), z_xy=np.zeros((0, 2)), z_ring_hole=np.zeros(0, np.int8))
    r = R.lr1(nf, C1)
    assert not r.ok and 'bottom zone not filled' in r.detail and 'bottom plane is 0 pieces, not 1' in r.detail
    # a top A0 track parallel to the hop: clear above (0.2 + 0.2) / 2 + 0.1 = 0.3 mm centre to centre
    assert not R.lr1(lr1_board(a0=(30, 30.25, 32, 30.25)), C1).ok
    assert R.lr1(lr1_board(a0=(30, 30.35, 32, 30.35)), C1).ok


# ----------------------------------------------------------------------------- LR-3
C3 = cfg(HIZ=('CH1_N',))


def lr3_board(other_y=None, length=(3, 4), via=False):
    s = Synth('/CH1_N', '/X', '/GND')
    s.s('/CH1_N', 'F', 0, 0, *length)
    if other_y is not None:
        s.s('/X', 'F', 0, other_y, 0.0001, other_y)
    if via:
        s.v('/CH1_N', 1, 1)
    return s.build()


def test_lr3():
    r = R.lr3(lr3_board(), C3)
    assert r.ok and r.figures['longest_mm'] == 5.0
    assert R.lr3(lr3_board(via=True), C3).detail == '/CH1_N: a via'
    assert R.lr3(lr3_board(length=(14, 0)), C3).ok and R.lr3(lr3_board(length=(14.5, 0)), C3).detail == '/CH1_N: 14.5 mm of track'
    # a parallel track of another net: allowed beyond 0.6 + (0.2 + 0.2) / 2 = 0.8 mm centre to centre
    assert R.lr3(lr3_board(other_y=-0.85, length=(10, 0)), C3).ok
    r = R.lr3(lr3_board(other_y=-0.75, length=(10, 0)), C3)
    assert not r.ok and r.detail == '/CH1_N track within 0.6 mm of /X track'
    s = Synth('/CH1_N', '/GND').s('/CH1_N', 'F', 0, 0, 10, 0).s('/GND', 'F', 0, -0.5, 10, -0.5)
    assert R.lr3(s.build(), C3).ok                                           # ground beside is allowed
    s = Synth('/CH1_N').s('/CH1_N', 'F', 0, 0, 5, 0).s('/CH1_N', 'F', 0, -0.3, 5, -0.3)
    assert R.lr3(s.build(), C3).ok                                           # the net's own copper beside itself is allowed
    s = Synth('/CH1_N', '/X').s('/CH1_N', 'F', 0, 0, 10, 0).s('/X', 'B', 0, -0.3, 10, -0.3)
    assert R.lr3(s.build(), C3).ok                                           # only top copper counts


# ----------------------------------------------------------------------------- LR-4 and INV_MAX
def lr4_board(fb=(3, 4), a0=(0, 0, 3, 4), a0_via=False, gnd_track=None, pour=None, fb_pad=(40, 40), r108=(1, 1), c104=(9, 10)):
    s = Synth('/A0', '/A1', '/AWG_FB', '/CH1_N', '/CH2_N', '/GND', '/VCC')
    s.part('R108', 0, 0).p('R108', '1', *r108, '/A1')
    s.part('U101', 0, 0).p('U101', '7', 1, 1).p('U101', '1', 1, 2).p('U101', '8', 9, 9)
    s.part('R208', 0, 0).p('R208', '1', 1, 2)
    s.part('U301', 0, 0).p('U301', '8', 20, 20).p('U301', '4', 21, 20)
    s.part('C104', 0, 0).p('C104', '1', *c104).part('C305', 0, 0).p('C305', '1', 20, 21).part('C306', 0, 0).p('C306', '1', 21, 21)
    s.part('R303', 0, 0).p('R303', '2', *fb_pad, '/AWG_FB')
    s.s('/AWG_FB', 'F', 40, 40, 40 + fb[0], 40 + fb[1])
    s.s('/A0', 'F', *a0)
    s.s('/A1', 'F', 0, 10, 0, 12)
    if a0_via:
        s.v('/A0', 0, 0)
    if gnd_track:
        s.s('/GND', 'F', *gnd_track)
    if pour is not None:
        s.z('/GND', 'F', pour)
    return s.build()


def test_lr4_passes_with_figures():
    r = R.lr4(lr4_board(), cfg())
    assert r.ok, r.detail
    assert r.figures['a0_mm'] == 5.0 and r.figures['fb_mm'] == 5.0 and r.figures['a1_mm'] == 2.0
    assert 'A0/A1 top only, no via (5/2 mm); FB node 5.0 mm of track' in r.detail


def test_lr4_via_bottom_and_fb_length():
    assert R.lr4(lr4_board(a0_via=True), cfg()).detail == '/A0: a via'
    assert R.lr4(lr4_board(fb=(14.0, 0)), cfg()).ok and not R.lr4(lr4_board(fb=(14.1, 0)), cfg()).ok
    b = lr4_board()
    from pcbtools import mutate as M
    assert R.lr4(M.add_segment(b, '/CH2_N', 'B', (0, 0), (1, 0)), cfg()).detail == '/CH2_N: inverting node has bottom copper'


def test_lr4_ground_copper_near_the_inverting_node():
    # the node starts at its pad (40,40): a top GND track 0.5 mm from that point, less its 0.1 half width, is 0.4 away -> fail
    r = R.lr4(lr4_board(gnd_track=(39.5, 39, 39.5, 41)), cfg())
    assert not r.ok and "(['GND track'])" in r.detail
    assert R.lr4(lr4_board(gnd_track=(35.0, 41, 35.0, 42)), cfg()).ok            # 5 mm away


@pytest.mark.parametrize('kw, ok', [(dict(r108=(6.0, 1)), True), (dict(r108=(6.1, 1)), False), (dict(c104=(9, 21.0)), True),
                                      (dict(c104=(9, 21.1)), False)])
def test_lr4_output_resistor_and_decoupling_distance_limits(kw, ok):
    r = R.lr4(lr4_board(**kw), cfg())
    assert r.ok == ok
    if not ok:
        assert ('R108 not at the output pin' if 'r108' in kw else 'C104 12 mm from its supply pin') in r.detail


@pytest.mark.parametrize('x, ok', [(39.3, True), (39.5, False)])
def test_lr4_ground_track_distance_threshold(x, ok):
    assert R.lr4(lr4_board(gnd_track=(x, 39, x, 41)), cfg()).ok == ok


@pytest.mark.parametrize('c', [(40.5, 40), (39.5, 40), (40, 40.5), (40, 39.5)], ids=['+x', '-x', '+y', '-y'])
def test_lr4_each_of_the_four_pour_probe_directions(c):
    # a pour 0.1 mm square centred on one probe point (0.5 mm from the pad) and nowhere else
    r = R.lr4(lr4_board(pour=[(SQ(c[0] - 0.05, c[1] - 0.05, c[0] + 0.05, c[1] + 0.05), False)]), cfg())
    assert not r.ok and "['top pour']" in r.detail
    d = 0.2
    assert R.lr4(lr4_board(pour=[(SQ(c[0] - 0.05 + d, c[1] - 0.05 + d, c[0] + 0.05 + d, c[1] + 0.05 + d), False)]), cfg()).ok


def test_lr4_pour_is_hole_aware():
    pour = SQ(30, 30, 60, 60)
    r = R.lr4(lr4_board(pour=[(pour, False)]), cfg())
    assert not r.ok and "(['top pour'])" in r.detail
    # the keep-back round the node is a hole in the pour: nothing within 0.5 mm of the node is copper
    keep = SQ(38, 38, 45, 46)
    assert R.lr4(lr4_board(pour=[(pour, False), (keep, True)]), cfg()).ok
    # a pour that starts beyond the last probe point (the node ends at (43, 44); the probe is 0.5 mm out) does not count
    assert R.lr4(lr4_board(pour=[(SQ(43.6, 30, 60, 60), False)]), cfg()).ok
    assert not R.lr4(lr4_board(pour=[(SQ(43.4, 30, 60, 60), False)]), cfg()).ok


def test_inv_max_boundary_all_layers():
    def board(fb, bottom=0.0):
        s = Synth('/AWG_FB', '/CH1_OUT', '/CH2_OUT').s('/AWG_FB', 'F', 0, 0, fb, 0).s('/CH1_OUT', 'F', 0, 0, 1, 0).s('/CH2_OUT', 'F', 0, 0, 2, 0)
        return s.build() if not bottom else s.s('/CH2_OUT', 'B', 0, 5, bottom, 5).build()
    r = R.lr4_inv(board(5.0), cfg())
    assert r.ok and r.figures == {'AWG_FB': 5.0, 'CH1_OUT': 1.0, 'CH2_OUT': 2.0}
    assert r.detail == 'AWG_FB 5.0 mm, CH1_OUT 1.0 mm, CH2_OUT 2.0 mm (<= 5.0)'
    assert R.lr4_inv(board(5.1), cfg()).detail.startswith('AWG_FB 5.1 mm of track exceeds INV_MAX 5.0 mm [')
    r = R.lr4_inv(board(1.0, bottom=3.5), cfg())                   # 2.0 top + 3.5 bottom: every layer counts
    assert not r.ok and r.figures['CH2_OUT'] == 5.5


# ----------------------------------------------------------------------------- LR-12
def lr12_board(d, cap_pins=('1',)):
    s = Synth('/VCC', '/GND').part('U1', 0, 0).p('U1', '8', 0, 0, '/VCC').part('C1', 0, 0)
    for k in ('1', '2'):
        on_supply = k in cap_pins
        s.p('C1', k, d if on_supply else 0.5, 0, '/VCC' if on_supply else '/GND')
    return s.build()


C12 = cfg(DECOUP={'C1': ('U1', '8')})


def test_lr12_boundary_and_supply_pad_choice():
    r = R.lr12(lr12_board(3.0), C12)
    assert r.ok and r.figures == {'C1>U1.8': 3.0} and r.detail == '1 caps within 3.0 mm: C1>U1.8 3.0'
    r = R.lr12(lr12_board(3.0001), C12)
    assert not r.ok and r.detail == 'C1 is 3.0 mm from U1 pin 8 (limit 3.0)'
    # the distance is from the pad on the supply net, even if the other pad is closer
    assert R.lr12(lr12_board(2.5, cap_pins=('1',)), C12).figures['C1>U1.8'] == 2.5
    assert R.lr12(lr12_board(4.0, cap_pins=('2',)), C12).figures['C1>U1.8'] == 4.0
    assert R.lr12(lr12_board(4.0, cap_pins=()), C12).figures['C1>U1.8'] == 0.5          # neither pad on the supply: pad 1


# ----------------------------------------------------------------------------- LR-5
C5 = cfg(GEN=('U401', 'C409'), GENERATOR_BLOCK=frozenset({'U401', 'C409'}), SENSITIVE=('/A0',))


def lr5_board(x, pad=None):
    s = Synth('/A0').part('U401', 1, 1, box=(0, 0, 2, 2)).part('C409', 50, 50, box=(49, 49, 51, 51))
    s.s('/A0', 'F', x, -5, x, 5)
    if pad:
        s.part('R1', *pad).p('R1', '1', *pad, '/A0')
    return s.build()


def test_lr5_boundary_exact_distance_and_pads():
    r = R.lr5(lr5_board(12.0), C5)
    assert r.ok and r.figures['min_distance_mm'] == 10.0
    r = R.lr5(lr5_board(11.9), C5)
    assert not r.ok and r.detail == '/A0 9.9 mm' and r.figures['min_distance_mm'] == pytest.approx(9.9)
    # a segment that only passes a corner: distance to the corner, not to an edge line
    s = Synth('/A0').part('U401', 1, 1, box=(0, 0, 2, 2)).part('C409', 50, 50, box=(49, 49, 51, 51)).s('/A0', 'F', 5, 5, 9, 9)
    assert R.lr5(s.build(), C5).figures['min_distance_mm'] == pytest.approx(np.hypot(3, 3))
    r = R.lr5(lr5_board(30.0, pad=(2 + 6, 1)), C5)                       # a sensitive pad 6 mm from the box
    assert not r.ok and r.detail == '/A0 pad R1.1 6.0 mm'
    assert R.lr5(lr5_board(30.0, pad=(2 + 10, 1)), C5).ok
    s = Synth('/A0').part('U401', 1, 1, box=(0, 0, 2, 2)).part('C409', 50, 50, box=(49, 49, 51, 51)).s('/A0', 'F', 0.5, 1, 1.5, 1)
    r = R.lr5(s.build(), C5)                                              # inside the courtyard: distance 0
    assert not r.ok and r.detail == '/A0 0.0 mm' and r.figures['min_distance_mm'] == 0.0


# ----------------------------------------------------------------------------- LR-6 / LR-8 and the touch rules
C6 = cfg(GROUPS={'/+3V3A': {'scope': {'U101'}, 'awg': {'U301'}}}, STAR={'/+3V3A': [('U401', '11')]}, BRIDGE_PADS=[])


def star_board(link=False, gap=0.0):
    s = Synth('/+3V3A').part('U401', 0, 0).p('U401', '11', 0, 0, '/+3V3A').part('U101', 10, 0).p('U101', '8', 10, 0, '/+3V3A')
    s.part('U301', 0, 10).p('U301', '8', 0, 10, '/+3V3A')
    s.s('/+3V3A', 'F', 0.2, 0, 10 - gap, 0).s('/+3V3A', 'F', 0, 0.2, 0, 10)           # the star: both legs start inside the generator pad
    if link:
        s.s('/+3V3A', 'F', 10, 0, 0, 10)
    return s.build()


def test_lr6_star_and_shared_copper():
    r = R.lr6(star_board(), C6)
    assert r.ok and r.figures['pieces'] == 2          # cutting the star pad leaves one piece per leg
    r = R.lr6(star_board(link=True), C6)
    assert not r.ok and r.detail == "/+3V3A: one piece of copper serves ['awg', 'scope']"
    s = Synth('/+3V3A').part('U101', 10, 0).p('U101', '8', 10, 0, '/+3V3A')
    assert "star pads ['U401.11'] are not on the net" in R.lr6(s.build(), C6).detail


def test_lr6_bridge_pads_join_a_piece():
    s = Synth('/+3V3A').part('U401', 0, 0).p('U401', '11', 0, 0, '/+3V3A')
    s.part('U101', 10, 0).p('U101', '8', 10, 0, '/+3V3A').part('U301', 0, 10).p('U301', '8', 0, 10, '/+3V3A')
    b = s.build()
    assert R.lr6(b, C6).ok                           # three isolated pads
    c = cfg(GROUPS=C6.GROUPS, STAR=C6.STAR, BRIDGE_PADS=[('U101', '8', 'U301', '8')])
    assert 'serves' in R.lr6(b, c).detail


@pytest.mark.parametrize('gap, joined', [(0.0, True), (0.04, True), (0.06, False)])
def test_touch_rule_track_end_to_line(gap, joined):
    """two collinear tracks: an end within 0.05 mm of the other's centre line touches (width is not used)"""
    s = Synth('/X').s('/X', 'F', 0, 0, 5, 0).s('/X', 'F', 5 + gap, 0, 10, 0)
    assert len(R.pieces(s.build(), cfg(BRIDGE_PADS=[]), '/X')) == (1 if joined else 2)


@pytest.mark.parametrize('off, joined', [(0.04, True), (0.06, False)])
def test_touch_rule_via_on_track(off, joined):
    s = Synth('/X').s('/X', 'F', 0, 0, 5, 0).v('/X', 2.5, off)
    assert len(R.pieces(s.build(), cfg(BRIDGE_PADS=[]), '/X')) == (1 if joined else 2)


@pytest.mark.parametrize('y, joined', [(0.3 + 0.02, True), (0.3 + 0.03, False)])
def test_touch_rule_track_to_pad_box_grown_by_0_02(y, joined):
    # pad box 0.6 square centred (0,0): half size 0.3; the track runs along y = const
    s = Synth('/X').part('R1', 0, 0).p('R1', '1', 0, 0, '/X').s('/X', 'F', -2, y, 2, y)
    n = len(R.pieces(s.build(), cfg(BRIDGE_PADS=[]), '/X'))
    assert (n == 1) == joined


def test_pads_never_join_each_other():
    s = Synth('/X').part('R1', 0, 0).p('R1', '1', 0, 0, '/X').p('R1', '2', 0.5, 0, '/X')
    assert len(R.pieces(s.build(), cfg(BRIDGE_PADS=[]), '/X')) == 2


def test_lr8_branches():
    c = cfg(VREF_SOURCE=['U1.1'], VREF_BRANCHES=[['R1.1'], ['R2.1']], BRIDGE_PADS=[])

    def board(link):
        s = Synth('/VREF').part('U1', 0, 0).p('U1', '1', 0, 0, '/VREF').part('R1', 10, 0).p('R1', '1', 10, 0, '/VREF')
        s.part('R2', 0, 10).p('R2', '1', 0, 10, '/VREF').s('/VREF', 'F', 0.2, 0, 10, 0).s('/VREF', 'F', 0, 0.2, 0, 10)
        if link:
            s.s('/VREF', 'F', 10, 0, 0, 10)
        return s.build()
    assert R.lr8(board(False), c).ok and R.lr8(board(False), c).detail == 'VREF: 2 branches each on its own copper'
    r = R.lr8(board(True), c)
    assert not r.ok and r.detail == "VREF: branches [0, 1] share copper (['R1', 'R2'])"


# ----------------------------------------------------------------------------- LR-7
def lr7_board(dac0=12.0, shells=3, r302=(0, 0)):
    s = Synth('/DAC0', '/GND').part('J301', 0, 0).part('R301', 10, 0).part('R302', *r302)
    for k in range(shells):
        s.p('J301', '2', k, 1, '/GND')
    return s.s('/DAC0', 'F', 0, 0, dac0, 0).build()


def test_lr7():
    r = R.lr7(lr7_board(), cfg())
    assert r.ok and r.figures['dac0_mm'] == 12.0 and r.figures['shell_pads'] == 3 and r.figures['R301_to_J301_mm'] == 10.0
    assert R.lr7(lr7_board(12.1), cfg()).detail == 'DAC0 12.1 mm of track'
    assert R.lr7(lr7_board(shells=2), cfg()).detail == '2 BNC shell pads on ground'
    assert R.lr7(lr7_board(r302=(16.0, 0)), cfg()).ok
    assert R.lr7(lr7_board(r302=(16.5, 0)), cfg()).detail == 'R302 16 mm from J301'            # .0f of 16.5 rounds to even


# ----------------------------------------------------------------------------- LR-9
def lr9_board(sda_ok):
    s = Synth('/SDA', '/SCL', '/X').part('U1', 10, 10, box=(8, 8, 12, 12))
    if sda_ok:
        s.p('U1', '1', 10, 10, '/SDA')
    return s.s('/SDA', 'F', 0, 10, 20, 10).s('/SCL', 'F', 0, 20, 20, 20).build()


def test_lr9():
    c = cfg(ANALOG_REFS=frozenset({'U1'}))
    r = R.lr9(lr9_board(False), c)
    assert not r.ok and r.detail == '/SDA through U1'
    assert R.lr9(lr9_board(True), c).ok                                # a part on the net may be crossed
    s = Synth('/SDA').part('U1', 10, 10, box=(8, 8, 12, 12)).s('/SDA', 'F', 0, 12.45, 20, 12.45)       # 0.45 above: outside 0.3 + 0.1
    assert R.lr9(s.build(), c).ok
    s = Synth('/SDA').part('U1', 10, 10, box=(8, 8, 12, 12)).s('/SDA', 'F', 0, 12.45, 20, 12.45, w=0.4)    # 0.3 + 0.2 reaches it
    assert not R.lr9(s.build(), c).ok


# ----------------------------------------------------------------------------- LR-11
def lr11_board(**kw):
    s = Synth('/A1', '/GND')
    s.part('R101', 5, 5).part('TP101', 6, 5).p('TP101', '1', 6, 5, '/A1').part('MH601', 50, 50, silk=kw.get('mh_silk', True))
    for w in ('CH1',):
        s.text(w)
    return s.build()


C11 = cfg(BLOCK={'R101': 'CH1', 'TP101': 'CH1', 'MH601': 'EDGE'}, BLOCK_OVERRIDE={}, OUTLINE={'CH1': [(0, 0, 10, 10)]}, TEST_BLOCKS=('CH1',),
          TP_NETS={'TP101': '/A1'}, SILK_WORDS=('CH1',))


def test_lr11():
    r = R.lr11(lr11_board(), C11)
    assert r.ok, r.detail
    assert r.detail == '1 outlines hold exactly their parts, 3 designators, 8 test points' and r.figures['designators'] == 3
    r = R.lr11(lr11_board(mh_silk=False), C11)
    assert r.detail == 'MH601: designator not on silk at 0.8 mm or more'
    c = cfg(**{**vars(C11), 'OUTLINE': {'CH1': [(0, 0, 5.5, 10)]}})                      # TP101 (x 6) falls out of the outline
    assert R.lr11(lr11_board(), c).detail == "CH1: outline holds [] extra, lacks ['TP101']"
    c = cfg(**{**vars(C11), 'TP_NETS': {'TP101': '/GND'}})
    assert R.lr11(lr11_board(), c).detail == 'TP101: missing or not on /GND'
    c = cfg(**{**vars(C11), 'SILK_WORDS': ('CH1', 'POWER')})
    assert R.lr11(lr11_board(), c).detail == "silk word 'POWER' missing"
    c = cfg(**{**vars(C11), 'BLOCK': {'R101': 'AWG', 'TP101': 'CH1'}})
    d = R.lr11(lr11_board(), c).detail
    assert 'R101: designator number says CH1, the part is in AWG' in d
    # a designator below 0.79 mm is not on silk "at 0.8 mm"
    s = Synth('/A1').part('R101', 5, 5, h=0.78).part('TP101', 6, 5).p('TP101', '1', 6, 5, '/A1').text('CH1')
    assert 'R101: designator not on silk at 0.8 mm or more' in R.lr11(s.build(), C11).detail


# ----------------------------------------------------------------------------- LR-2 (the flow rule, small geometry)
def lr2_board(x_r1=90.0, outl_extra=0.0, gen=(20, 20), pad2_y=40.0):
    s = Synth('/A1', '/A0', '/CH1_OUT', '/CH2_OUT', '/CH2_RISO', '/CH1_N', '/CH1_NP', '/CH1_IN', '/CH2_N', '/CH2_NP', '/CH2_IN', '/CH1_M1')
    for ch, base, bnc, adc, y in ((1, 100, 'J101', '7', 40.0), (2, 200, 'J201', '8', 20.0)):
        s.part(bnc, 102, y).p(bnc, '1', 102, y)
        s.part(f'R{base + 1}', x_r1 if ch == 1 else 90.5, y).part(f'R{base + 7}', 80, y).part(f'R{base + 8}', 70, y)
    s.part('U101', 75, 30).part('J602', 50, 2).p('J602', '7', 60, 2).p('J602', '8', 62, 2)
    s.part('J601', 20, 2).p('J601', '5', 30, 2).part('J301', 102, 8.89)
    s.part('U401', *gen, box=(gen[0] - 1, gen[1] - 1, gen[0] + 1, gen[1] + 1)).part('C409', gen[0] + 5, gen[1], box=(gen[0] + 4, gen[1] - 1, gen[0] + 6, gen[1] + 1))
    for r, x in (('U501', 40), ('U502', 45), ('R501', 50), ('R506', 55)):
        s.part(r, x, 45, box=(x - 1, 44, x + 1, 46))
    s.p('U101', '1', 60, 30, '/CH1_N').p('U101', '2', 60, pad2_y, '/CH2_N')
    s.s('/A1', 'F', 0, 0, 10 + outl_extra, 0).s('/CH1_M1', 'F', 0, 0, 2, 0)
    return s.build()


def test_lr2_flow_generator_and_separation():
    c = cfg(CHANNELS=((1, 100, 'J101', '7'),))
    r = R.lr2(lr2_board(), c)
    assert 'x does not fall' not in r.detail
    # channel 1 divider side: 2 mm of CH1_M1; the output (A1) run 10 mm is longer: no complaint
    assert 'not longer' not in r.detail
    assert R.lr2(lr2_board(outl_extra=-9.0), c).detail.startswith('CH1: output run 1.0 mm is not longer than the divider side 2.0 mm')
    r = R.lr2(lr2_board(x_r1=60.0), c)
    assert r.detail.startswith('CH1: x does not fall BNC > R1 > Rnp > U101 > Riso > ADC pad: [102.0, 60.0, 80.0, 75.0, 70.0, 60.0]')
    assert r.figures['generator_to_J101_mm'] == pytest.approx(np.hypot(82, 20.0 - 40.0))


# ----------------------------------------------------------------------------- remaining boundaries
def test_lr2_boundaries():
    c = cfg(CHANNELS=((1, 100, 'J101', '7'),))

    def detail(**kw):
        return R.lr2(lr2_board(**kw), c).detail
    # generator to the 5 V pad (J601.5 at (30, 2)): 15 mm is allowed
    assert 'from the 5 V pad' not in detail(gen=(30, 17.0))
    assert 'from the 5 V pad' in detail(gen=(30, 17.1))
    # generator to a BNC: J101 at (102, 40); 50 mm is allowed, 49.9 is not
    assert 'from J101' not in detail(gen=(52, 40))
    assert 'generator 50 mm from J101' in detail(gen=(52.1, 40))
    # reference parts: U501 courtyard (39..41, 44..46); C409's courtyard edge 10 mm away is allowed
    assert 'U501 only' not in detail(gen=(23, 45))
    assert 'U501 only 9.8 mm from the generator' in detail(gen=(23.2, 45))
    # divider pads of the two channels at least 5 mm apart
    r = R.lr2(lr2_board(), c)
    assert r.figures['divider_gap_mm'] == pytest.approx(10.0)             # U101.1 (60, 30) and U101.2 (60, 40)
    assert R.lr2(lr2_board(pad2_y=35.0), c).figures['divider_gap_mm'] == 5.0 and 'apart' not in detail(pad2_y=35.0)
    assert "divider pads only 4.9 mm apart" in detail(pad2_y=34.9)
    # the output run must be strictly longer than the divider side: equal fails
    assert 'not longer than the divider side 2.0 mm' in detail(outl_extra=-8.0) and 'not longer' not in detail(outl_extra=-7.9)
    # x must strictly fall along the chain: R1 at the same x as Rnp fails
    assert 'x does not fall' in detail(x_r1=80.0) and 'x does not fall' not in detail(x_r1=80.1)


def test_lr5_generator_block_pads_are_not_counted_and_lr7_shell_net():
    s = Synth('/A0').part('U401', 1, 1, box=(0, 0, 2, 2)).part('C409', 50, 50, box=(49, 49, 51, 51)).p('U401', '3', 5, 1, '/A0')
    assert R.lr5(s.build(), C5).ok                                         # the generator's own pad on a sensitive net
    s = Synth('/DAC0', '/GND', '/X').part('J301', 0, 0).part('R301', 10, 0).part('R302', 0, 0)
    s.p('J301', '2', 0, 1, '/GND').p('J301', '2', 1, 1, '/GND').p('J301', '2', 2, 1, '/X').p('J301', '3', 3, 1, '/GND')
    assert R.lr7(s.s('/DAC0', 'F', 0, 0, 1, 0).build(), cfg()).detail == '2 BNC shell pads on ground'


def test_touch_rule_via_to_via_and_via_in_pad_box():
    two = lambda d: Synth('/X').v('/X', 0, 0).v('/X', d, 0).build()
    assert len(R.pieces(two(0.04), cfg(BRIDGE_PADS=[]), '/X')) == 1
    assert len(R.pieces(two(0.06), cfg(BRIDGE_PADS=[]), '/X')) == 2
    pv = lambda x: Synth('/X').part('R1', 0, 0).p('R1', '1', 0, 0, '/X').v('/X', x, 0).build()
    assert len(R.pieces(pv(0.32), cfg(BRIDGE_PADS=[]), '/X')) == 1          # pad box half width 0.3 + 0.02
    assert len(R.pieces(pv(0.33), cfg(BRIDGE_PADS=[]), '/X')) == 2


def test_lr11_designators_with_fewer_than_three_digits_belong_to_nobody():
    s = Synth('/A1').part('R101', 5, 5).part('TP101', 6, 5).p('TP101', '1', 6, 5, '/A1').part('MH601', 50, 50).part('R10', 99, 99).text('CH1')
    assert R.lr11(s.build(), C11).ok
