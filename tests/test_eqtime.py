"""Equivalent-time reconstruction, on a device whose answer is known.

Board-free. A synthetic converter with a *stated* rise time and settling
tail is sampled exactly the way the real one is - at `(n * RC_adc) mod
P` - and the reconstruction has to give the stated numbers back.

This is the measurement that most needs it. The reconstruction turns
800,000 samples into one smooth curve, and a smooth curve is convincing
whether or not it is right: the 118 us settling tail this file's method
replaces was smooth, reproducible to the sample, and entirely an
artifact. So every case here plants a known answer and demands it back,
and the ones that matter most are the failures - a dropped frame and a
wrong period both smear an edge into a slope, which is precisely what a
slow settling tail looks like.
"""
import math
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "host"))
import eqtime  # noqa: E402

TC = eqtime.TC_CLOCK_HZ


def device(period, *, lo=677.0, hi=3423.0, rise_ticks=35.0,
           tail_ticks=0.0, tail_codes=0.0):
    """A square with a stated rise and an optional settling tail.

    `rise_ticks` is the exponential time constant of the edge;
    `tail_ticks`/`tail_codes` add a second, slower exponential - which
    is exactly the shape the question is asking about and the shape a
    smeared reconstruction can imitate.
    """
    half = period // 2

    def at(ph):
        x = ph % period
        edge = x if x < half else x - half
        # The level it is coming FROM, and the one it is going to. These
        # were inverted in the first version, which made `base == target`
        # on the rising half and gave the synthetic converter an
        # instantaneous edge - so the reconstruction was being asked to
        # recover a rise that was never planted.
        base = lo if x < half else hi
        target = hi if x < half else lo
        v = target + (base - target) * math.exp(-edge / rise_ticks)
        if tail_ticks and tail_codes:
            sign = 1.0 if x < half else -1.0
            v -= sign * tail_codes * math.exp(-edge / tail_ticks)
        return v
    return at


def sample(at, n, rc_adc, period, *, noise=0.0, seed=1, drop_at=None):
    """What the ADC returns: one value per trigger, phase walking.

    `drop_at` simulates a lost frame - every sample after it keeps its
    index but no longer keeps its time, which is the failure
    `check_contiguous` exists to refuse.
    """
    rng = random.Random(seed)
    out = []
    skew = 0
    for i in range(n):
        if drop_at is not None and i == drop_at:
            skew += 137            # a gap of some arbitrary size
        ph = ((i + skew) * rc_adc) % period
        v = at(ph)
        if noise:
            v += rng.gauss(0.0, noise)
        out.append(v)
    return out


# ------------------------------------------------------------------
# recovering RC, which everything else rests on
# ------------------------------------------------------------------

@pytest.mark.parametrize("rc", [86, 98, 130, 192, 193, 194, 195, 390, 780])
def test_rc_is_recovered_from_the_truncated_frequency(rc):
    """Not an estimate: the device divided by a known constant in
    integer arithmetic and this undoes it."""
    reported = TC // rc
    assert eqtime.rc_from_hz(reported) == rc


def test_a_frequency_no_rc_produces_is_refused():
    """A reported rate that does not round-trip is not a rate this
    device generated, and guessing an RC for it would put a wrong period
    under every number downstream."""
    assert eqtime.rc_from_hz(200_001) is None
    assert eqtime.rc_from_hz(0) is None


def test_the_period_counts_both_interleaved_channels():
    """TAG mode spends every other update on the second channel, so a
    cycle costs 2 * points updates - the factor of two in the
    generator's own frequency formula."""
    assert eqtime.period_ticks(195, 8) == 2 * 8 * 195
    assert eqtime.period_ticks(195, 8, updates_per_cycle=8) == 8 * 195


# ------------------------------------------------------------------
# the reconstruction
# ------------------------------------------------------------------

def test_a_coprime_rate_pair_visits_every_phase():
    """3,120 positions of 25.6 ns, from a converter sampling every
    2.2 us. This is the whole trick."""
    period = eqtime.period_ticks(195, 8)          # 3120
    assert math.gcd(193, period) == 1
    _, cnt = eqtime.reconstruct([0.0] * 40000, 193, period)
    assert eqtime.coverage(cnt) == 1.0


