"""Frames to something drawable, with no Qt in sight.

Three jobs, kept away from the widgets so they can be tested without a
display: decode a device frame into per-channel samples, hold a rolling
window of them, and reduce that window to what a plot can actually
show.

The reduction is the interesting one. At the full rate the device sends
about 907,000 samples a second and a plot is two thousand pixels wide,
so nothing here draws samples one for one: each pixel column becomes
the minimum and maximum of the samples that fall in it, which is what a
real DSO draws and the only honest way to show a signal wider than the
screen. Drawing every Nth sample instead would hide exactly the glitch
this project exists to find.
"""

from __future__ import annotations

import struct

import numpy as np

HDR_FMT = "<4sBBHIIIIII"
HDR_LEN = struct.calcsize(HDR_FMT)
MAGIC = b"DUE0"

FLAG_OVERRUN = 1 << 0

# ADC labels map descending: A0 is channel 7, A1 is channel 6.
LABELS = {7: "A0", 6: "A1"}

FULL_SCALE_CODES = 4095


def _advref_mv():
    """ADVREF as the scope measured it, not a nominal 3300.

    The DAC->ADC loop is ratiometric - the DAC's reference *is* the
    ADC's, Table 46-39's note - so the board cannot measure its own
    reference and 3300 was an assumption sitting where a measurement
    belongs. An external instrument settled it at 3270 mV by two routes
    agreeing to 0.1 mV; `tests/baseline.json` holds the result and
    `host/receive.py` reads it the same way.

    Every volt this window draws came from an ADC code, so the axis, the
    cursors and the trigger level were all 0.91% high until this.

    Falls back to the old assumption if the file is unreadable, because
    a display is not worth refusing to start over - and says so in
    ADVREF_SOURCE, so a reading can be attributed rather than guessed
    at.
    """
    import json
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tests", "baseline.json")
    try:
        with open(path) as f:
            return int(json.load(f)["adc_transfer"]["advref_mv"]), "measured"
    except Exception:                                    # noqa: BLE001
        return 3300, "assumed (baseline.json unreadable)"


ADVREF_MV, ADVREF_SOURCE = _advref_mv()
VREF_V = ADVREF_MV / 1000.0


class Frame:
    """One decoded frame. Samples stay as codes; volts are a view."""

    __slots__ = ("seq", "rate_hz", "n_samples", "mask", "timestamp_us",
                 "overrun_count", "flags", "channels")

    def __init__(self, seq, rate_hz, n_samples, mask, timestamp_us,
                 overrun_count, flags, channels):
        self.seq = seq
        self.rate_hz = rate_hz
        self.n_samples = n_samples
        self.mask = mask
        self.timestamp_us = timestamp_us
        self.overrun_count = overrun_count
        self.flags = flags
        self.channels = channels          # {tag: np.ndarray of codes}

    @property
    def discontinuous(self):
        """This frame is not continuous with the one before it."""
        return bool(self.flags & FLAG_OVERRUN)


def decode(buf):
    """Decode one frame. Returns None if it is not one.

    The tag rides in bits 15..12 of every sample, which is what makes
    demultiplexing a mask rather than an assumption about ordering.
    """
    if len(buf) < HDR_LEN or not buf.startswith(MAGIC):
        return None
    (_magic, _version, flags, mask, seq, rate, ts,
     overrun, _consumed, _crc) = struct.unpack_from(HDR_FMT, buf, 0)
    n = (len(buf) - HDR_LEN) // 2

    raw = np.frombuffer(buf, dtype="<u2", offset=HDR_LEN)
    tags = (raw >> 12).astype(np.uint8)
    codes = (raw & 0x0FFF).astype(np.uint16)

    channels = {}
    for tag in np.unique(tags):
        channels[int(tag)] = codes[tags == tag]
    return Frame(seq, rate, n, mask, ts, overrun, flags, channels)


def codes_to_volts(codes):
    return np.asarray(codes, dtype=np.float32) * (VREF_V / (FULL_SCALE_CODES + 1))


