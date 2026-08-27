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
VREF_V = 3.3


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


def select(ring, n):
    """Which `n` samples to draw.

    The whole "what goes on screen" decision, in one Qt-free place.

    It lived inside ScopeView.draw as `ring.window(n)` - the most recent
    n samples, every 33 ms, with nothing anchoring them. That is why a
    trace holds still only when the tone's period happens to divide the
    window, which CLAUDE.md records as a missing front-end feature that
    must not be confused with the signal defects around it.

    Extracting it changes nothing yet: this is still the most recent n.
    What it buys is somewhere for a trigger to live that a headless test
    can reach without a display.
    """
    samples, breaks = ring.window(n)
    return Sweep(samples, breaks, triggered=False, trigger_index=None)


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
