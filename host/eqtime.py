"""Equivalent-time sampling: resolving what the ADC is too slow to see.

The settling question - when does the DAC's output stop moving, to one
code - is out of reach of both instruments on this bench for opposite
reasons. The scope resolves 20 ns and 20 codes; the ADC resolves 4 codes
raw, 0.25 averaged, and 2.2 us. One is too coarse in the vertical, the
other in the horizontal, and the answer needs both.

This closes the horizontal gap without new hardware. `=<dac>,<adc>,<n>M`
already runs the DAC off TIOA1 and the ADC off TIOA0 as two independent
timers, and the handler's own comment says why it was built:

    Giving the two clocks slightly different rates walks that phase
    through a full period within one capture, so one run samples the
    whole phase space instead of whichever point a run happened to
    start at.

So sample n does not land 2.2 us after sample n-1 *in the waveform's
frame*: it lands at

    phase(n) = (n * RC_adc) mod P,      P = 2 * points * RC_dac

which for coprime RC_adc and P visits every one of the P tick positions.
At RC_dac 195 and RC_adc 193 that is 3,120 positions of 25.6 ns each -
35x finer than the sample period - and every position accumulates as
many samples as the capture is long, so the vertical improves as
sqrt(N) at the same time.

## Why this is exact rather than approximate

Everything above is integer arithmetic on tick counts. There is no
accumulated phase error, no fitted drift and no interpolation, provided
two things hold, and both are checked rather than assumed:

**The sample index must map to time.** It does only if no frame was
dropped and no overrun occurred - a gap makes n a lie for every sample
after it. `check_contiguous()` refuses a run rather than reconstructing
one, because the failure is silent otherwise: a dropped frame smears the
curve exactly the way a slow settling tail would.

**The two periods must be known exactly, not nearly.** They are integer
RC values, and a truncated frequency is not good enough - 4.6 ppm of
error accumulates to four whole waveform periods across a 900,000 sample
capture. `rc_from_hz()` recovers RC by undoing the device's own integer
division, which is exact rather than approximate: the worst margin to
ambiguity over every rate this project uses is 14,000x.

Note what does *not* matter: MCK's true value. The reconstruction needs
the **ratio** of two RC values, so a crystal that is not exactly 78 MHz
scales the time axis and leaves the phase arithmetic untouched.

## The period is found, not asserted

`find_period()` scans candidate RC_dac values and picks the one whose
reconstruction is sharpest, because a wrong period smears an edge and
the right one does not. That is deliberate: it needs no readback the
control channel does not have, and the sharpness peaking at exactly one
integer is itself evidence the model is right. A scan whose peak is flat
or lands between integers means something in the model is wrong, and
that is worth knowing before reading a curve off it.
"""
from __future__ import annotations

import math

#: Fraction of the hold discarded before the next transition. A
#: transition's onset is a couple of rise-widths before its steepest
#: point, and leaving any of it in the segment puts a large, contiguous,
#: out-of-band excursion at the far end - which makes every settling
#: band report the segment's own length.
GUARD_FRAC = 0.05

#: TC clock: MCK/2. Every RC in this project divides 39 MHz - CLAUDE.md
#: lists MCK = 78 and not 84 among the facts that are easy to get wrong.
TC_CLOCK_HZ = 39_000_000


def rc_from_hz(reported_hz, tc_clock=TC_CLOCK_HZ):
    """The exact RC behind a reported frequency.

    The device computes `(SystemCoreClock/2) / RC` in integer
    arithmetic, so this undoes a division rather than estimating a
    frequency - and the result is an integer that is either right or
    obviously wrong, never slightly off.

    Ambiguity would need the truncation error to approach the spacing
    between adjacent RC values. At the ADC's floor, RC 86, that spacing
    is 5,212 Hz against a 0.37 Hz truncation: a margin of 14,000. The
    check is here anyway, because "it cannot happen" is how this project
    has been wrong before.
    """
    if not reported_hz:
        return None
    rc = round(tc_clock / reported_hz)
    if rc < 1:
        return None
    back = tc_clock // rc
    if back != int(reported_hz):
        return None
    return rc


