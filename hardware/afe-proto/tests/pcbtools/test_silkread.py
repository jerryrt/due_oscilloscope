"""pcbtools.silkread (docs/afe.md D30, the owner's convention of 2026-11-15) on hand-built boards with known answers, each
property broken once on purpose, and on the two real boards, whose finding counts are held exactly (a ratchet: a change
that adds one fails, a change that removes some records the new count)."""
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


def board(labels=None, run_x=(30.0, 33.2, 36.4), run_refs=('R1', 'R2', 'R3')):
    """A and B labelled beside themselves; a row R1-R3 labelled at its left end; two BNCs with their labels.
    `labels` overrides {ref: (x, y, angle)}; None hides one."""
    s = Synth()
    two(s, 'A', 10.0, 10.0)
    two(s, 'B', 20.0, 10.0)
    for r, x in zip(run_refs, run_x):
        two(s, r, x, 20.0)
    for r, y in (('J1', 40.0), ('J2', 60.0)):
        s.part(r, 60.0, y, box=(58.0, y - 1.0, 66.0, y + 1.0), silk=None)
    lab = {'A': (10.0, 12.0, 0.0), 'B': (20.0, 12.0, 0.0), 'R1': (26.6, 20.0, 0.0), 'J1': (60.0, 38.0, 0.0), 'J2': (60.0, 58.0, 0.0)}
    lab.update(labels or {})
    refs = [f[0] for f in s.fp]
    for r, v in lab.items():
        if v is not None:
            s.rt.append((v[0], v[1], 1.0, 1.0, 0.15, v[2], 0, True, refs.index(r)))
    s.text('CH1 IN', 63.0, 42.0).text('CH2 IN', 63.0, 62.0)
    return s.build()


def has(f, start, text):
    return any(x.startswith(start) and text in x for x in f)


def test_the_good_board_has_no_findings():
    b = board()
    assert silkread.findings(b, BNC) == []
    assert silkread.runs(b) == {'R1': ['R2', 'R3']}


def test_a_designator_nearer_another_part_fails():
    assert has(silkread.findings(board({'A': (17.0, 12.0, 0.0)}), BNC), 'A:', 'margin under')


def test_a_tie_fails():
    assert has(silkread.findings(board({'A': (15.0, 10.0, 0.0)}), BNC), 'A:', 'margin under')


def test_a_designator_on_another_courtyard_fails():
    assert has(silkread.findings(board({'A': (20.0, 10.9, 0.0)}), BNC), 'A:', 'courtyard of B')


def test_a_designator_on_its_own_part_fails():
    assert has(silkread.findings(board({'A': (10.0, 10.0, 0.0)}), BNC), 'A:', 'its own part')


def test_a_designator_across_its_part_fails():
    assert has(silkread.findings(board({'A': (10.0, 13.5, 90.0)}), BNC), 'A:', 'does not read along')


def test_a_slanted_designator_fails():
    assert has(silkread.findings(board({'A': (10.0, 12.0, 45.0)}), BNC), 'A:', 'does not read along')


def test_a_run_label_off_its_line_leaves_the_run_unlabelled():
    f = silkread.findings(board({'R1': (26.6, 20.6, 0.0)}), BNC)
    assert has(f, 'R2:', 'in no labelled run') and has(f, 'R3:', 'in no labelled run'), f


def test_a_run_label_at_the_far_end_leaves_the_run_unlabelled():
    f = silkread.findings(board({'R1': (39.9, 20.0, 0.0)}), BNC)
    assert has(f, 'R2:', 'in no labelled run'), f


def test_a_run_out_of_order_is_not_a_run():
    f = silkread.findings(board(run_refs=('R1', 'R3', 'R2')), BNC)
    assert has(f, 'R2:', 'in no labelled run') and has(f, 'R3:', 'in no labelled run'), f


