"""pcbkit.geom's copper shapes (were pcbtools.shapes): edge-to-edge gaps of tracks and pads, against distances worked out by hand."""
import numpy as np
import pytest

from pcbkit import board as B
from pcbkit import geom


def pads(shape, sx, sy, rot=0.0, x=0.0, y=0.0):
    return B.BoardArrays.from_arrays(
        nets=('', 'N'), fp_idx=[0], fp_ref=['U1'], fp_x=[x], fp_y=[y], fp_rot=[0], fp_side=[0],
        fp_cx0=[x - 2], fp_cy0=[y - 2], fp_cx1=[x + 2], fp_cy1=[y + 2], fp_kind=['K'],
        p_fp=[0], p_pin=['1'], p_x=[x], p_y=[y], p_bx0=[x - sx / 2], p_by0=[y - sy / 2], p_bx1=[x + sx / 2], p_by1=[y + sy / 2],
        p_net=[1], p_smd=[1], p_rot=[rot], p_shape=[shape], p_sx=[sx], p_sy=[sy], p_layer_mask=[1])


def tracks(*segs, w=0.2):
    s = np.array(segs, float)
    return B.BoardArrays.from_arrays(nets=('', 'N'), s_idx=list(range(len(s))), s_x0=s[:, 0], s_y0=s[:, 1], s_x1=s[:, 2], s_y1=s[:, 3],
                                     s_w=[w] * len(s), s_layer=[0] * len(s), s_net=[1] * len(s))


def test_track_gap_is_edge_to_edge():
    cu = geom.track_copper(tracks((0, 0, 4, 0)), [0])                       # half width 0.1
    assert cu.gap_to_segments([[0, 1.0, 4, 1.0]]) == pytest.approx([0.9])
    assert cu.gap_to_segments([[2, -1.0, 2, 1.0]]) == pytest.approx([0.0])         # crossing
    assert np.isinf(cu.gap_to_segments(np.zeros((0, 4)))).all()


def test_round_pad_is_a_disc_and_rect_pad_is_its_rectangle():
    disc = geom.pad_copper(pads(0, 1.0, 1.0), [0])                          # radius 0.5
    assert disc.gap_to_segments([[2, -1, 2, 1]]) == pytest.approx([1.5])
    rect = geom.pad_copper(pads(1, 2.0, 1.0), [0])                          # x -1..1, y -0.5..0.5
    assert rect.gap_to_segments([[2, -1, 2, 1]]) == pytest.approx([1.0])
    rot = geom.pad_copper(pads(1, 2.0, 1.0, rot=90.0), [0])                 # now x -0.5..0.5, y -1..1
    assert rot.gap_to_segments([[2, -2, 2, 2]]) == pytest.approx([1.5])
    oval = geom.pad_copper(pads(2, 3.0, 1.0), [0])                          # a capsule: axis -1..1, radius 0.5
    assert oval.gap_to_segments([[3, -1, 3, 1]]) == pytest.approx([1.5])


def test_gap_to_box_and_fill():
    cu = geom.track_copper(tracks((0, 0, 1, 0)), [0])
    assert cu.gap_to_box([3, -1, 5, 1]) == pytest.approx([1.9])
    assert cu.gap_to_box([0.5, -1, 5, 1]) == pytest.approx([0.0])                   # an end point inside the box
    deep = geom.track_copper(tracks((2, 0, 3, 0)), [0])
    assert deep.gap_to_box([0, -5, 10, 5]) == pytest.approx([0.0])                   # wholly inside: no edge is near, still 0
    sq = np.array([[2, -2], [6, -2], [6, 2], [2, 2]], float)
    assert cu.gap_to_fill(sq, [0, 4], [0]) == pytest.approx([0.9])
    inside = geom.track_copper(tracks((3, 0, 4, 0)), [0])
    assert inside.gap_to_fill(sq, [0, 4], [0]) == pytest.approx([0.0])              # lies on the fill
    hole = np.vstack([sq, [[3, -1], [5, -1], [5, 1], [3, 1]]])
    in_hole = geom.track_copper(tracks((3.5, 0, 4.5, 0)), [0])
    assert in_hole.gap_to_fill(hole, [0, 4, 8], [0, 1]) == pytest.approx([0.4])      # in the hole: the distance to the hole's edge


def test_join_numbers_owners_part_by_part():
    a = geom.track_copper(tracks((0, 0, 1, 0), (0, 5, 1, 5)), [0, 1])
    b = geom.pad_copper(pads(0, 1, 1), [0])
    j = geom.join(a, b)
    assert j.n == 3 and sorted(set(j.owner.tolist())) == [0, 1, 2]
    g = j.gap_to_segments([[0, 2.0, 1, 2.0]])
    assert g[0] == pytest.approx(1.9) and g[1] == pytest.approx(2.9) and g[2] == pytest.approx(1.5)
