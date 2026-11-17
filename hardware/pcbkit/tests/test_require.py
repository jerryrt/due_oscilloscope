"""board.require: a field the reader did not fill raises naming it; a board read by pcbkit.board passes; every consumer of a later field calls it."""
import numpy as np
import pytest

from pcbkit import board as B
from synthetic import build_rich

FR = (50.0, 150.0)


def hand_built(**kw):
    return B.BoardArrays.from_arrays(nets=('',), fp_idx=[0], fp_ref=['A'], fp_x=[0], fp_y=[0], fp_rot=[0], fp_side=[0], fp_cx0=[0], fp_cy0=[0],
                                     fp_cx1=[1], fp_cy1=[1], fp_kind=['K'], fp_fab_x0=[0.0], fp_fab_y0=[0.0], fp_fab_x1=[1.0], fp_fab_y1=[1.0], **kw)


CONSUMERS = [(B.fab_boxes, 'fp_fab_x0'), (B.footprint_silk, 'fs_fp'), (B.board_silk_graphics, 'g_x0'), (B.text_boxes, 't_x0')]


def test_unread_field_raises_naming_it_even_when_the_array_has_values():
    b = hand_built()                                           # fp_fab_* are filled by hand but no reader says it filled them
    assert len(b.fp_fab_x0) == 1 and b.read_fields == frozenset()
    for fn, name in CONSUMERS:
        with pytest.raises(B.FieldNotRead, match=name):
            fn(b)
    with pytest.raises(B.FieldNotRead, match='fp_fab_y1'):
        B.require(b, 'fp_x', 'fp_fab_y1')


def test_first_release_fields_always_pass_and_unknown_names_are_an_error():
    B.require(hand_built(), 'fp_x', 'p_bx0', 't_h', 's_x0')
    with pytest.raises(ValueError, match='no_such_field'):
        B.require(hand_built(), 'no_such_field')


def test_a_board_that_declares_its_fields_passes():
    b = hand_built(read_fields={'fp_fab_x0', 'fp_fab_y0', 'fp_fab_x1', 'fp_fab_y1'})
    assert B.fab_boxes(b).tolist() == [[0.0, 0.0, 1.0, 1.0]]
    with pytest.raises(B.FieldNotRead, match='t_x0'):          # one group read does not cover another
        B.text_boxes(b)


def test_read_fields_survive_the_npz_cache_and_an_old_cache_has_none(tmp_path):
    b = hand_built(read_fields=B.LATER_FIELDS)
    B.save_npz(b, tmp_path / 'b.npz')
    assert B.load_npz(tmp_path / 'b.npz').read_fields == B.LATER_FIELDS
    c = B.load_npz(tmp_path / 'b.npz')
    old = {k: v for k, v in np.load(tmp_path / 'b.npz', allow_pickle=False).items() if k != '__read_fields'}
    np.savez_compressed(tmp_path / 'old.npz', **old)
    assert B.load_npz(tmp_path / 'old.npz').read_fields == frozenset()


@pytest.mark.pcbnew
def test_read_board_declares_every_later_field_and_every_consumer_passes(pcbnew_mod, tmp_path):
    b = B.read_board(build_rich(pcbnew_mod, tmp_path / 'r.kicad_pcb'), FR)
    assert b.read_fields == B.LATER_FIELDS
    assert B.fab_boxes(b).shape == (3, 4) and len(B.footprint_silk(b)[0]) and len(B.board_silk_graphics(b)[1]) == 5 and B.text_boxes(b).shape == (2, 4)
    # a field read with zero rows is read, not unread: a board with no board-level silk shapes still passes
    c = b.replace(g_x0=[], g_y0=[], g_x1=[], g_y1=[], g_kind=[])
    assert B.board_silk_graphics(c)[1] == ()
    # the retry child's cache carries it too
    assert B.read_board_retry(str(tmp_path / 'r.kicad_pcb'), FR).read_fields == B.LATER_FIELDS
