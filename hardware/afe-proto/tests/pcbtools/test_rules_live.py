"""pcbnew tier: the rules on a board read live agree with the rules on the cached arrays, the command line reads a
.kicad_pcb, and LR-10 (kicad-cli) gives the old tool's DRC verdicts. Small and few: each live read is one board load."""
import json
import os

import pytest

from pcbtools import boardio, drc, rules as R
from pcbtools.boards import v2
import pcbtools.check as CK

HERE = os.path.dirname(os.path.abspath(__file__))
FX = os.path.join(HERE, '..', 'fixtures', 'v2-8a1f7ac')
ARR = os.path.join(HERE, '..', 'fixtures', 'arrays')
GOLD = os.path.join(HERE, '..', 'golden', 'v2-8a1f7ac')
BOARDS = ['v2-integrated-990d4b03', 'v2-awg-bc96e334', 'v2-refcal-326f141b']


@pytest.mark.pcbnew
@pytest.mark.parametrize('name', BOARDS)
def test_rules_agree_on_the_live_read(pcbnew_required, name):
    live = boardio.read_board(os.path.join(FX, name + '.kicad_pcb'))
    cached = boardio.load_npz(os.path.join(ARR, name + '.npz'))
    for row, fn in R.ROWS:
        a, b = fn(live, v2), fn(cached, v2)
        assert (a.ok, a.detail, a.figures) == (b.ok, b.detail, b.figures), row


@pytest.mark.pcbnew
def test_cli_reads_a_kicad_pcb(pcbnew_required, capsys):
    rc = CK.main([os.path.join(FX, 'v2-refcal-326f141b.kicad_pcb'), '--config', 'v2', '--rows', 'LR-1', 'LR-11'])
    out = capsys.readouterr().out
    assert rc == 0 and out.count('[PASS]') == 2 and 'ALL PASS' in out


def _drc_parts(detail):
    """'DRC {a: 1, b: 2}; unconnected 6' -> ({'a': 1, 'b': 2}, 'unconnected 6'): the dict's key order follows kicad-cli's report
    order, which flips between runs and hosts (tests/fixtures/v2-8a1f7ac/SOURCE.md), so it is compared as a dict"""
    import ast
    head, tail = detail.rsplit('; ', 1)
    return ast.literal_eval(head[len('DRC '):]), tail


def _golden_lr10(name):
    with open(os.path.join(GOLD, f'{name}.lr_check.json')) as f:
        return next(r for r in json.load(f)['rows'] if r['name'] == 'LR-10')


@pytest.mark.pcbnew
@pytest.mark.slow
@pytest.mark.parametrize('name', ['v2-integrated-990d4b03', 'v2-refcal-326f141b'])
def test_lr10_matches_the_old_drc_row(pcbnew_required, tmp_path, name):
    b = boardio.load_npz(os.path.join(ARR, name + '.npz'))
    b = b.replace(path=os.path.join(FX, name + '.kicad_pcb'))
    r = drc.lr10(b, v2, outdir=str(tmp_path))
    old = _golden_lr10(name)
    assert ('PASS' if r.ok else 'FAIL') == old['verdict']
    assert _drc_parts(r.detail) == _drc_parts(old['detail'])
    assert r.figures['unconnected'] == float(old['detail'].rsplit(' ', 1)[1])
    assert drc.drc_time() > 0


@pytest.mark.pcbnew
@pytest.mark.slow
def test_lr10_arm_is_caught(pcbnew_required, tmp_path):
    name = 'v2-integrated-990d4b03'
    b = boardio.load_npz(os.path.join(ARR, name + '.npz')).replace(path=os.path.join(FX, name + '.kicad_pcb'))
    arm = drc.lr10_arm(b, str(tmp_path))
    assert os.path.exists(arm) and os.path.exists(arm.replace('.kicad_pcb', '.kicad_pro'))
    r = drc.lr10_path(arm, outdir=str(tmp_path))
    old = json.load(open(os.path.join(GOLD, f'{name}.lr_check_mutate.json')))['raw']
    old_line = next(l for l in old.splitlines() if 'LR-10' in l)
    assert not r.ok and 'track_width' in r.detail
    assert _drc_parts(old_line[old_line.index('DRC '):]) == _drc_parts(r.detail), (old_line, r.detail)


@pytest.mark.pcbnew
def test_read_board_retry_accepts_a_path_relative_to_the_callers_cwd(pcbnew_required, monkeypatch):
    """the child process runs in the package's parent folder, so a relative path used to be 'cannot load' (the CLI and the bench
    steps pass one); it is made absolute first"""
    monkeypatch.chdir(FX)
    b = boardio.read_board_retry('v2-refcal-326f141b.kicad_pcb')
    assert len(b.fp_ref) > 10
