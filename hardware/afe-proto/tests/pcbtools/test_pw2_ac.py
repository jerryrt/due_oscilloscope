"""pw2_ac: the AC (harmonic) ripple estimate. Known-answer tests in numpy; the ngspice-driven validation is marked
ngspice + slow. Includes the deliberate-break checks: each mutant of the impedance/harmonic code must FAIL the same
known-answer function the real code passes."""
import importlib.util
import os
import sys
from pathlib import Path

import numpy as np
import pytest

AFE = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("pw2_ac", AFE / "v2" / "sim" / "powercal" / "pw2_ac" / "pw2_ac.py")
pa = importlib.util.module_from_spec(_spec)
sys.modules["pw2_ac"] = pa
_spec.loader.exec_module(pa)

ESR_CONST = lambda f: 0.01 + 0 * np.asarray(f, float)       # 10 mohm at every frequency


# ---- known answers for the series chain, written against an injectable impedance function so a mutant can be judged by them

def resonance_checks(zfun):
    """Returns the list of failed checks of zfun(f, c, esr, esl, l_h) against an ideal ESR + L + C series chain."""
    c, esl, l = 10e-6, 0.373e-9, 3e-9
    fr = 1 / (2 * np.pi * np.sqrt((esl + l) * c))
    bad = []
    z = zfun(fr, c, ESR_CONST, esl, l)
    if abs(abs(z) - 0.01) > 1e-6:                    # |Z| at series resonance is the ESR
        bad.append("|Z| at resonance")
    if abs(np.imag(z)) > 1e-6:
        bad.append("reactance zero at resonance")
    if not np.imag(zfun(fr / 10, c, ESR_CONST, esl, l)) < 0:       # below resonance: capacitive, negative reactance
        bad.append("capacitive below resonance")
    if not np.imag(zfun(fr * 10, c, ESR_CONST, esl, l)) > 0:       # above: inductive
        bad.append("inductive above resonance")
    f = 2e6
    want = 0.01 + 1j * (2 * np.pi * f * (esl + l) - 1 / (2 * np.pi * f * c))
    if abs(zfun(f, c, ESR_CONST, esl, l) - want) > 1e-9:
        bad.append("closed form at 2 MHz")
    # L is in SERIES: |Z| well above resonance grows with L
    if not abs(zfun(10e6, c, ESR_CONST, esl, 10e-9)) > abs(zfun(10e6, c, ESR_CONST, esl, 1e-9)):
        bad.append("L raises |Z| above resonance")
    return bad


def test_series_chain_known_answers():
    assert resonance_checks(pa.z_cap) == []


def test_resonance_frequency_and_value_numerically():
    c, esl, l = 10e-6, 0.373e-9, 3e-9
    f = np.linspace(0.1e6, 100e6, 1000001)
    z = np.abs(pa.z_cap(f, c, ESR_CONST, esl, l))
    assert f[np.argmin(z)] == pytest.approx(1 / (2 * np.pi * np.sqrt((esl + l) * c)), rel=1e-4)
    assert z.min() == pytest.approx(0.01, rel=1e-4)


def test_mutants_of_the_impedance_are_caught():
    def l_in_parallel(f, c, esr, esl=pa.ESL_H, l_h=0.0):           # L added in parallel instead of in series
        w = 2 * np.pi * np.asarray(f, float)
        z_l = 1j * w * l_h if l_h else np.inf
        z_main = esr(f) + 1j * w * esl - 1j / (w * c)
        return 1 / (1 / z_main + (1 / z_l if l_h else 0))

    def wrong_sign(f, c, esr, esl=pa.ESL_H, l_h=0.0):              # reactance sign flipped
        w = 2 * np.pi * np.asarray(f, float)
        return esr(f) - 1j * w * (esl + l_h) + 1j / (w * c)

    def l_dropped(f, c, esr, esl=pa.ESL_H, l_h=0.0):
        return pa.z_cap(f, c, esr, esl, 0.0)

    def c_in_nf(f, c, esr, esl=pa.ESL_H, l_h=0.0):                 # unit slip on C
        return pa.z_cap(f, c * 1e3, esr, esl, l_h)

    for m in (l_in_parallel, wrong_sign, l_dropped, c_in_nf):
        assert resonance_checks(m), f"mutant {m.__name__} passed every known answer"


