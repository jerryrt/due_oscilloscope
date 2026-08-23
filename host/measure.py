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

import fcntl
import glob
import math
import os
import re
import select
import struct
import subprocess
import sys
import termios
import threading
import time
import zlib
from array import array
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ports import find_ports, open_raw
import jitter
import rt

# ---------------------------------------------------------------------
# Wire format. Shared verbatim with drivers/frame.h.
# ---------------------------------------------------------------------

HDR_FMT = "<4sBBBBIIHHIII"
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

# The ADC labels map to channels descending: A0 is AD7, A1 is AD6.
CH_A0 = 7
CH_A1 = 6
CHANNEL_LABELS = {7: "A0", 6: "A1"}


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
    bits_per_sample: int = 0
    packing: int = 0
    n_samples: int = 0
    inconsistent: int = 0
    ts_first: int = None
    ts_last: int = None
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
        (_m, ver, flags, bits, packing, seq, rate, nsamp,
         chmask, ts, overruns, crc) = struct.unpack(HDR_FMT, hdr)
        if zlib.crc32(hdr[:HDR_LEN - 4]) & 0xFFFFFFFF != crc:
            ps.crc_bad += 1
            pos = i + 4
            continue
        need = HDR_LEN + nsamp * 2
        if blen - i < need:
            break
        body = bytes(buf[i + HDR_LEN:i + need])
        pos = i + need

        shape = (ver, bits, packing, rate, nsamp, chmask)
        if ps.frames == 0:
            ps.first_seq = seq
            ps.ts_first = ts
            keep_from = (ts + settle_us) & 0xFFFFFFFF if settle_us else None
            ps.version = ver
            ps.bits_per_sample = bits
            ps.packing = packing
            ps.n_samples = nsamp
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

    def device_byte_rate(self):
        """Bytes per second the converter actually consumed, timed by
        the device's own clock. Repeated buffers are excluded, because
        an underrun consumes time and not data."""
        if not self.run_us or not self.consumed:
            return None
        return self.consumed * 1024 / (self.run_us / 1e6)

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


_OCC = re.compile(r"play_occ min=(\d+) endtx=(\d+) runus=(\d+) consumed=(\d+) hist=([\d,]+)")
_OCC_TRACE = re.compile(r"play_occ_trace decim=(\d+) n=(\d+) v=([\d,]*)")


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
    return got


def parse_play(text):
    return PlayCounters(_counters(text, "play:"))


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
        self.cfd = open_raw(control, 115200)
        self._console = b""
        if settle:
            time.sleep(settle)

    # -- control port ------------------------------------------------
    def cmd(self, text):
        os.write(self.cfd, text.encode() if isinstance(text, str) else text)

    def poll_console(self):
        """Non-blocking drain; returns whatever was waiting."""
        got = b""
        while True:
            r, _, _ = select.select([self.cfd], [], [], 0)
            if not r:
                break
            try:
                d = os.read(self.cfd, 65536)
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
            r, _, _ = select.select([self.cfd], [], [], 0.05)
            if r:
                try:
                    d = os.read(self.cfd, 65536)
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
    def open_native(self, wait=12.0, dtr=True, blocking_writes=False,
                    notify=None):
        """Re-glob and open the native node.

        Its name changes whenever the board resets, so it is discovered
        every time rather than remembered.
        """
        fd = None
        give_up = time.time() + wait
        while fd is None:
            cands = [n for n in sorted(glob.glob("/dev/cu.usbmodem*"))
                     if n != self.control]
            try:
                if cands:
                    fd = open_raw(cands[0], 115200, dtr=dtr)
                    if notify:
                        notify("native", path=cands[0],
                               changed=cands[0] != self.native)
                    self.native = cands[0]
            except OSError:
                fd = None
            if fd is None:
                if time.time() >= give_up:
                    raise BoardError("native port did not enumerate")
                time.sleep(0.5)
        if blocking_writes:
            # Without this a full queue raises EAGAIN and a naive writer
            # dies silently. VMIN=0 keeps reads non-blocking, so this
            # affects only the write side.
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)
        return fd

    def close_native(self, fd):
        # '0' stops the device draining bulk OUT, so bytes still in the
        # kernel's output queue can never leave - and close() on a tty
        # drains that queue first. Without the flush the process hangs
        # in close() forever, holding the port and leaving the board
        # streaming into the void for the next run to trip over.
        try:
            termios.tcflush(fd, termios.TCIOFLUSH)
        except (OSError, termios.error):
            # termios.error is not an OSError - it derives straight from
            # Exception - so `except OSError` never caught it, and a port
            # that had gone away (ENXIO) aborted the whole measurement
            # from inside the cleanup.
            pass
        os.close(fd)

    def close(self):
        if self.cfd is not None:
            os.close(self.cfd)
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
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try:
                n = len(os.read(fd, 65536))
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
        self.write_size = write_size
        self.count = 0
        self.note = None
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
        while not self._stop.is_set():
            now = time.monotonic()
            due = (int((now - t0) * self.byte_rate)
                   + self.LEAD - self.count)
            if due <= 0:
                time.sleep(min(0.005, -due / self.byte_rate + 0.001))
                continue
            # Whole 512-byte packets only: a short packet fragments the
            # device's stream DMA span, and on older firmware ended it.
            if self.write_size:
                if due < self.write_size:
                    time.sleep(0.0005)
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
                n = os.write(self.fd, block)
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

    def stop(self):
        # The device keeps consuming until the stream is stopped, so a
        # final blocking write completes on its own; the flush is only a
        # backstop against a writer wedged on a queue nobody drains.
        self._stop.set()
        t0 = time.monotonic()
        self._th.join(2.0)
        if self._th.is_alive():
            self.flushed = True
            termios.tcflush(self.fd, termios.TCOFLUSH)
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
        if self.stream.first_seq > 10:
            return False
        span = self.stream.dev_span_s
        want = host_seconds if host_seconds is not None else self.elapsed_s
        return span >= 0.5 * want


