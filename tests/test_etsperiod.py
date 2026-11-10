"""The clock ratio of a source with a clock of its own, from samples alone.

Board-free: a synthetic single-pole PRBS7 sampled by a clock that is a known
number of ppm away from the source's. Three things are held, each able to
fail on its own:

 * the ratio is recovered, in both directions and at a size the search
   window has to cope with;
 * a fold on the recovered period shows the eye, and a fold on a period
   only 20 ppm out does not, so the first assertion cannot be satisfied by
   a fold that is insensitive to the period;
 * a capture the pattern is absent from is refused, not reported as a
   ratio, and an idle stretch at the start is skipped.
"""
import math
import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import etsperiod  # noqa: E402
import ets_phase0  # noqa: E402

RC_DAC = 28
RC_ADC = 45
TAU = 4.0                       # ticks: a 2.2 * tau = 8.8-tick rise
N = 300_000


def _steady_curve(bits):
    """One period of a single-pole NRZ, one value per source tick."""
    period = len(bits) * RC_DAC
    x = [1.0 if bits[(t // RC_DAC) % len(bits)] else -1.0 for t in range(period)]
    y, a = -1.0, 1.0 - math.exp(-1.0 / TAU)
    for _ in range(4):
        for t in range(period):
            y += (x[t] - y) * a
    out = []
    for t in range(period):
        y += (x[t] - y) * a
        out.append(y)
    return out


def _samples(delta, n=N, sigma=0.002, seed=5, offset=311.7, odd_ticks=0.0):
    """`n` samples at ADC ticks `k * RC_ADC` of a source `delta` slow."""
    bits = ets_phase0.prbs7()
    curve = _steady_curve(bits)
    period = len(curve)
    rnd = random.Random(seed)
    vals = []
    for k in range(n):
        u = ((k * RC_ADC + (odd_ticks if k & 1 else 0.0)) / (1.0 + delta)
             + offset) % period
        i = int(u)
        f = u - i
        v = curve[i] * (1 - f) + curve[(i + 1) % period] * f
        vals.append(1500.0 + 600.0 * v + rnd.gauss(0, sigma * 600.0))
    return bits, vals


def _eye(vals, period, bits):
    curve, cnt = etsperiod.fold_scaled(vals, RC_ADC, period, len(bits) * RC_DAC)
    if any(c is None for c in curve):
        return 0.0
    fig, _ = ets_phase0.analyze(curve, RC_DAC, bits)
    return fig.get("eye_frac", 0.0) if fig["pattern_ok"] else 0.0


def test_the_ratio_is_recovered_in_both_directions():
    for ppm in (150.0, -150.0, 40.0):
        bits, vals = _samples(ppm * 1e-6)
        got = etsperiod.track_clock_ratio(vals, RC_ADC, bits, RC_DAC)
        # What matters is the phase a ratio error builds up over the whole
        # capture: half a tick is the most a fold on 1-tick bins tolerates.
        assert abs(got["delta"] - ppm * 1e-6) < 0.5 / (N * RC_ADC), (ppm, got)
        assert got["edge_hits"] == 0, got


def test_a_fold_on_the_recovered_period_shows_the_eye_and_a_wrong_one_does_not():
    bits, vals = _samples(60e-6)
    got = etsperiod.track_clock_ratio(vals, RC_ADC, bits, RC_DAC)
    assert _eye(vals, got["period"], bits) > 0.9
    assert _eye(vals, got["period"] * (1 + 20e-6), bits) < 0.5, (
        "a fold 20 ppm out still shows an open eye: the check cannot tell a "
        "right period from a wrong one")
    assert _eye(vals, 3556.0, bits) < 0.5


def test_a_capture_without_the_pattern_is_refused():
    rnd = random.Random(9)
    bits = ets_phase0.prbs7()
    vals = [1500.0 + rnd.gauss(0, 200.0) for _ in range(N)]
    with pytest.raises(ValueError):
        etsperiod.track_clock_ratio(vals, RC_ADC, bits, RC_DAC)


def test_a_start_up_stretch_of_idle_level_is_skipped_and_the_ratio_still_found():
    bits, vals = _samples(-80e-6)
    head = [1500.0] * 30_000
    got = etsperiod.track_clock_ratio(head + vals, RC_ADC, bits, RC_DAC)
    assert abs(got["delta"] + 80e-6) < 0.5 / (N * RC_ADC), got
    assert got["skipped"] >= 1, got


def _resolution(delta, tmp_path, odd_ticks=0.0):
    import array
    import ets_cross
    bits, vals = _samples(delta, n=1_200_000, odd_ticks=odd_ticks)
    path = tmp_path / "raw.bin"
    path.write_bytes(array.array("H", [int(round(v)) for v in vals]).tobytes())
    return ets_cross.resolution(str(path), RC_DAC, RC_ADC, 10, 2)


def test_samples_of_an_independent_clock_fill_the_fine_bins_and_a_shared_one_does_not(tmp_path):
    free = _resolution(60e-6, tmp_path)
    locked = _resolution(0.0, tmp_path)
    assert free["fine_filled_share"] > 0.9 and free["frac_min_over_max"] > 0.5, free
    assert locked["fine_filled_share"] < 0.15, (
        "samples on a shared clock reached the fine bins between ticks: the "
        "measure cannot tell a lattice from a continuous position", locked)


def test_a_one_tick_offset_of_the_odd_samples_is_found_with_its_sign_and_removed(tmp_path):
    tick_ns = ets_phase0.TICK_NS
    row = _resolution(60e-6, tmp_path, odd_ticks=-1.0)
    for edge in ("rise", "fall"):
        got = row["edge50_%s_odd_minus_even_ns" % edge]
        assert abs(got - tick_ns) < 0.1 * tick_ns, (edge, got, row)
    assert row["corr_rise_ns"] < row["rise_ns_fine"], (
        "moving the odd samples back did not sharpen the edge", row)
    clean = _resolution(60e-6, tmp_path, odd_ticks=0.0)
    assert abs(clean["edge50_rise_odd_minus_even_ns"]) < 0.1 * tick_ns, clean


def test_the_floor_fit_recovers_a_known_floor_and_reports_none_when_there_is_none():
    import ets_cross
    a, b = 0.0004, 40.0 ** 2          # slew term and a 40 ns floor
    steps = [1000.0, 700.0, 500.0, 350.0, 250.0, 175.0]
    pts = [(s, math.sqrt(a * s * s + b)) for s in steps]
    got = ets_cross.fit_floor(pts)
    assert abs(got["floor_ns"] - 40.0) < 0.5, got
    pure = ets_cross.fit_floor([(s, 0.02 * s) for s in steps])
    assert pure["floor_ns"] is None or pure["floor_ns"] < 1.0, (
        "a purely slew-limited edge was given a floor", pure)
