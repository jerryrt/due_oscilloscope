"""The old tools are frozen next to the fixture boards (tests/fixtures/v2-8a1f7ac/tools): they must run from there, refer to
nothing outside the fixture folder, and still print what the committed goldens hold. The re-take of the goldens of record
(tests/golden_capture/run_old_tools.py) runs these same files."""
import json
import os
import shutil
import pathlib
import re
import subprocess
import sys

import pytest

TESTS = pathlib.Path(__file__).resolve().parents[1]
FX = TESTS / 'fixtures' / 'v2-8a1f7ac'
TOOLS = FX / 'tools'
GOLD = TESTS / 'golden' / 'v2-8a1f7ac'
FILES = ['lr_check.py', 'fence_check.py', 'cap.py', 'route.py', 'design.py', 'floorplan.py', 'layout.py', 'afe-v2.kicad_pro']


def test_every_tool_and_what_it_imports_is_there():
    assert sorted(p.name for p in TOOLS.iterdir() if p.is_file() and p.suffix != '.pyc') == sorted(FILES)
    src = ''.join((TOOLS / f).read_text() for f in FILES if f.endswith('.py'))
    imported = set(re.findall(r'^\s*(?:import|from)\s+(\w+)', src, re.M))
    # every module the tools import that is not stdlib/third party must be a sibling
    assert "'floorplan'" in (TOOLS / 'fence_check.py').read_text()      # imported by name through __import__
    for name in ('design', 'layout', 'route'):
        assert name in imported and (TOOLS / f'{name}.py').is_file(), name
    assert not imported & {'silk', 'build_pcb', 'merge_blocks', 'sexpr', 'pcbtools'}, imported


def test_the_frozen_copies_of_design_floorplan_layout_are_the_fixture_ones():
    for n in ('design.py', 'floorplan.py', 'layout.py'):
        assert (TOOLS / n).read_bytes() == (FX / n).read_bytes(), n


def test_the_tools_name_no_worktree():
    for f in FILES:
        if f.endswith('.py'):
            t = (TOOLS / f).read_text()
            assert 'due_oscilloscope' not in t and '/home/' not in t, f


def _run(args, tmo=300):
    cap = os.environ.get('CAPPED', '')
    cmd = ([cap, '-m', '3G', '-t', str(tmo)] if cap else []) + [sys.executable, '-I', '-B', *map(str, args)]
    for _ in range(3):                                     # a pcbnew start-up segfault is retried, as everywhere else
        p = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), cwd=str(TOOLS.parent))
        if p.returncode not in (139, -11, 134, -6):
            return p
    return p


def _copy(tmp, *names):
    """the old tools (and kicad-cli under them) write .kicad_prl and lock files beside the board they open: run them on a copy of the
    board, its project file and the library table in tmp, never on the frozen fixture itself. Returns the copies' paths."""
    out = []
    for n in names:
        shutil.copyfile(FX / n, tmp / n)
        pro = FX / (n.rsplit('.', 1)[0] + '.kicad_pro')
        if pro.exists():
            shutil.copyfile(pro, tmp / pro.name)
        out.append(tmp / n)
    for extra in ('fp-lib-table', 'sym-lib-table'):
        if (FX / extra).exists():
            shutil.copyfile(FX / extra, tmp / extra)
    if (FX / 'lib').is_dir() and not (tmp / 'lib').exists():
        os.symlink(FX / 'lib', tmp / 'lib')
    return out


def _raw(name, tool):
    return json.loads((GOLD / f'{name}.{tool}.json').read_text())['raw']


@pytest.mark.pcbnew
def test_frozen_lr_check_prints_the_golden_text(pcbnew_required, tmp_path):
    name = 'v2-integrated-990d4b03'
    (b,) = _copy(tmp_path, f'{name}.kicad_pcb')
    p = _run([TOOLS / 'lr_check.py', b])
    assert p.stdout == _raw(name, 'lr_check')


@pytest.mark.pcbnew
@pytest.mark.parametrize('name,block', [('v2-refcal-326f141b', 'REFCAL'), ('v2-power3-7c838703', 'POWER')])
def test_frozen_fence_check_prints_the_golden_text(pcbnew_required, name, block, tmp_path):
    b, base = _copy(tmp_path, f'{name}.kicad_pcb', 'v2-BASE-056e1d03.kicad_pcb')
    p = _run([TOOLS / 'fence_check.py', block, b, base])
    assert p.stdout == _raw(name, 'fence_check')


@pytest.mark.pcbnew
@pytest.mark.slow
def test_frozen_cap_prints_the_golden_text(pcbnew_required, tmp_path):
    name = 'v2-integrated-990d4b03'
    (b,) = _copy(tmp_path, f'{name}.kicad_pcb')
    p = _run([TOOLS / 'cap.py', b], tmo=600)
    assert p.stdout == _raw(name, 'cap')


def test_running_the_tools_leaves_no_bytecode_in_the_fixtures():
    assert not list(FX.rglob('*.pyc')) and not list(FX.rglob('__pycache__'))