def run_loop(board, *, dac_sps=200000, adc_hz=200000, channels=2,
             tone=1000.0, seconds=3.0, dc=None, ramp=None, diag=False,
             drain=True, notify=None, scale=1.0):
    """The complete loop: HOST -> USB -> DAC -> wire -> ADC -> USB -> HOST.

    Because the host authored the signal, any discrepancy in what comes
    back is a fault in the path rather than an unknown property of a
    signal.
    """
    if ramp is not None:
        wave, tone_hz = build_ramp(step=ramp)
    elif dc is not None:
        wave, tone_hz = build_dc(dc)
    else:
        wave, tone_hz = build_waveform(tone, dac_sps)

    fd = board.open_native(blocking_writes=True, notify=notify)
    stale = drain_until_quiet(fd) if drain else 0
    if stale and notify:
        notify("stale", bytes=stale)

    board.poll_console()
    board.cmd(f"={dac_sps},{adc_hz},{channels}L")
    time.sleep(0.2)

    feeder = Feeder(fd, wave, dac_sps * 2, scale=scale)
    feeder.start()

    chunks = []
    console = b""
    diag_sent = False
    t0 = time.time()
    while time.time() - t0 < seconds:
        # The diagnostic must sample while both directions are live, so
        # it is triggered mid-run rather than before or after.
        if diag and not diag_sent and time.time() - t0 > 1.5:
            board.cmd("D")
            diag_sent = True
        r, _, _ = select.select([fd, board.cfd], [], [], 0.05)
        if board.cfd in r:
            try:
                console += os.read(board.cfd, 65536)
            except OSError:
                pass
        if fd in r:
            try:
                chunks.append(os.read(fd, 262144))
            except OSError:
                pass
    elapsed = time.time() - t0

    tx = feeder.stop()

    board.cmd("B")
    time.sleep(0.5)
    report = b""
    end = time.time() + 1.5
    while time.time() < end:
        r, _, _ = select.select([fd, board.cfd], [], [], 0.1)
        for f in r:
            try:
                d = os.read(f, 65536)
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
        rt_note=feeder.note, stale_bytes=stale)


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


def run_play(board, *, dac_sps, tone=1000.0, seconds=3.0, dc=None,
             scale=1.0, drain_s=0.0, write_size=None):
    if dc is not None:
        wave, tone_hz = build_dc(dc)
    else:
        wave, tone_hz = build_waveform(tone, dac_sps)

    fd = board.open_native(blocking_writes=True)
    drain_until_quiet(fd, quiet=0.3, cap=3.0)
    board.poll_console()
    board.cmd(f"={dac_sps}P")
    time.sleep(0.2)
    console = board.drain_console(0.3)

    feeder = Feeder(fd, wave, dac_sps * 2, scale=scale,
                    write_size=write_size)
    feeder.start()
    t0 = time.time()
    end = t0 + seconds
    while time.time() < end:
        r, _, _ = select.select([fd, board.cfd], [], [], 0.05)
        if fd in r:
            try:
                os.read(fd, 262144)
            except OSError:
                pass
        if board.cfd in r:
            try:
                console += os.read(board.cfd, 65536).decode("utf-8", "replace")
            except OSError:
                pass
    elapsed = time.time() - t0
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
        board.cmd("B")
        time.sleep(0.5)
        run_play_counters = parse_play(board.drain_console(1.2))
        end = time.time() + drain_s
        while time.time() < end:
            r, _, _ = select.select([fd, board.cfd], [], [], 0.05)
            if fd in r:
                try:
                    os.read(fd, 262144)
                except OSError:
                    pass
        board.cmd("B")
        time.sleep(0.5)
        report = board.drain_console(1.2)
        drained_play = parse_play(report)

    # Stop the device before reading its counters. Playback keeps
    # running after the feeder stops, so counters read afterwards
    # include the underruns of the shutdown rather than the run - which
    # is measuring the wrong thing and reads as a fault in the feed.
    board.cmd("0")
    time.sleep(0.2)
    board.cmd("B")
    time.sleep(0.4)
    # The occupancy histogram is read after the stop, but it describes
    # the run: the device accumulated it at every ENDTX while playing.
    board.cmd("O")
    time.sleep(0.3)
    report = board.drain_console(1.2)
    board.close_native(fd)

    play = parse_play(report)
    occ = parse_occ(report)
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
        occ = OccHist()

    return PlayResult(elapsed_s=elapsed, host_tx_bytes=tx, dac_sps=dac_sps,
                      tone_hz=tone_hz, refused="refused" in console,
                      console=console, report=report,
                      play=play, rt_note=feeder.note,
                      occ=occ, drained=drain_s > 0.0)


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
            termios.tcflush(fd, termios.TCIFLUSH)
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
            r, _, _ = select.select(watch, [], [], 0.2)
            if not uart and board.cfd in r:
                try:
                    console += os.read(board.cfd, 65536)
                except OSError:
                    pass
            if fd in r:
                try:
                    chunk = os.read(fd, 262144)
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

    want_rx = property(lambda s: s.mode in BENCH_RX)
    want_tx = property(lambda s: s.mode in BENCH_TX)
    rx_mbs = property(lambda s: s.host_rx_bytes / s.elapsed_s / 1e6
                      if s.elapsed_s else 0.0)
    tx_mbs = property(lambda s: s.host_tx_bytes / s.elapsed_s / 1e6
                      if s.elapsed_s else 0.0)