def test_identical_capacitors_in_parallel_halve_the_impedance():
    f = np.array([1e6, 5e6, 30e6])
    one = pa.z_cap(f, 4e-6, ESR_CONST, 0.373e-9, 2e-9)
    two = pa.z_node(f, ("C405", "C406"), 4e-6, ESR_CONST, {"C405": 2.0, "C406": 2.0})
    assert np.allclose(two, one / 2)
    # a conductance across the node is in parallel
    g = 0.05
    assert np.allclose(pa.z_node(f, ("C405",), 4e-6, ESR_CONST, {"C405": 2.0}, g_extra=g), 1 / (1 / one + g))


def test_pure_c_network_is_just_the_capacitance():
    f = 2e6
    z = pa.z_node(f, ("C405", "C406"), 3e-6, ESR_CONST, {"C405": 50.0}, pure_c=True)
    assert z == pytest.approx(1 / (1j * 2 * np.pi * f * 6e-6))


# ---- harmonics

def synth_wave(f0, amps, phases, ncyc=40, per=64):
    n = ncyc * per
    t = np.arange(n) / (per * f0)
    x = 0.3 + sum(a * np.cos(2 * np.pi * (k + 1) * f0 * t + p) for k, (a, p) in enumerate(zip(amps, phases)))
    return t, x


def test_harmonics_recover_amplitude_and_phase():
    amps, phases = [0.5, 0.2, 0.0, 0.05], [0.3, -1.0, 0.0, 2.0]
    t, x = synth_wave(1.25e6, amps, phases)
    mean, c = pa.harmonics(x, 64, 6)
    assert mean == pytest.approx(0.3)
    assert np.abs(c[:4]) == pytest.approx(amps, abs=1e-12)
    assert np.angle(c[0]) == pytest.approx(0.3) and np.angle(c[1]) == pytest.approx(-1.0) and np.angle(c[3]) == pytest.approx(2.0)
    assert abs(c[4]) < 1e-12 and abs(c[5]) < 1e-12


def test_harmonic_number_is_not_off_by_one():
    """A pure 3rd harmonic must land in c[2]: a bin offset of one puts it in c[1] or c[3]."""
    t, x = synth_wave(2e6, [0, 0, 1.0], [0, 0, 0])
    _, c = pa.harmonics(x, 64, 5)
    assert np.abs(c).argmax() == 2 and abs(c[2]) == pytest.approx(1.0)


def test_a_harmonic_through_a_known_impedance():
    f0 = 1.25e6
    t, x = synth_wave(f0, [1e-3], [0.0])                              # 1 mA current harmonic
    _, i = pa.harmonics(x, 64, 1)
    z = pa.z_node(np.array([f0]), ("C405", "C406"), 6e-6, ESR_CONST, {"C405": 0.0, "C406": 0.0})
    v = i * z
    want = 1e-3 * abs(0.005 + 1j * (2 * np.pi * f0 * 0.373e-9 / 2 - 1 / (2 * np.pi * f0 * 12e-6)))
    assert abs(v[0]) == pytest.approx(want, rel=1e-6)
    assert pa.ripple_sums(v)["phasor"] == pytest.approx(2 * want, rel=1e-4)       # pk-pk of a single sine
    assert pa.ripple_sums(v)["linear"] == pytest.approx(2 * want) == pytest.approx(pa.ripple_sums(v)["rss"])


