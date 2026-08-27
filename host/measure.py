#!/usr/bin/env python3
"""
Measurement library for the due_oscilloscope host tools.

The three CLI scripts (loopback.py, receive.py, usbbench.py) were
main() monoliths that measured and printed in one pass, so the only way
to test against them was to parse stdout. Everything that measures now
lives here and returns data; the scripts only format it.

Stdlib only, deliberately. The pytest suite runs from a venv because
pytest is not stdlib, but nothing in here may need one: these tools have
to work from the system interpreter during bring-up.

Nothing here may change measurement behaviour. The clock-paced feeder
with its 20 KB lead, the real-time thread promotion, the freshness
drain and the whole-packet write discipline are each load-bearing and
were arrived at by measuring the alternatives - read docs/usb.md before
touching any of them.
"""

from __future__ import annotations

import glob
import math
import os
import re
import shutil
import statistics
import struct
import subprocess
import sys
import threading
import time
import zlib
from array import array
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ports
from ports import find_ports, native_order, open_raw  # noqa: F401
import jitter
import rt
import transport

# ---------------------------------------------------------------------
# Wire format. Shared verbatim with lib/due_shared/src/frame.h.
# ---------------------------------------------------------------------

HDR_FMT = "<4sBBHIIIIII"
HDR_LEN = struct.calcsize(HDR_FMT)
MAGIC = b"DUE0"

FLAG_OVERRUN     = 1 << 0
FLAG_BURST_FIRST = 1 << 1
FLAG_BURST_LAST  = 1 << 2
FLAG_CONTINUOUS  = 1 << 3

# The ring primes and the DAC's first buffer plays before the signal is
# representative, so everything that judges the waveform starts a second
# into device time. It is the same offset loopback.py has always used
# for its settled sample window.
SETTLE_US = 1_000_000

FRAME_SAMPLES = 2032
FRAME_BYTES = HDR_LEN + FRAME_SAMPLES * 2

# TIMER_CLOCK1 is MCK/2. Both the TC and the ADC scale with MCK, which
# is why the measured cliffs sit at a fixed RC whatever MCK is set to.
MCK_HZ = 78_000_000
TC_CLOCK_HZ = MCK_HZ // 2          # 39 MHz

# The ADC labels map to channels descending: A0 is AD7, A1 is AD6,
# A2 is AD5. A2 carries the issue #5 impedance arm - 1.65 V behind
# 5.5k, against A1 at the same voltage behind a DAC output.
CH_A0 = 7
CH_A1 = 6
CH_A2 = 5
CHANNEL_LABELS = {7: "A0", 6: "A1", 5: "A2"}


def label_for(tag):
    return CHANNEL_LABELS.get(tag, "?")


def rc_for(hz):
    """Compare value the firmware will derive from a requested rate."""
    return TC_CLOCK_HZ // hz if hz else 0


def hz_for(rc):
    """Exact rate an RC produces. Rates that do not divide 39 MHz
    truncate in RC and shift every frequency derived from them."""
    return TC_CLOCK_HZ // rc if rc else 0


def goertzel(samples, fs, ftarget):
    """Single-bin DFT magnitude, normalised to sample count."""
    n = len(samples)
    if n == 0 or fs <= 0:
        return 0.0
    k = 2.0 * math.cos(2.0 * math.pi * ftarget / fs)
    s1 = s2 = 0.0
    mean = sum(samples) / n
    for x in samples:
        s0 = (x - mean) + k * s1 - s2
        s2, s1 = s1, s0
    power = s1 * s1 + s2 * s2 - k * s1 * s2
    return math.sqrt(max(power, 0.0)) * 2.0 / n


def slew_limit(tone_hz, amplitude_codes, fs_hz):
    """Largest step a clean sine can take between consecutive samples of
    one channel: the derivative peak, 2*pi*f*A/fs. Anything above it is
    data spliced from two points in time, which is exactly what the
    frame protocol exists to make impossible to present as continuous."""
    if fs_hz <= 0:
        return 0.0
    return 2.0 * math.pi * tone_hz * amplitude_codes / fs_hz


# The device's own sine is a staircase, not a wave: `gen` holds each DAC
# level for exactly two ADC samples and steps by up to ~38 codes. So
# slew_limit()'s continuous-sine derivative is the wrong model for it -
# it computes 16.85 where the honest ceiling is 38, and the "3x margin"
# that papered over the difference left only 1.3x of real headroom. That
# is why test_device_generated_waveform_is_continuous wobbled between
# passing and failing while a 780-splice defect sat under it.
#
# These two constants are measured, not chosen. See level_census().
STEP_FLAT_CODES = 2          # within this, two samples are one DAC level
STEP_SPLICE_CODES = 45       # above this, a step is not a DAC step


def level_steps(vals, flat=STEP_FLAT_CODES):
    """Collapse a staircase to its levels and return the steps between.

    Consecutive samples within `flat` codes of each other are one DAC
    level held across more than one ADC sample; each run of them becomes
    its mean. What comes back is the sequence of transitions between
    levels, which is what a splice has to survive and cannot.

    Collapsing matters even where the raw series separates just as well
    (it does on preset M). On a host-fed run the DAC update clock and
    the ADC trigger are free-running TC channels that beat, so one
    sample repeats and the next spans two DAC updates - a raw step of
    ~88 codes that is not a splice and that a raw threshold would count
    as one.
    """
    return _collapse(vals, flat)[0]


def _collapse(vals, flat):
    """(steps between levels, index of the sample each step lands on).

    The index matters as much as the step. Periodicity is a property of
    where events fall in the sample stream, and level indices do not
    carry it: a staircase collapses at a rate that follows the sine's
    own slope, so a metronome in sample space looks irregular in level
    space. This was got wrong once.
    """
    if len(vals) < 2:
        return [], []
    levels, starts, start = [], [], 0
    for i in range(1, len(vals)):
        if abs(vals[i] - vals[i - 1]) > flat:
            levels.append(sum(vals[start:i]) / (i - start))
            starts.append(start)
            start = i
    levels.append(sum(vals[start:]) / (len(vals) - start))
    starts.append(start)
    return ([abs(b - a) for a, b in zip(levels, levels[1:])], starts[1:])


def level_census(vals, threshold=STEP_SPLICE_CODES, flat=STEP_FLAT_CODES):
    """Count the steps a DAC staircase cannot account for.

    Returns `count` (steps above `threshold`), `max_step`, `levels`, and
    `gap` - the run of step sizes from `threshold` downward that nothing
    occupies.

    `gap` is the point of this. The threshold is not a tuned constant:
    on a healthy board the step distribution ends at 38 and on a spliced
    one the second population starts at 51, so 45 sits in a void twelve
    bins wide and any value across it reports the same number. A census
    that reports its own gap can be checked rather than trusted - if a
    later board narrows the void, the number to move is visible instead
    of inferred. Judge this by `count`, never by `max_step`: the defect
    that prompted it moved the maximum from 39 to 58, a factor of 1.5,
    while it moved the count from 0 to 780.
    """
    steps, where = _collapse(vals, flat)
    if not steps:
        return {"count": 0, "max_step": 0.0, "levels": 0, "gap": (0, 0),
                "threshold": threshold, "period": 0, "periodic": False}
    occupied = {int(s) for s in steps}
    lo = hi = int(threshold)
    while lo - 1 >= 0 and (lo - 1) not in occupied:
        lo -= 1
    while (hi + 1) not in occupied and hi < int(max(steps)) + 1:
        hi += 1

    # Where the oversized steps fall, not just how many. A splice is an
    # event: data joined at one point in time, once. Issue #5 is a
    # metronome - its events sit at a constant spacing equal to the
    # generator's table length, 779 of 779 gaps identical, and that
    # regularity is what says it is locked to the DAC's buffer wrap
    # rather than to anything that happened to the stream. Callers use
    # it to tell the known device artifact from a real discontinuity
    # without having to trust a count.
    at = [w for st, w in zip(steps, where) if st > threshold]
    # One occurrence can cross the threshold twice - going up into the
    # displaced sample and back down out of it - so neighbours a couple
    # of samples apart are one event, not two.
    occurrences = [w for k, w in enumerate(at) if k == 0 or w - at[k - 1] > 4]
    period, periodic = 0, False
    if len(occurrences) >= 10:
        gaps = [b - a for a, b in zip(occurrences, occurrences[1:])]
        period = max(set(gaps), key=gaps.count)
        periodic = gaps.count(period) >= 0.9 * len(gaps)
    return {
        "count": len(at),
        "max_step": max(steps),
        "levels": len(steps) + 1,
        "gap": (lo, hi),
        "threshold": threshold,
        "period": period,
        "periodic": periodic,
    }


# Within this many codes of the run's own median, a sample is the flat
# line plus noise. Measured, like the two above: on a healthy board A1
# sits at sd 0.87 with excursions to 7-8 codes, and the issue #5
# population lands at 26-32. The void between them measured 9..20 over
# four runs, so 20 sits in eleven empty bins and any value across them
# reports the same number. flat_census() reports that void so it can be
# checked rather than trusted.
FLAT_DEV_CODES = 20


def periodic_census(vals, min_events=10, regularity=0.9):
    """Find the issue #5 signature by its period, not by its size.

    Every fixed threshold written for this defect has gone blind to it
    within a day, because the amplitude is not a property of the defect.
    Measured so far, all of it the same artifact: 12-14 and ~15 codes
    with the two clocks locked, 26-32 on macOS, 49-50 and 63-68 on
    Windows. STEP_SPLICE_CODES = 45 missed the macOS form;
    FLAT_DEV_CODES = 20 misses both locked forms, including the one the
    session that chose 20 had itself measured at 15.

    What has never varied is the period. It is GEN_TABLE_LEN, it follows
    the table when the table is doubled, and the gaps are 100% identical
    on every reproduction on either host. So key on that: sweep the
    threshold down from the run's own noise floor and accept the widest
    set of events whose spacing is regular. Noise does not come at a
    constant interval; this does.

    `sd` is the corroborating tell and costs nothing to report - a clean
    A1 sits at 0.83-0.87 and a reproducing one at 1.04-1.05, because a
    few hundred displaced samples move the deviation of the whole run.

    Returns count, period, regularity, amplitude (median absolute
    deviation of the events), threshold used, and sd. count is 0 when
    nothing regular was found at any threshold.
    """
    import statistics as _st
    none = {"count": 0, "period": 0, "regularity": 0.0, "amplitude": 0.0,
            "threshold": 0.0, "sd": 0.0}
    if len(vals) < 4 * min_events:
        return none
    base = _st.median(vals)
    sd = _st.pstdev(vals[:min(len(vals), 20000)]) or 0.5
    best = none
    # Down from well clear of the noise. Stop before the floor: at 3 sd a
    # clean run offers plenty of excursions and some will look regular by
    # accident over a long series.
    for k in (12.0, 10.0, 8.0, 6.0, 5.0, 4.0):
        thr = k * sd
        at = [i for i, x in enumerate(vals) if abs(x - base) > thr]
        if len(at) < min_events:
            continue
        gaps = [b - a for a, b in zip(at, at[1:])]
        period = max(set(gaps), key=gaps.count)
        reg = gaps.count(period) / len(gaps)
        if reg >= regularity and period > 1 and len(at) > best["count"]:
            best = {"count": len(at), "period": period, "regularity": reg,
                    "amplitude": _st.median(abs(vals[i] - base) for i in at),
                    "threshold": thr, "sd": sd}
    if best["count"]:
        best["sd"] = sd
        return best

    # The gap test above assumes one event per period, and that is not
    # what the artifact always is. At ADC RC 200 on macOS each wrap
    # produces a burst of about four displaced samples spaced 64 apart,
    # the bursts repeating at 512: the gaps run 64, 64, 64, 320, so the
    # commonest gap holds 0.77 of them and nothing clears 0.9. That run
    # carried 3276 events at 68 codes with sd 4.58 against a clean 0.86,
    # and this function called it clean.
    #
    # Shift invariance does not care how the events are arranged inside
    # the period, only that the arrangement repeats: for the true P,
    # nearly every event has another event P samples later. It scores a
    # single displacement per wrap exactly as the gap test does, so the
    # simple case is unchanged and this only ever runs when that found
    # nothing.
    for k in (12.0, 10.0, 8.0, 6.0, 5.0, 4.0):
        thr = k * sd
        at = [i for i, x in enumerate(vals) if abs(x - base) > thr]
        if len(at) < min_events:
            continue
        found = _shift_period(at, min_period=2, max_period=4096,
                              regularity=regularity)
        if found and (not best["count"] or len(at) > best["count"]):
            period, reg = found
            best = {"count": len(at), "period": period, "regularity": reg,
                    "amplitude": _st.median(abs(vals[i] - base) for i in at),
                    "threshold": thr, "sd": sd}
    if best["count"]:
        best["sd"] = sd
    else:
        best = dict(none, sd=sd)
    return best