def volts_to_codes(volts):
    """The inverse, for controls that are entered in volts.

    One conversion, both directions, in the place that already owns it.
    A trigger level typed in volts and compared against codes elsewhere
    would be a second scale factor, and this project has already paid
    twice for one number living in two places.
    """
    return int(round(float(volts) / (VREF_V / (FULL_SCALE_CODES + 1))))


class ChannelRing:
    """A rolling window of one channel's samples.

    Sized in seconds rather than samples, because a ring sized in bytes
    silently becomes a fraction of a screen when the rate goes up - the
    same mistake the daemon's record buffer avoids for the same reason.
    """

    def __init__(self, seconds=2.0, rate_hz=200000):
        self.seconds = seconds
        self.rate_hz = max(1, rate_hz)
        self._buf = np.zeros(self._want(), dtype=np.uint16)
        self._breaks = np.zeros(self._want(), dtype=bool)
        # Write position and total are tracked separately. Deriving the
        # position from the total works right up until one append is
        # larger than the ring, and then the two disagree and the window
        # silently returns samples that are not the newest.
        self._pos = 0
        self._total = 0
        self.discontinuities = 0

    def _want(self):
        return max(1024, int(self.seconds * self.rate_hz))

    def set_rate(self, rate_hz):
        """Resize on a rate change, keeping the window in seconds."""
        rate_hz = max(1, int(rate_hz))
        if rate_hz == self.rate_hz:
            return
        self.rate_hz = rate_hz
        self._buf = np.zeros(self._want(), dtype=np.uint16)
        self._breaks = np.zeros(self._want(), dtype=bool)
        self._pos = 0
        self._total = 0

    def append(self, samples, discontinuous=False):
        cap = len(self._buf)
        k = len(samples)
        if k == 0:
            return
        if k >= cap:
            self._buf[:] = samples[-cap:]
            self._breaks[:] = False
            self._breaks[0] = discontinuous
            self._pos = 0
            self._total += k
            if discontinuous:
                self.discontinuities += 1
            return
        pos = self._pos
        end = pos + k
        if end <= cap:
            self._buf[pos:end] = samples
            self._breaks[pos:end] = False
            if discontinuous:
                self._breaks[pos] = True
        else:
            first = cap - pos
            self._buf[pos:] = samples[:first]
            self._buf[:end - cap] = samples[first:]
            self._breaks[pos:] = False
            self._breaks[:end - cap] = False
            if discontinuous:
                self._breaks[pos] = True
        self._pos = end % cap
        self._total += k
        if discontinuous:
            self.discontinuities += 1

    @property
    def filled(self):
        return min(self._total, len(self._buf))

    def window(self, n=None):
        """The most recent `n` samples, oldest first, with the
        discontinuity flags that go with them."""
        cap = len(self._buf)
        have = self.filled
        n = have if n is None else min(n, have)
        if n == 0:
            return (np.empty(0, dtype=np.uint16),
                    np.empty(0, dtype=bool))
        end = self._pos
        start = (end - n) % cap
        if start < end:
            return self._buf[start:end], self._breaks[start:end]
        return (np.concatenate((self._buf[start:], self._buf[:end])),
                np.concatenate((self._breaks[start:], self._breaks[:end])))


#: How far back select() looks for a trigger, in screenfuls. Four
#: is enough that a slow repetition still finds an edge and small
#: enough that the search stays inside the frame budget.
SEARCH_SPAN = 4

#: Below this peak-to-peak, midpoint crossings are noise rather than
#: the waveform and any frequency from them is invented. Ten codes is
#: about 5 mV, comfortably above the ~1-2 codes a quiet channel shows
#: and far below any signal worth timing.
MEASURE_MIN_SWING_CODES = 10


