"""The scope analysis, against signals whose answers are known.

Board-free and instrument-free on purpose. The analysis these replace
was calibrated by eye against 600-point screen records, and when the
record became 65,526 points at 10 ns it found 17,580 edges in a clean
sine - which nothing caught, because nothing here knew what the right
answer was.

So every case below builds a trace with the defect written into it, at
**both densities**, and asserts the same answer comes out of each. A
detector that passes at one sample rate and not the other has a
threshold in samples hiding in it.
"""
import math
import random

import pytest

import trace as tr

# The bench these are modelled on. tests/baseline.json's measured span,
# and the step response from tools/dso_metrics.py step.
V_PER_CODE = 2.193 / 4095
RISE_S = 900e-9
NOISE_V = 0.020 / 3        # ~20 mV pk, so ~7 mV RMS after averaging


def staircase(dt, *, levels, hold_s, rise_s=RISE_S, noise=0.0,
              spike=None, seed=1):
    """A held-level trace with real transition times.

    `spike` is (time, volts, width_s) - an excursion planted at a known
    place, which is what the issue-#5 hunt is looking for.
    """
    rnd = random.Random(seed)
    n_hold = int(round(hold_s / dt))
    n_rise = max(1, int(round(rise_s / dt)))
    v = []
    for k, lvl in enumerate(levels):
        prev = levels[k - 1] if k else levels[0]
        for i in range(n_rise):
            v.append(prev + (lvl - prev) * (i + 1) / n_rise)
        v += [lvl] * max(0, n_hold - n_rise)
    if spike:
        at_s, amp, width_s = spike
        a = int(round(at_s / dt))
        w = max(1, int(round(width_s / dt)))
        for i in range(a, min(a + w, len(v))):
            v[i] += amp
    if noise:
        v = [x + rnd.gauss(0, noise) for x in v]
    return v


DENSITIES = [
    pytest.param(10e-9, id="raw-10ns"),
    pytest.param(1.09e-6, id="screen-1.09us"),
]


@pytest.mark.parametrize("dt", DENSITIES)
def test_a_clean_staircase_has_one_edge_per_step(dt):
    """The failure that started this: a smooth trace at high density
    read as thousands of edges, because the threshold was four times the
    median sample-to-sample difference and at 10 ns that is nothing."""
    levels = [0.6, 1.0, 1.4, 1.8, 1.4, 1.0]
    v = staircase(dt, levels=levels, hold_s=10e-6, noise=NOISE_V)
    edges = tr.find_edges(v, dt, min_step=0.2)
    # Five transitions between six levels; the first is the run's start.
    assert 4 <= len(edges) <= 6, f"{len(edges)} edges for 5 steps"


@pytest.mark.parametrize("dt", DENSITIES)
def test_a_flat_trace_has_no_edges(dt):
    v = staircase(dt, levels=[1.674], hold_s=200e-6, noise=NOISE_V)
    assert tr.find_edges(v, dt, min_step=0.2) == []


@pytest.mark.parametrize("dt", DENSITIES)
def test_noise_floor_recovers_the_noise_it_was_given(dt):
    """Within a factor of two, at either density. The estimator has to
    be robust to the staircase's own steps, which is why it is a median
    and not an rms."""
    v = staircase(dt, levels=[0.6, 1.4, 0.6, 1.4], hold_s=20e-6,
                  noise=NOISE_V)
    got = tr.noise_floor(v, dt)
    assert 0.4 * NOISE_V <= got <= 2.5 * NOISE_V, (
        f"estimated {got*1000:.2f} mV for {NOISE_V*1000:.2f} mV given")


@pytest.mark.parametrize("dt", DENSITIES)
def test_a_planted_excursion_is_found_at_the_right_place(dt):
    """The measurement issue #5 needs: a brief excursion on a pin that
    is otherwise holding a level."""
    hold = 20e-6
    at = 2 * hold + 8e-6          # well inside the third plateau
    amp = 12 * V_PER_CODE         # 12 codes, mid of the reported 5-15
    v = staircase(dt, levels=[0.6, 1.0, 1.4, 1.0], hold_s=hold,
                  noise=NOISE_V / 4, spike=(at, amp, 2e-6))
    resid, segs = tr.residuals(v, dt, min_step=0.2)
    i, r = tr.worst(resid)
    assert i is not None, "no residual at all"
    found_at = i * dt
    assert abs(found_at - at) < 3e-6, (
        f"found the excursion at {found_at*1e6:.2f} us, planted at "
        f"{at*1e6:.2f} us")
    assert r > 0.5 * amp, (
        f"recovered {r/V_PER_CODE:.1f} codes of a planted "
        f"{amp/V_PER_CODE:.1f}")


