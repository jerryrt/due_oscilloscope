import pytest

from simtools import netlib_common as C

DECK = """t
V1 in 0 dc 0
R1 in out 1k
R2 out 0 1k
.control
dc V1 0 2 1
wrdata ../work/x.dat v(out) i(V1)
let a = v(in) - v(OUT)
.endc
.end
"""


def test_the_save_lists_exactly_the_vectors_the_control_block_reads_lowercased():
    assert C.derive_save(DECK) == ["v(out)", "i(v1)", "v(in)"]


def test_with_save_puts_the_save_before_end_and_nowhere_else():
    t = C.with_save(DECK)
    assert t.rstrip().endswith(".save v(out) i(v1) v(in)\n.end") and t.count(".save") == 1


def test_a_batch_deck_without_a_control_block_is_unchanged():
    d = "t\nR1 a 0 1\n.op\n.end\n"
    assert C.with_save(d) == d


def test_a_control_block_that_reads_nothing_is_refused():
    with pytest.raises(ValueError, match="nothing to .save"):
        C.with_save("t\nR1 a 0 1\n.control\nop\n.endc\n.end\n")


def test_a_deck_with_its_own_save_is_refused():
    with pytest.raises(ValueError, match="own .save"):
        C.with_save(DECK.replace(".end\n", ".save all\n.end\n"))


@pytest.mark.ngspice
def test_the_derived_save_is_what_ngspice_keeps(tmp_path):
    """Run the derived deck with a raw file: it holds the vectors the control block reads and not the other nodes."""
    import subprocess
    from simtools.raw import read_raw
    deck = ("t\nV1 in 0 PULSE(0 1 0 1n 1n 5u 10u)\nR1 in out 1k\nC1 out 0 1n\nR2 out x 1k\nC2 x 0 1n\n"
            ".tran 10n 20u\n.control\nrun\nwrdata o.dat v(out)\n.endc\n.end\n")
    (tmp_path / "d.cir").write_text(C.with_save(deck))
    r = subprocess.run(["ngspice", "-b", "-r", "d.raw", "d.cir"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0
    names = next(iter(read_raw(tmp_path / "d.raw").values())).names
    assert "v(out)" in names and "v(x)" not in names and "v(in)" not in names, names


def test_a_noise_analysis_deck_is_left_alone():
    d = "t\nV1 in 0 dc 0 ac 1\nR1 in out 1k\nR2 out 0 1k\n.control\nnoise v(out) V1 dec 5 10 1e6\nsetplot noise1\nwrdata o.dat onoise_spectrum\n.endc\n.end\n"
    assert C.with_save(d) == d