def test_a_run_with_a_gap_stops_at_the_gap():
    f = silkread.findings(board(run_x=(30.0, 33.2, 40.0)), BNC)
    assert has(f, 'R3:', 'in no labelled run') and not has(f, 'R2:', 'in no labelled run'), f


def test_a_run_label_too_far_from_its_starter_fails():
    assert has(silkread.findings(board({'R1': (25.5, 20.0, 0.0)}), BNC), 'R1:', 'more than')


def test_a_member_turned_across_the_row_ends_the_run():
    s = Synth()
    two(s, 'R1', 30.0, 20.0)
    two(s, 'R2', 32.6, 20.0, vertical=True)
    s.rt.append((26.6, 20.0, 1.0, 1.0, 0.15, 0.0, 0, True, 0))
    assert has(silkread.findings(s.build()), 'R2:', 'in no labelled run')


def test_a_vertical_run_reads_from_its_end():
    s = Synth()
    for n, y in enumerate((20.0, 23.2, 26.4)):
        two(s, f'C{n + 1}', 30.0, y, vertical=True)
    s.rt.append((30.0, 16.6, 1.0, 1.0, 0.15, 90.0, 0, True, 0))      # below C1, the run going up
    b = s.build()
    assert silkread.findings(b) == [] and silkread.runs(b) == {'C1': ['C2', 'C3']}


def test_an_exempt_part_needs_no_label():
    f = silkread.findings(board({'A': None}), BNC, exempt={'A': 'reason'})
    assert not [x for x in f if x.startswith('A:')], f
    assert has(silkread.findings(board({'A': None}), BNC), 'A:', 'in no labelled run')


def test_a_bnc_label_off_its_frame_fails():
    b = board()
    ty = list(b.t_y)
    ty[1] += 0.1
    b2 = boardio.BoardArrays(**{**{k: getattr(b, k) for k in b.__dataclass_fields__}, 't_y': ty})
    assert has(silkread.findings(b2, BNC), 'J2:', '"CH2 IN"')


def test_a_bnc_designator_off_its_frame_fails():
    assert has(silkread.findings(board({'J2': (61.0, 58.0, 0.0)}), BNC), 'J2:', 'designator at')


def test_a_missing_bnc_label_fails():
    assert has(silkread.findings(board(), {'J1': 'CH1 IN', 'J2': 'AWG OUT'}), 'J2:', '0 "AWG OUT" labels')


def test_the_frame_follows_the_connector_rotation():
    s = Synth()
    s.part('J1', 40.0, 20.0, box=(39.0, 12.0, 41.0, 20.0), rot=-90.0, silk=None)
    s.part('J2', 50.0, 20.0, box=(49.0, 12.0, 51.0, 20.0), rot=-90.0, silk=None)
    s.rt.append((42.0, 18.0, 1.0, 1.0, 0.15, 0.0, 0, True, 0))
    s.rt.append((52.0, 18.0, 1.0, 1.0, 0.15, 0.0, 0, True, 1))
    s.text('CH1 IN', 38.0, 15.0).text('CH2 IN', 48.0, 15.0)
    assert not [x for x in silkread.findings(s.build(), BNC) if 'frame' in x]


LABELS = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}
# Findings on 2026-11-15 under the run convention, before any board work for it: held exactly (a ratchet, not a tolerance).
OPEN = {'v2/layout/integrated/afe-v2-integrated.kicad_pcb': 182, 'kicad/afe-proto.kicad_pcb': 140}


@pytest.mark.pcbnew
@pytest.mark.parametrize('rel', sorted(OPEN))
def test_the_board_only_gets_closer_to_d30(rel):
    p = HERE / rel
    f = silkread.findings(boardio.read_board(str(p)), LABELS)
    assert len(f) <= OPEN[rel], f'{len(f)} D30 findings against {OPEN[rel]} recorded: {f[:5]}'
    assert len(f) == OPEN[rel], f'{len(f)} D30 findings, fewer than the {OPEN[rel]} recorded: lower OPEN to {len(f)}'