@pytest.mark.parametrize("dt", DENSITIES)
def test_no_excursion_means_no_excursion(dt):
    """The control. Same trace, nothing planted: the worst residual must
    stay near the noise rather than reporting the largest sample as a
    find."""
    v = staircase(dt, levels=[0.6, 1.0, 1.4, 1.0], hold_s=20e-6,
                  noise=NOISE_V / 4)
    resid, _ = tr.residuals(v, dt, min_step=0.2)
    i, r = tr.worst(resid)
    floor = tr.noise_floor(v, dt)
    assert r is None or abs(r) < 8 * floor, (
        f"worst residual {abs(r)/floor:.1f}x the noise floor with nothing "
        f"planted")


def test_worst_reports_nothing_when_there_is_nothing():
    """max(..., key=abs) over an all-zero list returns index 0 with a
    straight face, and that was once read as a feature landing in the
    same place every round."""
    assert tr.worst([0.0] * 100) == (None, None)
    assert tr.worst([None] * 100) == (None, None)


def test_rebin_trades_time_resolution_for_noise():
    """Averaging n samples a bin divides uncorrelated noise by sqrt(n).
    That is sensitivity bought with resolution nobody was using - 10 ns
    to 1 us is 100 to a bin and a tenfold drop in the floor."""
    dt = 10e-9
    v = staircase(dt, levels=[1.674], hold_s=400e-6, noise=NOISE_V)
    before = tr.noise_floor(v, dt)
    v2, dt2, per = tr.rebin(v, dt, 1e-6)
    after = tr.noise_floor(v2, dt2, lag_s=4e-6)
    assert per == 100
    assert dt2 == pytest.approx(1e-6)
    assert after < before / 3, (
        f"{before*1000:.3f} mV -> {after*1000:.3f} mV over {per} samples "
        f"a bin; expected roughly sqrt({per}) of an improvement")


def test_rebin_leaves_a_record_alone_when_the_bin_is_one_sample():
    v = [1.0, 2.0, 3.0]
    got, dt, per = tr.rebin(v, 1e-6, 1e-7)
    assert got is v and dt == 1e-6 and per == 1


@pytest.mark.parametrize("dt", DENSITIES)
def test_settling_is_excluded_by_time_not_by_fraction(dt):
    """A fraction of a segment makes the excluded window depend on how
    many samples the instrument happened to take. The measured rise is
    789-938 ns and that is what has to be skipped, at any density."""
    v = staircase(dt, levels=[0.6, 1.4], hold_s=20e-6, noise=0.0)
    edges = tr.find_edges(v, dt, min_step=0.2)
    segs = tr.plateaus(v, dt, edges, settle_s=1.2e-6)
    assert segs, "no plateau found"
    for a, b in segs:
        # Nothing inside a settling window survives, so every kept
        # sample sits at its plateau's level.
        held = v[a:b]
        assert max(held) - min(held) < 1e-6, (
            f"a kept plateau spans {max(held)-min(held)*1e3:.3f} mV, so "
            f"settling leaked in")


# ---------------------------------------------------------------------
# Folding: the instrument for a moving waveform.
# ---------------------------------------------------------------------

def sine_staircase(dt, *, hz, pts_per_cycle, cycles, amp=1.1, mid=1.674,
                   noise=0.0, spike=None, seed=3):
    """A staircase sine, the shape the generator actually emits.

    Step sizes run from nearly zero at the peaks to the full step at the
    crossings, which is exactly what defeats a plateau detector.
    """
    # Built from TIME, not from a whole number of samples per plateau.
    # Rounding the hold to an integer sample count makes the generated
    # period 313.9 us instead of 320 at the screen density, and then a
    # fold at the period it is *supposed* to have reports 807 codes of
    # deviation on a clean trace. The signal has to have the period the
    # test claims for it, at every density.
    rnd = random.Random(seed)
    period = 1.0 / hz
    hold = period / pts_per_cycle
    n = int(round(cycles * period / dt))
    v = []
    for i in range(n):
        k = int((i * dt) / hold) % pts_per_cycle
        v.append(mid + amp * math.sin(2 * math.pi * k / pts_per_cycle))
    if spike:
        cyc, frac, volts, width_s = spike
        at_s = (cyc + frac) * period
        a = int(round(at_s / dt))
        w = max(1, int(round(width_s / dt)))
        for i in range(a, min(a + w, len(v))):
            v[i] += volts
    if noise:
        v = [x + rnd.gauss(0, noise) for x in v]
    return v


@pytest.mark.parametrize("dt", DENSITIES)
def test_folding_cancels_the_waveform(dt):
    """With nothing planted, every cycle matches the others: the sine's
    own swing must not appear as a deviation. The plateau residual
    reported 3,921 codes here."""
    v = sine_staircase(dt, hz=3125, pts_per_cycle=32, cycles=8,
                       noise=NOISE_V / 4)
    per_cycle, typical, n = tr.fold_compare(
        v, dt, 1 / 3125, update_s=(1 / 3125) / 32)
    assert n >= 6, f"only {n} cycles folded"
    biggest = max(abs(x) for c in per_cycle for x in c if x is not None)
    assert biggest < 40 * V_PER_CODE, (
        f"{biggest/V_PER_CODE:.0f} codes of deviation on a clean sine; "
        f"the waveform is not being cancelled")


