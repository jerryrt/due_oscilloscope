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
    on_disk = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p.name != 'MANIFEST.json'}
    assert on_disk == set(m['files']), f'unlisted or missing: {sorted(on_disk ^ set(m["files"]))}'
    for rel, want in m['files'].items():
        assert hashlib.sha256((root / rel).read_bytes()).hexdigest() == want, f'{rel} changed'
    assert m['commit'] and m['branch']


def test_there_is_a_v1_fixture():
    assert any(p.parent.name == 'v1-34b2e51' for p in MANIFESTS)
