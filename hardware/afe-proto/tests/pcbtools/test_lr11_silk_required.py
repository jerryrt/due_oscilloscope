"""LR-11 under D30 (1c) (owner, 2026-11-17): on v1's final board an IC, a connector, a test point or a diode always carries its designator on top silk,
and any other part either carries it there or moves it to F.Fab, where the interactive BOM and the assembly drawing find it. Each way of
breaking that is caught, on the real board (broken once on purpose, kept as tests)."""
import pathlib
import re

import pytest

from pcbtools import boardio, rules as R
from pcbtools.boards import v1 as L

BOARD = pathlib.Path(__file__).resolve().parents[2] / 'kicad' / 'afe-proto.kicad_pcb'

pytestmark = pytest.mark.pcbnew


def _ref_layer(text, ref):
    m = re.search(r'\(property "Reference" "' + re.escape(ref) + r'"\n(\t+)\(at [^)]*\)\n\t+\(layer "([^"]+)"\)', text)
    assert m, ref
    return m


def _move(text, ref, layer):
    m = _ref_layer(text, ref)
    return text[:m.start(2)] + layer + text[m.end(2):]


def _lr11(tmp_path, text):
    p = tmp_path / 'b.kicad_pcb'
    p.write_text(text)
    return R.lr11(boardio.read_board(p), L)


def test_the_board_passes_with_its_off_silk_passives(pcbnew_required):
    text = BOARD.read_text()
    fab = [r for r in re.findall(r'\(property "Reference" "([A-Z]+\d+)"', text) if _ref_layer(text, r).group(2) == 'F.Fab']
    assert len(fab) >= 40 and not any(r.rstrip('0123456789') in L.SILK_REQUIRED_PREFIXES for r in fab)    # the floor: the check has passives to judge
    r = R.lr11(boardio.read_board(BOARD), L)
    assert r.ok, r.detail
    assert f'{len(fab)} passive designators on F.Fab' in r.detail


@pytest.mark.parametrize('ref', ['U401', 'J501', 'TP401', 'J101', 'D201'])
def test_an_anchor_moved_to_fab_is_caught(pcbnew_required, tmp_path, ref):
    text = BOARD.read_text()
    assert _ref_layer(text, ref).group(2) == 'F.SilkS'
    r = _lr11(tmp_path, _move(text, ref, 'F.Fab'))
    assert not r.ok and f'{ref}: designator not on silk' in r.detail


def test_a_passive_on_neither_silk_nor_fab_is_caught(pcbnew_required, tmp_path):
    text = BOARD.read_text()
    assert _ref_layer(text, 'C104').group(2) == 'F.Fab'
    r = _lr11(tmp_path, _move(text, 'C104', 'User.1'))
    assert not r.ok and 'C104: designator not on silk' in r.detail and 'not on F.Fab either' in r.detail
