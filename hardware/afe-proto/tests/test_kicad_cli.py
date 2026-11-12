"""kicad-cli in the image: the global library tables resolve, and a render is produced."""
import collections
import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.pcbnew

FIX = Path(__file__).resolve().parent / "fixtures"
SCH = FIX / "v1-34b2e51" / "kicad" / "afe-proto.kicad_sch"
PCB = FIX / "v2-8a1f7ac" / "v2-awg-bc96e334.kicad_pcb"


def erc(tmp_path, home):
    env = dict(os.environ, HOME=str(home))
    out = tmp_path / "erc.json"
    r = subprocess.run(["kicad-cli", "sch", "erc", "--format", "json", "-o", str(out), str(SCH)],
                       capture_output=True, text=True, env=env, timeout=250)
    assert out.exists(), r.stdout + r.stderr
    d = json.loads(out.read_text())
    return collections.Counter(v["type"] for s in d["sheets"] for v in s["violations"])


def test_erc_resolves_the_standard_libraries(tmp_path):
    c = erc(tmp_path, os.environ["HOME"])
    assert c["lib_symbol_issues"] == 0, c
    assert sum(c.values()) < 30, c          # 5 on 10.0.8 with the tables; 252 without


def test_the_same_erc_without_the_tables_does_fail_this_check(tmp_path):
    """The control: an empty home has no global tables, and the check above must see it."""
    empty = tmp_path / "emptyhome"
    empty.mkdir()
    c = erc(tmp_path, empty)
    assert c["lib_symbol_issues"] > 50, c


def test_a_render_is_produced(tmp_path):
    out = tmp_path / "r.png"
    r = subprocess.run(["kicad-cli", "pcb", "render", "-o", str(out), str(PCB)], capture_output=True,
                       text=True, timeout=250)
    assert r.returncode == 0 and out.exists(), r.stdout + r.stderr
    b = out.read_bytes()
    assert b[:8] == b"\x89PNG\r\n\x1a\n" and len(b) > 20_000, len(b)
