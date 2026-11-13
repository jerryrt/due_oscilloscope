"""engine.straddles: the exact condition under which a broken-once arm's DRC report agrees with the graph's prediction.

A cut splits the net into the kept piece (the source's) and the lost pieces. KiCad reports unconnected PAIRS and picks which item stands for
a piece (a pad here, a track there, differently from one run to the next), so the condition is on pieces and not on the items it names:
each pair has one item on a lost piece and one on the kept piece, and the lost pieces the pairs name are exactly the predicted ones.
Board-free: a hand-made graph (nodes, components, pad components) and hand-made DRC reports in KiCad's own JSON shape.
The three mutants the ruling asks for (both items kept, both lost, a predicted piece no pair names) must each fail."""
import numpy as np

from pcbtools.gate3 import engine as E

ORIGIN = (50.0, 150.0)


def _graph():
    # kept piece 0: pad R1.1 (the source) and a track along y=10; lost piece 1: pads U1.1, U1.2 and a track along y=20;
    # lost piece 2: pad C1.1 and a track along y=30 (a second place the net falls apart)
    nodes = [dict(kind='pad', label='R1.1', detail=()), dict(kind='track', detail=(0, 10, 10, 10, 0.3)),
             dict(kind='pad', label='U1.1', detail=()), dict(kind='pad', label='U1.2', detail=()), dict(kind='track', detail=(0, 20, 10, 20, 0.3)),
             dict(kind='pad', label='C1.1', detail=()), dict(kind='track', detail=(0, 30, 10, 30, 0.3))]
    comp = np.array([0, 0, 1, 1, 1, 2, 2])
    return dict(nodes=nodes, comp=comp, pad_comp={'R1.1': 0, 'U1.1': 1, 'U1.2': 1, 'C1.1': 2})


def _pad(label):
    ref, pin = label.split('.')
    return dict(description=f'Pad {pin} [/N] of {ref} on F.Cu', pos=dict(x=0, y=0))


def _track(y):                                        # a track item at Due (5, y), in KiCad's coordinates
    return dict(description='Track [/N] on F.Cu, length 10.0000 mm', pos=dict(x=5 + ORIGIN[0], y=ORIGIN[1] - y))


def _rep(*pairs):
    return dict(unconnected_items=[dict(items=list(p)) for p in pairs])


KEPT_TRACK, LOST_TRACK, LOST2_TRACK = _track(10), _track(20), _track(30)


def ok(rep, pred):
    return E.straddles(_graph(), rep, 'R1.1', pred, ORIGIN)


def test_a_pair_across_the_cut_agrees_whichever_item_stands_for_each_piece():
    for kept, lost in ((_pad('R1.1'), _pad('U1.1')), (KEPT_TRACK, _pad('U1.2')), (_pad('R1.1'), LOST_TRACK), (KEPT_TRACK, LOST_TRACK)):
        assert ok(_rep((kept, lost)), ['U1.1', 'U1.2'])
        assert ok(_rep((lost, kept)), ['U1.1', 'U1.2'])               # and in either order


def test_two_lost_pieces_need_a_pair_each_and_two_pairs_agree():
    rep = _rep((_pad('R1.1'), _pad('U1.1')), (KEPT_TRACK, LOST2_TRACK))
    assert ok(rep, ['U1.1', 'U1.2', 'C1.1'])


def test_mutant_both_items_from_the_kept_side_is_no():
    assert not ok(_rep((_pad('R1.1'), KEPT_TRACK)), ['U1.1', 'U1.2'])


def test_mutant_both_items_from_the_lost_side_is_no():
    assert not ok(_rep((_pad('U1.1'), LOST_TRACK)), ['U1.1', 'U1.2'])
    assert not ok(_rep((_pad('U1.1'), _pad('C1.1'))), ['U1.1', 'U1.2', 'C1.1'])      # two different lost pieces are not a straddle either


def test_mutant_a_predicted_piece_no_pair_names_is_no():
    assert not ok(_rep((_pad('R1.1'), _pad('U1.1'))), ['U1.1', 'U1.2', 'C1.1'])
    assert not ok(_rep(), ['U1.1', 'U1.2'])                          # nothing reported at all


def test_a_piece_nobody_predicted_is_no():
    assert not ok(_rep((_pad('R1.1'), _pad('U1.1')), (_pad('R1.1'), _pad('C1.1'))), ['U1.1', 'U1.2'])


def test_an_item_on_no_piece_is_no():
    away = dict(description='Track [/N] on F.Cu, length 1.0 mm', pos=dict(x=5 + ORIGIN[0], y=ORIGIN[1] - 15))
    assert not ok(_rep((_pad('R1.1'), away)), ['U1.1', 'U1.2'])
    assert not ok(_rep((_pad('R1.1'), _pad('X9.9'))), ['U1.1', 'U1.2'])  # a pad the graph does not have
    assert not ok(_rep((_pad('R1.1'),)), ['U1.1', 'U1.2'])           # a pair with one item
