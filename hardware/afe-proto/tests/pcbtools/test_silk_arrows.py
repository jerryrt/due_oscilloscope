"""LR-11 on arrows: v2's configuration carries none and its board silk forms no arrowhead (a V of two short lines, or a triangle).
The finder is checked on synthetic heads, on a dashed outline it must not flag, and on the first layout's four arrows."""
import pathlib
import subprocess

import pytest

from pcbtools import silkarrows as S
from pcbtools.boards import v2, v2_layout

BOARD = pathlib.Path(__file__).resolve().parents[2] / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb'


def line(a, b, c, d, layer='F.SilkS'):
    return f'\n\t(gr_line\n\t\t(start {a} {b})\n\t\t(end {c} {d})\n\t\t(stroke\n\t\t\t(width 0.2)\n\t\t\t(type default)\n\t\t)\n\t\t(layer "{layer}")\n\t)'


SHAFT_AND_HEAD = line(70.5, 145.8, 74, 145.8) + line(74, 145.8, 73.2, 145.4) + line(74, 145.8, 73.2, 146.2)
TRIANGLE = line(0, 0, 1, 0) + line(1, 0, 0.5, 0.8) + line(0.5, 0.8, 0, 0)
DASHES = ''.join(line(x, 0, x + 0.6, 0) for x in (0, 1.8, 3.6)) + line(0, 0, 0, 0.6) + line(0, 5, 0, 5.6)    # runs and a right-angle corner


def test_the_config_has_no_arrows():
    assert v2_layout.ARROWS == [] and v2.ARROWS == []


@pytest.mark.parametrize('txt', [SHAFT_AND_HEAD, TRIANGLE, SHAFT_AND_HEAD.replace('F.SilkS', 'B.SilkS')])
def test_a_synthetic_arrowhead_is_found(txt):
    assert S.arrowheads(S.silk_segments(txt))


def test_dashes_and_corners_are_not_arrowheads():
    assert S.arrowheads(S.silk_segments(DASHES)) == []


def test_a_line_on_another_layer_is_not_silk():
    assert S.silk_segments(SHAFT_AND_HEAD.replace('F.SilkS', 'User.1')) == []


def test_the_board_silk_forms_no_arrowhead():
    segs = S.silk_segments(BOARD.read_text())
    assert len(segs) > 20                                   # the outlines are what it looked at
    assert S.arrowheads(segs) == []


def test_the_first_layouts_four_arrows_are_found():
    """the four arrows the first layout had (shaft 3.5-4.5 mm, head 0.8 x 0.4 mm), from its board file"""
    def arrow(x0, y0, x1, y1):
        d = 1 if x1 > x0 else -1
        return line(x0, y0, x1, y1) + line(x1, y1, x1 - 0.8 * d, y1 - 0.4) + line(x1, y1, x1 - 0.8 * d, y1 + 0.4)
    t = arrow(70.5, 145.8, 74, 145.8) + arrow(126, 106.8, 121.5, 106.8) + arrow(142, 102.7, 138, 102.7) + arrow(138, 130.05, 142, 130.05)
    assert [(h[0], h[1]) for h in S.arrowheads(S.silk_segments(t))] == [(74.0, 145.8), (121.5, 106.8), (138.0, 102.7), (142.0, 130.05)]
