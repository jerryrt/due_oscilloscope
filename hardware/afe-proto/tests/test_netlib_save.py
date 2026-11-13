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


NOISE_DECK = """noise test
V1 in 0 dc 0 ac 1
R1 in out 10k
C1 out 0 1n
R2 out x 10k
C2 x 0 1n
.control
noise v(x) V1 dec 20 10 1e8
setplot noise1
wrdata o.dat onoise_spectrum
setplot noise2
print onoise_total
.endc
.end
"""
NOISE_PEAK_BUDGET_KB = 100_000          # a noise deck is small: 100 MB is a loose ceiling, not a measurement of it


@pytest.mark.ngspice
@pytest.mark.hostcap
def test_a_noise_deck_runs_unrestricted_under_the_cap_and_stays_under_its_budget(tmp_path):
    """Noise decks are exempt from the .save restriction (ngspice aborts the analysis under one), so the cap
    and a peak budget are what bound them."""
    import sys
    from simtools import capped
    if not capped.available():
        pytest.skip("no capped runner")
    (tmp_path / "n.cir").write_text(NOISE_DECK)
    r = capped.run(["ngspice", "-b", "n.cir"], mem="1G", timeout=60, cwd=tmp_path)
    assert r.returncode == 0 and (tmp_path / "o.dat").exists() and "onoise_total" in r.stdout + r.stderr, r.stdout[-300:]
    kb = r.peak_rss_bytes // 1024
    assert kb < NOISE_PEAK_BUDGET_KB, kb
    assert kb > 1_000, kb                 # and a budget of 1 MB would have failed: the measurement is real