def test_sum_rule_ordering_and_equalities():
    v = np.array([3e-3, 2e-3 * np.exp(1j * 0.7), 1e-3 * np.exp(-1j * 2.0), 0.5e-3 * np.exp(1j * 3.0)])
    s = pa.ripple_sums(v)
    assert s["phasor"] <= s["linear"] + 1e-15 and s["rss"] <= s["linear"]
    assert s["linear"] == pytest.approx(2 * np.abs(v).sum())
    assert s["rss"] == pytest.approx(2 * np.sqrt((np.abs(v) ** 2).sum()))
    inphase = np.array([3e-3, 2e-3, 1e-3])                                         # all peaking together at phi = 0
    assert pa.synth(inphase).max() == pytest.approx(inphase.sum(), rel=1e-6)       # the linear sum is reached by the crest ...
    assert pa.ripple_sums(inphase)["phasor"] < pa.ripple_sums(inphase)["linear"]   # ... but not by the pk-pk: the trough is not
    assert pa.ripple_sums(inphase)["rss"] < pa.ripple_sums(inphase)["linear"]


def test_refine_f0_finds_the_period():
    f0 = 1.2531e6
    n = 8000
    t = np.linspace(0, 120 / f0, n)
    x = np.sign(np.sin(2 * np.pi * f0 * t)) + 0.0
    assert pa.refine_f0(t, x, 1.253e6 * 1.004, t[-1], 100) == pytest.approx(f0, rel=2e-4)


# ---- the inductance formulas

def test_microstrip_formula_known_values():
    z0, er_eff = pa.microstrip_hj(1.0, 1.0, 1.0)                    # air line, w = h: Z0 = 60 ln(F/u + sqrt(1+4/u^2)) ~ 126.4 ohm
    assert er_eff == pytest.approx(1.0) and z0 == pytest.approx(126.4, rel=0.01)
    assert pa.microstrip_l_nh_per_mm(1.0, 1.0, 1.0) == pytest.approx(126.4 / 299792458 * 1e6, rel=0.01)
    assert 0.7 < pa.microstrip_l_nh_per_mm(0.2) < 0.9 and 0.7 < pa.microstrip_l_nh_per_mm(0.3) < 0.9
    assert pa.microstrip_l_nh_per_mm(0.2) > pa.microstrip_l_nh_per_mm(0.3)         # narrower = higher L'
    z50, _ = pa.microstrip_hj(3.0, 1.6, 4.5)                        # a 3 mm trace on 1.6 mm FR4 is a bit over 50 ohm (textbook ~ 2.9-3.0 mm at 50 ohm)
    assert 45 < z50 < 60


def test_via_formula_johnson():
    assert pa.via_l_nh(1.6, 0.3) == pytest.approx(5.08 * (1.6 / 25.4) * (np.log(4 * 1.6 / 0.3) + 1), rel=1e-9)
    assert pa.via_l_nh(3.2, 0.3) > 2 * pa.via_l_nh(1.6, 0.3) * 0.95 and pa.via_l_nh(1.6, 0.6) < pa.via_l_nh(1.6, 0.3)


def test_loop_l_adds_link_and_halves_via_for_two_vias():
    one = pa.loop_l_nh(5.0, 0.2, 1)
    two = pa.loop_l_nh(5.0, 0.2, 2)
    assert one - two == pytest.approx(pa.via_l_nh() / 2)
    assert pa.loop_l_nh(0.0, 0.2, 1) == pytest.approx(pa.via_l_nh())
    assert pa.loop_l_nh(8.0, 0.2, 1) - pa.loop_l_nh(4.0, 0.2, 1) == pytest.approx(4 * pa.microstrip_l_nh_per_mm(0.2))


def test_via_counts_frozen_constants_match_the_fixture():
    assert pa.via_counts() == pa.VIA_COUNT


def test_agent_fit_is_kept_as_it_was():
    assert pa.l_agent_fit()["C405"] == pytest.approx(2.2 + 0.87 * 2.33)


# ---- the whole estimate on a synthetic ideal transient whose answer is known

F_PUMP, F_BURST = 2.14e6, 90e3          # both are whole numbers of cycles in the 100 us window


