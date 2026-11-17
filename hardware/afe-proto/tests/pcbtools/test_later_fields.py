"""The arrays pcbkit added after the first release (footprint fab boxes, silk graphics, text boxes...) are not in what the AFE's
pcbtools.boardio.read_board returns, and a consumer that needs one must say so, not read an empty array: a board from the AFE binding handed to
a pcbkit consumer of fp_fab_* raises naming the field, a board read through pcbkit.board with FRAME passes."""
import glob
import os

import pytest
from pcbkit import board as K
from pcbtools import boardio

HERE = os.path.dirname(os.path.abspath(__file__))
FX = os.path.join(os.path.dirname(HERE), 'fixtures', 'v2-8a1f7ac')
BOARD = next(p for p in sorted(glob.glob(os.path.join(FX, '*.kicad_pcb'))) if 'integrated' in p)


@pytest.mark.pcbnew
def test_afe_binding_board_raises_naming_the_field(pcbnew_required):
    b = boardio.read_board(BOARD)
    assert b.read_fields == frozenset()
    with pytest.raises(K.FieldNotRead, match='fp_fab_x0'):
        K.fab_boxes(b)
    with pytest.raises(K.FieldNotRead, match='t_x0'):
        K.text_boxes(b)
    with pytest.raises(K.FieldNotRead, match='fs_fp'):
        K.footprint_silk(b)
    with pytest.raises(K.FieldNotRead, match='g_x0'):
        K.board_silk_graphics(b)


@pytest.mark.pcbnew
def test_pcbkit_board_with_frame_passes_and_agrees_with_the_binding_on_the_first_release(pcbnew_required):
    k = K.read_board(BOARD, boardio.FRAME)
    a = boardio.read_board(BOARD)
    boxes = K.fab_boxes(k)
    assert len(boxes) == len(k.fp_ref) and (~(boxes[:, 0] > boxes[:, 2])).all()
    K.footprint_silk(k), K.board_silk_graphics(k), K.text_boxes(k)
    import numpy as np
    assert np.array_equal(k.fp_x, a.fp_x) and np.array_equal(k.p_bx0, a.p_bx0) and k.nets == a.nets          # the first release's arrays are the same
