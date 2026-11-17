"""The committed gate-3 packages describe the board that is committed.

The v1 package (kicad/gate3) was left behind when the v1 board changed: its info.json recorded sha256 17689b0a... while the board file hashed to 044f733e..., and no test
noticed, because the only test that regenerates a package and compares (test_gate3_equivalence) runs for v2 alone and test_gate3_committed_arms reads the committed data without
looking at the board. This holds both packages to the board by content: info.json's recorded board sha256 equals the board file's, and no render the package lists is stale.
Pure text and JSON, no pcbnew. Broken on purpose below (a recorded hash that differs by one digit, a stale render)."""
import hashlib
import json
import pathlib

import pytest

AFE = pathlib.Path(__file__).resolve().parents[2]
PACKAGES = {'v1': (AFE / 'kicad' / 'gate3', AFE / 'kicad' / 'afe-proto.kicad_pcb'),
            'v2': (AFE / 'v2' / 'layout' / 'gate3', AFE / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb')}


def stale(info, renders, board_bytes):
    """[what is stale] in a package: its recorded board hash against the board's (first), and every render it lists"""
    out = []
    got = hashlib.sha256(board_bytes).hexdigest()
    if info.get('sha256') != got:
        out.append(f'info.json records board sha256 {str(info.get("sha256"))[:8]}..., the board file is {got[:8]}...')
    out += [f'render {r["view"]} is stale: {r.get("why") or "not current"}' for r in renders if not r.get('current')]
    return out


def load(name):
    pkg, board = PACKAGES[name]
    return pkg, board, json.loads((pkg / 'data' / 'info.json').read_text()), json.loads((pkg / 'data' / 'renders.json').read_text())


@pytest.mark.parametrize('name', sorted(PACKAGES))
def test_the_committed_package_records_the_boards_hash(name):
    pkg, board, info, renders = load(name)
    assert renders, 'the package lists no render: the check would look at nothing'
    assert [s for s in stale(info, renders, board.read_bytes()) if s.startswith('info.json')] == [], f'regenerate {pkg}: python3 -B -m pcbtools.gate3 (see the table\'s docstring)'


@pytest.mark.parametrize('name', [pytest.param('v1'), pytest.param('v2', marks=pytest.mark.xfail(
    strict=True, reason="v2's four renders were made before the AFE-2 silk labels landed (renders.json: made from another board file); regenerate them and drop this mark"))])
def test_the_committed_renders_are_the_boards(name):
    pkg, board, info, renders = load(name)
    assert [s for s in stale(info, renders, board.read_bytes()) if s.startswith('render')] == []


def test_a_stale_package_is_found():
    pkg, board = PACKAGES['v1']
    info = json.loads((pkg / 'data' / 'info.json').read_text())
    renders = json.loads((pkg / 'data' / 'renders.json').read_text())
    b = board.read_bytes()
    assert stale(info, renders, b) == []
    one_digit = dict(info, sha256=info['sha256'][:-1] + ('0' if info['sha256'][-1] != '0' else '1'))
    assert len(stale(one_digit, renders, b)) == 1 and 'info.json records' in stale(one_digit, renders, b)[0]
    assert stale(info, renders, b + b'\n')                                      # the board changed by a byte
    old = [dict(r, current=False, why='made from another board file') for r in renders]
    assert any('is stale' in s for s in stale(info, old, b))
