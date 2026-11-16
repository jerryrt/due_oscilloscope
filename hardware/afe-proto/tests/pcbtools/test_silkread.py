"""pcbtools.silkread (docs/afe.md D30, the owner's convention of 2026-11-15: every designator horizontal, centred just above
its part) on hand-built boards with known answers, each rule broken once on purpose, and on the two real boards, whose
finding counts are held exactly (a ratchet: a change that adds one fails, a change that removes some records the new count)."""
import pathlib

import numpy as np
import pytest

from pcbtools import boardio, silkread

from synth import Synth

HERE = pathlib.Path(__file__).resolve().parents[2]
BNC = {'J1': 'CH1 IN', 'J2': 'CH2 IN'}


def two(s, ref, x, y, vertical=False):
    """an 0603-like two-terminal part: courtyard 3.0 x 1.5 (or 1.5 x 3.0), two pads"""
    hx, hy = (0.75, 1.5) if vertical else (1.5, 0.75)
    s.part(ref, x, y, box=(x - hx, y - hy, x + hx, y + hy), rot=90.0 if vertical else 0.0, silk=None)
    d = 0.8
    if vertical:
        s.p(ref, '1', x, y - d, size=0.8).p(ref, '2', x, y + d, size=0.8)
    else:
        s.p(ref, '1', x - d, y, size=0.8).p(ref, '2', x + d, y, size=0.8)
    return s


def lab(s, ref, x, y, ang=0.0, layer=0):
    refs = [f[0] for f in s.fp]
    s.rt.append((x, y, 1.0, 1.0, 0.15, ang, layer, layer == 0, refs.index(ref)))


def board(over=None, extra=None):
    """A horizontal and V vertical, each labelled just above; header H along x, in the lower half, labelled centred above it
    (its inboard side); two BNCs
    with their labels. `over` replaces {ref: (x, y, ang)} or hides one with None; `extra(s)` adds parts."""
    s = Synth()
    two(s, 'A', 10.0, 10.0)                       # courtyard top y 10.75
    two(s, 'V', 20.0, 10.0, vertical=True)        # courtyard top y 11.5
    s.part('H', 40.0, 10.0, box=(35.0, 9.0, 45.0, 11.0), silk=None)
    for r, y in (('J1', 40.0), ('J2', 60.0)):
        s.part(r, 60.0, y, box=(58.0, y - 1.0, 66.0, y + 1.0), silk=None)
    pos = {'A': (10.0, 11.4, 0.0), 'V': (20.0, 12.15, 0.0), 'H': (40.0, 11.6, 0.0)}
    pos.update(over or {})
    for r, v in pos.items():
        if v is not None:
            lab(s, r, *v)
    lab(s, 'J1', 60.0, 38.0, 0.0, 1)
    lab(s, 'J2', 60.0, 58.0, 0.0, 1)
    s.text('CH1 IN', 63.0, 42.0).text('CH2 IN', 63.0, 62.0)
    if extra:
        extra(s)
    return s.build()


def find(over=None):
    return silkread.findings(board(over), BNC, edge_headers={'H'})


def has(f, start, text):
    return any(x.startswith(start) and text in x for x in f)


def test_the_good_board_has_no_findings():
    assert find() == []


def ic_board(label):
    """an IC U1 (courtyard 20-26 x 8-12) with its designator at `label`"""
    s = Synth()
    s.part('U1', 23.0, 10.0, box=(20.0, 8.0, 26.0, 12.0), silk=None)
    lab(s, 'U1', *label)
    return s.build()


def test_a_named_ic_may_carry_its_designator_beside_its_east_end():
    east = (26.0 + 0.2 + 0.9, 10.0, 0.0)                             # 'U1' is 1.8 wide: west edge 0.2 mm east of the courtyard
    assert silkread.findings(ic_board(east), east_end={'U1'}) == []
    assert has(silkread.findings(ic_board(east)), 'U1:', 'not centred above it')      # unnamed: the ordinary rule


def test_a_named_ic_beside_its_end_but_off_centre_or_far_fails():
    for x, y in ((26.0 + 0.2 + 0.9, 10.6), (26.0 + 1.0 + 0.9, 10.0), (20.0 - 0.2 - 0.9, 10.0), (26.0 - 0.2 + 0.9, 10.0)):
        # off centre, far, the west end, 0.2 mm into the courtyard
        assert has(silkread.findings(ic_board((x, y, 0.0)), east_end={'U1'}), 'U1:', 'beside its east end'), (x, y)


