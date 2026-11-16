"""pcbtools.silkread (docs/afe.md D30, the owner's convention of 2026-11-15: every designator horizontal, centred just above
its part) on hand-built boards with known answers, each rule broken once on purpose, and on the two real boards, whose
finding counts are held exactly (a ratchet: a change that adds one fails, a change that removes some records the new count)."""
import pathlib

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


def board(over=None):
    """A horizontal and V vertical, each labelled just above; header H along x labelled beyond its left end; two BNCs
    with their labels. `over` replaces {ref: (x, y, ang)} or hides one with None."""
    s = Synth()
    two(s, 'A', 10.0, 10.0)                       # courtyard top y 10.75
    two(s, 'V', 20.0, 10.0, vertical=True)        # courtyard top y 11.5
    s.part('H', 40.0, 10.0, box=(35.0, 9.0, 45.0, 11.0), silk=None)
    for r, y in (('J1', 40.0), ('J2', 60.0)):
        s.part(r, 60.0, y, box=(58.0, y - 1.0, 66.0, y + 1.0), silk=None)
    pos = {'A': (10.0, 11.4, 0.0), 'V': (20.0, 12.15, 0.0), 'H': (34.25, 10.0, 0.0)}
    pos.update(over or {})
    for r, v in pos.items():
        if v is not None:
            lab(s, r, *v)
    lab(s, 'J1', 60.0, 38.0, 0.0, 1)
    lab(s, 'J2', 60.0, 58.0, 0.0, 1)
    s.text('CH1 IN', 63.0, 42.0).text('CH2 IN', 63.0, 62.0)
    return s.build()


def find(over=None):
    return silkread.findings(board(over), BNC, edge_headers={'H'})


def has(f, start, text):
    return any(x.startswith(start) and text in x for x in f)


def test_the_good_board_has_no_findings():
    assert find() == []


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


def test_a_header_label_above_instead_of_at_its_end_fails():
    assert has(find({'H': (40.0, 11.6, 0.0)}), 'H:', 'beyond its left end')


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
# Findings on 2026-11-15 under the "horizontal, above" convention (silk lines read, mounting holes skipped), before the
# relayout: held exactly (a ratchet).
OPEN = {'v2/layout/integrated/afe-v2-integrated.kicad_pcb': 209, 'kicad/afe-proto.kicad_pcb': 207}


@pytest.mark.pcbnew
@pytest.mark.parametrize('rel', sorted(OPEN))
def test_the_board_only_gets_closer_to_d30(rel):
    p = HERE / rel
    f = silkread.findings(boardio.read_board(str(p)), LABELS, edge_headers=EDGE, silk=silkread.read_silk(p.read_text()))
    assert len(f) <= OPEN[rel], f'{len(f)} D30 findings against {OPEN[rel]} recorded: {f[:5]}'
    assert len(f) == OPEN[rel], f'{len(f)} D30 findings, fewer than the {OPEN[rel]} recorded: lower OPEN to {len(f)}'
