"""models/manifest.json: the offline structure check (always), and the real fetch (network step, never in the gate).

The gate runs --network none, so whether every entry still downloads and hashes to its pin is a separate
marked step:   pytest -m network --require-tool=network tests/test_manifest.py
It downloads the whole manifest (hundreds of MB) into a temp directory with tools/fetch_models.py, which verifies
every sha256 itself; a hash mismatch (as the Samsung page produced) fails it.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

AFE = Path(__file__).resolve().parents[1]
MANIFEST = AFE / "models" / "manifest.json"


def entries():
    return json.loads(MANIFEST.read_text())["files"]


def test_every_entry_has_a_path_a_url_and_a_sha256_and_paths_are_unique():
    fs = entries()
    assert len(fs) >= 50, len(fs)
    for f in fs:
        assert f["path"] and f["url"].startswith("https://") and re.fullmatch(r"[0-9a-f]{64}", f["sha256"]), f["path"]
        assert not f["path"].startswith("/") and ".." not in f["path"].split("/"), f["path"]
    assert len({f["path"] for f in fs}) == len(fs)


def test_an_extracted_member_names_an_archive_entry_with_the_same_url_and_hash():
    fs = entries()
    by_path = {f["path"]: f for f in fs}
    members = [f for f in fs if f.get("member")]
    assert members, "no extracted entries: the check would pass on nothing"
    for f in members:
        archives = [a for a in fs if a["url"] == f["url"] and a["sha256"] == f["archive_sha256"] and a is not f]
        assert archives, f"{f['path']}: no archive entry with its url and archive_sha256"


def test_the_stale_samsung_page_is_gone_and_its_csvs_are_committed():
    assert not [f for f in entries() if f["path"].startswith("cl21a106kaynnne/")]
    for n in ("dcbias.csv", "esr.csv", "PROVENANCE.md"):
        assert (AFE / "models-open" / "cl21a106kaynnne" / n).is_file()


@pytest.mark.network
@pytest.mark.slow
def test_every_manifest_entry_fetches_and_hash_matches(tmp_path):
    r = subprocess.run([sys.executable, "-I", str(AFE / "tools" / "fetch_models.py"), "--models-dir", str(tmp_path),
                        "--manifest", str(MANIFEST)], capture_output=True, text=True, timeout=3000)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-400:]
    assert f"all {len(entries())} files verified" in r.stdout
