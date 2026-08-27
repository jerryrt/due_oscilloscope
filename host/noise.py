"""How much of a converter's resolution the board actually leaves it.

This board wires a 78 MHz core, a high-speed USB PHY and two DMA engines
to the same ground and the same 3.3 V rail as its converters, and
ADVREF - the reference the ADC *and* the DAC share - comes off that
rail. That is not a defect to fix, it is what the hardware is. What it
is not allowed to be is a guess: the point of this module is to put a
number on it, so that an AFE, an external converter or a layout change
can be judged by how much the number moves.

**Everything here is in volts and bits, never in Due codes.** The LSB
size is a parameter. That is the whole reason the results will still
mean something when the converter changes, which is the point of having
a standard at all - and it is the same rule `host/trace.py` was rebuilt
under after thresholds calibrated in samples turned out to be
thresholds calibrated in an accident of the instrument's settings.

## The physics being used

**Splitting random noise from coupled noise.** Averaging N independent
acquisitions divides *uncorrelated* noise by sqrt(N) and does nothing at
all to anything phase-locked to the trigger. So

    rms(N)^2 = random^2 / N + coherent^2

is a straight line in 1/N, and a least-squares fit of rms^2 against 1/N
returns the random power as its slope and the coupled power as its
intercept. `split_by_averaging()`.

**The same split from one capture, with no averaging at all.** Random
noise is spread across every frequency bin; coupled noise from a clock,
a switching supply or a USB microframe is a *line*. So the spectrum of a
held DC level separates them directly: the broadband floor is thermal
and quantisation, the lines are the board. `line_split()`. This is the
better instrument of the two, because it also says *which* aggressor -
a line at 8 kHz is the USB microframe and a line at the conversion
cadence is the converter's own mux.

**Bits, not millivolts.** An ideal N-bit converter has quantisation
noise of 1/sqrt(12) LSB rms and nothing else, so observed rms noise
converts straight into an equivalent resolution. Two conventions, both
standard, both reported, because they answer different questions:

    effective bits   = N - log2(rms_lsb * sqrt(12))
    noise-free bits  = N - log2(rms_lsb * 6.6)

The first is the rms-equivalent resolution. The second is the vendors'
"noise-free" convention - 6.6 sigma is the 99.9% peak-to-peak span - and
says how many bits are stable enough to *read off a display* rather than
to average down.

## The trap this module has to state

A line in a spectrum taken at one sample rate may be an alias of
something above Nyquist. There is no anti-alias filter anywhere on this
board, so that is not a remote possibility, it is the expected case: at
453 ksps everything the digital side does above 226 kHz folds down into
the band and lands somewhere. **A line is not identified until it has
been seen at two sample rates.** A real line sits still; an alias moves.
`alias_check()` does the arithmetic and refuses to name anything from a
single rate.
"""
from __future__ import annotations

import cmath
import math

#: An ideal converter's quantisation noise, in LSB rms. Uniform error
#: over one LSB has variance 1/12.
Q_RMS_LSB = 1.0 / math.sqrt(12.0)

#: Smallest level ratio `scaling_fit` will fit a slope across. Below
#: this an additive term and a multiplicative one are not separable and
#: the fit reports whichever way the noise happened to fall.
MIN_LEVER = 1.5

#: Sigmas spanned by the "noise-free" convention: 6.6 sigma is 99.9% of
#: a Gaussian, which is what a reading has to sit inside to be stable on
#: a display rather than merely stable on average.
NOISE_FREE_SIGMA = 6.6


def rms(values, about=None):
    """Rms deviation about the mean, or about a stated level."""
    if not values:
        return 0.0
    m = (sum(values) / len(values)) if about is None else about
    return math.sqrt(sum((x - m) ** 2 for x in values) / len(values))


def effective_bits(rms_lsb, full_scale_bits=12):
    """Resolution an ideal converter would need to be this noisy.

    Returns None for zero noise rather than an infinity: a series with
    no spread is either a perfect converter or a measurement that is not
    connected to anything, and this cannot tell them apart.
    """
    if rms_lsb <= 0:
        return None
    return full_scale_bits - math.log2(rms_lsb / Q_RMS_LSB)


def noise_free_bits(rms_lsb, full_scale_bits=12):
    """Bits that are stable peak-to-peak, the vendors' convention."""
    if rms_lsb <= 0:
        return None
    return full_scale_bits - math.log2(rms_lsb * NOISE_FREE_SIGMA)


