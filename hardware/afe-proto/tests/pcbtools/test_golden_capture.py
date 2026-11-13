"""tests/golden_capture/ holds the scripts that WRITE goldens. Importing one must change nothing, and none may write into
tests/golden/ unless asked to with --into-golden. The proof is a subprocess per script and a hash comparison of the
golden folder against the manifest afterwards; its negative control is a script that does write at import."""
import filecmp
import importlib.util
import pathlib
import shutil
import subprocess
import sys

import pytest

TESTS = pathlib.Path(__file__).resolve().parents[1]
CAPTURE = TESTS / 'golden_capture'
GOLDEN = TESTS / 'golden'
SCRIPTS = sorted(p.stem for p in CAPTURE.glob('*.py'))
ENTRY_POINTS = ['bench_cap', 'bench_new', 'bench_rules', 'capture_old', 'old_counts', 'reparse_figures', 'run_old_tools']

spec = importlib.util.spec_from_file_location('test_golden_manifest_mod', pathlib.Path(__file__).with_name('test_golden_manifest.py'))
TGM = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TGM)


def import_each(capture_dir, golden_dir):
    """import every script of capture_dir in its own subprocess; -> (failures, (changed, missing, extra) of golden_dir)"""
    failures = []
    for p in sorted(pathlib.Path(capture_dir).glob('*.py')):
        code = f'import sys; sys.path.insert(0, {str(capture_dir)!r}); import importlib; importlib.import_module({p.stem!r})'
        r = subprocess.run([sys.executable, '-B', '-I', '-c', code], capture_output=True, text=True, cwd=str(golden_dir), timeout=120)
        if r.returncode:
            failures.append((p.stem, r.stderr[-300:]))
    return failures, TGM.compare(golden_dir, golden_dir / 'MANIFEST.sha256')


def test_the_scripts_are_there():
    assert set(ENTRY_POINTS) <= set(SCRIPTS) and '_common' in SCRIPTS
    assert not [p for p in (TESTS / 'golden').glob('*.py') if p.name != 'update_manifest.py'], 'a script is back in tests/golden'


def test_importing_every_capture_script_changes_no_golden():
    failures, (changed, missing, extra) = import_each(CAPTURE, GOLDEN)
    assert not failures, failures
    assert not (changed or missing or extra), (changed, missing, extra)


def test_the_check_fails_on_a_script_that_writes_at_import(tmp_path):
    """negative control: a copy of the folders with one script that writes into the golden folder when imported"""
    cap, gold = tmp_path / 'golden_capture', tmp_path / 'golden'
    shutil.copytree(CAPTURE, cap, ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(GOLDEN, gold, ignore=shutil.ignore_patterns('__pycache__'))
    assert import_each(cap, gold) == ([], ([], [], []))                    # the copy is clean to begin with
    (cap / 'evil.py').write_text(f'open({str(gold / "v2-8a1f7ac" / "stray.json")!r}, "w").write("{{}}")\n')
    failures, (changed, missing, extra) = import_each(cap, gold)
    assert extra == ['v2-8a1f7ac/stray.json']
    (cap / 'evil.py').write_text(f'open({str(gold / "netlib_v1.txt")!r}, "a").write("x")\n')
    assert import_each(cap, gold)[1][0] == ['netlib_v1.txt']


@pytest.mark.parametrize('name', ENTRY_POINTS)
def test_each_script_has_main_behind_the_guard(name):
    src = (CAPTURE / f'{name}.py').read_text()
    assert 'def main(' in src and "if __name__ == '__main__':" in src
    assert src.rstrip().splitlines()[-1].strip() in ('main()', 'sys.exit(main())'), 'the last statement must be the guarded call'


@pytest.mark.parametrize('name', ['capture_old', 'reparse_figures', 'bench_new', 'bench_rules', 'bench_cap'])
def test_a_script_refuses_to_write_into_golden_without_the_flag(name):
    r = subprocess.run([sys.executable, '-B', str(CAPTURE / f'{name}.py'), '--out', str(GOLDEN / 'v2-8a1f7ac')], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and '--into-golden' in r.stderr, r.stderr
    assert TGM.compare(GOLDEN, GOLDEN / 'MANIFEST.sha256') == ([], [], [])


def test_the_default_output_is_the_scratch_folder_not_the_golden_folder(monkeypatch):
    sys.path.insert(0, str(CAPTURE))
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True        # golden_capture must stay free of bytecode too
    try:
        import _common as C
        out, a = C.parse_out('x', [])
        assert out == str(TESTS.parent / 'pcbtools' / '.scratch' / 'golden_out') and not C.inside(out, C.GOLDEN) and not a.into_golden
        out, a = C.parse_out('x', ['--into-golden'])
        assert pathlib.Path(out) == GOLDEN / 'v2-8a1f7ac'
        assert 'update_manifest.py --i-changed-a-golden' in C.REMINDER
    finally:
        sys.dont_write_bytecode = keep
        sys.path.remove(str(CAPTURE))


def test_reparse_figures_reproduces_the_committed_goldens_byte_for_byte(tmp_path):
    """it is idempotent and needs no pcbnew: the output folder gets the same bytes the golden folder holds"""
    r = subprocess.run([sys.executable, '-B', str(CAPTURE / 'reparse_figures.py'), '--out', str(tmp_path)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    made = sorted(p.name for p in tmp_path.glob('*.json'))
    assert len(made) == 8
    for n in made:
        assert (tmp_path / n).read_bytes() == (GOLDEN / 'v2-8a1f7ac' / n).read_bytes(), n
    assert TGM.compare(GOLDEN, GOLDEN / 'MANIFEST.sha256') == ([], [], [])
