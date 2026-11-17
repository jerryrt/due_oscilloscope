"""rules.blocks and the outlines module on boards built here from numbers; each property broken once on purpose by mutate_kit.py."""
import pytest

from arrays import Arr
from pcbkit import outlines, rules
from pcbkit.config import ConfigError

OUT = {'A': [(0, 0, 10, 10)], 'B': [(20, 0, 30, 10)]}
BLK = {'R1': 'A', 'R2': 'A', 'R3': 'B', 'R4': 'B'}


def board(**pos):
    a = Arr()
    for ref, (x, y) in dict(R1=(2, 2), R2=(5, 5), R3=(22, 2), R4=(25, 5)).items():
        a.part(ref, *pos.get(ref, (x, y)))
    return a


def run(a, **over):
    return rules.blocks(a.build(), dict(BLOCK=BLK, OUTLINE=OUT, **over))


def test_every_part_in_its_blocks_rectangle_passes():
    r = run(board())
    assert r.ok and r.detail == '2 outlines hold exactly their parts' and r.figures['outlines'] == 2.0


def test_a_part_outside_its_rectangle_is_lacking_and_a_part_inside_the_wrong_one_is_extra():
    r = run(board(R2=(15, 5)))                                   # R2 belongs to A and sits between the rectangles
    assert not r.ok and r.detail == "A: outline holds [] extra, lacks ['R2']"
    r = run(board(R3=(5, 8)))                                    # R3 (block B) inside A's rectangle
    assert not r.ok and "A: outline holds ['R3'] extra, lacks []" in r.detail and "B: outline holds [] extra, lacks ['R3']" in r.detail


def test_the_rectangle_is_closed_and_a_part_is_judged_by_its_origin():
    assert run(board(R1=(0.0, 0.0))).ok and run(board(R1=(10.0, 10.0))).ok
    assert not run(board(R1=(10.01, 5))).ok


def test_a_named_stray_may_sit_outside_its_own_rectangle_but_never_inside_another():
    assert run(board(R2=(15, 5)), OUTLINE_STRAYS=['R2']).ok
    assert run(board(), OUTLINE_STRAYS=['R2']).ok                 # a stray that happens to sit inside its own rectangle is no extra part there
    r = run(board(R2=(25, 8)), OUTLINE_STRAYS=['R2'])             # a stray inside B's rectangle is still extra there
    assert not r.ok and "B: outline holds ['R2'] extra" in r.detail
    assert not run(board(R2=(15, 5)), OUTLINE_STRAYS=['R1']).ok


def test_the_edge_block_is_in_no_outline_unless_overridden():
    blk = {**BLK, 'J1': 'EDGE'}
    a = board().part('J1', 5, 5)
    assert rules.blocks(a.build(), dict(BLOCK=blk, OUTLINE=OUT, EDGE_BLOCK='EDGE')).ok                # J1 is inside A and not counted
    r = rules.blocks(a.build(), dict(BLOCK=blk, OUTLINE=OUT))
    assert not r.ok and "A: outline holds ['J1'] extra" in r.detail                                    # without the edge block it is a stray part
    r = rules.blocks(a.build(), dict(BLOCK=blk, OUTLINE=OUT, EDGE_BLOCK='EDGE', BLOCK_OVERRIDE=['J1']))
    assert not r.ok and "J1" in r.detail


def test_an_edge_block_with_a_rectangle_of_its_own_holds_none_of_its_parts():
    blk = {**BLK, 'J1': 'EDGE'}
    out = {**OUT, 'EDGE': [(40, 0, 50, 10)]}
    a = board().part('J1', 45, 5)
    assert rules.blocks(a.build(), dict(BLOCK=blk, OUTLINE=out, EDGE_BLOCK='EDGE')).ok          # its parts belong to no outline, not even its own
    r = rules.blocks(a.build(), dict(BLOCK=blk, OUTLINE=out, EDGE_BLOCK='EDGE', BLOCK_OVERRIDE=['J1']))
    assert not r.ok and "EDGE: outline holds ['J1'] extra" in r.detail       # an overridden part is judged, and the edge block still wants none


def test_a_shared_part_is_held_to_its_home_outline_within_the_margin_and_counted_in_no_other():
    blk = {**BLK, 'U1': 'A'}
    a = board().part('U1', 10.2, 5)                               # straddles the right edge of A
    assert not rules.blocks(a.build(), dict(BLOCK=blk, OUTLINE=OUT)).ok
    assert rules.blocks(a.build(), dict(BLOCK=blk, OUTLINE=OUT, SHARED_PARTS={'U1': 'A'}, SHARED_MARGIN=0.25)).ok
    assert not rules.blocks(a.build(), dict(BLOCK=blk, OUTLINE=OUT, SHARED_PARTS={'U1': 'A'}, SHARED_MARGIN=0.1)).ok


def test_block_of_parts_uses_the_configured_block_else_the_outline_holding_the_origin():
    a = board().part('X1', 25, 5).part('X2', 15, 5)
    got = rules.block_of_parts(a.build(), dict(BLOCK=BLK, OUTLINE=OUT))
    assert got == ['A', 'A', 'B', 'B', 'B', None]
    assert outlines.block_of_parts(a.build(), {'R1': 'Z'}, OUT)[0] == 'Z'


def test_project_names_raise_naming_the_key_and_tunables_default():
    a = board().build()
    for k in ('BLOCK', 'OUTLINE'):
        with pytest.raises(ConfigError, match=k):
            rules.blocks(a, {kk: v for kk, v in dict(BLOCK=BLK, OUTLINE=OUT).items() if kk != k})
    rep = []
    rules.blocks(a, dict(BLOCK=BLK, OUTLINE=OUT, SHARED_MARGIN=0.3), rep)
    got = {k: (v, s) for k, v, s in rep}
    assert got['SHARED_MARGIN'] == (0.3, 'project') and got['OUTLINE_STRAYS'] == ((), 'default') and got['EDGE_BLOCK'] == (None, 'default')