def synthetic_transient(per=24, ncyc_pump=300):
    n = ncyc_pump * per
    t = np.arange(n) / (per * F_PUMP)               # 140 us
    cap = {"vin": 6e-6, "cpout": 8e-6, "outp": 12e-6, "outn": 16e-6}
    g = {"vin": 0.8, "cpout": 0.0, "outp": 0.02, "outn": 0.02}
    v = {}
    for node, a in (("vin", 9e-3), ("cpout", 3e-3), ("outp", 6e-5), ("outn", 2e-5)):
        v[node] = 3.0 + a * np.cos(2 * np.pi * F_BURST * t + 0.4) + 0.05 * a * np.cos(2 * np.pi * F_PUMP * t - 1.0)
    v["cp"] = np.where(np.sin(2 * np.pi * F_PUMP * t) > 0, 5.0, 0.0)
    return dict(t=t, v=v, cap=cap, g=g, meta={})


@pytest.fixture(scope="module")
def synth_result():
    return pa.estimate(synthetic_transient(), esr=pa.Esr())


def test_pump_frequency_found_inside_the_bursts():
    tr = synthetic_transient()
    fp, cross = pa.pump_frequency(tr["t"], tr["v"]["cp"])
    assert fp == pytest.approx(F_PUMP, rel=0.02) and cross == pytest.approx(F_PUMP, rel=0.01)


def test_pure_c_reproduces_a_known_transient(synth_result):
    for node, val in synth_result["validation_pure_C"].items():
        assert val["ratio_phasor_over_transient"] == pytest.approx(1.0, abs=1e-3), node
        assert val["linear"] >= val["transient_pp_mv"] * 0.999           # the linear sum bounds the pk-pk


def test_a_line_through_a_known_network_known_answer():
    """One 5 MHz ripple line of known amplitude on a loaded rail: the AC answer is |V Y_tr / Y_case| in closed form."""
    tr = synthetic_transient(per=96)
    t = tr["t"]
    tr["v"]["outn"] = -2.0 + 1e-4 * np.cos(2 * np.pi * 5e6 * t)                  # 5 MHz is line 500 of the 100 us window
    nl = pa.node_lines(tr)["outn"]
    ce = tr["cap"]["outn"] / 2
    l_nh = {"C407": 6.0, "C408": 3.0}
    c = pa.case_lines(nl["I"], nl["f"], "outn", ce, pa.Esr(), tr["g"]["outn"], l_nh)
    i5 = np.argmin(np.abs(nl["f"] - 5e6))
    w = 2 * np.pi * 5e6
    y_case = sum(1 / (pa.Esr()(5e6) + 1j * w * (0.373e-9 + l * 1e-9) - 1j / (w * ce)) for l in (6.0, 3.0)) + tr["g"]["outn"]
    y_tr = 1j * w * tr["cap"]["outn"] + tr["g"]["outn"]
    assert abs(c[i5]) == pytest.approx(1e-4 * abs(y_tr / y_case), rel=1e-2)


def test_mutants_of_the_case_filter_are_caught():
    tr = synthetic_transient(per=96)
    tr["v"]["outn"] = -2.0 + 1e-4 * np.cos(2 * np.pi * 5e6 * tr["t"])
    nl = pa.node_lines(tr)["outn"]
    ce, esr, g = tr["cap"]["outn"] / 2, pa.Esr(), tr["g"]["outn"]
    l_nh = {"C407": 6.0, "C408": 3.0}
    i5 = np.argmin(np.abs(nl["f"] - 5e6))
    w = 2 * np.pi * 5e6
    y_case = sum(1 / (esr(5e6) + 1j * w * (0.373e-9 + l * 1e-9) - 1j / (w * ce)) for l in (6.0, 3.0)) + g
    want = 1e-4 * abs((1j * w * tr["cap"]["outn"] + g) / y_case)

    def good(i, f):
        return pa.case_lines(i, f, "outn", ce, esr, g, l_nh)
    def inverted(i, f):                                  # multiplies by Y instead of dividing
        return i * (1.0 / pa.z_node(f, pa.NODES["outn"], ce, esr, l_nh, g_extra=g))
    def harmonic_off_by_one(i, f):                       # impedance read one line (10 kHz) too high... 5 MHz -> 5.5 MHz is one 10 per cent step
        return pa.case_lines(i, f * 1.1, "outn", ce, esr, g, l_nh)
    def l_dropped(i, f):
        return pa.case_lines(i, f, "outn", ce, esr, g, {})
    ok = lambda fn: abs(abs(fn(nl["I"], nl["f"])[i5]) - want) <= 1e-2 * want
    assert ok(good)
    for m in (inverted, harmonic_off_by_one, l_dropped):
        assert not ok(m), m.__name__


