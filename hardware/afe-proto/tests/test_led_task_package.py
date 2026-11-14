"""The status-LED intern package (v2/tasks/status-leds/make_package.py).

The package goes outside the project, so what it must not hold matters as much as what it must:
no vendor SPICE model, nothing that gives the answers away, and design files that are byte-identical
to the repository's so "nothing else on the board moved" can be marked against them. The netlist is
the one file that differs; the ngspice arm runs it as packaged.
"""
import filecmp
import subprocess
import sys
from pathlib import Path

import pytest

AFE = Path(__file__).resolve().parents[1]
TASK = AFE / "v2" / "tasks" / "status-leds"
sys.path.insert(0, str(TASK))
import make_package as mp  # noqa: E402

sys.path.insert(0, str(AFE))
from simtools import netlib_common as nc  # noqa: E402

# strings only the answer sheet or the vendor comparison carry; none may reach the intern
LEAKS = ["Expected answers", "answer sheet", "AREF trap", "0.3 mA step"]
OPEN = {f"{p}-open" for p in mp.OPEN_MODELS}


@pytest.fixture(scope="module")
def pkg(tmp_path_factory):
    out = tmp_path_factory.mktemp("pkg")
    subprocess.run([sys.executable, str(TASK / "make_package.py"), str(out), "--no-datasheets"],
                   check=True, capture_output=True, text=True)
    return out / mp.NAME


def files(root):
    return sorted(p for p in root.rglob("*") if p.is_file())


def test_every_listed_source_is_in_the_package_byte_for_byte(pkg):
    checked = 0
    for src, dst in mp.FILES:
        d = pkg / dst
        pairs = [(src, d)] if src.is_file() else [(s, d / s.relative_to(src)) for s in files(src)]
        for s, t in pairs:
            assert t.is_file(), t
            assert filecmp.cmp(s, t, shallow=False), t
            checked += 1
    assert checked >= 40, checked          # floor: the board, schematic, libraries and five models


def test_nothing_else_is_in_the_package(pkg):
    expected = set()
    for src, dst in mp.FILES:
        expected |= {Path(dst)} if src.is_file() else {Path(dst) / s.relative_to(src) for s in files(src)}
    assert {p.relative_to(pkg) for p in files(pkg)} == expected


def test_only_clean_room_models_and_no_answers_go_out(pkg):
    assert {p.name for p in (pkg / "models").iterdir()} == OPEN
    text_files = [p for p in files(pkg) if p.suffix in {".md", ".cir", ".lib", ".txt", ".csv"}]
    assert len(text_files) >= 15, len(text_files)
    for p in text_files:
        body = p.read_text(errors="replace")
        for s in LEAKS:
            assert s.lower() not in body.lower(), f"{p.relative_to(pkg)} carries {s!r}"
    assert not (pkg / "answer-sheet.md").exists()


def test_the_netlist_includes_the_clean_room_amplifier_only(pkg):
    net = (pkg / "sim" / "scope_v2.cir").read_text()
    incs = [l.split(None, 1)[1].strip() for l in net.splitlines() if l.lower().startswith(".include")]
    assert incs == ["../models/tph2502-open/tph2502.lib"] and "TPH2501" not in net
    assert (pkg / "sim" / incs[0]).resolve().is_file()
    xs = [l for l in net.splitlines() if l.startswith("XU")]
    assert len(xs) == 2 and all("TPH2502_OPEN" in l and "VSREF=3.3" in l for l in xs), xs


def test_the_board_finds_its_3d_stand_in_inside_the_package(pkg):
    board = pkg / "afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pcb"
    rel = [l.split('"')[1] for l in board.read_text().splitlines() if '(model "${KIPRJMOD}' in l]
    assert rel, "no project-relative model: the check would pass on nothing"
    for r in rel:
        assert (board.parent / r.replace("${KIPRJMOD}/", "")).resolve().is_file(), r


@pytest.mark.ngspice
def test_the_packaged_netlist_runs_and_keeps_the_dc_point(pkg, tmp_path):
    # v2/sim/scope/report.md: +1.0 V in reads 1.5797 V at the pin; 1 mV is a little over one code (806 uV)
    sim = pkg / "sim"
    out = nc.run_ng(str(sim), str(tmp_path), "t_", "op", (sim / "scope_v2.cir").read_text(), 240, mem="1G")
    vals = {k: float(v) for k, v in
            (l.replace(" ", "").split("=") for l in out.splitlines() if l.strip().startswith("v(") and "=" in l)}
    assert abs(vals["v(apin)"] - 1.5797) < 1e-3 and abs(vals["v(bpin)"] - 1.5797) < 1e-3, out[-1500:]
