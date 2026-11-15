"""pcbtools.silkread (docs/afe.md D30) on hand-built boards with known answers, each property broken once on purpose, and on
the two real boards, where D30 is not met yet: their finding counts are held exactly, so a change that adds one fails and a
change that removes some must record the new count."""
import pathlib

import pytest

from pcbtools import boardio, silkread
from pcbtools.silkread import Key

from synth import Synth

HERE = pathlib.Path(__file__).resolve().parents[2]
BNC = {'J1': 'CH1 IN', 'J2': 'CH2 IN'}


def board(**over):
    """parts A and B labelled beside themselves; C1-C3 a cluster in a row with its designators in a key; two BNCs.
    `over` replaces a part's designator position ({ref: (x, y, ang)}) or hides it ({ref: None})."""
    s = Synth()
    lab = {'A': (10.0, 12.0, 0.0), 'B': (20.0, 12.0, 0.0), 'J1': (40.0, 18.0, 0.0), 'J2': (40.0, 38.0, 0.0)}
    lab.update({k: v for k, v in over.items() if k in lab})
    for r, x in (('A', 10.0), ('B', 20.0)):
        s.part(r, x, 10.0, box=(x - 1, 9.5, x + 1, 10.5), silk=None)
    for r, x in (('C1', 30.0), ('C2', 32.0), ('C3', 34.0)):
        s.part(r, x, 10.0, box=(x - 0.8, 9.6, x + 0.8, 10.4), silk=None)
    for r, y in (('J1', 20.0), ('J2', 40.0)):
        s.part(r, 40.0, y, box=(38.0, y - 1.0, 46.0, y + 1.0), silk=None)
    refs = [f[0] for f in s.fp]
    for r, (x, y, a) in lab.items():
        if over.get(r, 0) is None:
            continue
        s.rt.append((x, y, 1.0, 1.0, 0.15, a, 0, True, refs.index(r)))
    for r in ('C1', 'C2', 'C3'):
        if r in over and over[r] is not None:
            x, y, a = over[r]
            s.rt.append((x, y, 1.0, 1.0, 0.15, a, 0, True, refs.index(r)))
    s.text('CH1 IN', 43.0, 22.0).text('CH2 IN', 43.0, 42.0)
    return s.build()


KEY = Key(box=(28.0, 12.0, 36.0, 14.0), texts=(('C1', 29.5, 13.0), ('C2', 32.0, 13.0), ('C3', 34.5, 13.0)))


def test_the_good_board_has_no_findings():
    assert silkread.findings(board(), [KEY], BNC) == []


def test_a_designator_nearer_another_part_fails():
    f = silkread.findings(board(A=(18.0, 12.0, 0.0)), [KEY], BNC)       # A's text moved next to B
    assert any(x.startswith('A:') and 'margin under' in x for x in f), f


def test_a_tie_fails():
    f = silkread.findings(board(A=(15.0, 12.0, 0.0)), [KEY], BNC)       # halfway between A and B
    assert any(x.startswith('A:') and 'margin under' in x for x in f), f


def test_a_designator_on_another_courtyard_fails():
    f = silkread.findings(board(A=(20.0, 10.0, 0.0)), [KEY], BNC)
    assert any(x.startswith('A:') and 'courtyard of B' in x for x in f), f


def test_a_slanted_designator_fails():
    f = silkread.findings(board(A=(10.0, 12.0, 45.0)), [KEY], BNC)
    assert any(x.startswith('A:') and '45 degrees' in x for x in f), f


def test_a_hidden_designator_in_no_key_fails():
    f = silkread.findings(board(), [], BNC)
    assert {x for x in f if 'in no key' in x} == {'C1: no designator and in no key', 'C2: no designator and in no key',
                                                   'C3: no designator and in no key'}, f


def test_a_part_named_twice_fails():
    second = Key(box=(28.0, 15.0, 36.0, 17.0), texts=(('C1', 29.5, 16.0), ('C2', 32.0, 16.0)))
    f = silkread.findings(board(), [KEY, second], BNC)
    assert any('C1: named 2 times' in x for x in f), f


