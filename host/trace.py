"""Analysis for a captured trace, parameterised by time and volts only.

Every threshold in the first version of the scope analysis was expressed
in *samples* - "an edge is a jump four times the median sample-to-sample
difference", "settling is the first fifth of a segment". Those numbers
were calibrated against 600-point screen records. The acquisition memory
holds 65,526 at 10 ns, a 109x change in density, and at that density
consecutive samples of a clean sine barely differ: the median lag-one
difference collapses toward the quantiser, four times it is still
approximately nothing, and the detector found **17,580 edges in a clean
sine**.

The lesson is not "retune the constants". It is that a threshold in
samples is a threshold in an accident of the instrument's settings. A
DAC step is a change of a known size over a known time - 789 to 938 ns
of rise, measured - and noise is a voltage. Both are physical, and a
detector written in those terms works at 600 points and at 65,526
without being told which it is looking at.

So everything here takes seconds and volts. Nothing takes a sample
count, and `tests/test_trace.py` runs the same synthetic signals through
at both densities and asserts the same answers.
"""
from __future__ import annotations

import math


def rebin(v, dt, target_dt):
    """Average into bins of about `target_dt`. Returns (v, dt, per_bin).

    Two things at once, and the second is the reason to reach for it.
    It puts a record on a known time base so a threshold means the same
    thing whatever the capture was. And averaging n samples divides
    uncorrelated noise by sqrt(n) - going from 10 ns to 1 us is 100
    samples a bin and a tenfold drop in the floor, which is sensitivity
    bought with time resolution nobody was using.

    Returns the record unchanged when the bin would be one sample.
    """
    if not v or target_dt <= dt:
        return v, dt, 1
    per = max(1, int(round(target_dt / dt)))
    if per <= 1:
        return v, dt, 1
    n = len(v) // per
    out = [sum(v[i * per:(i + 1) * per]) / per for i in range(n)]
    return out, dt * per, per


