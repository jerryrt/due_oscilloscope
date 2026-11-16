"""pcbtools.align (docs/afe.md D31) on hand-built boards with known answers, each rule broken once on purpose, and on the two
real boards, whose finding counts are held exactly (a ratchet, as test_silkread's)."""
import pathlib

import pytest

from pcbtools import align, boardio

from synth import Synth

HERE = pathlib.Path(__file__).resolve().parents[2]


def board(**over):
    """R101-R103 a row at y 10 (labels at y 11), C104/C105 a column at x 40, C106 on U101's pin 1 line. `over` moves or
    adds a part: {ref: (x, y, rot)}; a label is moved with label_<ref>=y."""
    s = Synth()
    pos = {'R101': (10.0, 10.0, 0.0), 'R102': (13.0, 10.0, 0.0), 'R103': (16.0, 10.0, 0.0),
           'C104': (40.0, 10.0, 90.0), 'C105': (40.0, 13.0, 90.0), 'C106': (25.0, 20.0, 0.0),
           'U101': (30.0, 18.0, 0.0)}
    pos.update({k: v for k, v in over.items() if not k.startswith('label_')})
    for r, (x, y, a) in pos.items():
        s.part(r, x, y, box=(x - 1, y - 0.5, x + 1, y + 0.5), rot=a, silk=None)
    refs = [f[0] for f in s.fp]
    for r, (x, y, a) in pos.items():
        s.rt.append((x, over.get(f'label_{r}', y + 1.0), 1.0, 1.0, 0.15, 0.0, 0, True, refs.index(r)))
    ux, uy, _ = pos['U101']
    s.p('U101', '1', ux - 2.0, uy + 2.0).p('U101', '8', ux + 2.0, uy + 2.0)
    s.p('R101', '1', 9.5, 10.0)                                       # a passive's own pad is not a pin line
    return s.build()


def test_the_good_board_has_no_findings():
    assert align.findings(board()) == []


def test_a_part_off_its_row_fails():
    f = align.findings(board(R102=(13.0, 10.2, 0.0)))
    assert f == ['R102: in no row or column of block 1 and on no pin line'], f


def test_a_part_turned_against_its_row_fails():
    f = align.findings(board(R102=(13.0, 10.0, 90.0)))
    assert any(x.startswith('R102: in no row') for x in f), f


def test_0_and_180_are_one_orientation():
    assert align.findings(board(R102=(13.0, 10.0, 180.0))) == []


def test_a_column_counts():
    f = align.findings(board(C105=(40.3, 13.0, 90.0)))
    assert {x.split(':')[0] for x in f} == {'C104', 'C105'}, f


def test_a_mate_in_another_block_does_not_count():
    """R201 sits in R101's row, 3 mm from R103, but block 2 has no other part"""
    f = align.findings(board(R201=(19.0, 10.0, 0.0)))
    assert f == ['R201: in no row or column of block 2 and on no pin line'], f


def test_a_mate_beyond_reach_does_not_count():
    f = align.findings(board(R103=(16.0 + align.REACH + 1.0, 10.0, 0.0)))
    assert any(x.startswith('R103: in no row') for x in f), f


def test_a_pin_line_counts_and_only_near_the_pin():
    assert align.findings(board()) == []                              # C106 at y 20 = U101 pin 1's y
    f = align.findings(board(C106=(25.0, 20.3, 0.0)))
    assert f == ['C106: in no row or column of block 1 and on no pin line'], f
    f = align.findings(board(C106=(28.0 - align.PIN_REACH - 1.0, 20.0, 0.0)))
    assert f == ['C106: in no row or column of block 1 and on no pin line'], f


def test_a_row_with_a_label_out_of_line_fails():
    f = align.findings(board(label_R102=11.3))
    assert any('R101, R102: one row, designators 0.30 mm apart' in x for x in f), f


# Findings on main's boards on 2026-11-16, before any D31 work: a ratchet, as test_silkread's OPEN.
OPEN = {'v2/layout/integrated/afe-v2-integrated.kicad_pcb': 33, 'kicad/afe-proto.kicad_pcb': 59}


@pytest.mark.pcbnew
@pytest.mark.parametrize('rel', sorted(OPEN))
def test_the_board_only_gets_more_aligned(rel):
    f = align.findings(boardio.read_board(str(HERE / rel)))
    assert len(f) <= OPEN[rel], f'{len(f)} D31 findings against {OPEN[rel]} recorded: {f[:5]}'
    assert len(f) == OPEN[rel], f'{len(f)} D31 findings, fewer than recorded: lower OPEN to {len(f)}'