def describe(values, *, lsb_v, full_scale_bits=12):
    """One held level, in every unit that matters.

    `values` are converter codes; `lsb_v` is what one code is worth in
    volts, which is the parameter that makes this portable to a
    different converter.
    """
    if not values:
        return {"n": 0}
    n = len(values)
    mean = sum(values) / n
    r = rms(values, mean)
    ordered = sorted(values)
    def pct(p):
        return ordered[min(n - 1, max(0, int(p * (n - 1))))]
    return {
        "n": n,
        "mean_code": mean,
        "mean_v": mean * lsb_v,
        "rms_lsb": r,
        "rms_v": r * lsb_v,
        # Percentiles, not min/max. One outlying sample in 65,526 once
        # read a 2.19 V pin as 3.640 V peak to peak here.
        "p99_9_minus_p0_1_lsb": pct(0.999) - pct(0.001),
        "span_lsb": ordered[-1] - ordered[0],
        "effective_bits": effective_bits(r, full_scale_bits),
        "noise_free_bits": noise_free_bits(r, full_scale_bits),
        "quantisation_floor_lsb": Q_RMS_LSB,
        "excess_over_quantisation": r / Q_RMS_LSB if r else None,
    }


# ------------------------------------------------------------------
# spectrum
# ------------------------------------------------------------------

def hann(n):
    """The window, its coherent gain, and its noise bandwidth.

    A rectangular window smears every line that is not exactly on a bin
    across the whole spectrum, which is the difference between finding a
    50 Hz line and finding a raised floor.

    Both corrections are returned because they apply in different
    places and mixing them up is silent:

    **Coherent gain** scales a single bin, so that a line reads its own
    amplitude. Applied inside `spectrum()`.

    **Equivalent noise bandwidth** scales a *sum* of bins. A window
    spreads power into neighbouring bins, so adding bin powers
    overcounts by exactly this factor - 1.5 for Hann, measured here at
    1.5000 for a coherent tone on-bin and off-bin and 1.5050 for white
    noise, which is the check that it is the window and not the signal.
    Applied only where powers are summed, in `line_split()`.

    Computed from the window rather than written down, so it stays
    correct if the window is ever changed.
    """
    if n < 2:
        return [1.0] * n, 1.0, 1.0
    w = [0.5 - 0.5 * math.cos(2.0 * math.pi * i / n) for i in range(n)]
    sw = sum(w)
    return w, sw / n, n * sum(x * x for x in w) / (sw * sw)


def fft(x):
    """Iterative radix-2 Cooley-Tukey, on a power-of-two length.

    Pure stdlib on purpose: `host/` runs from the system interpreter
    during bring-up, and 4096 points costs about a millisecond, which is
    nothing against a capture that takes seconds to acquire.
    """
    n = len(x)
    if n & (n - 1):
        raise ValueError(f"length {n} is not a power of two")
    a = [complex(v) for v in x]
    # Bit-reversal permutation.
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    size = 2
    while size <= n:
        step = cmath.exp(-2j * math.pi / size)
        for start in range(0, n, size):
            w = 1.0 + 0j
            half = size // 2
            for k in range(start, start + half):
                u, v = a[k], a[k + half] * w
                a[k], a[k + half] = u + v, u - v
                w *= step
        size <<= 1
    return a


def largest_pow2(n):
    return 1 << (n.bit_length() - 1) if n else 0