def test_a_named_part_may_carry_its_designator_beside_it():
    for x in (11.5 + 0.2 + 0.45, 8.5 - 0.2 - 0.45):                   # A's courtyard x 8.5-11.5; 'A' is 0.9 wide
        assert silkread.findings(board({'A': (x, 10.0, 0.0)}), BNC, edge_headers={'H'}, beside={'A'}) == [], x
    assert has(find({'A': (11.5 + 0.2 + 0.45, 10.0, 0.0)}), 'A:', 'not centred above it')   # unnamed: the ordinary rule


def test_a_named_part_beside_but_off_centre_far_or_into_it_fails():
    for x, y in ((12.15, 10.6), (12.95, 10.0), (11.75, 10.0), (7.85, 10.6), (7.05, 10.0), (8.25, 10.0)):
        # east: off centre, 1.0 out, 0.2 into the courtyard; the same three west
        assert has(silkread.findings(board({'A': (x, y, 0.0)}), BNC, edge_headers={'H'}, beside={'A'}), 'A:', 'beside it'), (x, y)


def neighbour(x, label_y=None):
    """B, 1.0 x 1.5, centred at (x, 8.7) (courtyard top 9.45), just east of A, labelled above it at label_y"""
    def add(s):
        s.part('B', x, 8.7, box=(x - 0.5, 7.95, x + 0.5, 9.45), silk=None)
        lab(s, 'B', x, label_y if label_y is not None else 9.45 + 0.15 + 0.5)
    return add


A_WEST = {'A': (8.5 - 0.2 - 0.45, 10.0, 0.0)}


def test_a_part_labelled_beside_with_another_label_on_its_other_side_fails():
    # B's label, centred above B, lands 0.35 east of A at A's centre y + 0.1: A reads 'B' on one side and 'A' on the other
    f = silkread.findings(board(A_WEST, neighbour(12.3)), BNC, edge_headers={'H'}, beside={'A'})
    assert f == ["A: B's designator lies east of it, where its own would be read"], f


def test_the_same_neighbour_is_harmless_to_a_part_labelled_above():
    assert silkread.findings(board(None, neighbour(12.3)), BNC, edge_headers={'H'}) == []


def test_a_neighbour_label_well_off_centre_still_reads_as_the_parts():
    # B's label 0.45 mm above A's centre line (outside ABOVE_X) still shares A's y span: the eye still gives it to A
    f = silkread.findings(board(A_WEST, neighbour(12.3, 10.45)), BNC, edge_headers={'H'}, beside={'A'})
    assert has(f, 'A:', "B's designator lies east of it"), f


def test_the_neighbour_beyond_read_gap_or_out_of_the_band_passes():
    # label west edge 0.65 mm east of A's courtyard
    assert silkread.findings(board(A_WEST, neighbour(12.6)), BNC, edge_headers={'H'}, beside={'A'}) == []
    # label box bottom 10.8, above A's courtyard top 10.75
    f = silkread.findings(board(A_WEST, neighbour(12.3, 11.3)), BNC, edge_headers={'H'}, beside={'A'})
    assert not has(f, 'A:', 'where its own'), f


def test_a_beside_label_lying_above_another_part_fails():
    # A labelled east (box 11.7-12.6 x 9.5-10.5); C's courtyard top 0.2 under it and centred on it; C labelled far below
    def add(s):
        s.part('C', 12.15, 8.8, box=(11.65, 8.3, 12.65, 9.3), silk=None)
        lab(s, 'C', 12.15, 5.0)
    f = silkread.findings(board({'A': (11.5 + 0.2 + 0.45, 10.0, 0.0)}, add), BNC, edge_headers={'H'}, beside={'A'})
    assert has(f, 'A:', "where it reads as C's"), f


def test_a_missing_designator_fails():
    assert has(find({'A': None}), 'A:', 'no designator')


def test_a_turned_designator_fails_even_on_a_vertical_part():
    assert has(find({'V': (20.0, 12.15, 90.0)}), 'V:', 'not horizontal')


def test_a_designator_beside_instead_of_above_fails():
    assert has(find({'A': (13.6, 10.0, 0.0)}), 'A:', 'not centred above')


def test_a_designator_off_centre_fails():
    assert has(find({'A': (10.5, 11.4, 0.0)}), 'A:', 'off centre 0.50')


def test_a_designator_too_high_fails():
    assert has(find({'A': (10.0, 12.5, 0.0)}), 'A:', 'not centred above')


def test_a_designator_below_fails():
    assert has(find({'A': (10.0, 8.6, 0.0)}), 'A:', 'not centred above')


def test_a_designator_on_its_own_part_fails():
    assert has(find({'A': (10.0, 10.0, 0.0)}), 'A:', 'courtyard of A')


