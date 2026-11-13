"""The goldens are protected by hash: tests/golden/MANIFEST.sha256 lists every file under tests/golden/ (except itself), and
this test fails when a golden differs, is missing, or is on disk without being listed. A golden is the recorded output of
the OLD tools; editing one silently would make every equivalence test compare a thing with its own edit.

To change a golden on purpose: python tests/golden/update_manifest.py --i-changed-a-golden, and commit the manifest with it.
"""
import importlib.util
import pathlib
import shutil
import subprocess
import sys

import pytest

TESTS = pathlib.Path(__file__).resolve().parents[1]
GOLDEN = TESTS / 'golden'
HOWTO = ('to change a golden on purpose run `python tests/golden/update_manifest.py --i-changed-a-golden` and commit '
         'tests/golden/MANIFEST.sha256 in the same commit; a new golden file must be added to the manifest the same way')


def _um():
    spec = importlib.util.spec_from_file_location('update_manifest', GOLDEN / 'update_manifest.py')
    m = importlib.util.module_from_spec(spec)
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True        # the golden folder must stay free of bytecode
    try:
        spec.loader.exec_module(m)
    finally:
        sys.dont_write_bytecode = keep
    return m


UM = _um()


def compare(root, manifest):
    """-> (changed, missing, extra) for a golden folder against a manifest file"""
    want = UM.read_manifest(manifest)
    have = set(UM.golden_files(root))
    changed = sorted(r for r in want if r in have and UM.digest(pathlib.Path(root) / r) != want[r])
    return changed, sorted(set(want) - have), sorted(have - set(want))


def test_every_golden_matches_the_manifest():
    changed, missing, extra = compare(GOLDEN, GOLDEN / 'MANIFEST.sha256')
    assert not (changed or missing or extra), f'changed {changed}, missing {missing}, untracked-extra {extra}. {HOWTO}'


def test_the_manifest_covers_a_real_folder():
    """a floor: an empty manifest over an empty folder would pass everything"""
    want = UM.read_manifest(GOLDEN / 'MANIFEST.sha256')
    assert len(want) >= 25 and 'v2-8a1f7ac/v2-integrated-990d4b03.cap.json' in want and 'netlib_v1.txt' in want
    assert all(len(h) == 64 for h in want.values())


@pytest.fixture
def copy(tmp_path):
    dst = tmp_path / 'golden'
    shutil.copytree(GOLDEN, dst, ignore=shutil.ignore_patterns('__pycache__'))
    return dst


def test_a_changed_golden_is_caught(copy):
    f = copy / 'netlib_v1.txt'
    f.write_bytes(f.read_bytes() + b'x')
    assert compare(copy, GOLDEN / 'MANIFEST.sha256')[0] == ['netlib_v1.txt']


def test_a_missing_golden_is_caught(copy):
    (copy / 'netlib_v2.txt').unlink()
    assert compare(copy, GOLDEN / 'MANIFEST.sha256')[1] == ['netlib_v2.txt']


def test_an_untracked_extra_golden_is_caught(copy):
    (copy / 'v2-8a1f7ac' / 'new.json').write_text('{}')
    assert compare(copy, GOLDEN / 'MANIFEST.sha256')[2] == ['v2-8a1f7ac/new.json']


def test_bytecode_is_not_a_golden(copy):
    (copy / '__pycache__').mkdir()
    (copy / '__pycache__' / 'x.cpython-314.pyc').write_bytes(b'\0')
    assert compare(copy, GOLDEN / 'MANIFEST.sha256') == ([], [], [])


def test_the_manifest_is_in_sha256sum_format():
    """`sha256sum -c` must read it: hash, two spaces, relative path"""
    if not shutil.which('sha256sum'):
        pytest.skip('no sha256sum')
    r = subprocess.run(['sha256sum', '-c', '--quiet', 'MANIFEST.sha256'], cwd=GOLDEN, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_update_manifest_refuses_without_its_flag(tmp_path):
    before = (GOLDEN / 'MANIFEST.sha256').read_bytes()
    for args in ([], ['--yes'], ['--i-changed-a-golden', 'x']):
        r = subprocess.run([sys.executable, '-B', str(GOLDEN / 'update_manifest.py'), *args], capture_output=True, text=True)
        assert r.returncode != 0 and '--i-changed-a-golden' in r.stderr, args
    assert (GOLDEN / 'MANIFEST.sha256').read_bytes() == before


def test_update_manifest_with_its_flag_reproduces_the_committed_manifest():
    """idempotent on a consistent tree: rendering the manifest from the folder gives the committed text (no write here)"""
    assert UM.render(GOLDEN) == (GOLDEN / 'MANIFEST.sha256').read_text()
