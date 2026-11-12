"""The frozen fixtures must not drift: every file in a fixture's MANIFEST.json matches its recorded sha256, and no file
is unlisted. A fixture is a copy of one commit's inputs; editing it silently would turn an equivalence test into a lie."""
import hashlib
import json
import pathlib

import pytest

FIX = pathlib.Path(__file__).resolve().parents[1] / 'fixtures'
MANIFESTS = sorted(FIX.glob('*/MANIFEST.json'))


@pytest.mark.parametrize('mf', MANIFESTS, ids=lambda p: p.parent.name)
def test_fixture_matches_its_manifest(mf):
    m = json.loads(mf.read_text())
    root = mf.parent
    # bytecode is not fixture content: a test that imports a fixture's module must not be able to break this one
    on_disk = {str(p.relative_to(root)) for p in root.rglob('*')
               if p.is_file() and p.name != 'MANIFEST.json' and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    assert on_disk == set(m['files']), f'unlisted or missing: {sorted(on_disk ^ set(m["files"]))}'
    for rel, want in m['files'].items():
        assert hashlib.sha256((root / rel).read_bytes()).hexdigest() == want, f'{rel} changed'
    assert m['commit'] and m['branch']


def test_there_is_a_v1_fixture():
    assert any(p.parent.name == 'v1-34b2e51' for p in MANIFESTS)


def test_bytecode_in_a_fixture_does_not_count(tmp_path):
    """the defect found in the image: the first run wrote a .pyc into a fixture and the second run failed on it"""
    import shutil
    src = FIX / 'v1-34b2e51'
    dst = tmp_path / 'v1-34b2e51'
    shutil.copytree(src, dst)
    (dst / 'kicad' / '__pycache__').mkdir()
    (dst / 'kicad' / '__pycache__' / 'sexpr.cpython-314.pyc').write_bytes(b'\x00')
    test_fixture_matches_its_manifest(dst / 'MANIFEST.json')


def test_no_test_leaves_bytecode_in_a_fixture():
    assert not [p for p in FIX.rglob('*.pyc')]
