"""The two-way nearest test (pcbkit.rules.two_way_test) on the two approved boards: AFE-1's live board with v1_layout is clean, AFE-2's integrated board fails J605 and nothing else.
Read through pcbkit.board with the shapes-only F.Fab body. The tolerance EPS matters: AFE-1's J607 is 1.25 micrometres short of the margin and passes only because EPS = 0.005 mm
(with EPS = 0 it fails). J605's shortfall is 0.085 mm, far beyond EPS, and stays a failure (accepted by the owner's side). Broken on purpose in hardware/pcbkit/tests/mutate_kit.py (EPS not
applied, on the wrong side, twice, a second hard-coded value)."""
import pathlib

import pytest
from pcbtools.boards import v1_layout, v2_layout
from pcbkit import board, rules

AFE = pathlib.Path(__file__).resolve().parents[2]
FUN = {'CH1 IN': 'J101', 'CH2 IN': 'J201', 'AWG OUT': 'J301'}
FRAME = (50.0, 150.0)


def failing(path, cfg, **over):
    b = board.read_board(str(path), FRAME)
    out = rules.two_way_test(b, dict(SILK_REQUIRED_PREFIXES=cfg.SILK_REQUIRED_PREFIXES, LABEL_TEXTS=FUN, **over))
    return out, {p: v for p, v in out.items() if v[1] or v[2]}


@pytest.mark.pcbnew
def test_afe1_live_board_is_clean_and_needs_the_tolerance_for_j607(pcbnew_required):
    out, bad = failing(AFE / 'kicad' / 'afe-proto.kicad_pcb', v1_layout)
    assert len(out) == 68 and bad == {}
    _, strict = failing(AFE / 'kicad' / 'afe-proto.kicad_pcb', v1_layout, EPS=0.0)
    assert sorted(strict) == ['J607'] and strict['J607'][1] is None
    own, _, s2 = strict['J607']
    assert s2[1] == 'J201' and own == pytest.approx(0.395, abs=1e-4) and s2[3] == pytest.approx(0.54375, abs=1e-4)      # 1.25 micrometres short of the 0.15 margin


@pytest.mark.pcbnew
def test_afe2_integrated_board_fails_j605_and_nothing_else(pcbnew_required):
    for eps in (0.005, 0.0):
        out, bad = failing(AFE / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb', v2_layout, EPS=eps)
        assert len(out) == 60 and sorted(bad) == ['J605'] and bad['J605'][1] is None
        own, _, s2 = bad['J605']
        assert s2[1] == 'J101' and own == pytest.approx(0.48, abs=1e-4) and s2[3] == pytest.approx(0.54475, abs=1e-4)
        assert own + 0.15 - s2[3] == pytest.approx(0.08525, abs=1e-4)                       # short of the margin by 0.085 mm (own 0.48 + 0.15 = 0.63 against 0.545): not within EPS
