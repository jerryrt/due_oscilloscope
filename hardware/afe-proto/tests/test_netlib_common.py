"""The shared plumbing, driven through both boards' own netlib wrappers."""
import re

import numpy as np
import pytest

from netlib_snapshot import load as load_netlib
from simtools import netlib_common as C

pytestmark = pytest.mark.ngspice

NETLISTS = [("sim/scope/netlib.py", "nl_v1"), ("v2/sim/scope/netlib.py", "nl_v2")]


def deck(nl, name):
    return f"""wrap test
V1 in 0 dc 0
R1 in out 1k
R2 out 0 1k
.control
dc V1 0 2 1
wrdata {nl.wr(name, 'd')} v(out)
.endc
.end
"""


@pytest.mark.parametrize("rel, mod", NETLISTS)
def test_wrapper_runs_a_deck_and_loads_what_wrdata_wrote(rel, mod, tmp_path, monkeypatch):
    nl = load_netlib(rel, mod)
    monkeypatch.setattr(nl, "NETD", str(tmp_path / "netlists"))
    monkeypatch.setattr(nl, "WORK", str(tmp_path / "work"))
    monkeypatch.setattr(nl, "WORK_REL", "../work")
    monkeypatch.setattr(nl, "PFX", "p_")        # parallel sections prefix their files; the wrappers must honour it
    out = nl.run_ng("t", deck(nl, "t"), timeout=60)
    d = nl.load("t", "d")
    assert np.allclose(d[:, 1], d[:, 0] / 2)               # divider of two equal resistors
    assert "Error" not in out
    assert (tmp_path / "netlists" / "p_t.cir").exists() and (tmp_path / "work" / "p_t_d.dat").exists()
    assert re.search(r"ngspice", nl.ngspice_version(), re.I)


def test_v1_and_v2_keep_their_own_load_shape(tmp_path):
    f = tmp_path / "x_k.dat"
    f.write_text("1 2\n")
    assert C.load(str(tmp_path), "", "x", "k").shape == (2,)          # v1: bare loadtxt
    assert C.load(str(tmp_path), "", "x", "k", atleast_2d=True).shape == (1, 2)   # v2


@pytest.mark.jobcap
def test_a_runaway_deck_raises_instead_of_running_on(tmp_path):
    big = "big\nV1 in 0 PULSE(0 1 0 1n 1n 5u 10u)\nR1 in out 1k\nC1 out 0 1n\n.tran 1p 100u\n.control\nrun\n.endc\n.end\n"
    with pytest.raises(C.RunError, match="memory cap"):
        C.run_ng(str(tmp_path), str(tmp_path), "", "big", big, 60, mem="30M")