@pytest.mark.parametrize("dt", DENSITIES)
def test_folding_finds_an_excursion_in_one_cycle(dt):
    """What the reload hunt is for: something that happens in exactly
    one cycle of the wrap, at 12 codes - mid of issue #5's 5-15."""
    amp = 12 * V_PER_CODE
    v = sine_staircase(dt, hz=3125, pts_per_cycle=32, cycles=8,
                       noise=NOISE_V / 8,
                       spike=(3, 0.25, amp, 4e-6))
    per_cycle, _, n = tr.fold_compare(
        v, dt, 1 / 3125, update_s=(1 / 3125) / 32)
    k, j, x, prominence = tr.odd_cycle(per_cycle)
    assert k == 3, f"found it in cycle {k}, planted in 3"
    assert abs(j / len(per_cycle[0]) - 0.25) < 0.06, (
        f"found at phase {j/len(per_cycle[0]):.3f}, planted at 0.25")
    assert x > 0.5 * amp
    assert prominence > 5, f"only {prominence:.1f}x the typical deviation"


@pytest.mark.parametrize("dt", DENSITIES)
def test_folding_reports_nothing_when_nothing_is_there(dt):
    """The control. Prominence has to stay low, or every run 'finds'
    whichever sample was largest."""
    v = sine_staircase(dt, hz=3125, pts_per_cycle=32, cycles=8,
                       noise=NOISE_V / 8)
    per_cycle, _, _ = tr.fold_compare(
        v, dt, 1 / 3125, update_s=(1 / 3125) / 32)
    _, _, _, prominence = tr.odd_cycle(per_cycle)
    assert prominence < 12, (
        f"prominence {prominence:.1f}x with nothing planted")


@pytest.mark.parametrize("dt", DENSITIES)
def test_folding_masks_transitions_wherever_the_schedule_starts(dt):
    """The record begins where the trigger landed, not on an update
    boundary. Masking at multiples of the update period measured from
    sample zero puts the mask between the steps instead of on them, and
    the fold then reports the waveform's whole swing as a deviation -
    2.3 V of it, on hardware."""
    period = 1 / 3125
    # Shift the whole signal by a third of an update, so the schedule
    # does not start at t=0.
    offset_s = (period / 32) / 3
    n = int(round(8 * period / dt))
    v = []
    for i in range(n):
        k = int((i * dt + offset_s) / (period / 32)) % 32
        v.append(1.674 + 1.1 * math.sin(2 * math.pi * k / 32))
    per_cycle, _, _ = tr.fold_compare(v, dt, period,
                                      update_s=period / 32)
    live = [abs(x) for c in per_cycle for x in c if x is not None]
    assert live, "everything masked"
    assert max(live) < 40 * V_PER_CODE, (
        f"{max(live)/V_PER_CODE:.0f} codes with the schedule offset by a "
        f"third of an update; the mask is not finding the transitions")


@pytest.mark.parametrize("dt", DENSITIES)
def test_an_invalid_record_head_is_trimmed(dt):
    """A RAW acquisition does not begin with valid data: on hardware the
    first ~40 us spreads 3660 mV on a pin whose whole range is 2193.
    Folded across cycles that head becomes one cycle disagreeing with
    the others by the full swing, which is what a wrap-locked excursion
    would look like."""
    period = 1 / 3125
    good = sine_staircase(dt, hz=3125, pts_per_cycle=32, cycles=6)
    junk_n = int(round(40e-6 / dt))
    rnd = random.Random(7)
    # Junk that stays INSIDE the converter's range, so only the
    # record's own body can tell it apart. The absolute test passes it:
    # measured on hardware, a junk window spread 2300 mV against a
    # 2522 mV cap while being nine times a legitimate window.
    junk = [rnd.uniform(0.5, 2.7) for _ in range(junk_n)]
    v, dropped = tr.trim_invalid_head(junk + good, dt, max_spread=2.52)
    assert dropped >= junk_n * 0.5, (
        f"dropped only {dropped} of {junk_n} junk samples")
    assert len(v) > 3 * period / dt, "trimmed away the signal too"


@pytest.mark.parametrize("dt", DENSITIES)
def test_trimming_leaves_a_clean_record_alone(dt):
    """It must not eat a good record, and must not eat an excursion: a
    15-code spike does not move a window's spread past the converter's
    whole range."""
    v = sine_staircase(dt, hz=3125, pts_per_cycle=32, cycles=6,
                       noise=NOISE_V / 8,
                       spike=(2, 0.4, 15 * V_PER_CODE, 3e-6))
    got, dropped = tr.trim_invalid_head(v, dt, max_spread=2.52)
    assert dropped == 0
    assert got is v
