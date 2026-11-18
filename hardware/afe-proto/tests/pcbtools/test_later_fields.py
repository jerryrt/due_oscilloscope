"""The arrays pcbkit added after the first release (footprint fab boxes, silk graphics, text boxes...) are not in the AFE's recorded caches
(tests/fixtures/arrays), and a consumer that needs one must say so, not read an empty array: a recorded cache handed to a pcbkit consumer of
fp_fab_* raises naming the field, a board read through pcbkit.board with the AFE's FRAME passes and agrees with the cache on the first release."""
import glob
import os

import numpy as np
import pytest
from pcbkit import board as K
from pcbtools.frame import FRAME

HERE = os.path.dirname(os.path.abspath(__file__))
FX = os.path.join(os.path.dirname(HERE), 'fixtures', 'v2-8a1f7ac')
ARR = os.path.join(os.path.dirname(HERE), 'fixtures', 'arrays')
BOARD = next(p for p in sorted(glob.glob(os.path.join(FX, '*.kicad_pcb'))) if 'integrated' in p)
CACHE = os.path.join(ARR, os.path.basename(BOARD)[:-10] + '.npz')


def test_a_recorded_cache_raises_naming_the_field():
    b = K.load_npz(CACHE)
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
def test_pcbkit_board_with_frame_passes_and_agrees_with_the_cache_on_the_first_release(pcbnew_required):
    k = K.read_board(BOARD, FRAME)
    a = K.load_npz(CACHE)
    boxes = K.fab_boxes(k)
    assert len(boxes) == len(k.fp_ref) and (~(boxes[:, 0] > boxes[:, 2])).all()
    K.footprint_silk(k), K.board_silk_graphics(k), K.text_boxes(k)
    assert np.array_equal(k.fp_x, a.fp_x) and np.array_equal(k.p_bx0, a.p_bx0) and k.nets == a.nets          # the first release's arrays are the same