class Sweep:
    """One screenful, and where it came from.

    `triggered` is the part that matters later: a free-running sweep and
    a triggered one look identical as arrays, and the UI has to be able
    to say which it is drawing. A scope that silently free-runs when it
    cannot find an edge, without saying so, is how a shaking trace gets
    blamed on the signal - which has happened on this bench already, to
    a different instrument (`docs/awg.md`).
    """

    __slots__ = ("samples", "breaks", "triggered", "trigger_index")

    def __init__(self, samples, breaks, triggered=False, trigger_index=None):
        self.samples = samples
        self.breaks = breaks
        self.triggered = triggered
        self.trigger_index = trigger_index

    @property
    def empty(self):
        return self.samples.size == 0


class Trigger:
    """An edge trigger: where the sweep starts, instead of "wherever".

    Software, on samples already captured. Deliberately not an external
    trigger input - `docs/frontend.md` keeps anything that reads as
    "connect your signal here" disabled until the Phase 3 analog front
    end exists, and says in as many words that a warning label is not
    sufficient. Nothing here touches a pin.

    `level` is in ADC codes, the units the ring holds. Converting at the
    edge of the UI rather than here keeps this testable against integers
    and keeps one conversion, `codes_to_volts`, in one place.

    There is no holdoff knob. It would do nothing yet - the search takes
    the most recent qualifying edge, so a minimum spacing between
    consecutive accepted edges has nothing to reject - and this project
    has a name for that: a knob that is programmed is not a knob that
    does anything. It arrives when something needs it.
    """

    __slots__ = ("level", "rising", "mode", "pretrigger")

    #: How far into the screen the trigger point sits. Half is the
    #: convention and it is the useful one: it shows what led into the
    #: edge, which is most of why anyone triggers.
    def __init__(self, level, rising=True, mode="auto", pretrigger=0.5):
        self.level = int(level)
        self.rising = bool(rising)
        self.mode = mode
        self.pretrigger = float(pretrigger)


def find_edges(samples, level, rising=True, breaks=None):
    """Indices where the signal crosses `level` in the given direction.

    The crossing is reported at the first sample *at or past* the level,
    so `samples[i-1]` is on one side and `samples[i]` on the other.

    A crossing is rejected when `breaks[i]` is set. That sample begins a
    new run - a frame the device flagged as discontinuous with the one
    before it - so the step from `samples[i-1]` to `samples[i]` is not a
    transition the signal made. Invariant 5 forbids presenting
    discontinuous data as continuous, and triggering on a splice would
    be exactly that, with the added insult of holding the trace still
    and making it look right.
    """
    if samples.size < 2:
        return np.empty(0, dtype=np.int64)
    v = samples.astype(np.int32)
    if rising:
        cross = (v[:-1] < level) & (v[1:] >= level)
    else:
        cross = (v[:-1] > level) & (v[1:] <= level)
    idx = np.flatnonzero(cross) + 1
    if breaks is not None and idx.size:
        idx = idx[~breaks[idx]]
    return idx


def select(ring, n, trig=None):
    """Which `n` samples to draw.

    The whole "what goes on screen" decision, in one Qt-free place.

    It lived inside ScopeView.draw as `ring.window(n)` - the most recent
    n samples, every 33 ms, with nothing anchoring them. That is why a
    trace holds still only when the tone's period happens to divide the
    window, which CLAUDE.md records as a missing front-end feature that
    must not be confused with the signal defects around it.

    With a trigger, the sweep is anchored to the most recent edge that
    has a whole screen either side of it. Without one, or in `auto` when
    no edge is found, it is the most recent n - and `Sweep.triggered`
    says which happened, because the two are indistinguishable as
    arrays.

    Bounded on purpose. The ring holds up to two seconds, which is 1.8 M
    samples at the full rate, and this runs inside a 33 ms frame budget
    that rule 5 says must never block the feeder. The search looks at
    the newest `SEARCH_SPAN` windows and no further; an edge older than
    that is off the back of a display that redraws 30 times a second.
    """
    if trig is None:
        samples, breaks = ring.window(n)
        return Sweep(samples, breaks, triggered=False, trigger_index=None)

    span = min(ring.filled, int(n * SEARCH_SPAN))
    samples, breaks = ring.window(span)

    pre = int(round(trig.pretrigger * n))
    pre = max(0, min(n, pre))
    post = n - pre

    free = Sweep(*ring.window(n), triggered=False, trigger_index=None)
    if samples.size < n:
        return free

    idx = find_edges(samples, trig.level, trig.rising, breaks)
    # Only edges with a whole screen either side of them: a trigger at
    # the very edge of what has been captured would draw a half screen
    # that grows as more arrives, which reads as drift.
    idx = idx[(idx >= pre) & (idx + post <= samples.size)]
    if idx.size == 0:
        return free if trig.mode == "auto" else Sweep(
            np.empty(0, dtype=samples.dtype), np.empty(0, dtype=bool),
            triggered=False, trigger_index=None)

    t = int(idx[-1])                       # the most recent qualifying edge
    a, b = t - pre, t + post
    return Sweep(samples[a:b], breaks[a:b], triggered=True, trigger_index=pre)