def test_a_designator_shown_and_keyed_fails():
    f = silkread.findings(board(C1=(30.0, 8.0, 0.0)), [KEY], BNC)
    assert any(x.startswith('C1: has its own designator and a place in key') for x in f), f


def test_a_key_out_of_order_fails():
    swapped = Key(KEY.box, (('C2', 29.5, 13.0), ('C1', 32.0, 13.0), ('C3', 34.5, 13.0)))
    f = silkread.findings(board(), [swapped], BNC)
    assert any('C2 and C1 are out of order along x' in x or 'C1 and C2 are out of order along x' in x for x in f), f


def test_a_row_does_not_need_an_order_along_y():
    wobble = Key(KEY.box, (('C1', 29.5, 12.9), ('C2', 32.0, 13.1), ('C3', 34.5, 13.0)))
    assert silkread.findings(board(), [wobble], BNC) == []


def test_a_key_on_a_courtyard_fails():
    over = Key((28.0, 9.0, 36.0, 14.0), KEY.texts)
    f = silkread.findings(board(), [over], BNC)
    assert any('lies on the courtyard of C1' in x for x in f), f


def test_a_key_far_from_its_parts_fails():
    far = Key((28.0, 20.0, 36.0, 22.0), tuple((t, x, 21.0) for t, x, _ in KEY.texts))
    f = silkread.findings(board(), [far], BNC)
    assert any('mm from its parts' in x for x in f), f


def test_a_rectangle_with_a_word_is_not_a_key():
    outline = Key((0.0, 0.0, 60.0, 60.0), (('CH1', 5.0, 5.0), ('A', 10.0, 12.0)))
    assert silkread.findings(board(), [KEY, outline], BNC) == []


def test_a_bnc_label_off_its_frame_fails():
    b = board()
    s = list(b.t_y)
    s[1] += 0.1                                                      # CH2 IN, 0.1 mm off J1's offset
    f = silkread.findings(boardio.BoardArrays(**{**{k: getattr(b, k) for k in b.__dataclass_fields__}, 't_y': s}), [KEY], BNC)
    assert any(x.startswith('J2: "CH2 IN"') for x in f), f


def test_a_bnc_designator_off_its_frame_fails():
    f = silkread.findings(board(J2=(41.0, 38.0, 0.0)), [KEY], BNC)
    assert any(x.startswith('J2: designator') for x in f), f


def test_a_missing_bnc_label_fails():
    f = silkread.findings(board(), [KEY], {'J1': 'CH1 IN', 'J2': 'AWG OUT'})
    assert any('0 "AWG OUT" labels' in x for x in f), f


def test_the_frame_follows_the_connector_rotation():
    """two BNCs at -90 degrees, the second's labels where the first's are in its own frame: no finding"""
    s = Synth()
    s.part('J1', 40.0, 20.0, box=(39.0, 12.0, 41.0, 20.0), rot=-90.0, silk=None)
    s.part('J2', 50.0, 20.0, box=(49.0, 12.0, 51.0, 20.0), rot=-90.0, silk=None)
    s.rt.append((42.0, 18.0, 1.0, 1.0, 0.15, 0.0, 0, True, 0))
    s.rt.append((52.0, 18.0, 1.0, 1.0, 0.15, 0.0, 0, True, 1))
    s.text('CH1 IN', 38.0, 15.0).text('CH2 IN', 48.0, 15.0)
    f = silkread.findings(s.build(), [], BNC)
    assert not [x for x in f if 'frame' in x], f


def test_read_keys_takes_unfilled_top_rectangles_with_their_texts():
    x0, y0 = boardio.from_due(28.0, 12.0)
    x1, y1 = boardio.from_due(36.0, 14.0)
    tx, ty = boardio.from_due(32.0, 13.0)
    rect = lambda fill: (f'\t(gr_rect\n\t\t(start {float(x0)} {float(y0)})\n\t\t(end {float(x1)} {float(y1)})\n\t\t(fill {fill})\n'
                         f'\t\t(layer "F.SilkS")\n\t)\n')
    txt = f'(kicad_pcb\n{rect("no")}{rect("yes")}\t(gr_text "C2"\n\t\t(at {float(tx)} {float(ty)} 0)\n\t\t(layer "F.SilkS")\n\t)\n)\n'
    keys = silkread.read_keys(txt)
    assert len(keys) == 1 and [t[0] for t in keys[0].texts] == ['C2'], keys
    assert keys[0].box == pytest.approx((28.0, 12.0, 36.0, 14.0))