def _shift_period(at, min_period, max_period, regularity, probes=400):
    """Smallest P for which the event set repeats every P samples.

    Returns (P, score) or None. The score is the fraction of probed
    events that have another event exactly P later, which is 1.0 for any
    pattern locked to a period whatever its shape, and near the event
    density for an unlocked one.

    Smallest wins, because 2P and 4P score just as well and the period
    is meant to be comparable with GEN_TABLE_LEN. Probing a bounded
    subset keeps this linear in the range rather than in the event
    count - the full sweep is 4095 candidates and a long run has
    thousands of events.
    """
    if len(at) < 4:
        return None
    seen = set(at)
    last = at[-1]
    for period in range(min_period, max_period + 1):
        usable = [i for i in at[::max(1, len(at) // probes)] if i + period <= last]
        if len(usable) < 4:
            continue
        hits = sum(1 for i in usable if i + period in seen)
        score = hits / len(usable)
        if score >= regularity:
            return period, score
    return None


# The generator's table length, and so the period the artifact has been
# locked to on every reproduction. A default, not a constant: the table
# doubles under GEN_SINE_POINTS and the period follows it.
#
# It also stops being the generator's period the moment the resolution
# is changed. `=<shape>,<pts>W` sets points-per-cycle, and the internal
# generator's period is then 2 * points rather than the table length -
# so an issue-#5 fold taken at anything other than 256 points is folding
# at the wrong period. gen_fold_len() below is the honest form; this
# constant is the default because 256 is the default.
GEN_TABLE_LEN = 512

# Folding at 512 bins gives 512 chances for noise to throw up a peak, so
# the largest bin of a clean run sits around 3.2 sigma by construction.
# 6 is clear of that and still an order of magnitude more sensitive than
# any threshold detector written for this defect.
FOLD_Z_DIRTY = 6.0


def fold_profile(vals, period=GEN_TABLE_LEN, control_period=None):
    """Average the run at a known period. There is no threshold in here.

    Every detector this defect has defeated worked by deciding which
    samples are events, and each one went blind when the amplitude moved
    under whatever line it drew - 45 codes, then 20, then the shape.
    This one decides nothing. It folds the run at a period it is told
    and reports the average deviation at each phase, so a displacement
    smaller than the noise on any single sample still shows up in the
    mean of the several hundred wraps that share its phase.

    That is what answers the question the thresholds cannot: whether
    "presence may be constant" and only the amplitude varies. Noise in a
    bin falls as sqrt(n), so ~780 wraps buy a factor of 28 and put the
    floor near a fifth of a code - two orders below FLAT_DEV_CODES.

    `z` is the peak bin in units of the scatter between bins, estimated
    robustly (MAD across the bin means) so that the events themselves do
    not inflate it. `control_z` is the same statistic folded at a period
    the signal is not locked to; a real lock gives a high z and a low
    control_z, and anything with both high is an artifact of the fold
    rather than a finding.

    Deterministic: same samples in, same numbers out, no randomness and
    nothing tuned.
    """
    import statistics as _st
    if control_period is None:
        control_period = period + 1
    none = {"period": period, "peak": 0.0, "peak_phase": 0, "z": 0.0,
            "stderr": 0.0, "n_per_bin": 0, "control_period": control_period,
            "control_z": 0.0, "profile": [], "spike": 0.0, "spike_phase": 0,
            "spike_z": 0.0, "control_spike_z": 0.0}
    if len(vals) < 4 * period:
        return none
    base = _st.median(vals)

    def _fold(p):
        sums = [0.0] * p
        counts = [0] * p
        for i, x in enumerate(vals):
            b = i % p
            sums[b] += x - base
            counts[b] += 1
        means = [sums[b] / counts[b] for b in range(p) if counts[b]]
        centre = _st.median(means)
        devs = [abs(m - centre) for m in means]
        # MAD, not sd: a few hundred displaced samples all land in one
        # bin, and an sd across bins would be inflated by the very thing
        # being measured. 1.4826 makes MAD comparable to a sigma.
        mad = _st.median(devs) * 1.4826 or 1e-9
        peak_phase = max(range(len(means)), key=lambda b: abs(means[b] - centre))
        peak = means[peak_phase] - centre

        # Curvature, so the measurement survives a waveform underneath.
        # Folding assumes the profile is flat apart from the artifact,
        # which holds only while A1 is a DC channel. Pull the DAC1
        # jumper and the floating input follows A0's sine through the
        # multiplexer, the profile becomes the waveform, and peak/MAD
        # goes to 1 whether or not anything is there.
        #
        # A sine is smooth across neighbouring bins and the artifact is
        # one bin wide, so subtracting each bin's own neighbours removes
        # the waveform and leaves the spike at its full height. This is
        # strictly the better statistic - on a flat channel the
        # subtraction takes nothing away - and it is what makes the
        # disconnected-jumper test answerable at all.
        m = len(means)
        resid = [means[b] - (means[(b - 1) % m] + means[(b + 1) % m]) / 2.0
                 for b in range(m)]
        rc_ = _st.median(resid)
        rmad = _st.median([abs(x - rc_) for x in resid]) * 1.4826 or 1e-9
        sphase = max(range(m), key=lambda b: abs(resid[b] - rc_))
        speak = resid[sphase] - rc_
        return (means, peak, peak_phase, abs(peak) / mad, mad, min(counts),
                speak, sphase, abs(speak) / rmad)

    means, peak, phase, z, mad, n, speak, sphase, sz = _fold(period)
    _, _, _, cz, _, _, _, _, scz = _fold(control_period)
    return {"period": period, "peak": peak, "peak_phase": phase, "z": z,
            "stderr": mad, "n_per_bin": n, "control_period": control_period,
            "control_z": cz, "profile": means,
            "spike": speak, "spike_phase": sphase, "spike_z": sz,
            "control_spike_z": scz}


def pair_fold(vals, period=GEN_TABLE_LEN):
    """Fold the staircase channel, by differencing within each DAC level.

    fold_profile() needs a flat channel and A0 is not one: gen holds each
    DAC level for exactly two ADC samples, so the folded profile is the
    staircase and a one-sample event does not stand out from it - a
    40-code spike scores 1.4 on `spike_z`, which is why A0 could not be
    the control for the jumper test.

    The hold is itself the measurement. Two samples of one DAC level
    should read the same, and a one-sample artifact lands on exactly one
    of them, so differencing within the pair cancels the waveform by
    construction and leaves the event at full height. It is what made
    the track/settling sweep runnable with A1 grounded.

    `hold_ok` is false when the pairing does not hold - the two samples
    of a level are only a level while the DAC and ADC rates are locked,
    and at some rates they are not. A large median absolute difference
    says the differencing is measuring the staircase rather than
    cancelling it, and the result should not be read.
    """
    import statistics as _st
    if len(vals) < 4 * period:
        return dict(fold_profile([], period=max(1, period // 2)),
                    hold_ok=False, pair_spread=0.0)
    # Both parities, and keep the one that actually pairs. The caller
    # hands us a slice trimmed at a settle time, which lands on either
    # side of a level boundary depending on the rate and the trim - and
    # the wrong parity differences two samples from *different* DAC
    # levels, so every difference is a DAC step instead of noise. It
    # showed up as hold_ok refusing the sine arms of the layout sweep,
    # which was the guard working rather than the measurement failing,
    # but the measurement is available for one more subtraction.
    best_d, best_spread = None, None
    for off in (0, 1):
        d = [vals[i] - vals[i + 1] for i in range(off, len(vals) - 1, 2)]
        spread = _st.median([abs(x) for x in d])
        if best_spread is None or spread < best_spread:
            best_d, best_spread = d, spread
    d = best_d
    out = fold_profile(d, period=period // 2)
    # Within a held level the difference is noise; across a broken
    # pairing it is a DAC step, which is tens of codes.
    out["pair_spread"] = best_spread
    out["hold_ok"] = best_spread <= 4.0
    return out


def flat_census(vals, threshold=FLAT_DEV_CODES):
    """Count the samples a flat line cannot account for.

    The companion to level_census(), and needed because that one cannot
    see this. level_census() judges the steps of a DAC staircase against
    STEP_SPLICE_CODES = 45; on macOS the issue #5 displacement is 26-32
    codes, which forms its own level and lands *under* that threshold.
    Ten runs of tools/splices.py reported 0 splices on A0 across a
    period when six runs in ten were displacing samples on A1 - so the
    instrument said "does not reproduce on macOS" about a board that was
    reproducing it. Do not census a flat channel with a staircase tool.

    A flat channel is also where the defect is unmistakable rather than
    merely detectable: preset `M` drives DAC1 with DC 2048, so anything
    that moves A1 was made by the board and no waveform can be blamed
    for it.

    Returns `count` (samples further than `threshold` from the median),
    `max_dev`, `sd`, `median`, `samples`, the void around the threshold
    as `gap`, and `period`/`periodic` on the same terms level_census()
    uses - a metronome at GEN_TABLE_LEN is the issue #5 signature and is
    what tells it from a real discontinuity.
    """
    n = len(vals)
    if n < 2:
        return {"count": 0, "max_dev": 0.0, "sd": 0.0, "median": 0.0,
                "samples": n, "gap": (0, 0), "threshold": threshold,
                "period": 0, "periodic": False}
    med = statistics.median(vals)
    devs = [abs(v - med) for v in vals]
    # sd over a bounded prefix, not the whole run: this is reported for
    # eyeballing, and it separates the populations on its own (0.87
    # clean against 1.66 dirty) without needing to be exact.
    sd = statistics.pstdev(vals[:20000])

    occupied = {int(d) for d in devs}
    lo = hi = int(threshold)
    while lo - 1 >= 0 and (lo - 1) not in occupied:
        lo -= 1
    while (hi + 1) not in occupied and hi < int(max(devs)) + 1:
        hi += 1

    at = [i for i, d in enumerate(devs) if d > threshold]
    # One event can put two adjacent samples over, so neighbours a
    # couple of samples apart are one occurrence - the same merge
    # level_census() does, for the same reason.
    occurrences = [w for k, w in enumerate(at) if k == 0 or w - at[k - 1] > 4]
    period, periodic = 0, False
    if len(occurrences) >= 10:
        gaps = [b - a for a, b in zip(occurrences, occurrences[1:])]
        period = max(set(gaps), key=gaps.count)
        periodic = gaps.count(period) >= 0.9 * len(gaps)
    return {
        "count": len(occurrences),
        "max_dev": max(devs),
        "sd": sd,
        "median": med,
        "samples": n,
        "gap": (lo, hi),
        "threshold": threshold,
        "period": period,
        "periodic": periodic,
    }


# ---------------------------------------------------------------------
# Frame parsing
# ---------------------------------------------------------------------

# Samples are (tag << 12) | code, little endian, so the high byte holds
# the tag in its top nibble and the code's top nibble below it. Both
# fall out of a bytes.translate(), which keeps the whole parse at C
# speed - a per-sample Python loop over a 1.8 MB/s stream once stopped
# the port being drained and looked exactly like a firmware framing bug.
_TAG_TBL  = bytes(b >> 4 for b in range(256))
_LOW4_TBL = bytes(b & 0x0F for b in range(256))


@dataclass
class ChannelStats:
    tag: int
    n: int
    lo: int
    hi: int
    mean: float

    @property
    def label(self):
        return label_for(self.tag)


@dataclass
class ParsedStream:
    """Everything derivable from a captured byte stream, and nothing
    that depends on how it was captured."""
    raw_bytes: int = 0
    frames: int = 0
    payload_bytes: int = 0
    first_seq: int = 0
    last_seq: int = 0
    seq_gaps: int = 0
    dropped_frames: int = 0
    crc_bad: int = 0
    overrun_frames: int = 0
    first_overrun: int = None
    last_overrun: int = None
    max_overrun: int = 0
    declared_rate_hz: int = 0
    channel_mask: int = 0
    n_channels: int = 0
    version: int = 0
    inconsistent: int = 0
    ts_first: int = None
    ts_last: int = None
    # One PlayStat per frame, so loop mode can close the same rate loop
    # play-only closes on the bulk-IN records. The frame header already
    # carries the device clock in timestamp_us, so play_consumed
    # completes the pair and playstat_rate reads it unchanged.
    play_stats: list = field(default_factory=list)
    per_channel: dict = field(default_factory=dict)
    series: dict = field(default_factory=dict)   # tag -> array('H') codes
    marks: dict = field(default_factory=dict)    # tag -> [(index, ts_us)]
    settled: dict = field(default_factory=dict)  # tag -> list[int]

    @property
    def dev_span_s(self):
        if self.ts_first is None or self.ts_last is None:
            return 0.0
        return ((self.ts_last - self.ts_first) & 0xFFFFFFFF) / 1e6

    @property
    def total_samples(self):
        return sum(st.n for st in self.per_channel.values())

    def measured_rate_hz(self):
        """Per-channel conversion rate from device timestamps.

        The last frame's samples arrived after its own timestamp, so
        they are excluded. The declared channel count is used rather
        than the observed one: a single corrupt sample would otherwise
        invent a channel and skew the rate.
        """
        if self.frames < 2 or self.ts_first is None:
            return None
        span_us = (self.ts_last - self.ts_first) & 0xFFFFFFFF
        if not span_us:
            return None
        total = self.total_samples
        nch = max(1, self.n_channels)
        return (total - total / self.frames) * 1e6 / span_us / nch

    def _index_at(self, tag, from_us):
        """First sample index at or after `from_us` of device time."""
        if not from_us or self.ts_first is None:
            return 0
        want = (self.ts_first + from_us) & 0xFFFFFFFF
        idx = 0
        for i, ts in self.marks.get(tag, ()):
            if ts >= want:
                return idx
            idx = i
        return idx

    def window_amplitudes(self, tag, tone_hz, size=8192, stride=None,
                          from_us=0):
        """Tone amplitude per window against device time.

        Judged per window, never over the whole run: at 453,488 sps a
        whole-run Goertzel reads 232 codes against a theoretical 1370.5
        while nearly every window reads above 1360, because a single
        phase discontinuity cancels the average. A per-run number is the
        wrong instrument and reports collapses that are not happening.
        """
        vals = self.series.get(tag)
        if not vals or self.declared_rate_hz <= 0:
            return []
        stride = size if stride is None else stride
        marks = self.marks.get(tag) or [(0, self.ts_first or 0)]
        out = []
        mi = 0
        start = self._index_at(tag, from_us)
        for s in range(start, len(vals) - size, stride):
            while mi + 1 < len(marks) and marks[mi + 1][0] <= s:
                mi += 1
            t = ((marks[mi][1] - self.ts_first) & 0xFFFFFFFF) / 1e6
            out.append((t, goertzel(vals[s:s + size], self.declared_rate_hz,
                                    tone_hz)))
        return out

    def max_slew(self, tag, from_us=0):
        """Largest absolute step between consecutive samples of one
        channel.

        `from_us` skips the head of the run. Playback starts from a ring
        primed with mid-scale silence and the host's waveform joins it
        mid-cycle, so the first transition is a genuine discontinuity
        and an expected one - it is the start, not a splice.
        """
        vals = self.series.get(tag)
        if not vals or len(vals) < 2:
            return 0
        start = self._index_at(tag, from_us)
        sl = vals[start:]
        if len(sl) < 2:
            return 0
        return max(abs(b - a) for a, b in zip(sl, sl[1:]))


def parse_frames(buf, settle_us=0, settle_cap=8192, keep_series=True):
    """Walk the byte stream frame by frame, resynchronising on MAGIC.

    Frames whose header CRC fails are counted and skipped by four bytes
    so a corrupt header cannot swallow the frames behind it.
    """
    ps = ParsedStream(raw_bytes=len(buf))
    seq_prev = None
    keep_from = None
    first_shape = None
    pos = 0
    blen = len(buf)

    while True:
        i = buf.find(MAGIC, pos)
        if i < 0 or blen - i < HDR_LEN:
            break
        hdr = bytes(buf[i:i + HDR_LEN])
        (_m, ver, flags, chmask, seq, rate,
         ts, overruns, consumed, crc) = struct.unpack(HDR_FMT, hdr)
        if zlib.crc32(hdr[:HDR_LEN - 4]) & 0xFFFFFFFF != crc:
            ps.crc_bad += 1
            pos = i + 4
            continue
        need = HDR_LEN + FRAME_SAMPLES * 2
        if blen - i < need:
            break
        body = bytes(buf[i + HDR_LEN:i + need])
        pos = i + need

        shape = (ver, rate, chmask)
        if ps.frames == 0:
            ps.first_seq = seq
            ps.ts_first = ts
            keep_from = (ts + settle_us) & 0xFFFFFFFF if settle_us else None
            ps.version = ver
            first_shape = shape
        elif shape != first_shape:
            # The stream's shape must not change mid-run: a rate or mask
            # that moves under the host is a frame described by a header
            # that no longer applies to it.
            ps.inconsistent += 1
        ps.frames += 1
        ps.payload_bytes += len(body)
        ps.last_seq = seq
        ps.declared_rate_hz = rate
        ps.channel_mask = chmask
        ps.n_channels = max(1, bin(chmask).count("1"))
        ps.ts_last = ts
        ps.play_stats.append(PlayStat(consumed, 0, 0, ts))
        if flags & FLAG_OVERRUN:
            ps.overrun_frames += 1
        if ps.first_overrun is None:
            ps.first_overrun = overruns
        ps.last_overrun = overruns
        ps.max_overrun = max(ps.max_overrun, overruns)
        if seq_prev is not None and seq != seq_prev + 1:
            ps.seq_gaps += 1
            ps.dropped_frames += (seq - seq_prev - 1) & 0xFFFFFFFF
        seq_prev = seq

        settled = keep_from is None or ts >= keep_from
        _accumulate(ps, body, ts, settled, settle_cap, keep_series)

    return ps


def _accumulate(ps, body, ts, settled, settle_cap, keep_series):
    n = len(body) // 2
    if n == 0:
        return
    hi = body[1::2]
    tags = hi.translate(_TAG_TBL)
    codes = bytearray(len(body))
    codes[0::2] = body[0::2]
    codes[1::2] = hi.translate(_LOW4_TBL)
    vals = array("H")
    vals.frombytes(bytes(codes))

    # Conversions are strictly round robin, so the tag pattern repeats
    # with the channel count and each channel is a stride slice. Verify
    # it rather than assume it: a resync mid-frame breaks the pattern,
    # and silently mis-attributing samples is worse than being slow.
    nch = ps.n_channels
    fast = (nch and n % nch == 0 and tags == tags[:nch] * (n // nch)
            and len(set(tags[:nch])) == nch)

    if fast:
        for i in range(nch):
            tag = tags[i]
            sl = vals[i::nch]
            _merge(ps, tag, sl, ts, settled, settle_cap, keep_series)
        return

    # Fallback: whatever order the samples actually arrived in.
    buckets = {}
    for v16, tag in zip(vals, tags):
        buckets.setdefault(tag, array("H")).append(v16)
    for tag, sl in buckets.items():
        _merge(ps, tag, sl, ts, settled, settle_cap, keep_series)


def _merge(ps, tag, sl, ts, settled, settle_cap, keep_series):
    st = ps.per_channel.get(tag)
    lo, hi_, tot, cnt = min(sl), max(sl), sum(sl), len(sl)
    if st is None:
        ps.per_channel[tag] = ChannelStats(tag, cnt, lo, hi_, float(tot))
    else:
        st.n += cnt
        st.lo = min(st.lo, lo)
        st.hi = max(st.hi, hi_)
        st.mean += tot            # running total; divided out below
    if keep_series:
        ser = ps.series.get(tag)
        if ser is None:
            ser = ps.series[tag] = array("H")
            ps.marks[tag] = []
        ps.marks[tag].append((len(ser), ts))
        ser.extend(sl)
    if settled:
        k = ps.settled.setdefault(tag, [])
        room = settle_cap - len(k)
        if room > 0:
            k.extend(sl[:room])


def _finish(ps):
    for st in ps.per_channel.values():
        st.mean = st.mean / st.n if st.n else 0.0
    return ps


# ---------------------------------------------------------------------
# Device counters
# ---------------------------------------------------------------------

_KV = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*)=(-?\d+)")


def _counters(text, marker):
    """Last `key=value` set on the most recent line carrying `marker`.

    Both tracks print their counters as key=value pairs but not the same
    set of them - Track A adds svc, rebuilds and the activity counters -
    so the parse is by key, never by position.
    """
    got = {}
    for line in text.splitlines():
        if marker in line:
            got = {k: int(v) for k, v in _KV.findall(line)}
    return got


@dataclass
class PlayCounters:
    raw: dict = field(default_factory=dict)

    def _g(self, key):
        return self.raw.get(key)

    bytes_in   = property(lambda s: s._g("in"))
    produced   = property(lambda s: s._g("produced"))
    consumed   = property(lambda s: s._g("consumed"))
    underruns  = property(lambda s: s._g("under"))
    isr        = property(lambda s: s._g("isr"))
    endtx      = property(lambda s: s._g("endtx"))
    svc        = property(lambda s: s._g("svc"))
    spans      = property(lambda s: s._g("spans"))
    partial    = property(lambda s: s._g("partial"))
    rebuilds   = property(lambda s: s._g("rebuilds"))
    act_in     = property(lambda s: s._g("act-in"))
    act_out    = property(lambda s: s._g("act-out"))
    occ_min    = property(lambda s: s._g("occmin"))


@dataclass
class BenchCounters:
    raw: dict = field(default_factory=dict)
    mode: str = "off"
    in_bytes: int = 0
    out_bytes: int = 0

    passes   = property(lambda s: s.raw.get("passes"))
    arms_in  = property(lambda s: s.raw.get("arms-in"))
    arms_out = property(lambda s: s.raw.get("arms-out"))
    rebuilds = property(lambda s: s.raw.get("rebuilds"))


_BENCH = re.compile(r"bench=(\S+)\s+IN\s+(\d+)\s+B\s+OUT\s+(\d+)\s+B")


@dataclass
class OccHist:
    """Playback ring occupancy sampled by the device at every ENDTX.

    The host cannot sample this itself. produced - consumed read after a
    run is a frozen snapshot of the shutdown, and reading it during one
    means asking over the console, which at the rates where the ring is
    short costs more underruns than it measures. The device keeps the
    distribution instead; this is the readout of `O`.
    """
    buckets: list = field(default_factory=list)
    min: int = None
    endtx: int = None
    trace: list = field(default_factory=list)
    decim: int = 0
    run_us: int = 0
    consumed: int = 0
    rate_us: list = field(default_factory=list)
    rate_decim: int = 0

    def device_byte_rate(self):
        """Bytes per second the converter actually consumed, timed by
        the device's own clock. Repeated buffers are excluded, because
        an underrun consumes time and not data."""
        if not self.run_us or not self.consumed:
            return None
        return self.consumed * 1024 / (self.run_us / 1e6)

    def window_rates(self):
        """Bytes per second the converter consumed over each traced
        window, from the device's own clock.

        The trace is keyed on *consumed*, so every window is exactly
        `rate_decim` buffers of data and an underrun falling inside one
        does not bias it. This is what distinguishes a converter that
        held one rate all run from one that changed state part-way -
        `device_byte_rate()` averages the two together and reports a
        number that was never the rate at any instant.
        """
        out = []
        for a, b in zip(self.rate_us, self.rate_us[1:]):
            dt = (b - a) & 0xFFFFFFFF
            if dt:
                out.append(self.rate_decim * 1024 * 1e6 / dt)
        return out

    def traced_byte_rate(self):
        """Converter rate across the whole trace, first sample to last.

        Independent of `device_byte_rate()`: that one divides a counter
        by a run timer read after the stop, this one spans two samples
        taken during the run. They should agree, and disagreeing is
        itself worth knowing.
        """
        if len(self.rate_us) < 2:
            return None
        dt = (self.rate_us[-1] - self.rate_us[0]) & 0xFFFFFFFF
        if not dt:
            return None
        buffers = (len(self.rate_us) - 1) * self.rate_decim
        return buffers * 1024 * 1e6 / dt

    @property
    def total(self):
        return sum(self.buckets)

    def quantile(self, q):
        """Occupancy at quantile q, in slots. q=0.5 is the median slot
        depth the converter actually found waiting for it."""
        n = self.total
        if not n:
            return None
        want = q * n
        run = 0
        for i, c in enumerate(self.buckets):
            run += c
            if run >= want:
                return i
        return len(self.buckets) - 1

    def below(self, slots):
        """Fraction of ENDTX events that found fewer than `slots`."""
        n = self.total
        return sum(self.buckets[:slots]) / n if n else None


# Playback status on bulk IN, mirrored from lib/due_shared/src/playstat.h. In
# play-only the IN endpoint carries nothing else, so these are the whole
# stream; the host differences consecutive records to get the rate the
# converter is actually holding, without a console round trip.
PLAYSTAT_FMT = "<4sB3sIIIII"
PLAYSTAT_LEN = struct.calcsize(PLAYSTAT_FMT)
PLAYSTAT_MAGIC = b"DUEP"


@dataclass
class PlayStat:
    consumed: int
    underruns: int
    bytes_in: int
    dev_us: int


def parse_playstats(buf):
    """Status records out of a play-only IN stream.

    Scans for the magic and checks the CRC rather than assuming
    alignment: a read can start mid-record, and a record that fails its
    CRC is skipped by one byte rather than trusted, so a false magic
    inside other data cannot be half-read as a real one.
    """
    out = []
    i = 0
    while True:
        i = buf.find(PLAYSTAT_MAGIC, i)
        if i < 0 or i + PLAYSTAT_LEN > len(buf):
            return out
        rec = bytes(buf[i:i + PLAYSTAT_LEN])
        (_, ver, _pad, consumed, under,
         bytes_in, dev_us, crc) = struct.unpack(PLAYSTAT_FMT, rec)
        if ver == 1 and zlib.crc32(rec[:-4]) & 0xFFFFFFFF == crc:
            out.append(PlayStat(consumed, under, bytes_in, dev_us))
            i += PLAYSTAT_LEN
        else:
            i += 1


def scan_play_stats(buf, pos=0):
    """Header-only scan for the rate loop, resumable from `pos`.

    Loop mode carries the loop's signal in the frame header, so the host
    has to read it while the stream is still running. Re-parsing the
    payload every trim would mean several megabytes per correction on
    the same thread that services the port; this reads the 36-byte
    headers, skips each payload by its declared length, and returns
    where it stopped so the next call resumes there.

    Returns (stats, next_pos). A trailing partial frame is left for the
    next call rather than half-read.
    """
    out = []
    n = len(buf)
    while pos + HDR_LEN <= n:
        if bytes(buf[pos:pos + 4]) != MAGIC:
            i = buf.find(MAGIC, pos)
            if i < 0:
                # Keep only what could still be the start of a magic.
                return out, max(pos, n - 3)
            pos = i
            continue
        hdr = bytes(buf[pos:pos + HDR_LEN])
        vals = struct.unpack(HDR_FMT, hdr)
        # Field positions in HDR_FMT: 0 magic, 1 version, 2 flags,
        # 3 channel_mask, 4 seq, 5 sample_rate_hz, 6 timestamp_us,
        # 7 overrun_count, 8 play_consumed, 9 header_crc32. Named here
        # because v3 dropped three fields and the old numeric indices
        # kept parsing without complaint until they ran off the end.
        if zlib.crc32(hdr[:HDR_LEN - 4]) & 0xFFFFFFFF != vals[9]:
            pos += 4
            continue
        need = HDR_LEN + FRAME_SAMPLES * 2
        if pos + need > n:
            break                       # payload not all here yet
        out.append(PlayStat(vals[8], 0, 0, vals[6]))
        pos += need
    return out, pos


def playstat_rate(stats):
    """Bytes per second the converter consumed, from the records alone.

    Spans the widest interval over which `consumed` was actually moving,
    on the device's own clock. That span is far longer than the pipeline
    delay, which is what makes it usable as a rate model: the staleness
    that sank the earlier device-timestamp attempt biases a *position*,
    not a rate measured across a long baseline.

    Both ends have to be trimmed, and the tail is not optional. Once the
    host stops feeding, `consumed` freezes while `dev_us` keeps
    advancing, so a span that runs to the last record reports a
    converter far slower than any it ever ran at - measured, 55% slow
    against a true 1.6%, because a drained run collects several seconds
    of starvation after three of playback. The head is trimmed for the
    same reason at the other end, before priming has handed over a
    buffer.

    A live rate loop never sees either, since it reads while feeding.
    This is for reading a finished run back.
    """
    if len(stats) < 2:
        return None

    # Span the interval over which `consumed` was actually moving.
    #
    # Selecting on `underruns` instead does not work, though it looks
    # more principled: before the ring primes, the DACC trigger has not
    # started, so no ENDTX fires and underruns is frozen at 0 right
    # alongside consumed. The whole dead head then reads as one
    # un-starved span.
    #
    # That head is real and long. run_play issues P and then spends
    # about half a second on console reads before the feeder starts, so
    # the device sits play-active with nothing to play and emits ~30
    # records with consumed at 0.
    hi = len(stats) - 1
    while hi > 0 and stats[hi].consumed == stats[hi - 1].consumed:
        hi -= 1
    lo = 0
    while lo < hi and stats[lo].consumed == stats[lo + 1].consumed:
        lo += 1
    # lo is now the last record before consumption began, so the first
    # interval in the span is the partial one in which playback started.
    # Including it reads as a converter up to 0.6 pp slow - one interval
    # in ~150 - and by how much depends on where in that interval the
    # first buffer landed, which is why the error wandered run to run.
    lo += 1
    if hi - lo < 1:
        return None
    dt = (stats[hi].dev_us - stats[lo].dev_us) & 0xFFFFFFFF
    if not dt:
        return None
    return (stats[hi].consumed - stats[lo].consumed) * 1024 * 1e6 / dt


_OCC = re.compile(r"play_occ min=(\d+) endtx=(\d+) runus=(\d+) consumed=(\d+) hist=([\d,]+)")
_OCC_TRACE = re.compile(r"play_occ_trace decim=(\d+) n=(\d+) v=([\d,]*)")
_RATE = re.compile(r"play_rate decim=(\d+) n=(\d+) us=([\d,]*)")


def parse_occ(text):
    got = OccHist()
    for line in text.splitlines():
        m = _OCC.search(line)
        if m:
            got = OccHist(buckets=[int(v) for v in m.group(5).split(",")],
                          min=int(m.group(1)), endtx=int(m.group(2)),
                          run_us=int(m.group(3)), consumed=int(m.group(4)))
        t = _OCC_TRACE.search(line)
        if t and t.group(3):
            got.decim = int(t.group(1))
            got.trace = [int(v) for v in t.group(3).split(",")]
        rt = _RATE.search(line)
        if rt and rt.group(3):
            got.rate_decim = int(rt.group(1))
            got.rate_us = [int(v) for v in rt.group(3).split(",")]
    return got


def parse_play(text):
    """Track A's path, and Track B's fallback. Prefer play_counters().

    Reading counters by printing them costs 13.14 ms of blocked main
    loop for `B` and 15.40 ms for `O` - invariant 8 - and run_loop used
    to spend two of those *inside* the run it was measuring. It stays
    because Track A has no control channel (objective 1c) and this is
    the only thing that works there.
    """
    return PlayCounters(_counters(text, "play:"))


# What counts as "the link is gone" and may fall back to the console.
# Deliberately not Exception: a KeyError or TypeError from the control
# path is a bug in this file, and falling back on it would hide the bug
# behind a working-looking measurement taken the slow way.
_LINK_GONE = (OSError, ValueError)

# Console key names, so the control channel produces a PlayCounters
# indistinguishable from the console's and no caller has to know which
# path it came from.
_CTL_TO_CONSOLE = {
    "bytes_in": "in", "produced": "produced", "consumed": "consumed",
    "underruns": "under", "isr_calls": "isr", "endtx": "endtx",
    "svc_calls": "svc", "spans": "spans", "partial": "partial",
    "occ_min": "occmin", "run_us": "runus", "abandoned": "abandoned",
    "drain_polls": "drainpolls",
}


def play_counters(board, secs=1.2):
    """The playback counters, over the control channel where there is one.

    Falls back to `B` and the console scraper, and says which it used via
    `.via`. The fallback is not a preference - it is what Track A still
    has, and the day Track A grows a control channel this function stops
    having two halves.
    """
    link = board.ctl()
    if link is not None:
        try:
            ct = link.counters()
            got = PlayCounters({v: ct[k] for k, v in _CTL_TO_CONSOLE.items()
                                if k in ct})
            got.via = "control"
            return got
        except _LINK_GONE:
            # Only a transport failure falls back. A KeyError here is a
            # mapping bug, and swallowing it would degrade silently to
            # printf and report the wrong instrument as working - which
            # is what this whole migration exists to stop. It escapes.
            board.drop_ctl()
    board.cmd("B")
    time.sleep(0.5)
    got = parse_play(board.drain_console(secs))
    got.via = "console"
    return got


def occupancy(board, secs=1.2):
    """The occupancy histogram and traces, control channel first.

    Same split and the same reason as play_counters().
    """
    link = board.ctl()
    if link is not None:
        try:
            o = link.occupancy()
            got = OccHist(buckets=list(o["hist"]), min=o["occ_min"],
                          endtx=o["endtx"], run_us=o["run_us"],
                          consumed=o["consumed"])
            got.decim = o.get("decim", 0)
            got.trace = list(o.get("trace", []))
            got.via = "control"
            return got
        except _LINK_GONE:
            board.drop_ctl()
    board.cmd("O")
    time.sleep(0.3)
    got = parse_occ(board.drain_console(secs))
    got.via = "console"
    return got


def parse_bench(text):
    bc = BenchCounters(_counters(text, "bench="))
    m = None
    for line in text.splitlines():
        mm = _BENCH.search(line)
        if mm:
            m = mm
    if m:
        bc.mode = m.group(1)
        bc.in_bytes = int(m.group(2))
        bc.out_bytes = int(m.group(3))
    return bc


# ---------------------------------------------------------------------
# The board
# ---------------------------------------------------------------------

# How long close() on the native port may take before it is treated as
# objective 0c. Healthy closes measure 0.00 s across several hundred
# samples, so this is three orders of magnitude of headroom.
CLOSE_WEDGE_S = 3.0

# Where a wedge diagnosis goes. A file, because the failure being
# diagnosed is a hang, and anything buffered by a test runner is lost
# when the session never finishes.
WEDGE_LOG = os.environ.get("DUE_WEDGE_LOG", "/tmp/due-0c.log")


def _wedge_note(text):
    line = f"[0c] {text}"
    print(line, file=sys.stderr, flush=True)
    try:
        with open(WEDGE_LOG, "a") as fh:
            fh.write(f"{time.strftime('%F %T')} {line}\n")
    except OSError:
        pass


class BoardError(RuntimeError):
    pass


class Board:
    """The control port, held open.

    Opening it asserts NRSTB and resets the board, which also
    re-enumerates the native port under a possibly new name. Every
    measurement used to pay that: a reset, a 3 s settle and a re-glob,
    about 15 s of fixed cost. Holding one open port for a whole session
    turns that into roughly half a second per measurement, which is the
    difference between a suite that runs in minutes and one that runs in
    half an hour.
    """

    def __init__(self, control=None, native=None, settle=0.0, wait=8.0):
        if control is None:
            control, found_native = find_ports(wait=wait)
            if native is None:
                native = found_native
        if control is None:
            raise BoardError("no control port found")
        self.control = control
        self.native = native
        # Set when close() on the native port wedged: the fd is leaked
        # and a thread is stuck on it, so nothing in this process can
        # open it again.
        self.wedged = False
        # Opened lazily and only once. Track A has no control channel, so
        # None is an ordinary answer here and every caller falls back to
        # the console rather than failing.
        self._ctl = None
        self._ctl_tried = False
        self.cfd = open_raw(control, 115200)
        self._console = b""
        if settle:
            time.sleep(settle)

    # -- command channel ----------------------------------------------
    def ctl(self):
        """The native port's control channel, or None where there is none.

        None means Track A, or a board whose native port has not
        enumerated - both of which are states the suite has to keep
        working in, so this never raises. `self.control` is the
        *programming* port and is a different thing entirely.
        """
        if self._ctl_tried:
            return self._ctl
        self._ctl_tried = True
        try:
            import control as _control
            nodes = ports.native_nodes(exclude=self.control)
            if len(nodes) >= 2:
                link = _control.Control(nodes[-1], timeout=3.0)
                link.ping()
                self._ctl = link
        except Exception:                                    # noqa: BLE001
            self._ctl = None
        return self._ctl

    def drop_ctl(self):
        if self._ctl is not None:
            try:
                self._ctl.close()
            except Exception:                                # noqa: BLE001
                pass
        self._ctl = None

    # -- control port ------------------------------------------------
    def cmd(self, text):
        self.cfd.write(text.encode() if isinstance(text, str) else text)

    def poll_console(self):
        """Non-blocking drain; returns whatever was waiting."""
        got = b""
        while True:
            r = transport.wait_any([self.cfd], 0)
            if not r:
                break
            try:
                d = self.cfd.read(65536)
            except OSError:
                break
            if not d:
                break
            got += d
        self._console += got
        return got

    def drain_console(self, secs, quiet=None, cap=30.0, until=None):
        """Read the console until it is done talking.

        Whichever of these is given decides when that is: a fixed
        `secs`, a closing marker in `until` (a string or several), or
        `quiet` seconds with nothing arriving. Markers and quiet can be
        combined - the marker ends it promptly on the track that prints
        one, and quiet is the backstop for the track that does not.
        Guessing at a silence long enough to mean "finished" is how one
        command's tail ends up parsed as the next one's output.
        """
        marks = ()
        if until is not None:
            marks = ((until,) if isinstance(until, str) else tuple(until))
            marks = tuple(m.encode() for m in marks)
        out = b""
        last = time.time()
        end = time.time() + (secs if quiet is None and not marks else cap)
        while time.time() < end:
            r = transport.wait_any([self.cfd], 0.05)
            if r:
                try:
                    d = self.cfd.read(65536)
                except OSError:
                    break
                if d:
                    out += d
                    last = time.time()
                    if marks and any(m in out for m in marks):
                        break
                    continue
            if quiet is not None and time.time() - last >= quiet:
                break
        self._console += out
        return out.decode("utf-8", "replace")

    def ask(self, text, secs=1.0, quiet=None):
        """Send a command and return what the console said back."""
        self.poll_console()
        self.cmd(text)
        return self.drain_console(secs, quiet=quiet)

    def banner(self):
        return self.ask("h", secs=1.0)

    def stop(self):
        self.cmd("0")

    def reset(self, wait=10.0):
        """Software reset over the console.

        Does not reopen the control port, so the held fd survives -
        which is the whole point. Waits for the banner rather than a
        fixed delay, because the native port re-enumerates behind it and
        anything opened before the banner is aimed at a dead node.
        """
        self.poll_console()
        self.cmd("z")
        return self.drain_console(0, quiet=1.0, cap=wait)

    # -- native port -------------------------------------------------
    def open_native(self, wait=45.0, dtr=True, blocking_writes=False,
                    notify=None, attempt_timeout=6.0):
        """Re-glob and open the native node, and keep trying.

        Its name changes whenever the board resets, so it is discovered
        every time rather than remembered.

        **The open itself can block for ever**, which is why this is
        more than a retry loop. A COM node whose device has not finished
        coming back after a reset accepts the `CreateFile` and never
        returns from it, so a caller with a generous timeout still hangs:
        the deadline never gets tested because control never comes back.
        Measured on Windows after a NRSTB reset, and it is the whole
        reason a capture would fail with "native port did not enumerate"
        while `ports.native_nodes()` listed the node and Device Manager
        showed it healthy.

        So each attempt runs in a daemon thread and is abandoned if it
        does not return within `attempt_timeout`. An abandoned thread
        costs a leaked handle in a test process that is about to exit,
        which is a straight trade against hanging the run. The loop
        re-globs every pass, because the node can also come back under a
        different name.

        Generous by design: the board is re-enumerating and there is
        nothing to be gained by being brisk about it.
        """
        if self.wedged:
            raise BoardError(
                "the native port is held by a thread stuck in a close() "
                "that never returned (objective 0c); this process cannot "
                f"reopen it. See {WEDGE_LOG}.")

        def _try(node, out):
            try:
                out.append(open_raw(node, 115200, dtr=dtr))
            except Exception as exc:                 # noqa: BLE001
                out.append(exc)

        fd = None
        seen = []
        give_up = time.time() + wait
        while fd is None:
            # The board offers two native nodes now, samples and
            # commands. Ordering them by USB interface rather than by
            # name is what keeps this pointed at the sample one: the
            # names happen to sort the same way today, and that is a
            # property of macOS's naming rather than of the device.
            cands = ports.native_nodes(exclude=self.control)
            seen = cands or seen
            if cands:
                out = []
                th = threading.Thread(target=_try, args=(cands[0], out),
                                      daemon=True)
                th.start()
                th.join(attempt_timeout)
                if out and not isinstance(out[0], Exception):
                    fd = out[0]
                    if notify:
                        notify("native", path=cands[0],
                               changed=cands[0] != self.native)
                    self.native = cands[0]
            if fd is None:
                if time.time() >= give_up:
                    raise BoardError(
                        "native port did not open after "
                        f"{wait:.0f}s; nodes seen: {seen or 'none'}. "
                        "A listed node that will not open is the device "
                        "still coming back from a reset - see "
                        "Board.open_native().")
                time.sleep(1.0)
        if blocking_writes:
            # Without this a full queue raises EAGAIN and a naive writer
            # dies silently. VMIN=0 keeps reads non-blocking, so this
            # affects only the write side.
            fd.set_blocking(True)
        return fd

    def command_node(self):
        """Path of the native port's *command* node, or None.

        Derived from the same glob and the same ordering as
        open_native, and deliberately not from ports.find_all_ports():
        that probes the programming port to find the one that answers,
        and probing it asserts NRSTB and resets the board. Discovery
        that costs a reset is not discovery a running daemon can do.

        None on firmware with one CDC function - Track A today - and
        every caller must cope, because the fallback is the console and
        the console still works.
        """
        cands = ports.native_nodes(exclude=self.control)
        return cands[1] if len(cands) > 1 else None

    def close_native(self, fd):
        # Objective 0c: close() hangs here, and when it does the process
        # holds both ports so nothing outside can ask the board what
        # happened. The board itself stays healthy, so the state that
        # would explain it is readable right up to the moment of the
        # call - but only from in here.
        #
        # Off unless DUE_EP_DUMP_ON_CLOSE is set, because it costs a
        # console round trip on every close.
        if os.environ.get("DUE_EP_DUMP_ON_CLOSE"):
            try:
                # 'B' first: it names the mode. The main loop only drains
                # bulk OUT when nothing owns it -
                #   if (!play_active() && !stream_out_in_use())
                # - so a device still marked as running a bench or a
                # playback, with nothing actually consuming, is the one
                # state that produces a NAKing pipe with a healthy
                # endpoint. That is what the first captured wedge looked
                # like: ep2(OUT) ISR bit-identical to a healthy close,
                # but the OUT DMA holding 16896 bytes outstanding.
                txt = self.ask("B", secs=0.8) + self.ask("u", secs=0.8)
                for line in txt.splitlines():
                    if ("ep2(OUT)" in line or "dma ch1(OUT)" in line
                            or "bench=" in line or "play:" in line):
                        print(f"[0c] before close: {line.strip()}",
                              file=sys.stderr, flush=True)
            except Exception as e:                    # noqa: BLE001
                print(f"[0c] dump failed: {e!r}", file=sys.stderr, flush=True)

        # '0' stops the device draining bulk OUT, so bytes still in the
        # kernel's output queue can never leave - and close() on a tty
        # drains that queue first. Without the flush the process hangs
        # in close() forever, holding the port and leaving the board
        # streaming into the void for the next run to trip over.
        # flush_both() swallows the platform's own flush error itself:
        # termios.error is not an OSError - it derives straight from
        # Exception - so `except OSError` never caught it, and a port
        # that had gone away (ENXIO) aborted the whole measurement from
        # inside the cleanup. That guard now lives in transport.py.
        fd.flush_both()

        # Closing this port is the hang in objective 0c: macOS
        # waits for in-flight write URBs and a device that has stopped
        # draining bulk OUT never completes them. Four occurrences are
        # on record and none has ever been reproduced on demand, so the
        # trap has to be armed all the time rather than during a hunt.
        #
        # It costs nothing on a healthy close - the wait returns
        # immediately - and on a wedge it does the two things that were
        # impossible before. It reads the device's state, which works
        # because the *control* port is a different fd and the board
        # stays healthy throughout; every diagnosis so far had to guess
        # at this. And it re-sends the stop, because the leading theory
        # is that the device still believes something owns bulk OUT, so
        # the main loop is not running its fallback drain. If that is
        # right the close completes and the run continues.
        done = threading.Event()

        def _close():
            try:
                fd.close()
            finally:
                done.set()

        threading.Thread(target=_close, daemon=True,
                         name="close-native").start()
        if done.wait(CLOSE_WEDGE_S):
            return

        # To a file, not just stderr. The first wedge caught with this
        # armed produced nothing readable: pytest captures stderr per
        # test and only prints it in the failure report, and the report
        # never came because the session hung afterwards. A diagnosis
        # that only survives a clean exit is no use for a defect whose
        # whole signature is not exiting.
        _wedge_note(f"close() has not returned in {CLOSE_WEDGE_S}s")
        try:
            txt = self.ask("B", secs=0.8) + self.ask("u", secs=0.8)
            for line in txt.splitlines():
                if ("ep2(OUT)" in line or "dma ch1(OUT)" in line
                        or "bench=" in line or "play:" in line):
                    _wedge_note("  " + line.strip())
        except Exception as e:                       # noqa: BLE001
            _wedge_note(f"  dump failed: {e!r}")

        for attempt in range(3):
            try:
                self.cmd("0")
            except Exception:                        # noqa: BLE001
                pass
            if done.wait(2.0):
                _wedge_note(f"close() completed after re-issuing 0 "
                            f"({attempt + 1} time(s)) - the device had "
                            f"not stopped")
                return

        # A software unplug, which is the thing that actually works.
        #
        # The host is not waiting for the device to accept data: read
        # over the control channel during a wedge it is running 145 k
        # main-loop passes a second and draining bulk OUT on every one
        # of them. It is waiting on the USB pipe, and only a disconnect
        # aborts that. The recorded recovery was physical - unplug and
        # replug - and `Z` is that in software, commanded over the
        # programming port because detaching takes the control channel
        # down with it.
        #
        # Measured: 9 wedges out of 30 open/close cycles, 9 released,
        # 0.01 to 0.23 s. It costs a re-enumeration, which open_native
        # already re-globs for.
        for attempt in range(2):
            try:
                self.cmd("=400Z")
            except Exception:                        # noqa: BLE001
                pass
            if done.wait(6.0):
                _wedge_note(f"close() released by a software detach "
                            f"({attempt + 1} attempt(s)); the native port "
                            f"is re-enumerating")
                self.native = None
                time.sleep(2.0)
                return

        # The fd is leaked and a thread is stuck on it, so this process
        # can never use the port again. Say so once, here, rather than
        # letting the next open() block forever - which is what happened
        # the first time this fired: the close hang became an open hang
        # and the suite sat for eleven hours instead of twelve minutes.
        self.wedged = True
        _wedge_note("board marked unusable for the rest of this session")
        raise BoardError(
            "close() on the native port wedged and did not recover - "
            "objective 0c. The [0c] lines above are the device's state; "
            "the port is still held by a thread inside this process.")

    def close(self):
        self.drop_ctl()
        if self.cfd is not None:
            self.cfd.close()
            self.cfd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def drain_until_quiet(fd, quiet=1.0, cap=10.0):
    """Discard everything the native port has to say until it has been
    silent for `quiet` seconds.

    A stream from a previous run keeps flowing into the kernel's input
    buffer long after the run ends, and analysing those stale frames is
    exactly how a working loop was once diagnosed as frozen at mid
    scale. One tcflush is not enough; the buffer refills as long as the
    device is still streaming.
    """
    stale = 0
    last = time.time()
    end = time.time() + cap
    while time.time() - last < quiet and time.time() < end:
        r = transport.wait_any([fd], 0.1)
        if r:
            try:
                n = len(fd.read(65536))
            except OSError:
                break
            if n:
                stale += n
                last = time.time()
    return stale


# ---------------------------------------------------------------------
# Waveforms
# ---------------------------------------------------------------------

def build_waveform(tone_hz, dac_total_sps, cycles=20):
    """Whole cycles of a full-scale sine, every sample tagged for DAC0.

    An earlier version interleaved DAC0 with a fixed level on DAC1 to
    get a demultiplexing check for free. The DACC accepted it - TAG,
    MAXS, TRGEN and both channel enables all read back correct, and the
    ring held exactly the alternating tags the host sent - but the
    analog result behaved as though both samples reached channel 0.
    Rather than keep chasing that, drive one channel: it is what an
    arbitrary waveform generator needs, and it doubles DAC0's rate.
    """
    per_cycle = int(round(dac_total_sps / tone_hz))
    out = bytearray()
    for i in range(per_cycle * cycles):
        code = int(round(2047.5 + 2047.0 * math.sin(2.0 * math.pi * i / per_cycle)))
        code = max(0, min(4095, code))
        out += struct.pack("<H", (0 << 12) | (code & 0xFFF))
    return bytes(out), dac_total_sps / per_cycle


def build_square(tone_hz, dac_total_sps, cycles=20):
    """Whole cycles of a full-scale square on DAC0, 50% duty.

    The instrument the sine is not. A sine's slew is bounded by its own
    frequency, so however fast it is played the DAC is never asked for
    a full-scale step and the settling behaviour of the converter never
    appears in the output. A square asks for one twice a cycle, so
    overshoot, ring and settling time are the converter's answer rather
    than a property of the shape - which is what makes it the waveform
    worth watching at the top of the AWG ladder.

    Even samples per cycle, always. An odd count puts one extra sample
    on one half, and a 51% duty cycle authored by the generator is
    indistinguishable on a screen from one caused by the device.
    """
    per_cycle = int(round(dac_total_sps / tone_hz))
    per_cycle = max(2, per_cycle - (per_cycle & 1))
    half = per_cycle // 2
    out = bytearray()
    for i in range(per_cycle * cycles):
        code = 4095 if (i % per_cycle) < half else 0
        out += struct.pack("<H", (0 << 12) | (code & 0xFFF))
    return bytes(out), dac_total_sps / per_cycle


# DAC codes per sample in the ramp instrument.
#
# The DAC's span reaches the ADC at about 0.67 codes per DAC code, and
# the ADC's own noise is a few codes, so a ramp rising one DAC code per
# sample puts a single-sample offset below the noise floor. Eight puts
# it at about 5.4 ADC codes, which is unambiguous.
RAMP_STEP = 8


def build_ramp(step=RAMP_STEP, period=None):
    """A waveform where every sample encodes its own position.

    A sine tells you that the output jumped; a ramp tells you by how
    many samples. Any discontinuity in the captured ramp divides by the
    DAC-code-per-sample step to give the exact number of samples skipped
    or repeated, which is the difference between "the signal is wrong"
    and "313 bytes never arrived".
    """
    period = period or (4096 // step)
    out = bytearray()
    for i in range(period):
        out += struct.pack("<H", (0 << 12) | ((i * step) % 4096))
    return bytes(out), 0.0


def ramp_discontinuities(ps, tag=CH_A0, step=RAMP_STEP, period=None,
                         from_us=SETTLE_US, tolerance=3):
    """Sample offsets where a captured ramp did not advance by one step.

    Returns a list of (index, samples) - positive means the output
    skipped forward, so those samples never reached the DAC; negative
    means it repeated. The ADC's own noise is a few codes, so the
    tolerance is in samples and scaled by the measured slope.
    """
    vals = ps.series.get(tag)
    if not vals:
        return []
    start = ps._index_at(tag, from_us)
    tail = vals[start:]
    if len(tail) < 2:
        return []
    period = period or (4096 // step)
    lo, hi = min(tail), max(tail)
    span = hi - lo
    if span <= 0:
        return []
    # ADC codes per DAC code, measured from the ramp's own extent rather
    # than assumed: the DAC is not rail to rail.
    slope = span / float((period - 1) * step)
    # The sawtooth's own wrap is a full-scale analog step, and the DAC
    # and the ADC's sample-and-hold need a sample or two either side of
    # it to settle. Those samples say nothing about continuity, so the
    # wrap and its neighbours are excluded rather than corrected - an
    # earlier version corrected them and manufactured a matched pair of
    # +152/-152 sample "discontinuities" at every wrap, one per ramp
    # period, which is 390 of them a second at 200 ksps.
    skip = set()
    for i in range(1, len(tail)):
        if tail[i] - tail[i - 1] < -span * 0.4:
            skip.update((i - 2, i - 1, i, i + 1, i + 2))

    out = []
    for i in range(1, len(tail)):
        if i in skip:
            continue
        n = (tail[i] - tail[i - 1]) / slope / step
        if abs(n - 1.0) > tolerance:
            out.append((start + i, int(round(n - 1.0))))
    return out


def build_dc(code):
    """A constant on DAC0. If A0 does not move to the matching level the
    DAC is not consuming host data at all, which separates a data-path
    fault from a timing one."""
    return struct.pack("<H", (0 << 12) | (code & 0xFFF)) * 4000, 0.0


# ---------------------------------------------------------------------
# The firmware's own generator
#
# Everything above builds samples the *host* sends. This block drives
# the generator that lives on the device - drivers/gen.c on Track B,
# sketches/bringup/gen.cpp on Track A - which plays a table with no USB
# in the path at all. Two generators, two reasons: the streamed one is
# arbitrary and the internal one keeps running when no host is attached.
#
# The names and codes here are the device's, and both tracks must agree
# with them. A track that answers `=1W` with something other than
# "square" is a parity bug, not a host bug.
# ---------------------------------------------------------------------

GEN_SHAPES = {"sine": 0, "square": 1, "ramp": 2, "triangle": 3, "dc": 4}
GEN_SHAPE_NAMES = {v: k for k, v in GEN_SHAPES.items()}

# The sync output on the pin the waveform is not using - DAC1 in the
# normal layout. It is the bench trigger, so DAC1 is no longer a channel
# to measure: DSO tools look at DAC0, and A1 is what can still see DAC1.
GEN_SYNCS = {"off": 0, "cycle": 1, "wrap": 2}
GEN_SYNC_NAMES = {v: k for k, v in GEN_SYNCS.items()}

# Points in the table. A cycle may spend any power-of-two count from 2
# up to this, and nothing between - see gen.h for why a count that does
# not divide the table is a phase step at every PDC reload.
GEN_TABLE_POINTS = 256
GEN_POINTS_MIN = 2


def gen_points_for(points):
    """The resolution the device will actually adopt for a request.

    The device rounds down to the nearest legal power of two rather than
    refusing, so a host that predicts the frequency has to round the
    same way or its prediction is wrong for every non-power-of-two.
    """
    points = min(int(points), GEN_TABLE_POINTS)
    p = GEN_POINTS_MIN
    while (p << 1) <= points:
        p <<= 1
    return p


def gen_output_hz(trigger_hz, points=GEN_TABLE_POINTS):
    """Output frequency of the internal generator.

    The trigger clocks one table point per update and DACC TAG mode
    spends every other update on DAC1, so a cycle costs 2 * points
    updates. This is the resolution/frequency trade in one line: points
    buys staircase resolution and costs frequency, at a fixed update
    rate that only the trigger changes.
    """
    return trigger_hz / (2.0 * gen_points_for(points))


def gen_fold_len(points=GEN_TABLE_POINTS):
    """The period an issue-#5 fold should use at this resolution."""
    return 2 * gen_points_for(points)


def set_sync(board, mode):
    """`=<n>J`. The bench trigger on the spare DAC pin.

    Measured against triggering on the signal itself: 222x less jitter
    on a sine, 2.2x on a ramp. See docs/awg.md, including the two silent
    ways a DS1102E's EXT input refuses to trigger.
    """
    code = GEN_SYNCS[mode] if isinstance(mode, str) else int(mode)
    board.poll_console()
    board.cmd(f"={code}J")
    return board.drain_console(0.4)


def set_gen(board, shape, points=None):
    """`=<shape>,<pts>W`. Returns the device's own answer.

    Over the console, because that is the only place the generator can
    be set today: the control channel is all queries, so a deployed
    board - native port only - cannot change shape. `ctl_wire.h` keeps
    0x001x free for state the host writes and nothing occupies it yet.
    That gap is real and is called out in docs/awg.md rather than
    papered over here.
    """
    code = GEN_SHAPES[shape] if isinstance(shape, str) else int(shape)
    board.poll_console()
    board.cmd(f"={code},{int(points)}W" if points else f"={code}W")
    return board.drain_console(0.4)


def build_selected(dac_sps, *, tone=1000.0, dc=None, ramp=None, square=None):
    """The waveform kwargs every runner takes, resolved in one place.

    run_loop and run_play each carried their own copy of this chain and
    had already drifted apart once - `ramp` reached run_loop long before
    it reached run_play, so for a while the ADC path could measure a
    waveform the DAC-only path could not play. A tool that sweeps every
    supported waveform needs the same set from both, and one chain is
    the only way that stays true when the next shape is added.

    Returns (bytes, tone_hz), with tone_hz 0.0 for the aperiodic ones.
    """
    if ramp is not None:
        return build_ramp(step=ramp)
    if dc is not None:
        return build_dc(dc)
    if square is not None:
        return build_square(square, dac_sps)
    return build_waveform(tone, dac_sps)


# ---------------------------------------------------------------------
# The feeder
# ---------------------------------------------------------------------

class Feeder:
    """Clock-paced writer with a bounded lead, on a real-time thread.

    Three simpler policies were each tried and measured, and every one
    of them looked plausible first:

      - select()-paced writes in the shared main loop starved on loop
        granularity: ~1% rate shortfall, a few underruns per second.
      - free-running blocking writes saturated the queue, and macOS's
        CDC-ACM output path then silently dropped ~128-byte chunks that
        write() had already counted: ~75 clean phase jumps per second
        on the DAC, every counter green.
      - the empty-queue gate that the manual-FIFO device needed caps
        near 1.7 MB/s once IN traffic runs, because waiting for
        TIOCOUTQ==0 loses a millisecond per burst.

    With the device ingesting by endpoint DMA into a 30 KB ring the tty
    queue stays shallow as long as the lead is smaller than the ring, so
    the macOS pressure-drop condition cannot form and pacing by the
    clock is safe - and measurably clean.

    A fourth policy was tried and does not work, recorded so it is not
    rebuilt: hold the lead against the device's consumption rather than
    against the clock, using TIOCOUTQ to subtract whatever the kernel
    still holds. TIOCOUTQ reports the tty layer only. Measured against
    the device's own occupancy histogram it reads 0 essentially always
    while 55 to 450 KB sits in the CDC driver beneath it, so a loop
    closed on it is blind: it computes that it is already at its target
    depth while the ring holds five slots. Any feedback policy needs a
    signal from the device, not from the kernel.
    """

    LEAD = 20480

    # Every write is this size, and that is what keeps the path
    # lossless - not the size on its own.
    #
    # Measured with the pipeline drained, interleaved so a drifting
    # machine cannot favour one arm. Writing a constant 512 bytes:
    # 0.000% lost at 200,000, 600,000, 1,218,750 and 1,392,857 sps.
    # Writing "whatever is due, capped at 512 or 1024": 0.45-0.65% lost
    # at the same rates in every run. Same sizes on the wire, same
    # pacing, different result - so the mechanism is in how the writes
    # are issued rather than how big they are, and it is not yet
    # understood. What is established is which one is clean.
    #
    # Size alone was tested and is not sufficient: capping MAX_WRITE at
    # 1024 in the due-sized path leaves 0.47-0.84%, with or without a
    # finer idle sleep.
    #
    # This does not fix a feed that genuinely oversupplies. 1,000,000
    # and 886,363 sps still lose ~2.2% and ~1.5%, because their
    # converters run slow by nearly the same fraction and the surplus
    # is shed however it is written. That is rate matching and is
    # tracked separately.
    WRITE_SIZE = 512

    # Only the legacy due-sized path uses this, and that path is kept
    # solely so the two can be compared. It loses bytes.
    MAX_WRITE = 16384

    def __init__(self, fd, wave, byte_rate, scale=1.0,
                 write_size=None):
        self.fd = fd
        self.wave = wave
        # A deliberate feed-rate offset. Not a tuning knob: it is the
        # instrument for finding the rate at which the device's ring
        # neither fills nor drains, which is how the feed's true error
        # is measured rather than inferred from the underrun count.
        self.byte_rate = byte_rate * scale
        self.nominal_rate = byte_rate
        # Force every write to one size, instead of writing whatever is
        # due. The host's byte loss is not monotonic in rate, and the
        # rates that lose most are the ones whose due-sized writes land
        # on 1536 - so write size is the suspect and this is how it gets
        # varied independently of rate.
        # None takes the measured-clean constant size; 0 selects the
        # old due-sized path, which is kept only so the two can be
        # compared - it loses bytes.
        self.write_size = (self.WRITE_SIZE if write_size is None
                           else write_size)
        self.count = 0
        self.note = None
        # Closed-loop rate trim. The writer thread owns the pacing
        # anchor and applies a pending rate itself, so the observer
        # never takes a lock against a real-time thread - a missed
        # update costs one trim interval and the next one carries it.
        self._pending_rate = None
        self.retunes = 0
        # Whether stop() had to discard queued output. It does that only
        # when the writer is wedged, but the discarded bytes have
        # already been counted in self.count, so any byte-exactness
        # comparison drawn across a flushed stop is measuring the flush.
        self.flushed = False
        self.join_s = 0.0
        # How late does this thread actually run? The underrun counter
        # says the ring went dry; this says by how much the writer was
        # delayed, which is the number a fix has to move.
        self.gap = jitter.Histogram("feed-write-gap")
        self._stop = threading.Event()
        self._th = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._th.start()

    def _run(self):
        self.note = rt.promote(period_ms=10.0, computation_ms=1.0,
                               constraint_ms=5.0)
        wave = self.wave
        pos = 0
        t0 = time.monotonic()
        last_write = None
        # Pacing runs from a movable anchor, not from t0, so the rate
        # can change mid-run without the schedule stepping. `lead` is
        # the backlog carried across a retune: re-anchoring with a fixed
        # LEAD would hand the device a jump of up to 20 kB at the moment
        # the model changed, which is a position correction - exactly
        # what the rate loop is supposed to avoid making.
        anchor_t, anchor_count, lead = t0, 0, self.LEAD
        while not self._stop.is_set():
            now = time.monotonic()
            pending = self._pending_rate
            if pending is not None:
                self._pending_rate = None
                lead = (int((now - anchor_t) * self.byte_rate)
                        + lead - (self.count - anchor_count))
                anchor_t, anchor_count = now, self.count
                self.byte_rate = pending
                self.retunes += 1
            due = (int((now - anchor_t) * self.byte_rate)
                   + lead - (self.count - anchor_count))
            if due <= 0:
                time.sleep(min(0.005, -due / self.byte_rate + 0.001))
                continue
            # Whole 512-byte packets only: a short packet fragments the
            # device's stream DMA span, and on older firmware ended it.
            if self.write_size:
                if due < self.write_size:
                    # Sleep until the next write is actually due, rather
                    # than polling. A fixed short sleep here costs 10k
                    # wakeups a second and 0.14 of a core at the
                    # full-rate pair, for nothing: the arrival time of
                    # the next write is known exactly from the rate.
                    time.sleep(min(0.005,
                                   (self.write_size - due) / self.byte_rate))
                    continue
                due = self.write_size
            else:
                due = min(due, self.MAX_WRITE) & ~511
                if due == 0:
                    time.sleep(0.001)
                    continue
            block = wave[pos:pos + due]
            while len(block) < due:
                block += wave[:due - len(block)]
            try:
                n = self.fd.write(block)
            except BlockingIOError:
                time.sleep(0.001)
                continue
            except OSError:
                return
            if n > 0:
                if last_write is not None:
                    self.gap.add(now - last_write)
                last_write = now
                self.count += n
                pos = (pos + n) % len(wave)

    def retune(self, byte_rate):
        """Adopt a new rate model, applied by the writer thread.

        The rate only - never the position. Feeding a correction for
        bytes already missing takes the underrun counter to zero and
        leaves the waveform broken, which is the trap `docs/usb.md`
        records and invariant 5 exists to prevent. This changes how fast
        the schedule advances from here and touches nothing behind it.
        """
        if byte_rate and byte_rate > 0:
            self._pending_rate = float(byte_rate)

    def stop(self):
        # The device keeps consuming until the stream is stopped, so a
        # final blocking write completes on its own; the flush is only a
        # backstop against a writer wedged on a queue nobody drains.
        self._stop.set()
        t0 = time.monotonic()
        self._th.join(2.0)
        if self._th.is_alive():
            self.flushed = True
            self.fd.flush_output()
            self._th.join(1.0)
        self.join_s = time.monotonic() - t0
        return self.count


# ---------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------

@dataclass
class LoopResult:
    stream: ParsedStream
    elapsed_s: float
    host_tx_bytes: int
    host_rx_bytes: int
    dac_sps: int
    adc_hz: int
    channels: int
    tone_hz: float
    refused: bool
    console: str
    report: str
    play: PlayCounters
    bench: BenchCounters
    rt_note: str
    stale_bytes: int
    retunes: int = 0
    settle_frames: int = 0

    # Pass-throughs, so a test can read the numbers it cares about
    # without knowing whether they came from the stream or the host.
    frames        = property(lambda s: s.stream.frames)
    first_seq     = property(lambda s: s.stream.first_seq)
    last_seq      = property(lambda s: s.stream.last_seq)
    seq_gaps      = property(lambda s: s.stream.seq_gaps)
    crc_bad       = property(lambda s: s.stream.crc_bad)
    max_overrun   = property(lambda s: s.stream.max_overrun)
    dev_span_s    = property(lambda s: s.stream.dev_span_s)
    declared_rate_hz = property(lambda s: s.stream.declared_rate_hz)
    channel_mask  = property(lambda s: s.stream.channel_mask)
    per_channel   = property(lambda s: s.stream.per_channel)
    settled       = property(lambda s: s.stream.settled)

    @property
    def windows(self):
        """tag -> [(device time, amplitude)], every window, no overlap."""
        if getattr(self, "_win", None) is None:
            self._win = {tag: self.stream.window_amplitudes(
                                  tag, self.tone_hz, from_us=SETTLE_US)
                         for tag in self.stream.series}
        return self._win

    def fresh(self, host_seconds=None):
        """A measurement is only usable if the data is this run's.

        Sequence numbers near zero and device timestamps spanning the
        host's own window are the proof. Stale kernel-buffered frames
        from a previous run once manufactured a frozen DAC and cost a
        full session.
        """
        if self.stream.frames == 0:
            return False
        # Allow for frames the run deliberately discarded while settling,
        # exactly as tests/helpers.py assert_fresh does. Those frames are
        # this run's, read and thrown away on purpose; a bare
        # `first_seq > 10` calls every loop run stale - on macOS
        # first_seq is 86 - and two definitions of freshness that
        # disagree is how the next session loses an afternoon.
        if self.stream.first_seq > 10 + getattr(self, "settle_frames", 0):
            return False
        span = self.stream.dev_span_s
        want = host_seconds if host_seconds is not None else self.elapsed_s
        return span >= 0.5 * want


def run_loop(board, *, dac_sps=200000, adc_hz=200000, channels=2,
             tone=1000.0, seconds=3.0, dc=None, ramp=None, square=None,
             diag=False, drain=True, notify=None, scale=1.0,
             write_size=None, closed_loop=False):
    """The complete loop: HOST -> USB -> DAC -> wire -> ADC -> USB -> HOST.

    Because the host authored the signal, any discrepancy in what comes
    back is a fault in the path rather than an unknown property of a
    signal.
    """
    wave, tone_hz = build_selected(dac_sps, tone=tone, dc=dc, ramp=ramp,
                                   square=square)

    fd = board.open_native(blocking_writes=True, notify=notify)
    stale = drain_until_quiet(fd) if drain else 0
    if stale and notify:
        notify("stale", bytes=stale)

    board.poll_console()
    board.cmd(f"={dac_sps},{adc_hz},{channels}L")

    # Settle, but drain while settling instead of sleeping blind.
    #
    # There used to be a bare 0.2 s sleep here. The device starts
    # capturing the moment it takes the command, and its ADC ring is
    # four 4 KB buffers - 16 KB, or 20 ms at 800 KB/s - so not reading
    # for 0.2 s overruns that ring by an order of magnitude and the
    # device drops frames it has already numbered. Measured: overrun
    # 33-35 per run and a frame lost in three runs out of four.
    #
    # macOS hid it. Its CDC driver buffers 55-450 KB below the tty layer
    # and absorbed the burst, so the device overran and the host never
    # saw the consequence. Windows has no such cushion, which is how
    # this surfaced at all.
    #
    # The settle itself has to stay: removing it starts the feed before
    # the device has armed playback, and the device then receives fewer
    # bytes than the host sent - 6 KB to 20 KB, measured, which is a
    # byte-conservation failure and far worse than the overrun.
    #
    # Frames read here are deliberately discarded, so the run's first
    # analysed sequence number is not zero. settle_frames records how
    # many, because "starts near zero" is how a stale capture is caught
    # and that check has to know the difference.
    settle_bytes = 0
    _t = time.time()
    while time.time() - _t < 0.2:
        if transport.wait_any([fd], 0.02):
            settle_bytes += len(fd.read(262144))
    #
    # There used to be a 0.2 s sleep here, to let the device settle
    # before the feed began. But the device starts capturing the moment
    # it takes the command, and its ADC ring is four 4 KB buffers - 16 KB,
    # or 20 ms at 800 KB/s. Sleeping 0.2 s without reading overruns that
    # ring by an order of magnitude, and the device drops frames it has
    # already numbered: measured as overrun_count 33-35 per run and a
    # lost frame in three runs out of four.
    #
    # macOS hid it because its CDC driver buffers 55-450 KB below the tty
    # layer and absorbed the burst; the device still overran, the host
    # just never saw the consequence. Windows has no such cushion.
    #
    feeder = Feeder(fd, wave, dac_sps * 2, scale=scale,
                    write_size=write_size)
    feeder.start()

    chunks = []
    console = b""
    diag_sent = False
    # Loop mode's rate signal arrives inside frame headers, so it is
    # scanned incrementally: scanbuf holds only what has not been read
    # yet and is trimmed after every pass.
    scanbuf = bytearray()
    scanpos = 0
    loop_stats = []
    t0 = time.time()
    next_trim = t0 + TRIM_WARMUP_S
    while time.time() - t0 < seconds:
        # The diagnostic must sample while both directions are live, so
        # it is triggered mid-run rather than before or after.
        if diag and not diag_sent and time.time() - t0 > 1.5:
            board.cmd("D")
            diag_sent = True
        r = transport.wait_any([fd, board.cfd], 0.05)
        if board.cfd in r:
            try:
                console += board.cfd.read(65536)
            except OSError:
                pass
        if fd in r:
            try:
                got = fd.read(262144)
            except OSError:
                got = b""
            if got:
                chunks.append(got)
                if closed_loop:
                    scanbuf += got
        if closed_loop and time.time() >= next_trim:
            fresh, scanpos = scan_play_stats(scanbuf, scanpos)
            loop_stats += fresh
            measured = playstat_rate(loop_stats)
            if measured:
                feeder.retune(measured)
            del scanbuf[:scanpos]
            scanpos = 0
            next_trim = time.time() + TRIM_PERIOD_S
    elapsed = time.time() - t0

    tx = feeder.stop()

    board.cmd("B")
    time.sleep(0.5)
    report = b""
    end = time.time() + 1.5
    while time.time() < end:
        r = transport.wait_any([fd, board.cfd], 0.1)
        for f in r:
            try:
                d = f.read(65536)
                if f == board.cfd:
                    report += d
            except OSError:
                pass
    board.cmd("0")
    board.close_native(fd)

    buf = b"".join(chunks)
    # Settled window starts one second into device time: the ring primes
    # and the DAC's first buffer plays before the tone is representative.
    ps = _finish(parse_frames(buf, settle_us=SETTLE_US, settle_cap=16384))

    text = console.decode("utf-8", "replace")
    rep = report.decode("utf-8", "replace")
    return LoopResult(
        stream=ps, elapsed_s=elapsed, host_tx_bytes=tx, host_rx_bytes=len(buf),
        dac_sps=dac_sps, adc_hz=adc_hz, channels=channels, tone_hz=tone_hz,
        refused="refused" in text, console=text, report=rep,
        play=parse_play(rep), bench=parse_bench(rep),
        rt_note=feeder.note, stale_bytes=stale, retunes=feeder.retunes,
        settle_frames=settle_bytes // FRAME_BYTES)


def probe_loop(board, *, dac_sps=200000, adc_hz=200000, channels=2,
               settle=0.6):
    """Ask the device to start a loop and read whether it agreed.

    Refusals matter as much as successes here. An over-fast trigger is
    dropped silently with no status bit set, which reads downstream as
    clean data at half the rate, so the guard is the only thing between
    that and corrupt data presented as good. This starts nothing the
    host has to feed, and stops whatever it started.
    """
    board.poll_console()
    board.cmd(f"={dac_sps},{adc_hz},{channels}L")
    time.sleep(settle)
    text = board.drain_console(0.4)
    board.cmd("0")
    time.sleep(0.2)
    board.poll_console()
    return ("refused" not in text), text


@dataclass
class PlayResult:
    """Playback with no capture, so a DAC fault cannot be masked by, or
    blamed on, the capture path."""
    elapsed_s: float
    host_tx_bytes: int
    dac_sps: int
    tone_hz: float
    refused: bool
    console: str
    report: str
    play: PlayCounters
    rt_note: str
    occ: OccHist = field(default_factory=OccHist)
    drained: bool = False
    stats: list = field(default_factory=list)
    retunes: int = 0

    @property
    def host_deficit(self):
        """Bytes write() counted that the device never received.

        Only meaningful on a run made with drain_s long enough for the
        pipeline to empty - otherwise this is measuring what is still in
        flight. `drained` says which kind of run it was.
        """
        if self.play.bytes_in is None:
            return None
        return self.host_tx_bytes - self.play.bytes_in


# Closed-loop trim cadence. Deliberately slow: the handoff's warning is
# that a loop closed over a window comparable to the pipeline delay
# corrects for staleness it cannot see. The converter holds one rate for
# a whole run - measured - so a long baseline is the right estimator and
# not a lagging one.
TRIM_WARMUP_S = 0.8
TRIM_PERIOD_S = 0.5


def run_play(board, *, dac_sps, tone=1000.0, seconds=3.0, dc=None,
             ramp=None, square=None, scale=1.0, drain_s=0.0,
             write_size=None, closed_loop=False):
    wave, tone_hz = build_selected(dac_sps, tone=tone, dc=dc, ramp=ramp,
                                   square=square)

    fd = board.open_native(blocking_writes=True)
    drain_until_quiet(fd, quiet=0.3, cap=3.0)
    board.poll_console()
    board.cmd(f"={dac_sps}P")
    time.sleep(0.2)
    console = board.drain_console(0.3)

    # In play-only the IN endpoint carries only playback status
    # records, so keeping everything it says costs ~1.4 kB/s and gives
    # the rate loop its signal with no console round trip.
    inbuf = bytearray()

    feeder = Feeder(fd, wave, dac_sps * 2, scale=scale,
                    write_size=write_size)
    feeder.start()
    t0 = time.time()
    now_s = time.time
    next_trim = t0 + TRIM_WARMUP_S
    end = t0 + seconds
    while time.time() < end:
        r = transport.wait_any([fd, board.cfd], 0.05)
        if fd in r:
            try:
                inbuf += fd.read(262144)
            except OSError:
                pass
        if board.cfd in r:
            try:
                console += board.cfd.read(65536).decode("utf-8", "replace")
            except OSError:
                pass
        # The outer loop: trim the feed's rate model to what the device
        # says it is consuming. Off by default - it changes what every
        # measurement in this file measures, and the ladders that
        # established the baseline have to keep meaning what they meant.
        if closed_loop and now_s() >= next_trim:
            measured = playstat_rate(parse_playstats(inbuf))
            if measured:
                feeder.retune(measured)
            next_trim = now_s() + TRIM_PERIOD_S
    elapsed = time.time() - t0
    # Everything in the buffer now was emitted while the host was still
    # feeding. What arrives afterwards describes the shutdown: the ring
    # and then the CDC pipeline empty raggedly, so consumed keeps
    # advancing at a decaying rate before it freezes. Trimming only the
    # frozen tail leaves that decay in, and it reads as a converter
    # 0.1-0.7 pp slower than the trace says, varying run to run.
    fed_len = len(inbuf)
    tx = feeder.stop()

    # Optionally let everything the host wrote reach the device before
    # asking how much arrived. Without the wait the pipeline - measured
    # at 55 to 450 KB - reads as a loss, and with it a shortfall is a
    # real one. The device is left playing throughout, so it keeps
    # draining bulk OUT; the underruns this costs are the shutdown's and
    # are why the counters below are only trusted for their byte count.
    if drain_s > 0.0:
        # Counters first, while they still describe the run. The drain
        # below deliberately starves the device, so underruns and the
        # occupancy histogram accumulated across it describe the
        # shutdown - at RC 39 a 1.5 s drain adds ~6,000 underruns to a
        # run that had none.
        # Over the control channel where there is one. This read happens
        # *inside* the run, and as `B` it cost 13.14 ms of blocked main
        # loop during the thing being measured - the instrument
        # perturbing its own measurement, which is invariant 8's whole
        # point. GET_COUNTERS is 146 us.
        run_play_counters = play_counters(board)
        end = time.time() + drain_s
        while time.time() < end:
            r = transport.wait_any([fd, board.cfd], 0.05)
            if fd in r:
                try:
                    inbuf += fd.read(262144)
                except OSError:
                    pass
        drained_play = play_counters(board)

    # Stop the device before reading its counters. Playback keeps
    # running after the feeder stops, so counters read afterwards
    # include the underruns of the shutdown rather than the run - which
    # is measuring the wrong thing and reads as a fault in the feed.
    board.cmd("0")
    time.sleep(0.2)
    # The occupancy histogram is read after the stop, but it describes
    # the run: the device accumulated it at every ENDTX while playing.
    play = play_counters(board)
    occ = occupancy(board)
    report = board.drain_console(0.3)
    board.close_native(fd)
    if drain_s > 0.0:
        # Bytes from the drained read, because only then has everything
        # the host wrote had time to arrive. Everything else from the
        # read taken before the drain, because the drain starves the
        # device by design.
        play = run_play_counters
        play.raw["in"] = drained_play.bytes_in
        # The device accumulates its occupancy histogram until playback
        # stops, so on a drained run it spans the starvation too. There
        # is no honest way to report it; measure occupancy on a run made
        # without a drain.
        #
        # The rate trace survives that, because it is keyed on
        # *consumed* rather than on ENDTX: the drain starves the device,
        # which adds underruns and no consumed buffers, so it writes no
        # further samples. A drained run is therefore the one place
        # host_deficit and the converter's own rate can be read from the
        # same run, which is the comparison objective 0i rests on.
        occ = OccHist(rate_us=occ.rate_us, rate_decim=occ.rate_decim)

    return PlayResult(elapsed_s=elapsed, host_tx_bytes=tx, dac_sps=dac_sps,
                      tone_hz=tone_hz, refused="refused" in console,
                      console=console, report=report,
                      play=play, rt_note=feeder.note,
                      occ=occ, drained=drain_s > 0.0,
                      stats=parse_playstats(inbuf[:fed_len]),
                      retunes=feeder.retunes)


@dataclass
class CaptureResult:
    stream: ParsedStream
    elapsed_s: float
    host_rx_bytes: int
    console: str
    expect_hz: float
    rt_note: str

    frames      = property(lambda s: s.stream.frames)
    seq_gaps    = property(lambda s: s.stream.seq_gaps)
    crc_bad     = property(lambda s: s.stream.crc_bad)
    per_channel = property(lambda s: s.stream.per_channel)


def run_capture(board, *, preset="5", seconds=5.0, expect_hz=None,
                stop="0", settle_cap=8192, notify=None, uart=False):
    """Device-generated capture: no host feed, just the stream.

    The native port is opened and drained *before* the stream is
    started, so the first frame of the run is the first frame captured
    and freshness is provable rather than probable. Doing it the other
    way round leaves the device streaming into the kernel buffer for as
    long as the setup takes, and the capture then opens partway into a
    stream that is this run's but no longer starts at zero.

    Nothing but reading happens in the capture phase. An earlier
    receiver parsed each frame inline, including a per-sample Python
    loop; at ~0.9 MB/s that is far too slow, so the port stopped being
    drained, the kernel buffer overflowed and bytes were lost. The
    symptom looked exactly like a firmware framing bug.
    """
    if uart:
        # Single-port mode: frames arrive on the control port itself, as
        # Track B does when streaming over the UART. The command and the
        # binary share the one port, so nothing may print to it.
        fd = board.cfd
        time.sleep(0.2)
    else:
        board.poll_console()
        fd = board.open_native(notify=notify)
        try:
            fd.flush_input()
        except OSError:
            pass
        drain_until_quiet(fd, quiet=0.3, cap=5.0)

    note = rt.promote(period_ms=5.0, computation_ms=0.5, constraint_ms=2.5)
    if notify:
        notify("rt", note=note)

    if preset:
        board.cmd(preset)

    chunks = []
    console = b""
    t0 = time.time()
    end = t0 + seconds
    watch = [fd] if uart else [fd, board.cfd]
    try:
        while time.time() < end:
            r = transport.wait_any(watch, 0.2)
            if not uart and board.cfd in r:
                try:
                    console += board.cfd.read(65536)
                except OSError:
                    pass
            if fd in r:
                try:
                    chunk = fd.read(262144)
                except OSError:
                    time.sleep(0.02)
                    continue
                if chunk:
                    chunks.append(chunk)
    finally:
        elapsed = time.time() - t0
        if stop:
            board.cmd(stop)
            drain_until_quiet(fd, quiet=0.2, cap=1.0)
        if not uart:
            board.close_native(fd)

    buf = b"".join(chunks)
    ps = _finish(parse_frames(buf, settle_cap=settle_cap))
    return CaptureResult(stream=ps, elapsed_s=elapsed, host_rx_bytes=len(buf),
                         console=console.decode("utf-8", "replace"),
                         expect_hz=expect_hz, rt_note=note)


BENCH_CMD = {"in": "F", "out": "R", "duplex": "X",
             "in-dma": "G", "out-dma": "T", "duplex-dma": "Y"}
BENCH_RX = ("in", "duplex", "in-dma", "duplex-dma")
BENCH_TX = ("out", "duplex", "out-dma", "duplex-dma")


@dataclass
class BenchResult:
    mode: str
    block: int
    elapsed_s: float
    host_rx_bytes: int
    host_tx_bytes: int
    device: BenchCounters
    report: str
    rt_notes: dict
    flushed: bool = False

    @property
    def out_deficit(self):
        """Bytes the host wrote that the device never counted. Only
        meaningful on a run whose drain was long enough to empty the
        pipeline, and worthless if `flushed` - a flush discards output
        already counted in host_tx_bytes."""
        if not self.want_tx or self.device.out_bytes is None:
            return None
        return self.host_tx_bytes - self.device.out_bytes

    want_rx = property(lambda s: s.mode in BENCH_RX)
    want_tx = property(lambda s: s.mode in BENCH_TX)
    rx_mbs = property(lambda s: s.host_rx_bytes / s.elapsed_s / 1e6
                      if s.elapsed_s else 0.0)
    tx_mbs = property(lambda s: s.host_tx_bytes / s.elapsed_s / 1e6
                      if s.elapsed_s else 0.0)


def run_bench(board, *, mode, seconds=5.0, block=16384,
              drain_s=0.3, tx_rate=None):
    """Drive the device's flood / sink / duplex modes and measure each
    direction from the host side, so the host's own throughput is
    visible alongside what the device counted. A mismatch between the
    two is the signal that the host, not the transport, is the limit.
    """
    cmd = BENCH_CMD[mode]
    board.poll_console()
    board.cmd(cmd)
    time.sleep(0.4)

    fd = board.open_native(wait=10.0)
    fd.flush_input()

    # One thread per direction, and blocking writes. An earlier loop
    # interleaved reads and writes on one thread behind a select()
    # timeout, so each direction stalled while the other's syscall ran -
    # a ceiling made by the host's scheduling, not by the transport.
    fd.set_blocking(True)

    payload = bytes(range(256)) * (block // 256)
    want_rx = mode in BENCH_RX
    want_tx = mode in BENCH_TX

    rx_n = [0]
    tx_n = [0]
    notes = {}
    stop = threading.Event()

    def reader():
        # At ~30 MB/s a 5 ms scheduling hole is a lot of kernel buffer;
        # the real-time band keeps the drain ahead of it.
        notes["reader"] = rt.promote(period_ms=5.0, computation_ms=0.5,
                                     constraint_ms=2.5)
        while not stop.is_set():
            r = transport.wait_any([fd], 0.05)
            if r:
                try:
                    rx_n[0] += len(fd.read(262144))
                except OSError:
                    return

    def writer():
        notes["writer"] = rt.promote(period_ms=5.0, computation_ms=0.5,
                                     constraint_ms=2.5)
        # Optionally pace the writer, so the OUT loss can be measured
        # against offered rate with no DAC, no ring and no ring-derived
        # pacing in the picture. Free-running is the default and is what
        # the throughput figures are taken at.
        t_start = time.monotonic()
        while not stop.is_set():
            if tx_rate:
                due = (time.monotonic() - t_start) * tx_rate - tx_n[0]
                if due < len(payload):
                    time.sleep(0.0005)
                    continue
            try:
                tx_n[0] += fd.write(payload)
            except OSError:
                return

    threads = []
    if want_rx:
        threads.append(threading.Thread(target=reader, daemon=True))
    if want_tx:
        threads.append(threading.Thread(target=writer, daemon=True))
    t0 = time.time()
    for th in threads:
        th.start()
    time.sleep(seconds)
    elapsed = time.time() - t0
    stop.set()
    for th in threads:
        th.join(2.0)
    flushed = False
    if any(th.is_alive() for th in threads):
        # A writer wedged on a queue the device stopped draining.
        flushed = True
        fd.flush_output()
        for th in threads:
            th.join(1.0)

    # Let the pipeline empty before asking the device what it received.
    # Without this the tens to hundreds of KB still in the CDC driver
    # read as a loss, which is how a byte-perfect claim gets made from a
    # measurement that could not have supported one - in either
    # direction. The device keeps sinking OUT until the mode is stopped.
    t_drain = time.time() + drain_s
    while time.time() < t_drain:
        r = transport.wait_any([fd], 0.05)
        if r:
            try:
                fd.read(262144)
            except OSError:
                pass
    board.cmd("B")
    time.sleep(0.6)
    report = b""
    t1 = time.time()
    while time.time() - t1 < 1.5:
        # Keep draining so a blocked device can still answer.
        r = transport.wait_any([fd, board.cfd], 0.1)
        for f in r:
            try:
                d = f.read(262144)
                if f == board.cfd:
                    report += d
            except OSError:
                pass
    board.cmd("0")
    board.close_native(fd)

    rep = report.decode("utf-8", "replace")
    return BenchResult(mode=mode, block=block, elapsed_s=elapsed,
                       host_rx_bytes=rx_n[0], host_tx_bytes=tx_n[0],
                       device=parse_bench(rep), report=rep, rt_notes=notes,
                       flushed=flushed)


_HEX_KEYS = ("devisr", "ep0isr", "devimr")


def stream_stats(board, *, secs=1.2):
    """The `?` report: frame, ring, resync and USB-level counters.

    resync and ringovf are the honest flags behind invariant 5 - a
    capture that lapped its ring is counted here rather than spliced
    silently into the stream.
    """
    text = board.ask("?", secs=secs)
    got = {}
    for line in text.splitlines():
        if "frames=" in line or "usb isr=" in line:
            for k, v in _KV.findall(line):
                if k not in _HEX_KEYS:
                    got[k] = int(v)
    return got, text


TRACK_MARK = {"a": "Track A", "b": "Track B"}

# The identity line, emitted by `v` and by the banner on both tracks.
# See lib/due_shared/src/fw_version.h; the format is fixed and identical on the two.
_ID_LINE = re.compile(
    r"#\s*id:\s*track=(?P<track>[AB])\s+fw=(?P<fw>[0-9]+\.[0-9]+\.[0-9]+)"
    r"\s+ctlver=(?P<ctlver>\d+)\s+framever=(?P<framever>\d+)"
    r"\s+mck=(?P<mck>\d+)\s+adcclk=(?P<adcclk>\d+)"
    r"\s+framebytes=(?P<framebytes>\d+)\s+framesamples=(?P<framesamples>\d+)"
    r"\s+build=(?P<build>.+?)\s*$", re.M)


def parse_identity(text):
    """The identity line, or None. Same shape as the control channel's
    IDENTITY record, so a caller can use either interchangeably."""
    m = _ID_LINE.search(text)
    if not m:
        return None
    g = m.groupdict()
    return {
        "track": g["track"].lower(),
        "fw_version": g["fw"],
        # 0 means "this track has no control channel" - Track A today.
        "ctl_version": int(g["ctlver"]),
        "frame_version": int(g["framever"]),
        "mck_hz": int(g["mck"]),
        "adc_clock_hz": int(g["adcclk"]),
        "frame_bytes": int(g["framebytes"]),
        "frame_samples": int(g["framesamples"]),
        "build": g["build"].strip(),
    }


def identity(board, *, secs=1.0):
    """Ask the board what it is. One short line, not the banner.

    The banner costs 89 ms of blocked main loop (invariant 8) and says
    which track only in prose. `v` is one line in a fixed format, cheap
    enough to ask while something is running.
    """
    return parse_identity(board.ask("v", secs=secs))


def which_track(board, *, secs=1.5):
    """Which firmware is actually on the board, from its own report.

    Asked rather than assumed: flashing is the slowest thing the suite
    does, and a stale image is the failure that looks like a firmware
    regression.

    `v` first, because it is one line and it states the track as a field
    rather than as prose. The banner is the fallback, for an image built
    before `v` existed - matching "Track A" in a paragraph is what this
    used to do and it is kept only for that case.
    """
    text = board.ask("v", secs=min(secs, 1.0))
    ident = parse_identity(text)
    if ident:
        return ident["track"], text
    text = board.banner() if secs is None else board.ask("h", secs=secs)
    ident = parse_identity(text)
    if ident:
        return ident["track"], text
    for track, mark in TRACK_MARK.items():
        if mark in text:
            return track, text
    return None, text


# ---------------------------------------------------------------------
# Console sweeps
# ---------------------------------------------------------------------

@dataclass
class SweepRow:
    rc: int = None
    want_hz: int = None
    trigger_hz: int = None
    per_channel_hz: int = None
    aggregate_hz: int = None
    ratio: float = None
    rxbuff: int = None
    govre: int = None
    refused: bool = False
    raw: str = ""


_NUM = re.compile(r"-?\d+")


_SWEEP_HDR = re.compile(r"TC->ADC->PDC.*?(\d+)\s*(?:ch\b|channel)")


def _sweep_rows(text, channels, dac=False):
    """Parse a `t` or `d` sweep.

    The two tracks print different columns for the same measurement -
    Track A drives the ladder by RC and prints the aggregate, Track B
    drives it by Hz and prints the per-channel rate - so the header line
    selects the layout and both normalise to the same row.
    """
    rows = []
    layout = None
    reported = None
    for line in text.splitlines():
        m = _SWEEP_HDR.search(line)
        if m:
            # A fresh sweep starts here; anything above belongs to an
            # earlier command and is not this measurement.
            reported = int(m.group(1))
            rows = []
            layout = None
            continue
        s = line.strip()
        if s.startswith("#") and " RC " in s and "ratio" in s:
            layout = "rc" if s.split()[1] == "RC" else "want"
            continue
        if not s.startswith("#") or layout is None:
            continue
        if "REFUSED" in s:
            nums = _NUM.findall(s.split("REFUSED")[0])
            row = SweepRow(refused=True, raw=s)
            if layout == "rc" and nums:
                row.rc = int(nums[0])
                if len(nums) > 1:
                    row.want_hz = row.trigger_hz = int(nums[1])
            elif nums:
                row.want_hz = int(nums[0])
                row.rc = rc_for(row.want_hz)
            rows.append(row)
            continue
        m = re.match(r"^#\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\.(\d{3})"
                     r"(?:\s+(\d+)\s+(\d+))?\s*$", s)
        if m and layout == "rc":
            rc, hz, agg = int(m.group(1)), int(m.group(2)), int(m.group(3))
            rows.append(SweepRow(
                rc=rc, want_hz=hz, trigger_hz=hz, aggregate_hz=agg,
                per_channel_hz=agg // channels,
                ratio=int(m.group(4)) + int(m.group(5)) / 1000.0,
                rxbuff=int(m.group(6)) if m.group(6) else None,
                govre=int(m.group(7)) if m.group(7) else None, raw=s))
            continue
        m = re.match(r"^#\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\.(\d{3})"
                     r"(?:\s+(\d+)\s+(\d+))?\s*$", s)
        if m and layout == "want":
            want, rc = int(m.group(1)), int(m.group(2))
            trig, meas = int(m.group(3)), int(m.group(4))
            rows.append(SweepRow(
                rc=rc, want_hz=want, trigger_hz=trig, per_channel_hz=meas,
                aggregate_hz=meas * (1 if dac else channels),
                ratio=int(m.group(5)) + int(m.group(6)) / 1000.0,
                rxbuff=int(m.group(7)) if m.group(7) else None,
                govre=int(m.group(8)) if m.group(8) else None, raw=s))
    return rows, reported


def sweep_rates(board, *, channels=2, timeout=40.0):
    """The TC -> ADC -> PDC trigger-rate sweep (`t`).

    Everything downstream is sized against this, and the failure mode is
    silent: an over-fast trigger is ignored with no status bit set,
    which looks exactly like clean data at half the rate.
    """
    board.poll_console()
    board.cmd(f"=0,0,{channels}t" if channels != 2 else "t")
    # Both tracks print a closing line, and they print different ones.
    text = board.drain_console(0, quiet=2.0, cap=timeout,
                               until=("past the measured ceiling",
                                      "every trigger produced a conversion"))
    rows, reported = _sweep_rows(text, channels)
    if reported is not None and reported != channels:
        raise BoardError(f"asked for a {channels}-channel sweep and the "
                         f"device ran a {reported}-channel one")
    return rows, text


def sweep_dac(board, *, timeout=40.0):
    """The DAC update-rate sweep (`d`). Track A only."""
    board.poll_console()
    board.cmd("d")
    text = board.drain_console(0, quiet=2.0, cap=timeout,
                               until="every trigger produced a DAC update")
    return _sweep_rows(text, 1, dac=True)[0], text


_PROF = re.compile(r"^#\s+(\S.*?)\s{2,}(\d+)\s+ns\s*$")


def profile(board, *, timeout=30.0):
    """Where the main loop's time goes (`Q`), ns per call.

    The DMA benches re-arm at most one transfer per main-loop pass, so
    the cost of a pass is a throughput ceiling, not a curiosity.
    """
    board.poll_console()
    board.cmd("Q")
    text = board.drain_console(0, quiet=1.5, cap=timeout,
                               until="services early-return unless started")
    out = {}
    for line in text.splitlines():
        m = _PROF.match(line.rstrip())
        if m:
            out[m.group(1).strip()] = int(m.group(2))
    return out, text


# ---------------------------------------------------------------------
# Flashing
# ---------------------------------------------------------------------

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tool_env():
    """PATH with the build tools on it, wherever this host keeps them.

    ~/.local/bin with a ':' separator is where they live on macOS and it
    is not portable in either half: Windows separates PATH with ';' and
    keeps cmake inside the Visual Studio tree. toolchains.json already
    knows both, so ask it rather than guessing, and keep the POSIX
    default as one more entry rather than as the rule.
    """
    env = dict(os.environ)
    extra = [os.path.expanduser("~/.local/bin")]
    try:
        sys.path.insert(0, os.path.join(REPO, "tools"))
        import toolchain
        reg = toolchain.load()
        for tool in ("cmake", "ninja", "arm_toolchain", "bossac",
                     "arduino_cli"):
            d, _exe = toolchain.resolve(tool, reg)
            if d:
                extra.append(d.replace("/", os.sep))
    except Exception:                                        # noqa: BLE001
        pass                       # no registry is no information, not an error
    have = env.get("PATH", "").split(os.pathsep)
    env["PATH"] = os.pathsep.join(
        [d for d in extra if d and d not in have] + have)
    return env


def _exe(name, env):
    """Absolute path to a build tool, or the bare name.

    CreateProcess searches the *parent's* PATH on Windows, not the one
    handed to the child, so putting a directory in env["PATH"] is not
    enough to make the child findable. Every caller here passes env, so
    every caller needs this too.
    """
    return shutil.which(name, path=env.get("PATH")) or name


def flash(track, control=None, retries=2, build=False):
    """Flash a track, retrying with the port named explicitly.

    An interrupted flash leaves SAM-BA enumerated and the banner silent;
    a plain retry recovers it. SAM-BA drops happened twice in one
    session, so the retry is not optional - without it the suite reports
    false failures for a cable-level event.
    """
    if control is None:
        control, _ = find_ports()
    last = None
    for attempt in range(retries + 1):
        try:
            if track == "b":
                env = _tool_env()
                if build:
                    subprocess.run([_exe("cmake", env), "--build", "build",
                                    "-j"],
                                   cwd=REPO, check=True, env=env,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
                # flash.py, not the .sh shim, for the reason the Track A
                # branch below spells out: a shell script is not
                # executable on win32, and this path only ever ran
                # because the board already happened to be on this track.
                cmd = [sys.executable, os.path.join(REPO, "tools", "flash.py"),
                       "--bin",
                       os.path.join(REPO, "build", "baremetal_bringup.bin")]
                if control:
                    cmd += ["--port", control]
            elif track == "a":
                # tools/sketch.py, and through this interpreter.
                #
                # Not the .sh shim: it is not executable on win32, where
                # CreateProcess answers "%1 is not a valid Win32
                # application" and the whole track becomes unreachable
                # from the suite. Not a bare arduino-cli call either -
                # Track A needs two build properties, both silent when
                # missing (a wrong f_cpu makes micros() lie, a missing
                # ldscript leaves the capture ring in bank 0), and
                # `arduino-cli upload` cannot flash a Due on this host
                # and fails destructively. sketch.py decides the
                # properties and routes the upload through flash.py,
                # which works everywhere.
                sk = os.path.join(REPO, "tools", "sketch.py")
                if build:
                    subprocess.run(
                        [sys.executable, sk, "compile"],
                        cwd=REPO, check=True, env=_tool_env(),
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                cmd = [sys.executable, sk, "upload"]
                if control:
                    cmd.append(control)
            else:
                raise ValueError(f"unknown track {track!r}")
            subprocess.run(cmd, cwd=REPO, check=True, env=_tool_env(),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=300)
            time.sleep(2.0)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            last = e
            time.sleep(2.0)
    raise BoardError(f"flashing track {track} failed: {last}")