def period_ticks(rc_dac, points, *, updates_per_cycle=None):
    """Ticks in one waveform cycle.

    DACC TAG mode interleaves DAC0 and DAC1, so a cycle costs
    `2 * points` updates unless the second channel has been given up -
    which is `gen_updates_per_cycle()` on the device, and the factor of
    two the generator's frequency formula carries.
    """
    n = updates_per_cycle if updates_per_cycle else 2 * points
    return n * rc_dac


def check_contiguous(stream):
    """Why this run may or may not be reconstructed.

    Returns a list of reasons, empty when the index-to-time mapping
    holds. A dropped frame does not announce itself in the reconstructed
    curve, and what it does is worse than smearing: it re-phases every
    later sample by a constant, so the fold averages two shifted copies
    of the waveform and produces a *half-amplitude* step. A 10-90% width
    measured against that reduced amplitude reads 19 ticks where the
    truth is 77.

    The failure therefore does not look like damage. It looks like a
    faster converter - which is the direction in which a result gets
    believed rather than questioned.
    """
    bad = []
    if getattr(stream, "seq_gaps", 0):
        bad.append(f"{stream.seq_gaps} sequence gaps")
    if getattr(stream, "dropped_frames", 0):
        bad.append(f"{stream.dropped_frames} dropped frames")
    if getattr(stream, "overrun_frames", 0):
        bad.append(f"{stream.overrun_frames} frames flagged overrun")
    if getattr(stream, "crc_bad", 0):
        bad.append(f"{stream.crc_bad} bad CRCs")
    return bad


def reconstruct(values, rc_adc, period):
    """Fold every sample onto its phase within one waveform cycle.

    Returns `(curve, counts)`, both `period` long and indexed in TC
    ticks. `curve[i]` is None where no sample landed there, which
    happens when RC_adc and the period share a factor - and saying so is
    better than interpolating, since a gap in phase coverage is a
    property of the rate pair the caller chose.
    """
    if period < 2 or not values:
        return [], []
    acc = [0.0] * period
    cnt = [0] * period
    step = rc_adc % period
    ph = 0
    for v in values:
        acc[ph] += v
        cnt[ph] += 1
        ph += step
        if ph >= period:
            ph -= period
    curve = [acc[i] / cnt[i] if cnt[i] else None for i in range(period)]
    return curve, cnt


def sharpness(curve):
    """How much of the waveform's own amplitude survived the fold.

    The figure `find_period()` maximises, and the choice of statistic
    matters more than it looks. A period that is wrong maps each
    reconstruction bin onto many different true phases, so the bin
    averages toward the mean and the waveform's levels collapse into
    each other; the right period stacks every cycle on the same bin and
    the full amplitude comes back.

    Measured against the alternative rather than assumed. On a synthetic
    square with 2 codes of noise, scanning five candidate periods:

        statistic                right period   next best   margin
        sum of squared diffs       7,540,293    4,309,099     1.75x
        robust span (p99.5-p0.5)     2,746.9        145.0    18.9x

    Sum of squared differences is dominated by the noise in every bin,
    which is why its margin is thin. The span is also interpretable:
    2,746.9 is the square's actual amplitude, so the winning candidate
    does not merely score highest, it returns the right number.

    Percentiles rather than min and max, for the reason recorded twice
    already in this project - one outlying sample in 65,526 read a
    2.19 V pin as 3.640 V peak to peak.
    """
    vals = sorted(v for v in curve if v is not None)
    if len(vals) < 8:
        return 0.0
    hi = vals[int(0.995 * (len(vals) - 1))]
    lo = vals[int(0.005 * (len(vals) - 1))]
    return hi - lo


def coverage(counts):
    """Fraction of phase positions that got at least one sample."""
    return (sum(1 for c in counts if c) / len(counts)) if counts else 0.0


