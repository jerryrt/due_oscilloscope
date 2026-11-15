"""pcbtools.silkapply: a placement written into a board text as a splice. Pure text; the real board's placement is held by the D30 ratchet in
test_silkread.py. Broken once on purpose, as the suite requires."""
import pathlib
import re

import pytest

from pcbtools import silkapply as A

BOARD = pathlib.Path(__file__).resolve().parents[2] / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb'


def field(text, ref):
    s, e = A._span(text, ref)
    fp = re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', text[s:e])
    m = re.search(r'\(property "Reference" "%s"\n\t\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)\n\t\t\t\(layer "([^"]*)"' % ref, text[s:e])
    return tuple(float(v) for v in fp.groups(default='0')), tuple(float(v) for v in m.groups()[:3] if v is not None), m.group(4)


def board_pos(text, ref):
    """the field's board position (Due mm) and angle as written, from the footprint's own frame"""
    (fx, fy, fa), (lx, ly, *rest), _ = field(text, ref)
    ox, oy = A._rot(fa, lx, ly)
    return round(fx + ox - 50.0, 3), round(150.0 - (fy + oy), 3), (rest[0] if rest else 0.0)


def test_a_placed_designator_reads_back_where_it_was_put_and_a_second_pass_moves_nothing():
    text = BOARD.read_text()
    placed = {'R309': (86.0, 20.0, 90), 'C104': (88.0, 30.0, 0), 'R308': (80.0, 31.0, 90)}     # R309 and R308 are on footprints turned by 90 degrees
    new, changed = A.apply_moves(text, None, placed)
    assert sorted(changed) == sorted(placed)
    for r, (x, y, a) in placed.items():
        assert board_pos(new, r) == (x, y, float(a)), r
    again, changed2 = A.apply_moves(new, None, placed)
    assert again == new and changed2 == []
    assert sum(1 for a, b in zip(text.splitlines(), new.splitlines()) if a != b) <= 2 * len(placed)       # only the fields' (at ...) lines changed


def test_a_part_whose_designator_is_off_the_silk_is_not_moved():
    text = BOARD.read_text()
    assert field(text, 'R203')[2] == 'F.Fab'                                  # a member of CH2's labelled run: its designator is off the silk
    new, changed = A.apply_moves(text, None, {'R203': (86.0, 20.0, 90)})
    assert changed == [] and new == text


def test_broken_once_a_wrong_frame_is_caught_by_the_read_back():
    """a splice that forgot the footprint's turn would put R308 (a turned part) elsewhere: the read-back test above must fail for it"""
    text = BOARD.read_text()
    real = A._rot
    try:
        A._rot = lambda a, x, y: real(0.0, x, y)
        new, _ = A.apply_moves(text, None, {'R308': (80.0, 31.0, 90)})
        with pytest.raises(AssertionError):
            A._rot = real
            assert board_pos(new, 'R308') == (80.0, 31.0, 90.0)
    finally:
        A._rot = real