def test_a_shared_factor_leaves_gaps_and_says_so():
    """RC_adc 194 and a period of 3,120 share a factor of two, so half
    the phases are never sampled. Reported as gaps rather than
    interpolated: it is a property of the rate pair, not of the pin."""
    period = eqtime.period_ticks(195, 8)
    curve, cnt = eqtime.reconstruct([0.0] * 40000, 194, period)
    assert eqtime.coverage(cnt) == pytest.approx(0.5)
    assert curve[1] is None


def test_the_reconstructed_edge_has_the_rise_it_was_given():
    """The headline check. A 35-tick time constant is 0.9 us, which is
    the scope's measured full-scale rise on this board - and it is
    recovered from samples taken 2.2 us apart."""
    period = eqtime.period_ticks(195, 8)
    at = device(period, rise_ticks=35.0)
    vals = sample(at, 400_000, 193, period)
    curve, _ = eqtime.reconstruct(vals, 193, period)
    rot = eqtime.segment_after_edge(curve, pre=60)
    lo, hi = 677.0, 3423.0
    # 10% to 90% of the step, in ticks, against the analytic value for
    # an exponential: tau * ln(9) = 2.197 tau.
    t10 = next(i for i, v in enumerate(rot) if v > lo + 0.1 * (hi - lo))
    t90 = next(i for i, v in enumerate(rot) if v > lo + 0.9 * (hi - lo))
    assert (t90 - t10) == pytest.approx(35.0 * math.log(9), abs=3)