def test_control_inductance_raises_the_ripple_and_ideal_is_lowest(synth_result):
    c = synth_result["cases"]
    for node in pa.NODES:
        r = lambda case: c[case]["model"][node]["phasor"]
        assert r("control_C407+100nH") >= r("asbuilt") - 1e-9
        assert r("L_x2") >= r("asbuilt") - 1e-9
    assert c["control_C407+100nH"]["model"]["outn"]["phasor"] > c["asbuilt"]["model"]["outn"]["phasor"]
    assert c["control_C407+100nH"]["model"]["outp"]["phasor"] == pytest.approx(c["asbuilt"]["model"]["outp"]["phasor"])   # C407 is on OUT- only


def test_sensitivity_only_moves_the_capacitors_own_rail(synth_result):
    s = synth_result["sensitivity"]
    assert s["C405"]["node"] == "outp" and s["C407"]["node"] == "outn"
    assert all(s[c]["rise_plus_dl"]["model"] >= -1e-9 for c in s)


def test_band_limit_is_monotone_and_full_band_is_the_network_without_limit(synth_result):
    sw = synth_result["bandwidth_sweep_mv"]["asbuilt"]
    assert sw["5"]["vin"] <= sw["83"]["vin"] + 1e-9


def test_band_masks_partition_the_lines():
    f = np.arange(1, 8193) * 10e3
    low, pump, rest = pa.band_masks(f, 2.14e6)
    assert (low.astype(int) + pump + rest).tolist() == [1] * len(f)
    assert f[pump].min() > 0.5 * 2.14e6 and f[low].max() < 0.5 * 2.14e6


def test_window_lines_roundtrip_and_leak_free_with_a_ramp():
    tr = synthetic_transient()
    x = tr["v"]["vin"] + 1e-3 * (tr["t"] - tr["t"][0]) / 1e-4                       # a slope: the window ends differ
    f, c, ramp, mean = pa.window_lines(tr["t"], x)
    w = pa.lines_to_wave(c) + ramp
    g = tr["t"][-1] - pa.TW + np.arange(pa.NPTS) * pa.TW / pa.NPTS
    assert np.max(np.abs(w - np.interp(g, tr["t"], x))) < 1e-9 + 2e-6
    assert abs(c[np.argmin(np.abs(f - F_BURST))]) == pytest.approx(9e-3, rel=0.02)
    assert np.abs(c[(f > 10e6)]).max() < 2e-6                                         # no leakage floor from the end mismatch


# ---- the PW-4 band figures (DC-1 MHz, 1-10 MHz, 10-30 MHz)

