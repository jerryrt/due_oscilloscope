"""v2's scope on version 1's +-5 V range (v2/sim/scope/range5v.py, range5v.md): the closed-form half, board-free.

The ngspice half is `run.py --range 5v` (range5v/results); the test below only holds the profile table to the board values
and the arithmetic to the requirement text, with a mutant per claim so a green run cannot be a check that sees nothing.
"""
import importlib.util
from pathlib import Path

import pytest

SCOPE = Path(__file__).resolve().parents[1] / "v2" / "sim" / "scope"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCOPE / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def r5():
    return _load("range5v")


def figs(r5, **kw):
    v = {k: (tuple(x) if isinstance(x, (tuple, list)) else x) for k, x in r5.VALUES["5 V"].items()}
    v.update(kw)
    return r5.sweep("5 V", v, n=20_000)


def test_the_five_volt_values_pass_every_check(r5):
    bad = [n for n, ok, d in r5.verdicts(figs(r5)) if not ok]
    assert not bad, bad


def test_the_figures_are_the_ones_the_note_states(r5):
    f = figs(r5)
    assert f["a_nom"] == pytest.approx(0.2328, abs=5e-5) and f["voff_nom"] == pytest.approx(1.6295, abs=5e-5)
    assert f["rin_nom_k"] == pytest.approx(1003.6, abs=0.05)
    assert f["span_pct_FS_nom"] == pytest.approx(71.63, abs=0.01)


@pytest.mark.parametrize("what,kw", [
    ("R3 lost (REF not connected): no centre, the low margin goes", dict(R3=(10e6, 0.0))),
    ("R2 330k -> 300k: 1 % corners put the span under 70 %", dict(R2=(470e3, 300e3))),
    ("R1 770k -> 830k: Rin 1.07 Mohm", dict(R1=(470e3, 360e3))),
    ("a v2-old divider on the 5 V range: the pin leaves 0..AREF", dict(R1=(510e3, 30e3), R2=(1e6, 510e3), R3=(470e3, 200e3))),
])
def test_a_wrong_value_set_fails_a_check(r5, what, kw):
    assert [n for n, ok, d in r5.verdicts(figs(r5, **kw)) if not ok], what


def test_the_run_py_profile_holds_the_board_values_and_leaves_the_default_alone():
    src = (SCOPE / "run.py").read_text()
    # the 5v profile and the default P0 of netlib: the board's refs R1a.. are CH1 R101-R106 (v2/kicad/design.py) and the values below
    assert 'P0=dict(R1=(470e3, 300e3), R2=(470e3, 330e3), R3=(330e3, 0.0), C1=12e-12, Cn=30e-12)' in src
    assert 'RANGES["5vc"] = dict(RANGES["5v"], MUT_C1=33e-12, P0=dict(RANGES["5v"]["P0"], C1=18e-12, Cn=47e-12))' in src
    net = (SCOPE / "netlib.py").read_text()
    assert "R1=(510e3, 30e3)" in net and "C1=22e-12" in net and "Cn=12e-12" in net     # the design's own values are untouched
