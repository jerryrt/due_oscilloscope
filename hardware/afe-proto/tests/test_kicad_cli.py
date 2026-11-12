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


MODEL_DIR = Path(os.environ.get("KICAD10_3DMODEL_DIR", "/usr/share/kicad/3dmodels"))
MODEL_REF = __import__("re").compile(r'\(model "\$\{KICAD\d*_3DMODEL_DIR\}/([^"]+)"')


# Models a board names that KiCad's own 3D library does not contain (checked in 10.0.7 and 10.0.8: the
# package has Package_SON.3dshapes but no file of this name). The footprint's model link dangles, so
# those boards render this part without a body. Listed so it is visible and so it cannot grow
# unnoticed; the second test fails if the library ever gains the file and the entry is stale.
KNOWN_UNRESOLVED = {"Package_SON.3dshapes/WSON-12-1EP_3x2mm_P0.5mm_EP1x2.65.step"}


def _refs():
    boards = list((Path(__file__).resolve().parents[1]).rglob("*.kicad_pcb"))
    assert len(boards) >= 5, f"{len(boards)} boards scanned; the scope moved"
    refs = {m for b in boards for m in MODEL_REF.findall(b.read_text())}
    assert len(refs) >= 10, refs
    return refs


def test_every_3d_model_a_repository_board_names_resolves():
    """The image carries only the 3D models the boards use (docker/pcb/3dmodels.txt); a board that
    starts using another must fail here until its path is added there."""
    missing = sorted(r for r in _refs() if not (MODEL_DIR / r).is_file() and r not in KNOWN_UNRESOLVED)
    assert not missing, missing


def test_the_known_unresolved_models_really_are_missing():
    present = sorted(r for r in KNOWN_UNRESOLVED if (MODEL_DIR / r).is_file())
    assert not present, f"the library now has {present}: remove it from KNOWN_UNRESOLVED and add it to docker/pcb/3dmodels.txt"
    assert KNOWN_UNRESOLVED <= _refs(), "a known-unresolved model is no longer referenced by any board"


def _step_products(tmp_path, model_dir):
    out = tmp_path / "b.step"
    env = dict(os.environ, KICAD10_3DMODEL_DIR=str(model_dir))
    r = subprocess.run(["kicad-cli", "pcb", "export", "step", "-o", str(out), str(PCB)],
                       capture_output=True, text=True, env=env, timeout=250)
    assert out.exists(), r.stdout + r.stderr
    return out.stat().st_size, __import__("re").findall(r"PRODUCT\('([^']*)'", out.read_text(errors="replace"))


def test_the_3d_export_carries_named_bodies(tmp_path):
    """Gate 3's review needs real bodies, not just a render that exists: the STEP export names each model."""
    size, names = _step_products(tmp_path, MODEL_DIR)
    assert "BNC_Amphenol_B6252HB-NPP3G-50_Horizontal" in names, sorted(set(names))[:10]
    assert any(n.startswith("PinSocket_") for n in names)
    assert size > 1_000_000


def test_the_same_export_without_the_models_has_no_bodies(tmp_path):
    """The control: with the model directory pointed at nothing the named bodies must vanish."""
    size, names = _step_products(tmp_path, tmp_path / "nothing-here")
    assert "BNC_Amphenol_B6252HB-NPP3G-50_Horizontal" not in names
    assert size < 1_000_000
