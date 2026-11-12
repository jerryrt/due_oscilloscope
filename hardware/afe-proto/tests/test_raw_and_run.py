import numpy as np
import pytest

from simtools import ngspice_run as nr
from simtools.raw import read_raw

pytestmark = pytest.mark.ngspice

DECK = """rc ladder
V1 in 0 PULSE(0 1 0 1n 1n 5u 10u) AC 1
R1 in out {r}
C1 out 0 1n
R2 out x 1k
C2 x 0 1n
.tran 0.1u 20u
.ac dec 5 1k 1meg
.end
"""


def deck(r=1000):
    return DECK.replace("{r}", str(r))


def test_run_returns_only_the_saved_vectors_and_the_right_physics(tmp_path):
    out = nr.run(deck(), save=["v(out)", "i(V1)"], workdir=tmp_path, name="rc", mem="1G", timeout=60)
    plots = out.plots()
    ac = next(p for p in plots.values() if "complex" in p.flags)
    assert "v(x)" not in ac and "v(out)" in ac
    # closed form of the two-section RC ladder, H = 1/(1 + 3x + x^2), x = j w R C
    x = 2j * np.pi * ac["frequency"].real * 1e3 * 1e-9
    assert np.allclose(ac["v(out)"], (1 + x) / (1 + 3 * x + x * x), rtol=1e-6)
    tr = next(p for p in plots.values() if p.name == "Transient Analysis")
    assert tr["time"][0] == 0 and 0.5 < tr["v(out)"].max() < 1.0
    assert out.peak_rss_bytes and out.wall_s is not None


def test_corner_reaches_the_netlist(tmp_path):
    a = nr.run(deck("{rv}"), save=["v(out)"], workdir=tmp_path, name="a", corner={"rv": 1000}, timeout=60)
    b = nr.run(deck("{rv}"), save=["v(out)"], workdir=tmp_path, name="b", corner={"rv": 100000}, timeout=60)
    hz = lambda r: next(p for p in r.plots().values() if "complex" in p.flags)
    assert abs(hz(b)["v(out)"][-1]) < abs(hz(a)["v(out)"][-1])   # larger R, more roll-off at 1 MHz


def test_raw_reader_matches_ngspice_wrdata(tmp_path):
    """The reader against ngspice's own text output of the same vector."""
    text = nr.prepare(deck(), ["v(out)"]).replace(".end", ".control\nrun\nset wr_vecnames\nwrdata w.dat tran.v(out)\n.endc\n.end")
    (tmp_path / "w.cir").write_text(text)
    import subprocess
    subprocess.run(["ngspice", "-b", "-r", "w.raw", "w.cir"], cwd=tmp_path, capture_output=True, timeout=60, check=True)
    ref = np.loadtxt(tmp_path / "w.dat", skiprows=1)
    tr = next(p for p in read_raw(tmp_path / "w.raw").values() if p.name == "Transient Analysis")
    assert np.allclose(tr["time"], ref[:, 0], rtol=1e-6, atol=1e-15)
    assert np.allclose(tr["v(out)"], ref[:, 1], rtol=1e-6, atol=1e-12)


def test_raw_reader_refuses_a_truncated_file(tmp_path):
    out = nr.run(deck(), save=["v(out)"], workdir=tmp_path, name="t", timeout=60)
    data = out.raw_path.read_bytes()
    out.raw_path.write_bytes(data[:-40])
    with pytest.raises(ValueError, match="truncated"):
        read_raw(out.raw_path)


@pytest.mark.parametrize("bad, why", [
    (dict(save=[]), "required"),
    (dict(save=["all"]), "bad .save"),
    (dict(save=["v(out)"], corner={"t": [1, 2]}), "one corner"),
])
def test_arguments_that_break_the_rules_are_refused(tmp_path, bad, why):
    with pytest.raises(nr.DeckError, match=why):
        nr.prepare(deck(), **bad)


@pytest.mark.parametrize("line", [".save all", "save all", ".options savecurrents", ".step param r 1 2 1",
                                  ".save v(out)"])
def test_a_deck_that_saves_everything_or_steps_is_refused(line):
    d = deck().replace(".end", line + "\n.end")
    with pytest.raises(nr.DeckError):
        nr.prepare(d, ["v(out)"])


def test_cap_kill_names_the_corner(tmp_path):
    big = "big\nV1 in 0 PULSE(0 1 0 1n 1n 5u 10u)\nR1 in out 1k\nC1 out 0 1n\n.tran 1p 100u\n.end\n"
    with pytest.raises(nr.RunError, match="memory cap"):
        nr.run(big, save=["v(out)"], workdir=tmp_path, name="big", corner={"k": 1}, mem="30M", timeout=60)


def test_a_raw_file_with_unrequested_vectors_is_refused_after_the_run(tmp_path, monkeypatch):
    """The post-run check, reached by sabotaging prepare() so ngspice saves every node."""
    monkeypatch.setattr(nr, "prepare", lambda d, s, c=None: d)
    with pytest.raises(nr.RunError, match="beyond the .save list"):
        nr.run(deck(), save=["v(out)"], workdir=tmp_path, name="all", timeout=60)
