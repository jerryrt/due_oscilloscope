"""The generic gate-3 tool reproduces the committed v1 package byte for byte (as test_gate3_equivalence does for v2).

`python3 -B -m pcbtools.gate3 --config v1_layout --table gate3_v1` on the live board must give GATE3.md and every file of data/ that kicad/gate3 holds, identical to the byte. The
generated-at text is injected from the committed package; nothing else in a run depends on the clock. This became possible when a broken-once arm began to record the PIECES the
DRC names instead of the items KiCad chose to name them (they varied from run to run: test_gate3_pieces.py), and it is what would have caught the v1 package going stale.
Broken once on purpose, as the suite requires: a changed table entry and a broken engine rule must each make the comparison fail.

pcbnew tier: needs kicad-cli (in the PCB image); under --require-tool=pcbnew a missing one fails, never skips."""
import hashlib
import json
import os
import pathlib
import re
import shutil
import types

import pytest

from pcbtools.boards import gate3_v1 as TABLE
from pcbtools.boards import v1_layout as CFG

AFE = pathlib.Path(__file__).resolve().parents[2]
PKG = AFE / 'kicad' / 'gate3'
EXPECT_PCBNEW = os.environ.get('PCBTOOLS_EXPECT_PCBNEW') == '1'


def injected():
    """the generated-at text, read off the committed package"""
    return re.search(r' at (\S+)\. \*\*Every number below', (PKG / 'GATE3.md').read_text()).group(1)


def package_files(root):
    root = pathlib.Path(root)
    return sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and (p.name == 'GATE3.md' or 'data' in p.relative_to(root).parts))


def differences(out):
    """the files of the committed package that `out` does not reproduce to the byte (and files only one side has)"""
    a, b = package_files(PKG), package_files(out)
    bad = [f'only on one side: {f}' for f in sorted(set(a) ^ set(b))]
    for f in sorted(set(a) & set(b)):
        if (PKG / f).read_bytes() != (pathlib.Path(out) / f).read_bytes():
            bad.append(f)
    return bad


@pytest.fixture(scope='module')
def tools():
    if shutil.which('kicad-cli') is None:
        (pytest.fail if EXPECT_PCBNEW else pytest.skip)('needs kicad-cli (in the PCB image)')


@pytest.fixture(scope='module')
def drc_reports():
    return {}


@pytest.fixture()
def memo_drc(monkeypatch, drc_reports):
    import pcbtools.gate3.engine as eng
    real = eng.run_drc if not getattr(eng.run_drc, '_memo', False) else eng.run_drc._real

    def cached(board, setup=None, board_text=None):
        k = (str(board), json.dumps(setup, sort_keys=True, default=str), hashlib.sha256((board_text or '').encode()).hexdigest())
        if k not in drc_reports:
            drc_reports[k] = real(board, setup, board_text)
        return drc_reports[k]
    cached._memo, cached._real = True, real
    monkeypatch.setattr(eng, 'run_drc', cached)


def run(tmp_path, table=TABLE):
    import pcbtools.gate3.engine as eng
    eng.generate(CFG, table, str(tmp_path), 'v1_layout', stamp=injected())
    return tmp_path


@pytest.mark.pcbnew
def test_v1_package_is_reproduced_byte_for_byte(pcbnew_required, tools, memo_drc, tmp_path):
    out = run(tmp_path)
    assert len(package_files(PKG)) >= 10                     # a floor: GATE3.md and the data files were compared, not an empty set
    assert differences(out) == []


@pytest.mark.pcbnew
def test_broken_once_a_table_entry_is_caught(pcbnew_required, tools, memo_drc, tmp_path):
    t = types.SimpleNamespace(**{k: v for k, v in vars(TABLE).items() if not k.startswith('_')})
    t.LR_RENAMES = (('LR-12 DECOUP_MAX', 'LR-4 supply decoupling ({:.1f} mm)', 'DECOUP_MAX'),)
    bad = differences(run(tmp_path, t))
    assert 'GATE3.md' in bad and 'data/lr.json' in bad


@pytest.mark.pcbnew
def test_broken_once_an_engine_rule_is_caught(pcbnew_required, tools, memo_drc, tmp_path, monkeypatch):
    import pcbtools.gate3.engine as eng
    monkeypatch.setattr(eng, 'classify_net', lambda name, classes: None)         # no ADC / divider / VREF line is recognised
    bad = differences(run(tmp_path))
    assert 'GATE3.md' in bad and any(f.startswith('data/') for f in bad)
