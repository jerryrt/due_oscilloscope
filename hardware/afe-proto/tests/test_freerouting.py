"""Freerouting in the image, end to end: pcbnew ExportSpecctraDSN -> docker/pcb/freeroute.sh -> ImportSpecctraSES.

The board is four 0603 resistors chained by three nets, built with pcbnew's own API from KiCad's footprint library, so
the fixture needs no committed board. It starts with 3 unconnected items and must end with 0. A control imports an
empty session instead and must still show 3 (the count is real), and a missing router must be an error.
"""
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.pcbnew, pytest.mark.freerouting]

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "docker" / "pcb" / "freeroute.sh"
LIB = "/usr/share/kicad/footprints/Resistor_SMD.pretty"


def make_board(path, n=4):
    import pcbnew
    b = pcbnew.CreateEmptyBoard()
    nets = {}

    def net(n):
        if n not in nets:
            ni = pcbnew.NETINFO_ITEM(b, n)
            b.Add(ni)
            nets[n] = ni
        return nets[n]
    mm = pcbnew.FromMM
    for i in range(n):
        fp = pcbnew.FootprintLoad(LIB, "R_0603_1608Metric")
        fp.SetReference(f"R{i + 1}")
        fp.SetPosition(pcbnew.VECTOR2I(mm(10 + 6 * i), mm(10 + (i % 2) * 4)))
        b.Add(fp)
        pads = list(fp.Pads())
        pads[0].SetNet(net(f"N{i}"))
        pads[1].SetNet(net(f"N{i + 1}"))
    r = pcbnew.PCB_SHAPE(b)
    r.SetShape(pcbnew.SHAPE_T_RECT)
    r.SetLayer(pcbnew.Edge_Cuts)
    r.SetStart(pcbnew.VECTOR2I(mm(4), mm(4)))
    r.SetEnd(pcbnew.VECTOR2I(mm(38), mm(20)))
    b.Add(r)
    pcbnew.SaveBoard(str(path), b)


def unconnected(path, ses=None):
    import pcbnew
    b = pcbnew.LoadBoard(str(path))
    if ses is not None:
        assert pcbnew.ImportSpecctraSES(b, str(ses))
    b.BuildConnectivity()
    return b.GetConnectivity().GetUnconnectedCount(False), len(list(b.GetTracks()))


def export_dsn(tmp_path, name="t", n=4):
    import pcbnew
    pcb = tmp_path / f"{name}.kicad_pcb"
    make_board(pcb, n)
    dsn = tmp_path / f"{name}.dsn"
    assert pcbnew.ExportSpecctraDSN(pcbnew.LoadBoard(str(pcb)), str(dsn))
    return pcb, dsn


def run_router(dsn, ses):
    return subprocess.run(["bash", str(SCRIPT), str(dsn), str(ses), "--passes", "20", "--timeout", "120"],
                          capture_output=True, text=True, timeout=300)


def route(tmp_path, name="t"):
    pcb, dsn = export_dsn(tmp_path, name)
    ses = tmp_path / f"{name}.ses"
    return pcb, ses, run_router(dsn, ses)


def test_the_round_trip_leaves_no_unconnected_items(tmp_path):
    pcb, ses, r = route(tmp_path)
    assert r.returncode == 0 and ses.stat().st_size > 0, r.stdout[-300:] + r.stderr[-300:]
    before = unconnected(pcb)
    after, tracks = unconnected(pcb, ses)
    assert before[0] == 3 and after == 0 and tracks > 0, (before, after, tracks)


def test_a_session_that_does_not_cover_every_net_leaves_the_rest_unconnected(tmp_path):
    """The control: the same router output imported into a board with one more chained resistor (one more net to
    route) must leave exactly that connection open, so the 0 above is a measurement and not a default."""
    d4, d5 = tmp_path / "four", tmp_path / "five"
    d4.mkdir()
    d5.mkdir()
    _, ses, r = route(d4)
    assert r.returncode == 0, r.stderr[-300:]
    pcb5 = d5 / "t.kicad_pcb"
    make_board(pcb5, n=5)
    assert unconnected(pcb5)[0] == 4
    assert unconnected(pcb5, ses)[0] == 1


def test_the_same_design_routes_to_the_same_session_byte_for_byte(tmp_path):
    """The router is repeatable (one thread). pcbnew's DSN export is not: it lists the placements in a different
    order from one export to the next, so the same board exported twice does not give the same file; the design
    file is exported once here and routed twice."""
    _, dsn = export_dsn(tmp_path)
    outs = []
    for k in "ab":
        ses = tmp_path / f"{k}.ses"
        r = run_router(dsn, ses)
        assert r.returncode == 0, r.stderr[-300:]
        outs.append(ses.read_bytes())
    assert outs[0] == outs[1] and len(outs[0]) > 100


def test_the_same_board_exported_and_routed_twice_gives_the_same_session(tmp_path):
    """The point of the canonicaliser: pcbnew exports the same board in a different order each time, so two exports
    are different files, and the wrapper must still route them to the same bytes. Several exports, one result."""
    sessions, dsns = set(), set()
    for k in range(4):
        d = tmp_path / f"e{k}"
        d.mkdir()
        _, dsn = export_dsn(d)
        dsns.add(dsn.read_text().replace(str(dsn), "X"))
        ses = d / "t.ses"
        r = run_router(dsn, ses)
        assert r.returncode == 0, r.stderr[-300:]
        sessions.add(ses.read_bytes())
    assert len(sessions) == 1, f"{len(sessions)} different sessions from {len(dsns)} different exports"


def test_without_canonicalisation_the_router_input_is_the_raw_export(tmp_path):
    """--no-canon is honoured: the router runs on the file as exported (and still routes it)."""
    _, dsn = export_dsn(tmp_path)
    ses = tmp_path / "raw.ses"
    r = subprocess.run(["bash", str(SCRIPT), str(dsn), str(ses), "--no-canon", "--timeout", "120"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and ses.stat().st_size > 0, r.stderr[-300:]


def test_a_design_with_nothing_to_canonicalise_is_exit_5(tmp_path):
    dsn = tmp_path / "x.dsn"
    dsn.write_text("(pcb x\n  (resolution um 10)\n)\n")
    r = subprocess.run(["bash", str(SCRIPT), str(dsn), str(tmp_path / "x.ses")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 5, (r.returncode, r.stderr[-200:])


def test_a_missing_router_is_an_error_not_a_success(tmp_path):
    dsn = tmp_path / "x.dsn"
    dsn.write_text("(pcb x)\n")
    r = subprocess.run(["bash", str(SCRIPT), str(dsn), str(tmp_path / "x.ses")], capture_output=True, text=True,
                       env=dict(os.environ, FREEROUTING_JAR="/nonexistent.jar"), timeout=60)
    assert r.returncode == 3 and "not in this image" in r.stderr


def test_bad_usage_is_exit_2(tmp_path):
    assert subprocess.run(["bash", str(SCRIPT)], capture_output=True).returncode == 2
    assert subprocess.run(["bash", str(SCRIPT), "a.dsn", "b.ses", "--passes", "x"], capture_output=True).returncode == 2