def test_noise_averages_down_as_the_capture_lengthens():
    """4 codes rms of ADC noise becomes 0.25 at 256 samples a bin, which
    is what puts a one-code question inside reach."""
    period = eqtime.period_ticks(195, 8)
    at = device(period, rise_ticks=35.0)
    resid = []
    for n in (40_000, 640_000):
        vals = sample(at, n, 193, period, noise=4.0, seed=5)
        curve, cnt = eqtime.reconstruct(vals, 193, period)
        # Residual against the noiseless truth, away from the edges.
        errs = [curve[i] - at(i) for i in range(period)
                if curve[i] is not None and 200 < i % (period // 2) < 1400]
        resid.append(math.sqrt(sum(e * e for e in errs) / len(errs)))
    assert resid[1] < resid[0] / 3, resid
    assert resid[1] < 0.5, resid


# ------------------------------------------------------------------
# the two ways it can lie, both of which imitate a settling tail
# ------------------------------------------------------------------

def test_the_period_is_found_and_the_margin_is_visible():
    period = eqtime.period_ticks(195, 8)
    at = device(period, rise_ticks=35.0)
    vals = sample(at, 300_000, 193, period, noise=2.0)
    cands = [eqtime.period_ticks(rc, 8) for rc in range(193, 198)]
    got = eqtime.find_period(vals, 193, cands)
    assert got[0]["period"] == period
    # The margin is the point, not just the ranking: a scan whose top two
    # are level has identified nothing.
    assert got[0]["sharpness"] > 10 * got[1]["sharpness"]
    # And the winner returns the waveform's actual amplitude, 3423-677.
    assert got[0]["sharpness"] == pytest.approx(2746.0, rel=0.05)


def test_a_period_wrong_by_one_rc_smears_the_edge():
    """Which is the point: a smeared edge is indistinguishable from a
    slow settling tail by eye, so the period cannot be assumed."""
    period = eqtime.period_ticks(195, 8)
    at = device(period, rise_ticks=35.0)
    vals = sample(at, 300_000, 193, period)
    right, _ = eqtime.reconstruct(vals, 193, period)
    wrong, _ = eqtime.reconstruct(vals, 193, eqtime.period_ticks(196, 8))
    assert eqtime.sharpness(right) > 10 * eqtime.sharpness(wrong)


def test_a_dropped_frame_is_refused_rather_than_reconstructed():
    class S:
        seq_gaps, dropped_frames, overrun_frames, crc_bad = 3, 1, 0, 0
    bad = eqtime.check_contiguous(S())
    assert any("gap" in b for b in bad) and any("dropped" in b for b in bad)

    class Clean:
        seq_gaps = dropped_frames = overrun_frames = crc_bad = 0
    assert eqtime.check_contiguous(Clean()) == []


def _edge_width(curve):
    """10-90% width of the reconstructed edge, in ticks.

    Levels from the curve itself, so a smeared reconstruction is
    measured against its own amplitude rather than against the one it
    would have had if nothing had gone wrong.
    """
    lo, hi = eqtime.levels(curve)
    seg = eqtime.segment_after_edge(curve, pre=0)
    t10 = t90 = None
    for i, v in enumerate(seg):
        if v is None:
            continue
        if t10 is None and v > lo + 0.1 * (hi - lo):
            t10 = i
        if v > lo + 0.9 * (hi - lo):
            t90 = i
            break
    if t10 is None or t90 is None:
        return float("inf")
    return t90 - t10


def test_a_gap_makes_the_converter_look_faster_than_it_is():
    """Why `check_contiguous` refuses, and it is worse than smearing.

    A dropped frame re-phases every later sample by a constant, so the
    fold averages two copies of the waveform offset from each other -
    here 137 lost samples become a 1,481-tick shift out of 3,120, near
    antiphase. The result is a *half-amplitude* step, and a 10-90%
    width measured against that reduced amplitude reads **19 ticks
    against the true 77**.

    So the failure does not look like damage. It looks like a faster
    converter, which is the direction a result gets believed in.
    """
    period = eqtime.period_ticks(195, 8)
    at = device(period, rise_ticks=35.0)
    clean = sample(at, 300_000, 193, period)
    gapped = sample(at, 300_000, 193, period, drop_at=150_000)
    a, _ = eqtime.reconstruct(clean, 193, period)
    b, _ = eqtime.reconstruct(gapped, 193, period)
    assert _edge_width(b) < _edge_width(a) * 0.5, (_edge_width(a),
                                                   _edge_width(b))
    assert eqtime.sharpness(b) < eqtime.sharpness(a) * 0.9


# ------------------------------------------------------------------
# settling
# ------------------------------------------------------------------

def test_a_planted_settling_tail_is_measured_back():
    """A 30-code tail with a 400-tick time constant leaves a 1-code band
    at tau*ln(30) = 3.4 tau. The number this whole exercise is for."""
    period = eqtime.period_ticks(195, 64)
    at = device(period, rise_ticks=35.0, tail_ticks=400.0, tail_codes=30.0)
    vals = sample(at, 900_000, 193, period)
    curve, _ = eqtime.reconstruct(vals, 193, period)
    seg = eqtime.segment_after_edge(curve)
    rows = eqtime.settle_profile(seg, lsb=1.0)
    prof = {r["codes"]: r["settled_by_s"] for r in rows}
    want = 400.0 * math.log(30.0) / TC
    assert prof[1.0] == pytest.approx(want, rel=0.15), prof
    # And the bands order the way a real tail does - a tighter band is
    # left later. Every band answering the same number is the signature
    # of a rail, which is what the retracted 118 us figure was.
    assert prof[10.0] < prof[5.0] < prof[2.0] < prof[1.0]


def test_one_stray_sample_does_not_become_a_settling_time():
    """The regression for the failure that found `min_run`. A single
    sample from the next half-cycle, 30 codes out, made every band
    report the whole segment."""
    curve = [3423.0] * 4000
    for i in range(120):                       # a real tail, 120 ticks
        curve[i] = 3423.0 - 20.0 * math.exp(-i / 40.0)
    curve[-1] = 3453.0                         # one stray at the far end
    rows = {r["codes"]: r for r in eqtime.settle_profile(curve, lsb=1.0)}
    assert rows[1.0]["settled_by_s"] == pytest.approx(
        40.0 * math.log(20.0) / TC, rel=0.2)
    assert rows[1.0]["n_outside"] > rows[1.0]["settled_by_s"] * TC - 5
    # Ungated, the stray wins and the answer becomes the whole record.
    lax = eqtime.settle_profile(curve, lsb=1.0, min_run=1)[3]
    assert lax["settled_by_s"] == pytest.approx(4000 / TC, rel=0.01)


def test_a_band_the_curve_never_leaves_reports_none_not_zero():
    period = eqtime.period_ticks(195, 8)
    at = device(period, rise_ticks=35.0)
    vals = sample(at, 200_000, 193, period)
    curve, _ = eqtime.reconstruct(vals, 193, period)
    prof = eqtime.settle_profile(eqtime.segment_after_edge(curve),
                                 bands=(100000.0,), lsb=1.0)
    assert prof[0]["settled_by_s"] is None
    assert prof[0]["left_band"] is False


def test_a_flat_level_produces_a_flat_reconstruction():
    """The control arm. A held level must come back flat - if the method
    manufactures a tail out of a constant, nothing it says about a real
    edge can be believed."""
    period = eqtime.period_ticks(195, 8)
    vals = sample(lambda ph: 2048.0, 400_000, 193, period, noise=4.0)
    curve, _ = eqtime.reconstruct(vals, 193, period)
    # Rms, not peak to peak: 3,120 bins of Gaussian noise span about
    # seven sigma by construction, so a peak-to-peak bound would be a
    # test of the bin count rather than of the reconstruction.
    ok = [v for v in curve if v is not None]
    mean = sum(ok) / len(ok)
    rms = math.sqrt(sum((v - mean) ** 2 for v in ok) / len(ok))
    assert rms < 0.5, rms
    assert eqtime.sharpness(curve) < 2.0
    # A band ABOVE the reconstruction's own residual is never left.
    assert eqtime.settle_profile(curve, bands=(3.0,),
                                 lsb=1.0)[0]["settled_by_s"] is None
    # And one below it is left constantly, on a level that is not
    # moving at all - the same lesson docs/noise.md records for the
    # scope. A band under the noise measures the noise.
    assert eqtime.settle_profile(curve, bands=(0.5,),
                                 lsb=1.0)[0]["settled_by_s"] is not None


def test_the_curve_goes_out_in_seconds_not_ticks():
    curve = [1.0, 2.0, None, 4.0]
    got = eqtime.to_seconds(curve)
    assert [i for i, _ in got] == pytest.approx([0.0, 1 / TC, 3 / TC])


def test_the_segment_starts_at_the_edge_not_at_the_start_of_the_level():
    """Found on the board, not here. Walking back "while still at the
    base level" walks across the entire other half of the cycle, so the
    segment began 40 us early and carried the far edge inside it - which
    put 319 codes rms into a region whose real residual is 0.28, and
    made every band answer the same number."""
    period = eqtime.period_ticks(195, 8)
    at = device(period, rise_ticks=35.0)
    vals = sample(at, 300_000, 193, period)
    curve, _ = eqtime.reconstruct(vals, 193, period)
    seg = eqtime.segment_after_edge(curve, pre=0)
    # One half cycle, give or take the edge, and NOT the whole period.
    assert len(seg) < period * 0.6, len(seg)
    assert len(seg) > period * 0.4, len(seg)
    # It begins at the base and ends settled at the far level.
    lo, hi = 677.0, 3423.0
    assert abs(seg[0] - lo) < 0.1 * (hi - lo)
    assert abs(seg[-1] - hi) < 0.1 * (hi - lo)


def test_a_rotated_cycle_gives_the_same_segment():
    """The fold's phase origin is arbitrary, so the answer must not
    depend on where the array happens to begin."""
    period = eqtime.period_ticks(195, 8)
    at = device(period, rise_ticks=35.0)
    vals = sample(at, 300_000, 193, period)
    curve, _ = eqtime.reconstruct(vals, 193, period)
    a = eqtime.segment_after_edge(curve, pre=0)
    for shift in (137, 900, 1600, 2500):
        rot = curve[shift:] + curve[:shift]
        b = eqtime.segment_after_edge(rot, pre=0)
        assert abs(len(b) - len(a)) <= 2, (shift, len(a), len(b))