def find_period(values, rc_adc, candidates):
    """The waveform period, chosen by which reconstruction is sharpest.

    `candidates` is an iterable of periods in ticks. Returns a list of
    `{period, sharpness, coverage}` sorted best first, so the caller can
    see the margin rather than only the winner - a scan whose top two
    are level has not identified anything, and that is a result about
    the model rather than about the converter.
    """
    out = []
    for p in candidates:
        curve, cnt = reconstruct(values, rc_adc, p)
        out.append({"period": p, "sharpness": sharpness(curve),
                    "coverage": coverage(cnt)})
    out.sort(key=lambda r: -r["sharpness"])
    return out


def to_seconds(curve, tc_clock=TC_CLOCK_HZ):
    """The curve as (t, value) pairs, gaps dropped.

    In seconds, because everything downstream of here - `host/trace.py`
    and every edge and settling routine in it - takes seconds and volts
    and nothing else, for the reason a threshold in samples is a
    threshold in an accident of the instrument's settings.
    """
    dt = 1.0 / tc_clock
    return [(i * dt, v) for i, v in enumerate(curve) if v is not None]


def edge_index(curve, *, rising=True):
    """Where the waveform steps, as the steepest adjacent difference.

    Returns the index *after* the step, or None if the curve has no
    edge in it - which is what a held level looks like and is a valid
    answer rather than a failure.

    **The scan wraps.** The curve is one folded cycle, so its two edges
    are at an arbitrary rotation and one of them routinely falls across
    the join - the array can begin at the high level and end at the low
    one, with the rise existing only between the last bin and the first.
    A scan that stopped at the end of the array found no rising edge at
    all in exactly that case, which is not a rare alignment: it is
    whatever phase the two timers happened to start at.
    """
    vals = [(i, v) for i, v in enumerate(curve) if v is not None]
    if len(vals) < 4:
        return None
    best_i, best_d = None, 0.0
    pairs = list(zip(vals, vals[1:])) + [(vals[-1], vals[0])]
    for (ia, a), (ib, b) in pairs:
        d = (b - a) if rising else (a - b)
        if d > best_d:
            best_d, best_i = d, ib
    return best_i


def rotate(curve, index, *, pre=0):
    """Rotate the curve so `index` lands `pre` ticks from the start.

    The absolute phase origin is whatever the two timers happened to be
    doing when they started - not knowable, and not needed, because the
    curve is circular. `pre` keeps some pre-edge baseline in view, which
    a rise measurement needs and a settling measurement does not.
    """
    if index is None or not curve:
        return curve
    start = (index - pre) % len(curve)
    return curve[start:] + curve[:start]


def levels(curve, *, lo_pct=0.02, hi_pct=0.98):
    """The waveform's two levels, robustly.

    Percentiles rather than min and max: a single outlying bin would set
    the step size, and every threshold below is a fraction of it.
    """
    vals = sorted(v for v in curve if v is not None)
    if len(vals) < 8:
        return None, None
    return (vals[int(lo_pct * (len(vals) - 1))],
            vals[int(hi_pct * (len(vals) - 1))])