def noise_floor(v, dt, lag_s=200e-9):
    """The record's own noise, in volts RMS. Robust to the signal.

    The median absolute difference across a short lag, scaled to a
    standard deviation. Robust because a staircase's steps are a small
    minority of the differences and the median ignores them - which is
    what lets the same estimator run on a flat pin and on a moving one.

    `lag_s` rather than one sample, because at 10 ns the noise is
    bandwidth-limited and adjacent samples are correlated: differencing
    neighbours measures the correlation, not the amplitude. 200 ns is
    past that here and still short against any real slope.
    """
    if len(v) < 8:
        return 0.0
    lag = max(1, int(round(lag_s / dt)))
    d = [abs(v[i + lag] - v[i]) for i in range(0, len(v) - lag, max(1, lag))]
    if not d:
        return 0.0
    d.sort()
    mad = d[len(d) // 2]
    # |X - Y| for independent normals has mean sigma*2/sqrt(pi); the
    # median of the folded difference is ~0.9539*sigma*sqrt(2).
    return mad / (0.9539 * math.sqrt(2.0))


def quantised_floor(v, dt, quantum=None):
    """noise_floor(), never below what the instrument can resolve.

    A pin quieter than one screen level reads as exactly zero noise -
    correctly, because every sample lands on the same level - and zero
    is useless as a scale: every prominence computed against it comes
    out at 10^12. The quantiser's own contribution is q/sqrt(12), and
    that is the floor when the pin is below it.

    `quantum` is one screen level in volts; inferred from the trace's
    own distinct values when not given.
    """
    est = noise_floor(v, dt)
    if quantum is None:
        vals = sorted(set(v))
        gaps = [b - a for a, b in zip(vals, vals[1:]) if b > a]
        quantum = min(gaps) if gaps else 0.0
    return max(est, quantum / math.sqrt(12.0))


def period_of(v, dt, hint_s, search=0.25):
    """The trace's own repeat period, near `hint_s`.

    Folding at the COMMANDED frequency is an assumption, and on this
    bench it was wrong enough to matter: folding a sine at its nominal
    3125 Hz put one cycle's peak against another's trough and reported
    the whole 2.3 V swing as a per-cycle deviation. The trace knows its
    own period; ask it.

    Coarse search by mean absolute difference against a shifted copy,
    on a rebinned record so the search is cheap, then refined.
    """
    if len(v) < 4:
        return hint_s
    # Rebin to about 200 points per hinted period - enough to locate the
    # period well inside a sample, cheap enough to scan.
    target = hint_s / 200.0
    w, wdt, _ = rebin(v, dt, target) if target > dt else (v, dt, 1)
    centre = hint_s / wdt
    lo = max(2, int(centre * (1 - search)))
    hi = min(len(w) - 2, int(centre * (1 + search)))
    if hi <= lo:
        return hint_s
    best, best_lag = None, centre
    n = len(w)
    for lag in range(lo, hi + 1):
        m = n - lag
        if m < 8:
            continue
        step = max(1, m // 400)
        acc = cnt = 0
        for i in range(0, m, step):
            acc += abs(w[i + lag] - w[i])
            cnt += 1
        score = acc / cnt
        if best is None or score < best:
            best, best_lag = score, lag
    return best_lag * wdt


def find_edges(v, dt, min_step, rise_s=900e-9):
    """Where the trace steps by at least `min_step` volts.

    Differenced over a window matched to the converter's rise time, not
    over one sample. At 10 ns a real DAC step spans about ninety
    samples, so a single-sample difference sees a ninetieth of it and is
    indistinguishable from noise - which is exactly how a clean sine
    produced 17,580 edges.

    Returns one index per edge, at its steepest point, rather than one
    per sample that happens to be inside a transition.
    """
    if len(v) < 4:
        return []
    w = max(1, int(round(rise_s / dt)))
    if w >= len(v):
        return []
    d = [v[i + w] - v[i] for i in range(len(v) - w)]
    hits = [i for i, x in enumerate(d) if abs(x) >= min_step]
    if not hits:
        return []
    # Collapse each contiguous run to its steepest sample.
    out, run = [], [hits[0]]
    for i in hits[1:]:
        if i - run[-1] <= w:
            run.append(i)
        else:
            out.append(max(run, key=lambda k: abs(d[k])) + w // 2)
            run = [i]
    out.append(max(run, key=lambda k: abs(d[k])) + w // 2)
    return out


def plateaus(v, dt, edges, settle_s=1.2e-6, min_hold_s=1e-6,
             guard_s=None):
    """(start, stop) index ranges where the trace is holding a level.

    Excluded by TIME at BOTH ends, and the second end is the one that is
    easy to forget. `find_edges` reports an edge at the middle of its
    transition, so the samples just before it are already on their way
    to the next level - a segment that runs up to the edge index carries
    half a step in it, and the residual then reports a fraction of the
    step as an excursion. Measured here as a 0.196 V "find" on a trace
    with nothing planted in it.

    Settling after an edge is the measured 789-938 ns rise plus margin;
    the guard before the next one defaults to the same. A *fraction* of
    the segment would make both windows depend on how many samples the
    instrument happened to take, which is the mistake this module
    exists to remove.
    """
    n = len(v)
    marks = [0] + [e for e in edges if 0 < e < n] + [n]
    skip = max(1, int(round(settle_s / dt)))
    guard = max(1, int(round((settle_s if guard_s is None else guard_s)
                             / dt)))
    least = max(2, int(round(min_hold_s / dt)))
    out = []
    for a, b in zip(marks, marks[1:]):
        start = a + skip if a else a
        stop = b - guard if b < n else b
        if stop - start >= least:
            out.append((start, stop))
    return out


def residuals(v, dt, *, min_step, rise_s=900e-9, settle_s=1.2e-6):
    """Deviation from each held level, on the settled samples only.

    Returns (resid, segments) with `None` wherever the sample was inside
    a transition or its settling and therefore says nothing about a
    level being held. This is the shape the issue-#5 artifact is
    described in: a brief excursion on a pin that is otherwise holding.
    """
    edges = find_edges(v, dt, min_step, rise_s)
    segs = plateaus(v, dt, edges, settle_s, guard_s=max(settle_s, rise_s))
    resid = [None] * len(v)
    for a, b in segs:
        window = sorted(v[a:b])
        level = window[len(window) // 2]
        for i in range(a, b):
            resid[i] = v[i] - level
    return resid, segs


def worst(resid):
    """(index, value) of the largest residual, or (None, None).

    Explicitly None when there is nothing to report. `max(..., key=abs)`
    over an all-zero list returns index 0 with a straight face, and that
    was read once as a feature landing in the same place every run.
    """
    live = [(i, r) for i, r in enumerate(resid) if r is not None]
    if not live:
        return None, None
    i, r = max(live, key=lambda p: abs(p[1]))
    return (i, r) if r else (None, None)


def fold_compare(v, dt, period_s, update_s=None, settle_s=1.2e-6):
    """Split a record into cycles and compare each against the others.

    The instrument a plateau residual is not. A residual from a held
    level works when the trace holds levels; a sine staircase does not
    hold one for long, because its step sizes run from nearly zero at
    the peaks to a couple of hundred millivolts at the crossings. A
    detector tuned to the large steps treats a run of small ones as one
    long plateau and reports the waveform's own slope as an excursion -
    3,921 codes of "defect" on a clean sine, measured.

    Folding removes the waveform instead of modelling it. Every cycle is
    the same commanded waveform, so the median across cycles at each
    phase IS the waveform, with no fit and no assumption about shape.
    What is left is what differs between cycles, and something that
    happens once per table wrap is in exactly one of them.

    **Transitions are masked by time, from `update_s`, and not by
    finding steps in the data.** A cycle is not a whole number of
    samples, so successive cycles sample a step at different points on
    its rise: one just before, the next just after, and the difference
    is the entire step. No interpolation removes that - the two cycles
    genuinely saw different voltages, because the pin really was in
    transit. Detecting those phases from `typical` was tried and is a
    trap: a staircase's steps are 32 phases out of 32,000, so the median
    phase-to-phase move is zero, and every threshold built on it either
    masks nothing or masks the entire record.

    The converter updates on a schedule this project knows - `update_s`
    - and settles in a time it has measured. That is enough to say which
    phases are meaningless without looking at the data at all, which is
    the principle the rest of this module runs on.
    """
    period_f = period_s / dt
    if period_f < 8 or len(v) < 2 * period_f:
        return [], [], 0
    n = int(len(v) // period_f)
    bins = int(period_f)

    def at(x):
        i = int(x)
        if i + 1 >= len(v):
            return v[-1]
        f = x - i
        return v[i] * (1.0 - f) + v[i + 1] * f

    cycles = [[at(k * period_f + j * period_f / bins) for j in range(bins)]
              for k in range(n)]
    typical = []
    for j in range(bins):
        col = sorted(c[j] for c in cycles)
        typical.append(col[len(col) // 2])

    dev = [[c[j] - typical[j] for j in range(bins)] for c in cycles]
    if update_s and update_s > 0:
        # WHERE the update schedule starts, from the data.
        #
        # Masking at multiples of update_s measured from the record's
        # first sample assumes the record begins on an update boundary,
        # and it does not - it begins wherever the trigger landed. The
        # mask then falls between the transitions instead of on them,
        # leaving every step unmasked while deleting good phases, and
        # the fold reports the sine's full 2.3 V swing as a per-cycle
        # deviation.
        #
        # The transitions are in `typical`, which is the waveform with
        # the noise already taken out of it by the median across cycles.
        # Find the first and count from there.
        bin_dt = period_s / bins
        swing = max(typical) - min(typical)
        marks = find_edges(typical, bin_dt, min_step=max(0.06 * swing,
                                                         1e-6),
                           rise_s=max(2 * bin_dt, 200e-9))
        origin = (marks[0] * bin_dt) if marks else 0.0
        for j in range(bins):
            t = j * period_s / bins - origin
            r = t % update_s
            # Distance to the nearest update boundary, not the time
            # since the last one. A phase just BEFORE a boundary is as
            # useless as one just after: the interpolation there
            # straddles the step, and one cycle lands on each side of
            # it. Masking only the trailing side left a full step -
            # 402 codes on a sine whose steps are 400 - at exactly the
            # phases the mask was supposed to remove.
            if min(r, update_s - r) < settle_s:
                for c in dev:
                    # None, not 0.0. A masked phase is one that says
                    # nothing, and zero is a statement - counted into
                    # the typical magnitude it drags the median toward
                    # nothing and inflates every prominence computed
                    # against it. Same convention as residuals().
                    c[j] = None
    return dev, typical, n


def odd_cycle(per_cycle, floor=None):
    """(cycle, phase, value) of the largest single deviation, and how
    far it stands above the rest.

    Returns (None, None, None, 0.0) when nothing stands out, rather than
    handing back an argmax over noise.
    """
    if not per_cycle:
        return None, None, None, 0.0
    flat = [(k, j, x) for k, c in enumerate(per_cycle)
            for j, x in enumerate(c) if x is not None]
    if not flat:
        return None, None, None, 0.0
    k, j, x = max(flat, key=lambda t: abs(t[2]))
    if not x:
        return None, None, None, 0.0
    # Prominence against the NOISE, not against the median deviation.
    #
    # Most compared phases sit at exactly zero deviation, because the
    # pin is quieter than one screen level there and both cycles land
    # on the same level. A median over those is zero, and dividing by
    # it produced prominences of 2.3e12 - a number that says only that
    # the denominator was wrong.
    if floor is None:
        mags = sorted(abs(t[2]) for t in flat)
        floor = mags[int(len(mags) * 0.75)] or 1e-12
    return k, j, x, abs(x) / max(floor, 1e-12)
