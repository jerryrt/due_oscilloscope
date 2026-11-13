import numpy as np
import pytest

from simtools import pw2

DECK = """* x
Cin vin 0 6.0000e-06
Ccpo cpout 0 8.0000e-06
Cop outp 0 1.2000e-05
Con outn 0 1.6000e-05
Cfly cp cn 5.0000e-06
X1 cn cp cpout pg vin vin vin fbn fbp 0 outn outp 0 LM27762_TRANS
.options method=gear abstol=1e-3
.tran 5e-09 0.0013 0 2.5e-07 uic
.control
run
linearize v(outp) v(outn)
wrdata x.dat v(outp) v(outn)
.endc
.end
"""


def test_every_lumped_cap_becomes_its_physical_parts_with_the_capacitance_conserved():
    d = pw2.inject_l(pw2.strip_control(DECK))
    for node, parts, total in (("vin", ("C401", "C402"), 6e-6), ("cpout", ("C403", "C404"), 8e-6),
                               ("outp", ("C405", "C406"), 12e-6), ("outn", ("C407", "C408"), 16e-6)):
        cs = [float(l.split()[3]) for l in d.splitlines() if l.split()[0] in [f"C{p}" for p in parts]]
        assert len(cs) == 2 and sum(cs) == pytest.approx(total, rel=1e-3)
    assert "CC409 cp C409_1 5.0000e-06" in d
    assert "Cin " not in d and "Cfly " not in d


def test_l_follows_the_distance_model_and_scales():
    d = pw2.inject_l(DECK)
    l405 = float(next(l for l in d.splitlines() if l.startswith("LC405 ")).split()[3])
    assert l405 == pytest.approx((2.2 + 0.87 * 2.33) * 1e-9, rel=1e-3)
    d2 = pw2.inject_l(DECK, scale=2.0)
    assert float(next(l for l in d2.splitlines() if l.startswith("LC405 ")).split()[3]) == pytest.approx(2 * l405, rel=1e-3)
    assert "LC405 " not in pw2.inject_l(DECK, scale=0.0)                       # the ideal case has no inductor at all


def test_the_control_adds_inductance_to_one_cap_only():
    base = pw2.inject_l(DECK)
    ctl = pw2.inject_l(DECK, extra_nh={"C405": 100.0})
    def l(d, n):
        return float(next(x for x in d.splitlines() if x.startswith(f"L{n} ")).split()[3])
    assert l(ctl, "C405") - l(base, "C405") == pytest.approx(100e-9, rel=1e-3)
    assert l(ctl, "C406") == l(base, "C406")


def test_a_deck_missing_a_lumped_line_is_an_error_not_a_silent_pass():
    with pytest.raises(ValueError, match="Cop"):
        pw2.inject_l(DECK.replace("Cop outp 0 1.2000e-05\n", ""))


def test_the_control_block_is_removed_and_the_analysis_kept():
    d = pw2.strip_control(DECK)
    assert ".control" not in d and "wrdata" not in d and ".tran 5e-09 0.0013" in d and d.rstrip().endswith(".end")


def _wave(tstop, f=1.4e6, a=0.2e-3):
    t = np.linspace(0, tstop, 20000)
    return t, {"outp": 3.4 + a * np.sin(2 * np.pi * f * t), "outn": -2.05 + 0.5 * a * np.sin(2 * np.pi * f * t),
               "vin": 5 + 10e-3 * np.sin(2 * np.pi * f * t), "cp": 5 + 0.3 * np.sign(np.sin(2 * np.pi * f * t))}


def test_analyse_reads_the_ripple_mean_and_pump_frequency_off_a_known_wave():
    t, v = _wave(1.3e-3)
    r = pw2.analyse(t, v, 1.3e-3)
    assert r.status == "OK" and r.outp_pp_mv == pytest.approx(0.4, rel=0.02) and r.outn_pp_mv == pytest.approx(0.2, rel=0.02)
    assert r.vin_pp_mv == pytest.approx(20.0, rel=0.02) and r.pump_hz == pytest.approx(1.4e6, rel=0.02)
    assert r.outp_mean == pytest.approx(3.4, abs=1e-3)


def test_a_run_that_stopped_early_is_no_converge_with_no_figures():
    t, v = _wave(0.4e-3)
    r = pw2.analyse(t, v, 1.3e-3)
    assert r.status == "NO_CONVERGE" and r.outp_pp_mv is None and r.tstop_reached == pytest.approx(0.4e-3)


def test_the_csv_stand_in_reproduces_the_numbers_kvm_02_recorded():
    S = pw2.samsung_from_csv()
    assert S["esr"](2e6) == pytest.approx(4.04e-3, rel=0.01)
    assert S["k"](3.4) * 1 == pytest.approx(0.682, abs=0.003)          # PROVENANCE.md: k(3.4 V) = 0.682
    assert S["k"](2.06) == pytest.approx(0.865, abs=0.003) and S["k"](5.0) == pytest.approx(0.497, abs=0.003)
    assert S["k"](-3.4) == S["k"](3.4)                                   # |V|
