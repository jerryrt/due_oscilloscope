"""pcbtools.fence on hand-built boards: ownership, the inside masks, and the two violation kinds, with the indices an
editor needs. (The equivalence with the old fence_check on the real block boards is in test_rules_equivalence.py.)"""
import numpy as np
import pytest

from pcbtools import fence, mutate as M
from synth import Synth, cfg

C = cfg(FENCES={'A': [(0, 0, 10, 10), (20, 0, 30, 10)]}, HUNDREDS={'1': 'A', '2': 'B', '5': 'B', '6': None}, OWNER_OVERRIDE={'U9': 'A'}, TOL_MM=0.001)


def board(r201=(50, 50), r201_rot=0.0, r101=(5, 5), extra=()):
    s = Synth('/X', '/GND').part('R101', *r101).part('R201', *r201, rot=r201_rot).part('U9', 60, 60).part('J601', 70, 70).part('R5', 1, 1)
    s.s('/X', 'F', 1, 1, 9, 1)                      # row 0: inside fence 0
    s.s('/X', 'F', 8, 5, 12, 5)                     # row 1: crosses the fence edge: outside
    s.s('/X', 'F', 9, 5, 21, 5)                     # row 2: endpoints in two different fences: outside
    s.s('/X', 'B', 22, 1, 28, 1)                    # row 3: inside fence 1
    s.v('/GND', 10, 10).v('/GND', 10.0001, 5)       # via 0 on the corner (closed: inside), via 1 outside
    for e in extra:
        e(s)
    return s.build()


def test_owner_of():
    assert fence.owner_of('R101', C) == 'A' and fence.owner_of('R201', C) == 'B'
    assert fence.owner_of('R5', C) is None                          # fewer than three digits: nobody's
    assert fence.owner_of('J601', C) is None                        # the edge parts: digit 6 -> None
    assert fence.owner_of('U9', C) == 'A'                           # override beats the digits
    assert fence.owner_of('MH7', C) is None


def test_inside_masks():
    ms, ma, mv = fence.inside_masks(board(), 'A', C)
    assert ms.tolist() == [True, False, False, True]
    assert mv.tolist() == [True, False] and ma.tolist() == []


def test_identical_boards_are_clean():
    r = fence.check_fence(board(), board(), 'A', C)
    assert r.ok and r.violations == [] and r.foreign_moved == []
    assert fence.violations(board(), board(), 'A', C) == []


def test_own_part_may_move_foreign_part_may_not():
    assert fence.check_fence(board(), board(r101=(6, 6)), 'A', C).ok
    r = fence.check_fence(board(), board(r201=(50.01, 50)), 'A', C)
    assert r.violations == ['R201 (belongs to B): moved (50.0, 50.0, 0.0, 0) -> (50.01, 50.0, 0.0, 0)'] and r.foreign_moved == ['R201']
    assert fence.check_fence(board(), board(r201=(50.0005, 50)), 'A', C).ok                        # inside TOL_MM
    r = fence.check_fence(board(), board(r201_rot=90.0), 'A', C)
    assert r.foreign_moved == ['R201'] and '90.0' in r.violations[0]


def test_part_missing_or_added():
    b = board()
    s = Synth('/X', '/GND').part('R101', 5, 5).part('U9', 60, 60).part('J601', 70, 70).part('R5', 1, 1).part('R301', 3, 3)
    r = fence.check_fence(b, s.build(), 'A', C)
    assert 'R201: part missing from the block board' in r.violations and 'R301: part not in the base' in r.violations
    assert set(r.foreign_moved) == {'R201', 'R301'}


def test_copper_outside_the_fence_is_compared_inside_is_free():
    inside_changed = lambda s: s.s('/X', 'F', 2, 2, 3, 2)              # a new track wholly inside fence 0
    assert fence.check_fence(board(), board(extra=[inside_changed]), 'A', C).ok
    outside_added = lambda s: s.s('/X', 'F', 40, 40, 41, 40)
    r = fence.check_fence(board(), board(extra=[outside_added]), 'A', C)
    assert len(r.violations) == 1 and r.violations[0].startswith('copper outside the A fence added or changed: (\'trk\', \'/X\', 0, (40.0, 40.0), (41.0, 40.0), 0.2)')
    assert r.outside_changed_idx['blk']['s_idx'].tolist() == [4] and r.outside_changed_idx['base']['s_idx'].tolist() == []
    # remove the crossing track (row 1) from the block board: reported as removed, with the base index
    b = board()
    keep = np.ones(len(b.s_idx), bool); keep[1] = False
    blk = b.replace(**{n: getattr(b, n)[keep] for n in ('s_idx', 's_x0', 's_y0', 's_x1', 's_y1', 's_w', 's_layer', 's_net')})
    r = fence.check_fence(b, blk, 'A', C)
    assert len(r.violations) == 1 and 'removed or changed' in r.violations[0]
    assert r.outside_changed_idx['base']['s_idx'].tolist() == [1]


def test_via_moved_outside_and_layer_code():
    b = board()
    blk = M.add_via(b, '/GND', (40, 40))
    r = fence.check_fence(b, blk, 'A', C)
    assert r.violations[0].startswith("copper outside the A fence added or changed: ('via', '/GND', 40.0, 40.0, 0.6, 0.3)")
    assert r.outside_changed_idx['blk']['v_idx'].tolist() == [int(blk.v_idx[-1])]
    # a bottom track outside the fences is keyed with KiCad's B.Cu number 2 (the old tool printed int(GetLayer()))
    blk = M.add_segment(b, '/X', 'B', (40, 40), (41, 40))
    assert "('trk', '/X', 2, (40.0, 40.0), (41.0, 40.0), 0.2)" in fence.check_fence(b, blk, 'A', C).violations[0]


def test_duplicate_items_differ():
    b = board()
    blk = M.add_segment(b, '/X', 'F', (8, 5), (12, 5))                  # an exact copy of row 1 (outside the fence)
    r = fence.check_fence(b, blk, 'A', C)
    assert r.violations == ['copper outside the A fence: duplicate items differ (3 vs 4)']
