"""pcbtools.silkplace on hand-built boards (no pcbnew): the placer puts a designator beside its own part, never over a pad, a
courtyard or another designator, with the margin D30 asks, and lists the part it cannot place instead of forcing it."""
import dataclasses
import types

import numpy as np

from pcbtools import silkplace
from tests.pcbtools.synth import Synth

CFG = types.SimpleNamespace(DESIGNATOR_ADVANCE=0.95, DESIGNATOR_INK_H=1.2)


def board(s):
    return dataclasses.replace(s.build(), outline=np.array([[0.0, 0.0], [60.0, 0.0], [60.0, 40.0], [0.0, 40.0]]))


def part(s, ref, x, y, hw=1.0, hh=0.5, pad=True, text_at=None):
    s.part(ref, x, y, box=(x - hw, y - hh, x + hw, y + hh), h=1.0)
    if pad:
        s.p(ref, '1', x - hw + 0.3, y, size=0.5)
        s.p(ref, '2', x + hw - 0.3, y, size=0.5)
    if text_at:
        s.rt[-1] = (*text_at, 1.0, 1.0, 0.15, 0.0, 0, True, len(s.fp) - 1)
    return s


def box_of(ref, p):
    l, w = len(ref) * CFG.DESIGNATOR_ADVANCE, CFG.DESIGNATOR_INK_H
    if p[2] == 90:
        l, w = w, l
    return (p[0] - l / 2, p[1] - w / 2, p[0] + l / 2, p[1] + w / 2)


def gap(a, c):
    return float(np.hypot(max(c[0] - a[2], a[0] - c[2], 0), max(c[1] - a[3], a[1] - c[3], 0)))


def test_a_lone_part_gets_a_place_beside_itself():
    s = part(Synth('/GND'), 'C1', 30, 20, text_at=(30, 20))                # the text sits on the part: wrong
    placed, un = silkplace.place(board(s), CFG)
    assert un == [] and 'C1' in placed
    B = box_of('C1', placed['C1'])
    assert gap(B, (29, 19.5, 31, 20.5)) < 1.0 and not (B[0] < 31 and B[2] > 29 and B[1] < 20.5 and B[3] > 19.5)


def test_the_text_keeps_clear_of_a_neighbours_courtyard_and_every_pad():
    s = part(Synth('/GND'), 'C1', 30, 20, text_at=(30, 20))
    part(s, 'C2', 32.3, 20, text_at=(32.3, 20))                             # 0.3 mm from C1's courtyard
    b = board(s)
    placed, un = silkplace.place(b, CFG)
    assert un == [], un
    cour = {'C1': (29, 19.5, 31, 20.5), 'C2': (31.3, 19.5, 33.3, 20.5)}
    for r, p in placed.items():
        B = box_of(r, p)
        other = [c for k, c in cour.items() if k != r][0]
        assert gap(B, other) - gap(B, cour[r]) >= 0.30 - 1e-9, r
        for j in range(len(b.p_fp)):
            assert gap(B, (b.p_bx0[j], b.p_by0[j], b.p_bx1[j], b.p_by1[j])) > 0, r
    assert gap(box_of('C1', placed['C1']), box_of('C2', placed['C2'])) >= silkplace.HARD_GAP - 1e-9


def test_a_part_boxed_in_is_listed_and_keeps_its_text():
    s = part(Synth('/GND'), 'C1', 30, 20, hw=1.0, hh=0.5, text_at=(30, 20))
    for k, (dx, dy) in enumerate([(2.3, 0), (-2.3, 0), (0, 1.8), (0, -1.8), (2.3, 1.8), (-2.3, 1.8), (2.3, -1.8), (-2.3, -1.8)]):
        part(s, f'X{k}', 30 + dx, 20 + dy, hw=1.0, hh=0.9 if dy else 0.5, pad=False, text_at=(0.5, 0.5))
    placed, un = silkplace.place(board(s), CFG, keep=[f'X{k}' for k in range(8)])
    assert 'C1' in un and 'C1' not in placed