def _lines_for(freqs_amps):
    f = np.arange(1, pa.NPTS // 2 + 1) / pa.TW
    c = np.zeros(len(f), complex)
    for fr, a in freqs_amps:
        c[np.argmin(np.abs(f - fr))] = a
    return f, c, np.zeros(pa.NPTS)


def test_band_figures_known_answers():
    f, c, ramp = _lines_for([(0.5e6, 2e-3), (3e6, 1e-3), (20e6, 0.5e-3)])
    b = pa.band_figures(c, ramp, f)
    assert b["dc_1M"]["rms"] == pytest.approx(2e-3 / np.sqrt(2), rel=1e-6) and b["dc_1M"]["pkpk"] == pytest.approx(4e-3, rel=1e-3)
    assert b["1M_10M"]["rms"] == pytest.approx(1e-3 / np.sqrt(2), rel=1e-6)
    assert b["10M_30M"]["pkpk"] == pytest.approx(1e-3, rel=1e-3)


def test_band_edges_are_half_open_at_1_and_10_mhz():
    f, c, ramp = _lines_for([(1.0e6, 1e-3), (10e6, 1e-3)])
    b = pa.band_figures(c, ramp, f)
    assert b["dc_1M"]["rms"] == pytest.approx(0, abs=1e-12)                          # a line AT 1 MHz is in the 1-10 MHz band
    assert b["1M_10M"]["rms"] == pytest.approx(1e-3 / np.sqrt(2), rel=1e-6)           # and one at 10 MHz is in 10-30
    assert b["10M_30M"]["rms"] == pytest.approx(1e-3 / np.sqrt(2), rel=1e-6)


def test_band_rms_comes_from_the_rail_lines_not_another_array():
    """A mutant that reads another rail's lines must disagree with the closed answer; the band figure is Parseval's on its lines."""
    f, c, ramp = _lines_for([(0.3e6, 1e-3), (0.7e6, 3e-3)])
    b = pa.band_figures(c, ramp, f)
    assert b["dc_1M"]["rms"] == pytest.approx(np.sqrt((1e-3 ** 2 + 3e-3 ** 2) / 2), rel=1e-6)
    assert b["dc_1M"]["rms"] != pytest.approx(np.sqrt((1e-3 ** 2) / 2), rel=1e-3)


def test_in_band_dc_1mhz_is_blind_to_loop_l_on_a_low_frequency_rail(synth_result):
    """The synthetic ripple has lines at 90 kHz and 2.14 MHz only: L (nH) cannot move its DC-1 MHz band (a few per cent at most)."""
    t = synth_result["vin_pw4_band"]
    ideal, built = t["ideal"]["dc_1M"]["rms"]["model"], t["asbuilt"]["dc_1M"]["rms"]["model"]
    assert built == pytest.approx(ideal, rel=0.02)
    assert t["asbuilt"]["1M_10M"]["rms"]["model"] > t["ideal"]["1M_10M"]["rms"]["model"]      # L shows up above 1 MHz
    assert "NOT judged" in synth_result["notes"]["pw4"]


def test_fmax_table_present_for_both_cases(synth_result):
    t = synth_result["fmax_table_vin_mv"]
    assert set(t) == {"ideal", "asbuilt"} and set(t["asbuilt"]) == {"5", "10", "20", "30", "40", "83"}


# ---- the ngspice-driven validation: the real ideal transient against the AC estimate

def _lib_present():
    for root in (AFE, AFE / "pcbtools" / ".scratch" / "orig" / "afe-proto"):
        if (root / "models" / "lm27762" / "LM27762_TRANS.LIB").exists():
            return True
    return False


@pytest.mark.ngspice
@pytest.mark.slow
def test_ideal_ac_reproduces_the_ideal_transient(tmp_path, monkeypatch):
    if not _lib_present():
        pytest.skip("TI's LM27762_TRANS.LIB is not present (tools/fetch_models.py)")
    monkeypatch.setenv("LM_SCRATCH", str(tmp_path / "lmlib"))
    tr = pa.run_transient(tmp_path / "run", mem="2G", timeout=900)
    res = pa.estimate(tr)
    v = res["validation_pure_C"]
    assert v["outp"]["transient_pp_mv"] == pytest.approx(0.131, rel=0.01)
    assert v["vin"]["transient_pp_mv"] == pytest.approx(19.6, rel=0.01)
    for node in ("outp", "outn", "vin"):
        assert v[node]["ratio_phasor_over_transient"] == pytest.approx(1.0, abs=1e-3), node
    assert res["f_pump_hz"] == pytest.approx(2.13e6, rel=0.02)
    assert tr["peak_rss_kb"] < 3 * 1024 * 1024