def test_a_header_label_at_its_end_fails():
    assert has(find({'H': (34.25, 10.0, 0.0)}), 'H:', 'above it, on its inboard side')


def test_a_header_label_on_its_outboard_side_fails():
    assert has(find({'H': (40.0, 8.4, 0.0)}), 'H:', 'above it, on its inboard side')


def test_a_header_label_off_centre_along_its_length_fails():
    assert has(find({'H': (38.0, 11.6, 0.0)}), 'H:', 'off centre 2.00')


def _with_outline(b, y1):
    outline = np.array([[0.0, 0.0], [100.0, 0.0], [100.0, y1], [0.0, y1]])
    return boardio.BoardArrays(**{**{k: getattr(b, k) for k in b.__dataclass_fields__}, 'outline': outline})


@pytest.mark.parametrize('label_y,ok', [(88.4, True), (91.6, False)])
def test_a_header_in_the_upper_half_takes_its_label_below(label_y, ok):
    s = Synth()
    s.part('H', 40.0, 90.0, box=(35.0, 89.0, 45.0, 91.0), silk=None)
    lab(s, 'H', 40.0, label_y)
    f = silkread.findings(_with_outline(s.build(), 100.0), edge_headers={'H'})
    assert (f == []) if ok else has(f, 'H:', 'below it, on its inboard side'), f


def test_the_outline_decides_the_half():
    """the same header and label, read against a taller board, is in the lower half and wants its label above"""
    s = Synth()
    s.part('H', 40.0, 90.0, box=(35.0, 89.0, 45.0, 91.0), silk=None)
    lab(s, 'H', 40.0, 88.4)
    assert has(silkread.findings(_with_outline(s.build(), 200.0), edge_headers={'H'}), 'H:', 'above it, on its inboard side')


def test_a_mounting_hole_needs_no_designator():
    s = Synth()
    s.part('MH1', 10.0, 10.0, box=(8.0, 8.0, 12.0, 12.0), silk=None)
    s.part('MHX', 30.0, 10.0, box=(28.0, 8.0, 32.0, 12.0), silk=None)      # not a hole's name: still needs one
    assert silkread.findings(s.build()) == ['MHX: no designator on the top silk']


def test_two_designators_too_close_fail():
    s = Synth()
    two(s, 'AAA', 10.0, 10.0)
    two(s, 'BBB', 13.0, 10.0)
    lab(s, 'AAA', 10.0, 11.4)
    lab(s, 'BBB', 13.0, 11.4)                     # boxes 2.7 wide, 0.3 mm apart
    assert has(silkread.findings(s.build()), 'AAA:', "from BBB's, under 0.5")


def test_a_designator_on_a_via_fails():
    s = Synth()
    two(s, 'A', 10.0, 10.0)
    lab(s, 'A', 10.0, 11.4)
    s.v('', 10.0, 11.4)
    assert has(silkread.findings(s.build()), 'A:', 'on a via')


def test_a_designator_on_a_silk_line_fails():
    line = ('seg', 5.0, 11.4, 15.0, 11.4, 0.15)                      # a block outline through A's label
    assert has(silkread.findings(board(), BNC, edge_headers={'H'}, silk=[line]), 'A:', 'on a silk line')


def test_a_silk_line_near_a_designator_passes():
    line = ('seg', 5.0, 12.2, 15.0, 12.2, 0.15)                      # 0.2 mm above A's label box, stroke included
    assert silkread.findings(board(), BNC, edge_headers={'H'}, silk=[line]) == []


def test_a_diagonal_silk_line_across_a_designator_fails():
    line = ('seg', 9.0, 10.8, 11.0, 12.0, 0.1)
    assert has(silkread.findings(board(), BNC, edge_headers={'H'}, silk=[line]), 'A:', 'on a silk line')


def test_a_bnc_label_on_a_silk_line_fails():
    line = ('seg', 63.0, 55.0, 63.0, 65.0, 0.15)
    assert has(silkread.findings(board(), BNC, edge_headers={'H'}, silk=[line]), 'J2:', '"CH2 IN" lies on a silk line')


def test_read_silk_takes_top_lines_and_rectangles():
    x0, y0 = boardio.from_due(10.0, 10.0)
    x1, y1 = boardio.from_due(20.0, 14.0)
    item = lambda kind, layer, fill='': (f'\t({kind}\n\t\t(start {float(x0)} {float(y0)})\n\t\t(end {float(x1)} {float(y1)})\n'
                                         f'\t\t(stroke\n\t\t\t(width 0.15)\n\t\t)\n{fill}\t\t(layer "{layer}")\n\t)\n')
    txt = ('(kicad_pcb\n' + item('gr_line', 'F.SilkS') + item('gr_line', 'F.Fab') + item('gr_rect', 'F.SilkS', '\t\t(fill no)\n')
           + item('gr_rect', 'F.SilkS', '\t\t(fill yes)\n') + ')\n')
    got = silkread.read_silk(txt)
    assert [g[0] for g in got] == ['seg'] * 5 + ['box'], got
    assert got[0] == pytest.approx(('seg', 10.0, 10.0, 20.0, 14.0, 0.15))
    assert got[-1][1:] == pytest.approx((10.0, 10.0, 20.0, 14.0))