def test_the_margin_is_what_rejects_a_place():
    """break the check on purpose: a margin no place can meet leaves the part unplaced, and the same board at 0.30 places it"""
    s = part(Synth('/GND'), 'C1', 30, 20, text_at=(30, 20))
    part(s, 'C2', 32.1, 20, text_at=(0.5, 0.5))                              # the courtyards are 0.1 mm apart
    b = board(s)
    placed, un = silkplace.place(b, CFG, margin=0.30, keep=['C2'])
    assert un == [] and 'C1' in placed
    B = box_of('C1', placed['C1'])
    assert gap(B, (31.1, 19.5, 33.1, 20.5)) - gap(B, (29, 19.5, 31, 20.5)) >= 0.30 - 1e-9
    placed, un = silkplace.place(b, CFG, margin=5.0, keep=['C2'])
    assert un == ['C1'] and placed == {}


def test_a_pad_in_the_best_place_is_avoided():
    s = part(Synth('/GND'), 'C1', 30, 20, text_at=(30, 20))
    free, _ = silkplace.place(board(s), CFG)
    B = box_of('C1', free['C1'])
    cx, cy = (B[0] + B[2]) / 2, (B[1] + B[3]) / 2
    s.part('P1', 5, 5, box=(4.9, 4.9, 5.1, 5.1), silk=None).p('P1', '1', cx, cy, size=0.4)
    moved, un = silkplace.place(board(s), CFG)
    assert un == [] and moved['C1'] != free['C1']
    M = box_of('C1', moved['C1'])
    assert gap(M, (cx - 0.2, cy - 0.2, cx + 0.2, cy + 0.2)) > 0


def test_two_designators_keep_apart():
    """two parts 1.3 mm apart in a column against the board's west edge, a pad bar above and below: both texts can only go on the
    east side, where each wants the height of its own part, and the second must not sit on the first"""
    s = part(Synth('/GND'), 'C1', 3, 20, text_at=(3, 20))
    part(s, 'C2', 3, 21.3, text_at=(3, 21.3))
    for k, y in enumerate((18.2, 23.1)):
        s.part(f'B{k}', 3, y, box=(2.9, y - 0.1, 3.1, y + 0.1), silk=None).p(f'B{k}', '1', 3, y, size=6.0, sy=0.5)
    placed, un = silkplace.place(board(s), CFG, keep=['B0', 'B1'])
    assert un == [] and set(placed) == {'C1', 'C2'}
    assert gap(box_of('C1', placed['C1']), box_of('C2', placed['C2'])) >= silkplace.HARD_GAP - 1e-9


def _shared_gap_board():
    """A (x 1..3) and B (x 5.6..7.6) face one 2.6 mm gap. The board's west edge shuts A's other side; pad bars shut every side of B
    but the gap and the east side beyond 0.95 mm. A label 1.2 mm wide fits the gap beside each part (0 mm from it, 1.4 mm from the
    other part: margin met), and two of them leave 0.2 mm between them"""
    s = part(Synth('/GND'), 'C1', 2, 20, text_at=(2, 20))
    part(s, 'C2', 6.6, 20, text_at=(6.6, 20))
    for k, (x, y, w, h) in enumerate([(4.5, 21.3, 9.0, 0.5), (4.5, 18.7, 9.0, 0.5), (8.2, 20.0, 0.5, 3.0)]):
        s.part(f'B{k}', x, y, box=(x - 0.05, y - 0.05, x + 0.05, y + 0.05), silk=None).p(f'B{k}', '1', x, y, size=w, sy=h)
    return board(s), ['B0', 'B1', 'B2']


def _close(placed):
    return [(a, c) for a in placed for c in placed
            if a < c and gap(box_of(a, placed[a]), box_of(c, placed[c])) < 0.3 - 1e-9]                  # 0.3: the constant itself is what the test holds, not whatever it is set to


def test_two_labels_do_not_share_one_gap(monkeypatch):
    """the margin alone does not keep them apart: only HARD_GAP does. With HARD_GAP at 0 both labels take the gap, under 0.3 mm apart
    (the case is the right one); with it, no two placed labels are closer than HARD_GAP"""
    b, keep = _shared_gap_board()
    with monkeypatch.context() as m:
        m.setattr(silkplace, 'HARD_GAP', 0.0)
        loose, un = silkplace.place(b, CFG, keep=keep)
        assert set(loose) == {'C1', 'C2'} and un == []
        assert gap(box_of('C1', loose['C1']), box_of('C2', loose['C2'])) < 0.3 - 1e-9
    placed, un = silkplace.place(b, CFG, keep=keep)
    assert placed and _close(placed) == []        # one of the two may be left for a key or a spread, and is listed
    assert set(placed) | set(un) == {'C1', 'C2'}