def run_bench(board, *, mode, seconds=5.0, block=16384):
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
    termios.tcflush(fd, termios.TCIFLUSH)

    # One thread per direction, and blocking writes. An earlier loop
    # interleaved reads and writes on one thread behind a select()
    # timeout, so each direction stalled while the other's syscall ran -
    # a ceiling made by the host's scheduling, not by the transport.
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)

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
            r, _, _ = select.select([fd], [], [], 0.05)
            if r:
                try:
                    rx_n[0] += len(os.read(fd, 262144))
                except OSError:
                    return

    def writer():
        notes["writer"] = rt.promote(period_ms=5.0, computation_ms=0.5,
                                     constraint_ms=2.5)
        while not stop.is_set():
            try:
                tx_n[0] += os.write(fd, payload)
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
    if any(th.is_alive() for th in threads):
        # A writer wedged on a queue the device stopped draining.
        termios.tcflush(fd, termios.TCOFLUSH)
        for th in threads:
            th.join(1.0)

    time.sleep(0.3)
    board.cmd("B")
    time.sleep(0.6)
    report = b""
    t1 = time.time()
    while time.time() - t1 < 1.5:
        # Keep draining so a blocked device can still answer.
        r, _, _ = select.select([fd, board.cfd], [], [], 0.1)
        for f in r:
            try:
                d = os.read(f, 262144)
                if f == board.cfd:
                    report += d
            except OSError:
                pass
    board.cmd("0")
    board.close_native(fd)

    rep = report.decode("utf-8", "replace")
    return BenchResult(mode=mode, block=block, elapsed_s=elapsed,
                       host_rx_bytes=rx_n[0], host_tx_bytes=tx_n[0],
                       device=parse_bench(rep), report=rep, rt_notes=notes)


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


def which_track(board, *, secs=1.5):
    """Which firmware is actually on the board, from its own banner.

    Asked rather than assumed: flashing is the slowest thing the suite
    does, and a stale image is the failure that looks like a firmware
    regression.
    """
    text = board.banner() if secs is None else board.ask("h", secs=secs)
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
    """cmake and arduino-cli live in ~/.local/bin, which is on the
    interactive PATH but not necessarily on pytest's."""
    env = dict(os.environ)
    local = os.path.expanduser("~/.local/bin")
    if local not in env.get("PATH", "").split(":"):
        env["PATH"] = local + ":" + env.get("PATH", "")
    return env


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
                if build:
                    subprocess.run(["cmake", "--build", "build", "-j"],
                                   cwd=REPO, check=True, env=_tool_env(),
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
                cmd = [os.path.join(REPO, "tools", "flash.sh"),
                       os.path.join(REPO, "build", "baremetal_bringup.bin")]
                if control:
                    cmd.append(control)
            elif track == "a":
                sketch = os.path.join(REPO, "sketches", "bringup")
                if build:
                    subprocess.run(
                        ["arduino-cli", "compile", "--fqbn",
                         "arduino:sam:arduino_due_x_dbg",
                         "--build-property", "build.f_cpu=78000000L", sketch],
                        cwd=REPO, check=True, env=_tool_env(),
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                cmd = ["arduino-cli", "upload", "--fqbn",
                       "arduino:sam:arduino_due_x_dbg", "-p", control, sketch]
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
