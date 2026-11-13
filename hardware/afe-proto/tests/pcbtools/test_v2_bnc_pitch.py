"""The three BNCs of the v2 layout of record: one x, CH1 to CH2 at SCOPE_PITCH, AWG to CH2 at least SCOPE_PITCH (owner's ruling
2026-11-13), and each scope input run leaving its BNC at the BNC's own y. Every figure is the config's (boards/v2_layout.py BNC_X,
BNC_Y, SCOPE_PITCH); nothing is typed here. Pure text on the board file: no pcbnew. Broken once on purpose, as the suite requires."""
import pathlib
import re
import sys

import pytest

from pcbtools.boards import v2_layout as CFG

LAYOUT = pathlib.Path(__file__).resolve().parents[2] / 'v2' / 'layout'
BOARD = LAYOUT / 'integrated' / 'afe-v2-integrated.kicad_pcb'
sys.path.insert(0, str(LAYOUT))
import place_bncs as P  # noqa: E402


def positions(text):
    out = {}
    for ref in CFG.BNC_Y:
        s, e = P._fp_span(text, ref)
        m = re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)', text[s:e])
        out[ref] = (float(m.group(1)) - P.SX, P.SY - float(m.group(2)))
    return out


def problems(text, tol=0.01):
    """what is wrong with the BNC layout in `text`, as a list (empty = fine)"""
    pos = positions(text)
    x = {r: p[0] for r, p in pos.items()}
    y = {r: p[1] for r, p in pos.items()}
    bad = []
    if max(x.values()) - min(x.values()) > tol or abs(x['J101'] - CFG.BNC_X) > tol:
        bad.append(f'x not shared / not the config\'s: {x}')
    if abs((y['J101'] - y['J201']) - CFG.SCOPE_PITCH) > tol:
        bad.append(f'CH1-CH2 pitch {y["J101"] - y["J201"]:.3f} != SCOPE_PITCH {CFG.SCOPE_PITCH}')
    if (y['J201'] - y['J301']) < CFG.SCOPE_PITCH - tol:
        bad.append(f'AWG-CH2 {y["J201"] - y["J301"]:.3f} < SCOPE_PITCH {CFG.SCOPE_PITCH}')
    for r, v in CFG.BNC_Y.items():
        if abs(y[r] - v) > tol:
            bad.append(f'{r} at y {y[r]:.3f}, config {v}')
    return bad


def test_config_pitches_hold_on_their_own():
    assert abs((CFG.BNC_Y['J101'] - CFG.BNC_Y['J201']) - CFG.SCOPE_PITCH) < 0.01
    assert CFG.BNC_Y['J201'] - CFG.BNC_Y['J301'] >= CFG.SCOPE_PITCH - 0.01


def test_the_board_has_the_bncs_where_the_config_says():
    assert problems(BOARD.read_text()) == []


def test_broken_once_a_bnc_moved_by_half_a_millimetre_is_caught():
    text = BOARD.read_text()
    bad = P.move_footprint(text, 'J201', P.footprint_y(text, 'J201') + 0.5)
    got = problems(bad)
    assert any('pitch' in g for g in got) and any('J201' in g for g in got)
    bad = P.move_footprint(text, 'J301', P.footprint_y(text, 'J301') + 2.0)            # AWG too close to CH2
    assert any('AWG-CH2' in g for g in problems(bad))


@pytest.mark.parametrize('ref', ['J101', 'J201'])
def test_each_scope_run_leaves_its_bnc_at_the_bncs_own_y(ref):
    """a track on pin 1's net starts at pin 1's centre; none starts at the old y (the run was replaced, not duplicated)"""
    text = BOARD.read_text()
    net = P.pin1_net(text, ref)
    starts = [(float(a) - P.SX, P.SY - float(b)) for a, b in re.findall(
        r'\n\t\(segment\n\t\t\(start ([-\d.]+) ([-\d.]+)\)\n\t\t\(end [-\d.]+ [-\d.]+\)\n\t\t\(width [\d.]+\)\n\t\t\(layer "F.Cu"\)\n\t\t\(net "%s"\)' % re.escape(net), text)]
    assert any(abs(x - CFG.BNC_X) < 1e-3 and abs(y - CFG.BNC_Y[ref]) < 1e-3 for x, y in starts)
    assert not any(abs(x - CFG.BNC_X) < 1e-3 and abs(y - CFG.BNC_Y[ref]) > 1e-3 for x, y in starts)


def test_placing_again_changes_nothing_and_the_j605_label_is_where_the_config_says():
    text = BOARD.read_text()
    new, rep = P.place(text)
    assert rep == [] and new == text
    s, e = P._fp_span(text, 'J605')
    fx, fy = (float(v) for v in re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)', text[s:e]).groups())
    lx, ly = (float(v) for v in re.search(r'\(property "Reference" "J605"\n\t\t\t\(at ([-\d.]+) ([-\d.]+)', text[s:e]).groups())
    assert (fx + lx - P.SX, P.SY - (fy + ly)) == pytest.approx(CFG.DESIGNATOR_AT['J605'], abs=1e-3)