BLOCKS = {'CH1': '1', 'CH2': '2', 'AWG': '3', 'POWER': '4', 'REF / CAL': '5'}


def far_cluster():
    """C201 and C202 in a row with hidden designators, and nothing else"""
    s = Synth()
    for r, x in (('C201', 30.0), ('C202', 32.0)):
        s.part(r, x, 10.0, box=(x - 0.8, 9.6, x + 0.8, 10.4), silk=None)
    return s.build()


def legend(head, refs=('C201', 'C202')):
    """a key 20 mm from the cluster, with an optional heading text"""
    t = tuple((r, 2.0 + 3.0 * n, 31.0) for n, r in enumerate(refs)) + (((head, 4.0, 33.0),) if head else ())
    return Key((0.0, 30.0, 8.0, 34.0), t)


def test_a_headed_key_may_sit_in_the_legend_area():
    assert silkread.findings(far_cluster(), [legend('CH2')], {}, blocks=BLOCKS) == []


@pytest.mark.parametrize('head,refs', [('POWER', ('C401', 'C402')), ('REF / CAL', ('R501', 'R502'))])
def test_the_power_and_ref_cal_headings_head_their_blocks_keys(head, refs):
    s = Synth()
    for r, x in zip(refs, (30.0, 32.0)):
        s.part(r, x, 10.0, box=(x - 0.8, 9.6, x + 0.8, 10.4), silk=None)
    b = s.build()
    assert silkread.findings(b, [legend(head, refs=refs)], {}, blocks=BLOCKS) == []
    wrong = 'CH2' if head == 'POWER' else 'POWER'
    f = silkread.findings(b, [legend(wrong, refs=refs)], {}, blocks=BLOCKS)
    assert any(f'{refs[0]} is not in block {wrong}' in x for x in f), f


def test_an_unheaded_key_in_the_legend_area_is_too_far():
    f = silkread.findings(far_cluster(), [legend(None)], {}, blocks=BLOCKS)
    assert any('mm from its parts' in x for x in f), f


def test_a_key_headed_with_the_wrong_block_fails():
    f = silkread.findings(far_cluster(), [legend('CH1')], {}, blocks=BLOCKS)
    assert any('C201 is not in block CH1' in x for x in f), f


def test_a_heading_that_is_not_a_block_makes_no_key():
    f = silkread.findings(far_cluster(), [legend('NOTE')], {}, blocks=BLOCKS)
    assert any('C201: no designator and in no key' in x for x in f), f


def test_a_headed_key_keeps_its_order():
    f = silkread.findings(far_cluster(), [legend('CH2', refs=('C202', 'C201'))], {}, blocks=BLOCKS)
    assert any('out of order along x' in x for x in f), f


LABELS = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}
# Findings on 2026-11-14, before any D30 work. A ratchet, not a tolerance: a change may lower a count and must lower the
# number here with it; a board at 0 changes its row to 0 and stays there. (A strict xfail would say the same, but the pcbnew
# guard counts only passes.)
OPEN = {'v2/layout/integrated/afe-v2-integrated.kicad_pcb': 48, 'kicad/afe-proto.kicad_pcb': 79}


@pytest.mark.pcbnew
@pytest.mark.parametrize('rel', sorted(OPEN))
def test_the_board_only_gets_closer_to_d30(rel):
    p = HERE / rel
    f = silkread.findings(boardio.read_board(str(p)), silkread.read_keys(p.read_text()), LABELS, blocks=BLOCKS)
    assert len(f) <= OPEN[rel], f'{len(f)} D30 findings against {OPEN[rel]} recorded: {f[:5]}'
    assert len(f) == OPEN[rel], f'{len(f)} D30 findings, fewer than the {OPEN[rel]} recorded: lower OPEN to {len(f)}'