def spectrum(values, fs, *, lsb_v=1.0):
    """One-sided amplitude spectrum of a held level, DC removed.

    Returns `(freqs, amps)` where `amps` are the **rms amplitude of a
    sinusoid** at that frequency, in codes - so a line's amplitude can
    be compared directly against the total rms, and the powers add.

    The mean is subtracted before windowing: the DC level is the thing
    being held, not noise, and leaving it in puts a mountain at bin 0
    whose skirts are wider than anything being looked for.
    """
    n = largest_pow2(len(values))
    if n < 16:
        return [], []
    x = values[:n]
    m = sum(x) / n
    w, cg, _ = hann(n)
    a = fft([(v - m) * wi for v, wi in zip(x, w)])
    freqs, amps = [], []
    for k in range(1, n // 2):
        # 2/N for the one-sided pair, /cg to undo the window's coherent
        # gain, /sqrt(2) to state a sinusoid's rms rather than its peak.
        peak = 2.0 * abs(a[k]) / n / cg
        freqs.append(k * fs / n)
        amps.append(peak / math.sqrt(2.0))
    return freqs, amps


#: Bins next to DC that are never reported as lines. Bin 0 is the level
#: being held; subtracting the mean leaves a residual whenever the
#: record does not contain a whole number of cycles of everything in it,
#: and the window leaks that residual into the first bin or two. It is
#: an artifact of the analysis, not an aggressor.
#:
#: The cost is stated rather than hidden: at 453 ksps over 4096 samples
#: a bin is 110 Hz wide, so mains at 50/60 Hz is below bin 1 and this
#: window cannot see it at all. Finding mains needs a far longer record,
#: not a smaller skip.
SKIP_BINS = 2


def welch(values, fs, *, window=4096, lsb_v=1.0, limit=None):
    """Averaged periodogram: the same spectrum, from all of the record.

    One 4096-point window of a 900,000-sample capture uses 0.5% of what
    was acquired and throws the rest away, and the estimate it returns
    has a spread to match - Phase 0 measured 42% run to run on the rms
    it produced, which is far wider than any difference worth looking
    for.

    Averaging K periodograms divides the *variance of the estimate* by
    K, so 200 windows of a two-second capture tighten it by about 14x
    for no extra bench time at all. This is the same 1/sqrt(N) that
    `split_by_averaging` uses, applied to the estimator rather than to
    the signal.

    Each window has its own mean removed, so slow drift across the
    record does not appear as a mountain at DC in every window.
    """
    n = 1 << (window.bit_length() - 1) if window else 0
    if n < 16 or len(values) < n:
        return [], [], 0
    w, cg, _ = hann(n)
    k = len(values) // n
    if limit:
        k = min(k, limit)
    acc = [0.0] * (n // 2)
    for j in range(k):
        seg = values[j * n:(j + 1) * n]
        m = sum(seg) / n
        a = fft([(v - m) * wi for v, wi in zip(seg, w)])
        for i in range(1, n // 2):
            peak = 2.0 * abs(a[i]) / n / cg
            acc[i] += peak * peak / 2.0
    freqs = [i * fs / n for i in range(1, n // 2)]
    amps = [math.sqrt(acc[i] / k) for i in range(1, n // 2)]
    return freqs, amps, k


def stability(values, *, window=4096):
    """Fast noise and slow wander, separated.

    Rms about a *whole* record's mean mixes two different things: the
    noise inside a moment, and the level moving over seconds. They have
    different causes and different fixes, so they are reported apart.

    `within_rms` is the median of the per-window rms - what an averaging
    measurement cannot remove. `drift_rms` is the rms of the window
    means about the record's mean - thermal, 1/f, or anything slower
    than a window.
    """
    n = 1 << (window.bit_length() - 1) if window else 0
    k = len(values) // n if n else 0
    if k < 2:
        return {}
    means, rmss = [], []
    for j in range(k):
        seg = values[j * n:(j + 1) * n]
        m = sum(seg) / n
        means.append(m)
        rmss.append(math.sqrt(sum((v - m) ** 2 for v in seg) / n))
    rmss.sort()
    gm = sum(means) / len(means)
    return {
        "windows": k,
        "within_rms_lsb": rmss[len(rmss) // 2],
        "within_rms_min": rmss[0],
        "within_rms_max": rmss[-1],
        "drift_rms_lsb": math.sqrt(sum((m - gm) ** 2 for m in means)
                                   / len(means)),
        "drift_span_lsb": max(means) - min(means),
    }


def peaks(freqs, amps, *, count=10, floor_mult=4.0, skip=SKIP_BINS):
    """Lines that stand above the local floor, strongest first.

    The floor is the median amplitude, which a handful of lines cannot
    move - a mean can, and then the lines hide behind their own
    contribution to the threshold.

    Four times the median is not a tuned constant: bin amplitudes of
    Gaussian noise are Rayleigh, so P(a > k x median) = 2^-(k^2), and
    k = 4 gives one false bin in 65,536 - well under one across a 4,096
    point spectrum.
    """
    if not amps:
        return []
    ordered = sorted(amps)
    floor = ordered[len(ordered) // 2]
    out = []
    for i, (f, a) in enumerate(zip(freqs, amps)):
        if i < skip:
            continue
        if a < floor * floor_mult:
            continue
        # Local maximum only, so one line does not report as three.
        if i and amps[i - 1] > a:
            continue
        if i + 1 < len(amps) and amps[i + 1] > a:
            continue
        out.append({"hz": f, "amp_lsb": a, "over_floor": a / floor})
    out.sort(key=lambda p: -p["amp_lsb"])
    return out[:count]


def line_split(freqs, amps, *, floor_mult=4.0, skip=SKIP_BINS, enbw=None):
    """How much of the noise power is lines, and how much is floor.

    The measurement this module exists for. Random noise spreads over
    every bin; noise coupled from a clock, a supply or a USB microframe
    lands in a few. So the ratio says whether the board's contribution
    is something a filter could remove or something only layout can.
    """
    if not amps:
        return {}
    # From the window itself, for the length this spectrum came from, so
    # there is no constant here to drift out of step with `hann()`.
    if enbw is None:
        enbw = hann(2 * (len(amps) + 1))[2]
    ordered = sorted(amps)
    floor = ordered[len(ordered) // 2]
    body = amps[skip:]
    # Divided by the window's noise bandwidth, because these are sums of
    # bins and a window spreads power across them. Without it every
    # figure below reads 22% high - 1.2247 on a tone whose amplitude is
    # known exactly.
    line_p = sum(a * a for a in body if a >= floor * floor_mult) / enbw
    total_p = sum(a * a for a in body) / enbw
    return {
        "total_rms_lsb": math.sqrt(total_p),
        "line_rms_lsb": math.sqrt(line_p),
        "floor_rms_lsb": math.sqrt(max(0.0, total_p - line_p)),
        "line_power_fraction": (line_p / total_p) if total_p else None,
        "median_bin_lsb": floor,
    }


def split_by_averaging(points):
    """Random and coherent power, from rms against averaging depth.

    `points` is [(N, rms_lsb), ...]. Averaging N acquisitions divides
    uncorrelated noise by sqrt(N) and leaves anything phase-locked to
    the trigger untouched, so

        rms(N)^2 = random^2 / N + coherent^2

    is a straight line in 1/N. Least squares on it returns both terms,
    and - the part that matters - a *negative* intercept is the honest
    answer that the data does not support a coherent term, rather than a
    small positive one invented by clamping.
    """
    pts = [(1.0 / n, r * r) for n, r in points if n > 0]
    if len(pts) < 2:
        return {}
    sx = sum(p[0] for p in pts)
    sy = sum(p[1] for p in pts)
    sxx = sum(p[0] * p[0] for p in pts)
    sxy = sum(p[0] * p[1] for p in pts)
    k = len(pts)
    den = k * sxx - sx * sx
    if not den:
        return {}
    slope = (k * sxy - sx * sy) / den
    icept = (sy - slope * sx) / k
    out = {"random_power": slope, "coherent_power": icept,
           "n_points": k}
    out["random_rms_lsb"] = math.sqrt(slope) if slope > 0 else None
    out["coherent_rms_lsb"] = math.sqrt(icept) if icept > 0 else None
    if icept <= 0:
        out["note"] = ("intercept is not positive: the data does not "
                       "support a coherent term at this depth")
    return out


def scaling_fit(points):
    """Is the noise additive, or does it scale with the level?

    The one question the ratiometric loop still answers about its own
    reference. `points` is [(level, rms), ...].

    ADVREF is the reference for the DAC *and* the ADC, so a DAC code
    makes a fixed fraction of ADVREF and the ADC reads it as a fraction
    of the same ADVREF: the level cancels, and the board cannot measure
    its reference directly. What does not cancel is the *signature*.
    Reference noise - and gain noise generally - is **multiplicative**,
    so it grows in proportion to the output level. Noise from the ADC's
    input, its comparator or thermal sources is **additive** and does
    not.

    Fits `rms = a + b * level` and reports what each term is worth at
    the top of the range, so the answer is a proportion rather than a
    slope nobody can size. A fit is not a mechanism: multiplicative here
    means "the reference or the DAC's gain", and separating those two
    needs an input that is not derived from ADVREF, which this board
    does not have without firmware or hardware.
    """
    pts = [(x, y) for x, y in points if x is not None and y is not None]
    if len(pts) < 3:
        return {}
    # A lever, or no answer. Fitting a slope through points that share an
    # x is not a weak measurement, it is an arithmetic accident: the
    # first run of this returned "51% of the noise scales with the
    # level" and a -39-code additive term from six points whose levels
    # were all 2050, because the command driving the DAC was setting an
    # amplitude on a shape that has none. The tool printed `lever 1.0x`
    # in the same breath and gave a verdict anyway.
    xs = [x for x, _ in pts]
    lo, hi = min(xs), max(xs)
    if lo <= 0 or hi / lo < MIN_LEVER:
        return {"n": len(pts), "level_lo": lo, "level_hi": hi,
                "lever": (hi / lo) if lo else None,
                "refused": f"levels span {hi/lo if lo else 0:.2f}x, under "
                           f"the {MIN_LEVER:.1f}x needed to separate a "
                           f"slope from an offset"}
    n = len(pts)
    sx = sum(x for x, _ in pts)
    sy = sum(y for _, y in pts)
    sxx = sum(x * x for x, _ in pts)
    sxy = sum(x * y for x, y in pts)
    den = n * sxx - sx * sx
    if not den:
        return {}
    b = (n * sxy - sx * sy) / den
    a = (sy - b * sx) / n
    xs = [x for x, _ in pts]
    lo, hi = min(xs), max(xs)
    # Residual of the fit, so a bad fit cannot masquerade as a finding.
    resid = math.sqrt(sum((y - (a + b * x)) ** 2 for x, y in pts) / n)
    mult_at_top = b * hi
    return {
        "n": n,
        "additive": a,
        "slope": b,
        "level_lo": lo,
        "level_hi": hi,
        "multiplicative_at_top": mult_at_top,
        "fraction_multiplicative": (abs(mult_at_top) /
                                    (abs(a) + abs(mult_at_top))
                                    if (a or mult_at_top) else None),
        "fit_residual": resid,
        "lever": (hi / lo) if lo else None,
    }


def paired_delta(pairs):
    """A difference measured within rounds, not between runs.

    Comparing the median of seven runs of A against seven of B throws
    away the fact that the runs were interleaved: whatever wanders
    between rounds is common to both arms in the same round and cancels
    in the difference. This project has already paid for that lesson
    once - a 42% throughput gap between two firmware tracks evaporated
    when the arms were interleaved instead of run in blocks.

    `pairs` is [(a, b), ...], one per round. Returns the mean paired
    difference, its standard error, and - the part that matters - a
    plain verdict on whether the difference is resolved at all. An
    unresolved difference is reported as a *bound*, which is a real
    result and is not the same as zero.
    """
    d = [b - a for a, b in pairs if a is not None and b is not None]
    if len(d) < 2:
        return {}
    n = len(d)
    mean = sum(d) / n
    var = sum((x - mean) ** 2 for x in d) / (n - 1)
    se = math.sqrt(var / n)
    # Two standard errors: the usual convention, and stated as such
    # rather than dressed up as a p-value from n = 5.
    resolved = abs(mean) > 2.0 * se
    return {
        "n_rounds": n,
        "mean_delta": mean,
        "stdev": math.sqrt(var),
        "sem": se,
        "resolved": resolved,
        "bound": None if resolved else 2.0 * se,
        "verdict": (f"{mean:+.3f} +- {se:.3f}" if resolved
                    else f"not resolved; |delta| < {2.0*se:.3f} at 2 sem"),
    }


def alias_check(lines_a, fs_a, lines_b, fs_b, *, tol_hz=None):
    """Which lines are real and which are folded, from two sample rates.

    There is no anti-alias filter anywhere on this board, so a line seen
    once is a *candidate* and nothing more: everything the digital side
    does above Nyquist folds into the band and lands somewhere. A real
    line sits at the same frequency at both rates; an alias moves,
    because where it folds to depends on the rate it folded through.

    Returns one row per candidate with a verdict, and never names a
    source - naming is for a line that has already survived this.
    """
    tol = tol_hz if tol_hz is not None else max(fs_a, fs_b) / 4096.0
    out = []
    for la in lines_a:
        match = min(lines_b, key=lambda lb: abs(lb["hz"] - la["hz"])) \
            if lines_b else None
        d = abs(match["hz"] - la["hz"]) if match else None
        out.append({
            "hz": la["hz"],
            "amp_lsb": la["amp_lsb"],
            "matched_hz": match["hz"] if match else None,
            "delta_hz": d,
            "verdict": ("stationary" if d is not None and d <= tol
                        else "moved - alias or absent"),
        })
    out.sort(key=lambda r: -r["amp_lsb"])
    return out
