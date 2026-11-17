"""A broken-once arm of gate 3 records the PIECE each DRC pair names, not the item KiCad chose to stand for it.

KiCad picks, from run to run, which of several equal candidates represents an unconnected piece (a pad or a track; this pad or that), so the item lines of
proof5v.json differed between two regenerations of unchanged code while the counts and verdicts did not. pair_pads records the pads of the lost piece each pair
names; two reports that name different items of the same pieces give the same record. Broken on purpose below (a record that follows the item, a piece that
is not lost)."""
from pcbtools.gate3 import engine as E

PADS = {'U401.8': 0, 'U401.3': 1, 'C401.1': 1, 'TP402.1': 1, 'U401.12': 2, 'R9.1': 2}
G = {'pad_comp': PADS, 'nodes': [], 'comp': []}


def pad(ref, pin):
    return {'description': f'Pad {pin} [/+5V_F] of {ref} on F.Cu'}


def report(*pairs):
    return {'unconnected_items': [{'items': list(p)} for p in pairs]}


def test_the_record_is_the_lost_pieces_pads_whichever_item_stands_for_them():
    a = report((pad('U401', '8'), pad('C401', '1')), (pad('U401', '8'), pad('U401', '12')))
    b = report((pad('U401', '8'), pad('TP402', '1')), (pad('R9', '1'), pad('U401', '8')))          # other items of the same two pieces, in another order
    want = [['C401.1', 'TP402.1', 'U401.3'], ['R9.1', 'U401.12']]
    assert E.pair_pads(G, a, 'U401.8', (0, 0)) == want == E.pair_pads(G, b, 'U401.8', (0, 0))
    twice = report((pad('U401', '8'), pad('C401', '1')), (pad('U401', '8'), pad('TP402', '1')))                 # two pairs naming one piece: one record
    assert E.pair_pads(G, twice, 'U401.8', (0, 0)) == [['C401.1', 'TP402.1', 'U401.3']]
    assert E.straddles(G, a, 'U401.8', ['U401.3', 'U401.12'], (0, 0)) and E.straddles(G, b, 'U401.8', ['U401.3', 'U401.12'], (0, 0))


def test_a_pair_that_is_not_one_lost_one_kept_piece_records_nothing_and_does_not_straddle():
    for bad in (report((pad('C401', '1'), pad('TP402', '1'))),                                   # both on one lost piece
                report((pad('U401', '8'), {'description': 'Track [/+5V_F] on F.Cu, length 1.0 mm'})),   # an item on no piece (no position)
                {'unconnected_items': [{'items': [pad('U401', '8')]}]}):                         # not a pair
        assert E.pair_pads(G, bad, 'U401.8', (0, 0)) == []
        assert not E.straddles(G, bad, 'U401.8', ['U401.3'], (0, 0))
    assert E.straddles(G, {}, 'U401.8', [], (0, 0))                                              # no pair and nothing lost: the cut changed nothing
    assert not E.straddles(G, report((pad('U401', '8'), pad('C401', '1'))), 'U401.8', ['U401.3', 'U401.12'], (0, 0))   # a predicted piece no pair names