def test_a_bnc_label_off_its_frame_fails():
    b = board()
    ty = list(b.t_y)
    ty[1] += 0.1
    b2 = boardio.BoardArrays(**{**{k: getattr(b, k) for k in b.__dataclass_fields__}, 't_y': ty})
    assert has(silkread.findings(b2, BNC, edge_headers={'H'}), 'J2:', '"CH2 IN" at')


def test_a_bnc_label_under_a_body_fails():
    b = board()
    tx, ty = list(b.t_x), list(b.t_y)
    tx[0], ty[0], tx[1], ty[1] = 62.0, 40.0, 62.0, 60.0
    b2 = boardio.BoardArrays(**{**{k: getattr(b, k) for k in b.__dataclass_fields__}, 't_x': tx, 't_y': ty})
    assert has(silkread.findings(b2, BNC, edge_headers={'H'}), 'J1:', 'whose body hides it')


def test_a_bnc_designator_belongs_on_the_bottom():
    s = Synth()
    for r, y in (('J1', 40.0), ('J2', 60.0)):
        s.part(r, 60.0, y, box=(58.0, y - 1.0, 66.0, y + 1.0), silk=None)
    lab(s, 'J1', 60.0, 38.0, 0.0, 1)
    lab(s, 'J2', 60.0, 58.0, 0.0, 0)              # J2's on top
    s.text('CH1 IN', 63.0, 42.0).text('CH2 IN', 63.0, 62.0)
    assert has(silkread.findings(s.build(), BNC), 'J2:', '0 designators on the bottom and 1 on top')


def test_a_bnc_bottom_designator_off_its_frame_fails():
    s = Synth()
    for r, y in (('J1', 40.0), ('J2', 60.0)):
        s.part(r, 60.0, y, box=(58.0, y - 1.0, 66.0, y + 1.0), silk=None)
    lab(s, 'J1', 60.0, 38.0, 0.0, 1)
    lab(s, 'J2', 61.0, 58.0, 0.0, 1)
    s.text('CH1 IN', 63.0, 42.0).text('CH2 IN', 63.0, 62.0)
    assert has(silkread.findings(s.build(), BNC), 'J2:', 'bottom designator at')


LABELS = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}
EDGE = {'J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607'}
# Findings on 2026-11-15 under the "horizontal, above" convention (silk lines read, mounting holes skipped, header labels
# inboard), before the
# relayout: held exactly (a ratchet).
OPEN = {'v2/layout/integrated/afe-v2-integrated.kicad_pcb': 211, 'kicad/afe-proto.kicad_pcb': 206}
# D30's named exceptions to rule 1, per board: the IC whose designator sits beside its pin-free east end (rule 2a).
EAST_END = {'v2/layout/integrated/afe-v2-integrated.kicad_pcb': {'U101', 'U301', 'U401'}, 'kicad/afe-proto.kicad_pcb': {'U101', 'U301'}}
# and the parts whose designator sits beside them (rule 2b).
BESIDE = {'v2/layout/integrated/afe-v2-integrated.kicad_pcb': {'R304', 'C301', 'C306', 'C402', 'C403', 'C405', 'C406', 'C407', 'C408', 'R402', 'R403', 'R404', 'R405', 'C502'}, 'kicad/afe-proto.kicad_pcb': {'R302', 'R303', 'C301', 'R305', 'C302', 'C401', 'C402', 'C405', 'C409'}}


@pytest.mark.pcbnew
@pytest.mark.parametrize('rel', sorted(OPEN))
def test_the_board_only_gets_closer_to_d30(rel):
    p = HERE / rel
    f = silkread.findings(boardio.read_board(str(p)), LABELS, edge_headers=EDGE, silk=silkread.read_silk(p.read_text()),
                          east_end=EAST_END[rel], beside=BESIDE[rel])
    assert len(f) <= OPEN[rel], f'{len(f)} D30 findings against {OPEN[rel]} recorded: {f[:5]}'
    assert len(f) == OPEN[rel], f'{len(f)} D30 findings, fewer than the {OPEN[rel]} recorded: lower OPEN to {len(f)}'
