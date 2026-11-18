"""boards/v1_layout is the configuration of the v1 live board (kicad/afe-proto.kicad_pcb): LR-11 passes there with the approved rectangles and the nine named strays, and
boards/v1 (which the arms tests run on the frozen board) still carries its own outlines. Broken on purpose below: a stray left out of the list makes LR-11 fail naming it."""
import pathlib
import types

import pytest
from pcbtools import rules as R
from pcbkit import board as KB
from pcbtools.frame import FRAME
from pcbtools.boards import v1, v1_layout

BOARD = pathlib.Path(__file__).resolve().parents[2] / 'kicad' / 'afe-proto.kicad_pcb'
STRAYS = ('R411', 'R412', 'R413', 'R515', 'R516', 'D201', 'R111', 'R309', 'R310')


def test_the_layout_config_differs_from_v1_only_in_its_outlines():
    assert tuple(v1_layout.OUTLINE_STRAYS) == STRAYS and not hasattr(v1, 'OUTLINE_STRAYS')
    assert v1_layout.OUTLINE != v1.OUTLINE and sorted(v1_layout.OUTLINE) == sorted(v1.OUTLINE)
    for k in ('BLOCK', 'TEST_BLOCKS', 'TP_NETS', 'ANALOG_FENCE', 'EDGE_BLOCK', 'LR_HUNDREDS'):
        assert getattr(v1_layout, k) == getattr(v1, k), k
    assert v1_layout.OUTLINE['SCOPE'][:2] == [(64.3, 33.9, 92.0, 46.4), (75.5, 22.4, 92.0, 32.0)]          # CH1 and CH2, two rectangles of one block


@pytest.mark.pcbnew
def test_lr11_passes_on_the_live_board_with_the_strays_and_fails_without_one(pcbnew_required):
    b = KB.read_board(str(BOARD), FRAME)
    assert R.lr11(b, v1_layout).ok
    cfg = types.SimpleNamespace(**{k: getattr(v1_layout, k) for k in dir(v1_layout) if k.isupper()})
    cfg.OUTLINE_STRAYS = tuple(r for r in STRAYS if r != 'R111')
    r = R.lr11(b, cfg)
    assert not r.ok and 'R111' in r.detail