def segment_after_edge(curve, *, rising=True, pre=0, frac=0.1):
    """One step and the hold that follows it, cut before the next step.

    **Both ends are found by where the output leaves a level, not by the
    steepest difference.** That distinction is the whole correctness of
    this function and it was wrong in the first version. The steepest
    single-tick difference sits in the *middle* of a transition, so a
    segment delimited by steepest points starts partway up the rise and
    ends partway down the fall - and the "settled" part then contains a
    falling edge. Measured on the board, that put 189 codes rms into a
    region whose real residual is 0.28, and every band in the settling
    profile answered the same number: the signature of a rail, produced
    here by the analysis rather than by the instrument.

    So: walk back from the steepest rise while the trace is still at the
    base level, and forward from it until the trace leaves the settled
    level by `frac` of the step. A settling tail is orders of magnitude
    smaller than that threshold, so the cut cannot clip the thing being
    measured.

    A full cycle contains both levels, and a band taken about one of
    them is left by the other - which reports the whole period as the
    settling time. That is the shape of the retracted 118 us figure,
    arriving by a different route.
    """
    i = edge_index(curve, rising=rising)
    lo, hi = levels(curve)
    if i is None or lo is None or hi is None or hi <= lo:
        return curve
    n = len(curve)
    step = hi - lo
    base = lo if rising else hi
    settled = hi if rising else lo

    def at(k):
        return curve[k % n]

    # Back to the LAST sample still at the base level - the one
    # immediately before the transition, not the first one of the whole
    # base region. Walking back "while at base" walks the entire other
    # half of the cycle, which put the far edge back inside the segment
    # and reproduced the very artifact this cut exists to remove.
    start = i
    for back in range(1, n):
        v = at(i - back)
        if v is None:
            continue
        if abs(v - base) <= frac * step:
            start = i - back
        break

    # Forward to the next transition, then back off a guard.
    #
    # The end is taken from the *steepest* opposite difference and then
    # trimmed, rather than from "where the trace leaves the settled
    # level". That threshold cannot be set: too loose and it admits the
    # first samples of the fall - which are large, contiguous and
    # out-of-band, so every band reports the whole segment - and too
    # tight and it fires on the settling tail itself, truncating the
    # thing being measured. The steepest point of a transition is
    # unambiguous and its onset is a couple of time constants earlier,
    # so a guard proportional to the hold clears it without depending on
    # how big the tail is.
    #
    # 5% rather than 2%, measured: at 2% the 200 kHz segment kept enough
    # of the fall to leave 8.6 codes rms in a region whose real residual
    # is 0.6, and every band then answered the segment's own length. The
    # cost is 5% of the hold, which is 2 us out of 39.
    rest = [at(start + f) for f in range(1, n)]
    fall = edge_index(rest, rising=not rising)
    if fall is None:
        return [at(k) for k in range(start - pre, start + n)]
    end = start + fall
    guard = max(8, int(GUARD_FRAC * max(1, fall)))
    end -= guard
    if end <= start:
        end = start + 1

    return [at(k) for k in range(start - pre, end + 1)]


def settle_profile(curve, level=None, *, tc_clock=TC_CLOCK_HZ,
                   bands=(10.0, 5.0, 2.0, 1.0, 0.5), lsb=1.0, min_run=2):
    """When the curve last leaves each band about its final level.

    The measurement the whole file is for. The final level is taken from
    the far end of the segment, not from a coarse pass that might have
    been looking at the other level - which is how the retracted 118 us
    figure picked the wrong one in one run of seven.

    **`min_run` is not a tuning knob, it is the fix for a specific
    failure.** "The last sample outside the band" is maximally sensitive
    to one stray: a single sample from the next half-cycle, 30 codes out
    of 12,480 in the segment, made every band report the full
    half-period as its settling time - the same shape as the artifacts
    this project has already retracted twice. A settling tail is
    contiguous by definition, so an excursion has to persist for at
    least `min_run` ticks to count. `n_outside` is reported alongside so
    a caller can see when the two answers differ.

    Returns None for a band the curve never leaves, which is the honest
    answer for a band wider than anything that happened and is not the
    same as zero.
    """
    vals = [(i, v) for i, v in enumerate(curve) if v is not None]
    if len(vals) < 8:
        return []
    if level is None:
        tail = sorted(v for _, v in vals[int(len(vals) * 0.75):])
        level = tail[len(tail) // 2]
    dt = 1.0 / tc_clock
    out = []
    for b in bands:
        thr = b * lsb
        last, n_out, run, run_end = None, 0, 0, None
        for i, v in vals:
            if abs(v - level) > thr:
                n_out += 1
                run += 1
                run_end = i
                if run >= min_run:
                    last = run_end
            else:
                run = 0
        out.append({"codes": b,
                    "settled_by_s": None if last is None else (last + 1) * dt,
                    "n_outside": n_out,
                    "left_band": last is not None,
                    "level": level})
    return out
