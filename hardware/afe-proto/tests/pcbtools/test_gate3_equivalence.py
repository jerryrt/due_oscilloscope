"""The generic gate-3 tool reproduces the committed v2 package byte for byte.

`python3 -B -m pcbtools.gate3 --config v2_layout --table gate3_v2` on the integrated board must give GATE3.md and every file of data/ that
v2/layout/gate3 holds, identical to the byte. Two inputs of a run depend on the clock and are injected from the committed package itself,
so the comparison is exact everywhere else: the generated-at text (read off the committed GATE3.md's third line) and the file modification
times (the board's, and the renders' offsets from it, from the committed info.json and renders.json: a checkout rewrites them). Nothing is
filtered out of the comparison and no line is skipped.

Broken once on purpose, as the suite requires of a new guard: a changed table entry and a broken engine rule must each make the same
comparison fail, so it is known to be able to. The mutated runs reuse the DRC reports of the faithful run (a DRC run is most of the 18 s),
which is sound because neither mutation touches what DRC reads.

pcbnew tier: needs KiCad 10.x's pcbnew and kicad-cli (both in the PCB image); under --require-tool=pcbnew a missing one fails, never skips.
"""
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import types

import pytest

from pcbtools.boards import gate3_v2 as TABLE
from pcbtools.boards import v2_layout as CFG

AFE = pathlib.Path(__file__).resolve().parents[2]
PKG = AFE / 'v2' / 'layout' / 'gate3'
EXPECT_PCBNEW = __import__('os').environ.get('PCBTOOLS_EXPECT_PCBNEW') == '1'


def injected():
    """(stamp, mtimes) read off the committed package"""
    doc = (PKG / 'GATE3.md').read_text()
    stamp = re.search(r' at (\S+)\. \*\*Every number below', doc).group(1)
    info = json.loads((PKG / 'data' / 'info.json').read_text())
    bm = datetime.datetime.fromisoformat(info['mtime']).timestamp()
    mt = {info['board']: bm}
    for r in json.loads((PKG / 'data' / 'renders.json').read_text()):
        if r['exists']:
            mt[r['file']] = bm + r['delta_s']
    return stamp, mt


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
    stamp, mt = injected()
    eng.generate(CFG, table, str(tmp_path), 'v2_layout', stamp=stamp, mtimes=mt)
    return tmp_path


@pytest.mark.pcbnew
def test_v2_package_is_reproduced_byte_for_byte(pcbnew_required, tools, memo_drc, tmp_path):
    out = run(tmp_path)
    assert len(package_files(PKG)) >= 15                     # a floor: GATE3.md and the 14 data files were compared, not an empty set
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
    assert 'data/bridges.json' in bad and 'GATE3.md' in bad


@pytest.mark.pcbnew
@pytest.mark.slow
def test_command_line_reproduces_the_package_and_the_stamp_is_injectable(pcbnew_required, tools, tmp_path):
    """the real entry point in a child process, as build_gate3.sh runs it, with the clock inputs injected through its flags"""
    stamp, mt = injected()
    mtf = tmp_path / 'mtimes.json'
    mtf.write_text(json.dumps(mt))
    out = tmp_path / 'out'
    r = subprocess.run([sys.executable, '-B', '-m', 'pcbtools.gate3', '--config', 'v2_layout', '--table', 'gate3_v2', '--out', str(out),
                        '--stamp', stamp, '--mtimes', str(mtf)], capture_output=True, text=True, cwd=str(AFE), timeout=600)
    assert r.returncode == 0, r.stderr[-500:]
    assert differences(out) == []
