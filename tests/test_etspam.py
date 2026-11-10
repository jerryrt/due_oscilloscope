"""Levels, eyes and gates of a PAM-N capture, read from synthetic data.

Board-free. A staircase through a single pole, sampled by a clock a few ppm
from the source's, with noise: the answer is known, so the ladder, the eyes
and the gates can be checked against it, and each gate has a control that
must make it fail. The gates are those of docs/ets-pam.md.
"""
import math
import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import etspam  # noqa: E402
import etsperiod  # noqa: E402
import etspattern  # noqa: E402
import etsplan  # noqa: E402

DAC_LSB = 2214.0 / 4095
ADC_LSB = 3300.0 / 4095
MID = (2048 * DAC_LSB + 546.0) / ADC_LSB


def _adc_of(code, comp):
    lin = (code * DAC_LSB + 546.0) / ADC_LSB
    if not comp:
        return lin
    x = (lin - MID) / 700.0
    return MID + 700.0 * (x - comp * x ** 3)


def _synth(pam, rc_dac=29, rc_adc=46, delta=-2.5e-6, n=600_000, sigma=1.3,
           tau=2.8, comp=0.0, seed=3):
    """A pattern and its samples: ADC codes of a source `delta` slow."""
    pat = etspattern.pattern(pam)
    length = pat.length
    period = length * rc_dac
    x = [_adc_of(pat.codes[pat.symbols[(t // rc_dac) % length]], comp)
         for t in range(period)]
    y, a = x[0], 1.0 - math.exp(-1.0 / tau)
    for _ in range(4):
        for t in range(period):
            y += (x[t] - y) * a
    curve = []
    for t in range(period):
        y += (x[t] - y) * a
        curve.append(y)
    rnd = random.Random(seed)
    vals = []
    for k in range(n):
        u = (k * rc_adc / (1.0 + delta) + 311.7) % period
        i = int(u)
        f = u - i
        v = curve[i] * (1 - f) + curve[(i + 1) % period] * f + rnd.gauss(0, sigma)
        vals.append(float(min(4095, max(0, round(v)))))
    return pat, vals


@pytest.fixture(scope="module")
def pam4():
    pat, vals = _synth(4)
    return pat, vals, etspam.analyze(vals, 46, pat, 29)


def _passed(res):
    return {k: v["passed"] for k, v in res["gates"].items()}


def test_an_ideal_pam4_capture_passes_every_gate_with_the_ladder_it_was_given(pam4):
    pat, _, res = pam4
    assert _passed(res) == {"A3": True, "A4": True, "A5": True, "A6": True}, res["gates"]
    ideal = (pat.codes[-1] - pat.codes[0]) * DAC_LSB / ADC_LSB / 3
    assert abs(res["spacing_codes"] - ideal) < 0.01 * ideal, (res["spacing_codes"], ideal)
    assert res["residual_max_codes"] < 0.5, res["residual_max_codes"]
    assert res["eye_height_min"] > 0.9 * ideal and res["eye_width_min"] >= 0.6, res["eyes"]
    assert abs(res["delta_ppm"] + 2.5) < 0.01, res["delta_ppm"]


def test_ideal_captures_of_more_levels_pass_with_the_pair_the_planner_picks():
    for pam, n in ((8, 600_000), (16, 1_000_000), (32, 1_500_000)):
        pl = etsplan.plan(length=etspattern.pattern(pam).length)
        pat, vals = _synth(pam, pl["rc_dac"], pl["rc_adc"], n=n)
        res = etspam.analyze(vals, pl["rc_adc"], pat, pl["rc_dac"])
        assert _passed(res) == {"A3": True, "A4": True, "A5": True, "A6": True}, (pam, res["gates"])


def test_noise_that_closes_the_eyes_fails_the_separation_and_the_eye_gates():
    pat, vals = _synth(16, n=1_000_000, sigma=40.0)
    got = _passed(etspam.analyze(vals, 46, pat, 29))
    assert got["A4"] is False and got["A6"] is False and got["A3"] is True, got


def test_a_compressed_ladder_fails_the_linearity_gate_alone():
    pat, vals = _synth(4, comp=0.55)
    res = etspam.analyze(vals, 46, pat, 29)
    assert _passed(res) == {"A3": True, "A4": True, "A5": False, "A6": True}, res["gates"]


def test_labels_a_symbol_out_of_step_fail_the_level_gates(pam4):
    pat, vals, res = pam4
    trk = etsperiod.track_clock_ratio(vals, 46, pat.symbols, 29, levels=4)
    centre, by_t = etspam.label_samples(vals, 46, trk["model"], pat, 29,
                                        res["b0_ticks"] + 29)
    bad = etspam.analyze_levels(centre, by_t, pat)
    g = etspam.gates(bad, trk)
    assert not g["A4"][0] and not g["A5"][0] and not g["A6"][0], g


def test_an_adc_rc_sharing_a_factor_with_the_period_fails_the_clock_gate():
    """2,047 = 23 * 89, so RC 46 shares 23 with the period of PAM32."""
    pat, vals = _synth(32, n=1_500_000)
    res = etspam.analyze(vals, 46, pat, 29)
    assert res["lattice_gcd"] == 23 and res["gates"]["A3"]["passed"] is False, res["gates"]["A3"]


def test_a_quantile_reads_the_tail_of_a_histogram():
    h = [0] * etspam.ADC_CODES
    for code in range(1000, 1200):
        h[code] = 10
    assert etspam._quantile(h, 0.001) == 1000.0
    assert etspam._quantile(h, 0.001, from_top=True) == 1199.0
    assert etspam._quantile([0] * etspam.ADC_CODES, 0.5) is None


def test_the_widest_open_stretch_of_an_eye_is_the_longest_run_not_the_total():
    assert etspam._longest_open_run([1, 1, -1, 1, 1, 1, -1, None]) == 3 / 8


def test_the_boundary_of_a_folded_staircase_is_where_it_moves():
    """Hard steps between ticks 21 and 22 after a shift of 7: the edge is at
    tick 22, and a window that merely contains it must not be taken for it."""
    rc = 29
    curve = []
    for sym in (0, 1, 0, 0, 1, 1, 0, 1):
        curve += [100.0 + 300.0 * sym] * rc
    got = etspam.boundary_offset(curve[7:] + curve[:7], rc)
    assert abs((got - 22.0 + rc / 2) % rc - rc / 2) < 0.5, got


def test_the_eye_document_carries_every_sample_once_and_the_levels_it_was_given(pam4):
    pat, vals, _ = pam4
    res = etspam.analyze(vals, 46, pat, 29, want_eye=True)
    eye = res["eye"]
    assert sum(c for _, _, c in eye["cells"]) == len(vals)
    assert eye["nx"] == 2 * 29 * etspam.LABEL_K and len(eye["levels"]) == 4
    assert all(0 <= x < eye["nx"] for x, _, _ in eye["cells"])
    assert sum(eye["centre_hist"]) == sum(lv["n"] for lv in eye["levels"])
    lo, hi = eye["ymin_code"], eye["ymax_code"]
    assert lo <= eye["levels"][0]["mean"] and eye["levels"][-1]["mean"] <= hi


def test_a_capture_that_starts_part_way_through_a_run_is_labelled_from_its_own_start(pam4):
    """The tracker, the fold and the labels all count samples from the run's
    start; trimming the first samples off must move all three together, or
    every label is out by the drift of the samples that were dropped."""
    pat, vals, _ = pam4
    cut = 80_000
    res = etspam.analyze(vals[cut:], 46, pat, 29, start=cut)
    assert _passed(res) == {"A3": True, "A4": True, "A5": True, "A6": True}, res["gates"]
    assert res["eye_height_min"] > 380, res["eyes"]
