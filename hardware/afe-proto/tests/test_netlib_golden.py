"""The two boards' netlist builders, against text captured before the plumbing was shared."""
import pytest

from netlib_snapshot import GOLDEN, v1_text, v2_text


@pytest.mark.parametrize("name, fn", [("netlib_v1", v1_text), pytest.param("netlib_v2", v2_text, marks=pytest.mark.vendor)])
def test_builders_reproduce_the_golden_netlists(name, fn):
    want = (GOLDEN / f"{name}.txt").read_text()
    got = fn()
    assert len(want.splitlines()) > 150, "golden is suspiciously small; it would pass anything"
    assert got == want


def test_golden_covers_the_pieces_that_matter():
    t1, t2 = (GOLDEN / "netlib_v1.txt").read_text(), (GOLDEN / "netlib_v2.txt").read_text()
    for needle in ("variant legacy", "variant lowz2", "R3", "Cs3", "XSWI"):
        assert needle in t1, needle
    for needle in ("Exb", "Rnp", "coupling"):
        assert needle in t2, needle