def measure(sweep, rate_hz):
    """Automatic measurements over the sweep on screen.

    Every value is either a number or None with a reason, never a
    plausible-looking figure. "Do not invent numbers" is a rule in
    CLAUDE.md because a guessed value that later reads as established
    fact is the most expensive error this project makes.

    **A window containing a discontinuity measures nothing.** An
    overrun-flagged frame is not continuous with the one before it, so
    the largest excursion may span two unrelated moments and the
    interval between crossings is not a period. Invariant 5 forbids
    presenting discontinuous data as continuous; a number carries that
    lie further than a plot does, because the plot at least shows the
    break.

    **There is deliberately no rise or fall time.** The DAC's step was
    measured with a scope at 789-938 ns (`docs/awg.md`), and this ADC's
    sample interval is 1.1 us at its very fastest and 5 us at 200 ksps.
    A 10-90% time computed from these samples would be one sample wide
    at best - it would be reporting the sampling interval and calling it
    the converter's edge. The instrument that can measure it is the one
    on the bench, and it already has.
    """
    out = {"vpp_v": None, "mean_v": None, "rms_v": None,
           "freq_hz": None, "period_s": None, "duty": None, "note": None}
    if sweep.empty:
        out["note"] = "no data"
        return out
    if sweep.breaks is not None and bool(sweep.breaks.any()):
        out["note"] = "discontinuity in window"
        return out

    v = np.asarray(codes_to_volts(sweep.samples), dtype=np.float64)
    out["vpp_v"] = float(v.max() - v.min())
    out["mean_v"] = float(v.mean())
    out["rms_v"] = float(np.sqrt(np.mean(v * v)))

    # Frequency from the signal's own midpoint rather than the trigger
    # level: the trigger may sit anywhere on the waveform, and a level
    # near a peak crosses twice per period in one place and not at all
    # in another. The midpoint is where a symmetric wave crosses once
    # per period going up.
    codes = sweep.samples.astype(np.int32)
    mid = int((int(codes.max()) + int(codes.min())) // 2)
    if codes.max() - codes.min() < MEASURE_MIN_SWING_CODES:
        out["note"] = "signal too flat to time"
        return out

    ups = find_edges(sweep.samples, mid, rising=True)
    if ups.size < 2:
        out["note"] = "fewer than two crossings in window"
        return out

    # The mean interval over the whole window rather than one period:
    # averaging N intervals divides the one-sample edge uncertainty by
    # N, which is the same reason a frequency counter gates over many
    # cycles instead of timing one.
    period_samples = float(ups[-1] - ups[0]) / float(ups.size - 1)
    if period_samples <= 0 or rate_hz <= 0:
        out["note"] = "rate unknown"
        return out
    out["period_s"] = period_samples / float(rate_hz)
    out["freq_hz"] = float(rate_hz) / period_samples
    out["duty"] = float(np.count_nonzero(codes > mid)) / float(codes.size)
    return out


#: FFT windows. Rectangular is included and is not a default: it is the
#: right answer only when the window holds a whole number of cycles, and
#: the wrong one everywhere else, where it smears a tone across the
#: whole spectrum. Hann is the usable default.
FFT_WINDOWS = ("hann", "hamming", "blackman", "rectangular")

#: The most points the transform runs on. The ring holds two seconds -
#: 1.8 M samples at the full rate - and an FFT that size inside a 33 ms
#: redraw would block the feeder, which rule 5 forbids. 16384 bins put
#: about 55 Hz per bin at 907 ksps and cost well under a millisecond.
FFT_MAX_POINTS = 16384


def spectrum(sweep, rate_hz, window="hann"):
    """The sweep's spectrum, in dB relative to a full-scale sine.

    Returns (freqs_hz, db) or (None, None) with the reason as the third
    element. Same rule as `measure`: a refusal with a reason, never a
    plausible-looking curve.

    Refuses on a discontinuity for a sharper reason than the time
    domain's. A splice is a step, a step is broadband, and the transform
    will happily draw that step's energy spread across every frequency
    on the screen - which looks like a noise floor rather than like the
    missing data it is.

    dB is relative to a full-scale sine rather than to the largest bin,
    so two captures can be compared. Normalised by the window's own sum
    so the amplitude a tone reports does not change with the window
    chosen - only its leakage does, which is the whole reason for
    choosing one.
    """
    if sweep.empty:
        return None, None, "no data"
    if sweep.breaks is not None and bool(sweep.breaks.any()):
        return None, None, "discontinuity in window"
    if rate_hz <= 0:
        return None, None, "rate unknown"

    x = sweep.samples
    if x.size > FFT_MAX_POINTS:
        x = x[-FFT_MAX_POINTS:]           # the most recent, not the oldest
    n = int(x.size)
    if n < 16:
        return None, None, "window too short to transform"

    v = x.astype(np.float64)
    v -= v.mean()                          # DC would swamp bin 0 and nothing else

    if window == "hann":
        w = np.hanning(n)
    elif window == "hamming":
        w = np.hamming(n)
    elif window == "blackman":
        w = np.blackman(n)
    else:
        w = np.ones(n)

    mag = np.abs(np.fft.rfft(v * w))
    # Amplitude in codes: two for the half spectrum, divided by the
    # window's coherent gain so a tone reads the same whichever window
    # is chosen.
    amp = 2.0 * mag / max(float(w.sum()), 1.0)
    full = (FULL_SCALE_CODES + 1) / 2.0
    db = 20.0 * np.log10(np.maximum(amp, 1e-9) / full)
    freqs = np.fft.rfftfreq(n, d=1.0 / float(rate_hz))
    return freqs, db, None


def minmax(samples, columns, breaks=None):
    """Reduce samples to one min/max pair per pixel column.

    Returns (x, y) ready to plot as a single polyline: each column
    contributes its minimum then its maximum, so the line covers the
    signal's excursion in that column rather than a sample that happened
    to land there.

    A column containing a discontinuity gets a NaN, which breaks the
    line instead of drawing across the gap. Invariant 5 says never
    present discontinuous data as continuous, and a plot is exactly
    where that lie would be believed.
    """
    n = len(samples)
    if n == 0 or columns <= 0:
        return np.empty(0), np.empty(0)
    columns = int(min(columns, n))
    edges = np.linspace(0, n, columns + 1).astype(np.int64)

    x = np.empty(columns * 2, dtype=np.float64)
    y = np.empty(columns * 2, dtype=np.float64)
    vals = samples.astype(np.float64)
    for i in range(columns):
        a, b = edges[i], edges[i + 1]
        if b <= a:
            b = a + 1
        chunk = vals[a:b]
        lo, hi = chunk.min(), chunk.max()
        if breaks is not None and breaks[a:b].any():
            lo = hi = np.nan
        x[2 * i] = x[2 * i + 1] = a
        y[2 * i] = lo
        y[2 * i + 1] = hi
    return x, y
