"""What the daemon needs from a device, and two things that provide it.

The interface exists so the API can be tested without a board. That is
not a retreat from this project's "no simulator, no mock" rule for the
hardware suite - `tests/` still talks to real hardware for everything
about signals, timing and transport. What is being tested here is the
*API*: framing, ownership, backpressure, refusals, recording. None of
that is a property of the Due, and tying it to a board would mean the
protocol could only be exercised at a bench.

`BoardDevice` is the real one. `FakeDevice` produces frames in the
device's own format - same header, same CRC, same sequence numbers - so
a client cannot tell them apart at the wire and the daemon's own
parsing gets exercised too.
"""

from __future__ import annotations

import os
import select
import struct
import threading
import time
import zlib

# Frame layout, shared verbatim with drivers/frame.h and host/measure.py.
HDR_FMT = "<4sBBHIIIIII"
HDR_LEN = struct.calcsize(HDR_FMT)
FRAME_MAGIC = b"DUE0"
FRAME_SAMPLES = 2032
FRAME_BYTES = HDR_LEN + FRAME_SAMPLES * 2

FLAG_CONTINUOUS = 1 << 3

MODES = ("capture", "play", "loop")


class DeviceError(RuntimeError):
    """The device refused, or is not in a state that allows this."""


class Device:
    """The surface the server uses. Implementations must be safe to call
    from the server's reader thread and its client threads at once."""

    def describe(self):
        raise NotImplementedError

    def start(self, mode, *, dac_sps=None, adc_hz=None, channels=2,
              waveform=None, preset=None):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def read(self, timeout=0.2):
        """Bytes from the sample stream, or b'' if none arrived."""
        raise NotImplementedError

    def console(self):
        """Whatever the device has said since the last call."""
        return ""

    def counters(self):
        """Counters from the device. May cost a console round trip, so
        it is never called on a status poll - see `stats`."""
        return {}

    def trace(self):
        """The playback ring's occupancy and the converter's own rate.

        A separate call from `counters` because it is a different device
        command and a much longer reply - two lines of up to 256 values
        each - so it costs more than a poll path can afford. Like
        `counters`, never dragged in by `status`.
        """
        return {}

    def stats(self):
        """What the host knows without asking the device anything.

        The distinction is not tidiness. Asking the board for its banner
        while it is playing costs eleven underruns, every run, because
        the console print holds up the main loop while the DAC drains
        its ring. Anything on a poll path must be answerable from here.
        """
        return {}

    def close(self):
        pass

    # State every implementation shares, so the server can report it.
    running = False
    mode = None
    rates = None


class FakeDevice(Device):
    """A synthetic device that produces real frames.

    Deterministic by construction: the same start() gives the same
    bytes, so a test can assert on them. `pace=False` produces frames as
    fast as they are read, which is what makes the API tests quick;
    `pace=True` produces them at the rate the frame header claims, for
    testing backpressure and drop policy against something like real
    timing.
    """

    def __init__(self, *, pace=False, track="fake", amplitude=1300,
                 tone_hz=1000.0):
        self.pace = pace
        self.track = track
        self.amplitude = amplitude
        self.tone_hz = tone_hz
        self._lock = threading.Lock()
        self._seq = 0
        self._t0 = 0.0
        self._phase = 0.0
        self._sent_frames = 0
        self._awg_bytes = 0
        self._console = []
        self.running = False
        self.mode = None
        self.rates = None
        self.closed = False

    # -- control -----------------------------------------------------
    def describe(self):
        return {"track": self.track, "kind": "fake",
                "frame_bytes": FRAME_BYTES, "samples_per_frame": FRAME_SAMPLES}

    def start(self, mode, *, dac_sps=None, adc_hz=None, channels=2,
              waveform=None, preset=None):
        if self.closed:
            raise DeviceError("device is closed")
        if mode not in MODES:
            raise DeviceError(f"unknown mode {mode!r}")
        if self.running:
            # The same refusal the board gives. A fake that is more
            # permissive than the device it stands in for is worse than
            # no fake at all: it makes the API tests pass on behaviour
            # the hardware will not accept.
            raise DeviceError("already running; stop first")
        with self._lock:
            self.running = True
            self.mode = mode
            self.rates = {"dac_sps": dac_sps, "adc_hz": adc_hz,
                          "channels": channels, "preset": preset}
            self._seq = 0
            self._t0 = time.monotonic()
            self._phase = 0.0
            self._console.append(f"started {mode}\n")

    def stop(self):
        with self._lock:
            self.running = False
            self.mode = None
            self._console.append("stopped\n")

    def close(self):
        self.stop()
        self.closed = True

    # -- stream ------------------------------------------------------
    def read(self, timeout=0.2):
        with self._lock:
            if not self.running or self.mode == "play":
                # Play-only produces no capture stream, exactly as the
                # device does not.
                if timeout:
                    time.sleep(min(timeout, 0.01))
                return b""
            rate = self.rates.get("adc_hz") or 200000
            channels = self.rates.get("channels") or 2
            if self.pace:
                per_frame = FRAME_SAMPLES / float(rate * channels)
                due = self._t0 + (self._seq + 1) * per_frame
                wait = due - time.monotonic()
                if wait > 0:
                    if wait > timeout:
                        time.sleep(timeout)
                        return b""
                    time.sleep(wait)
            frame = self._make_frame(rate, channels)
            self._sent_frames += 1
            return frame

    def _make_frame(self, rate, channels):
        import math
        seq = self._seq
        self._seq += 1
        ts = int(seq * FRAME_SAMPLES * 1e6 / (rate * channels))
        mask = 0
        tags = [7, 6][:channels]
        for t in tags:
            mask |= 1 << t
        body = bytearray()
        step = 2.0 * math.pi * self.tone_hz / rate
        for i in range(FRAME_SAMPLES // channels):
            v = int(2048 + self.amplitude * math.sin(self._phase))
            self._phase += step
            for t in tags:
                # 12-bit right aligned, tag in the top nibble, exactly as
                # the ADC delivers it with TAG enabled.
                body += struct.pack("<H", (t << 12) | (v & 0xFFF))
        hdr = struct.pack(HDR_FMT, FRAME_MAGIC, 3, FLAG_CONTINUOUS, mask,
                          seq, rate, ts, 0, 0, 0)
        crc = zlib.crc32(hdr[:HDR_LEN - 4]) & 0xFFFFFFFF
        hdr = hdr[:HDR_LEN - 4] + struct.pack("<I", crc)
        return bytes(hdr) + bytes(body)

    def write_awg(self, data):
        with self._lock:
            self._awg_bytes += len(data)
            return len(data)

    def console(self):
        with self._lock:
            out = "".join(self._console)
            self._console = []
            return out

    def counters(self):
        with self._lock:
            return {"frames": self._sent_frames, "awg_bytes": self._awg_bytes,
                    "underruns": 0, "overruns": 0, "seq_gaps": 0}

    def trace(self):
        """A structurally real trace: a converter holding one exact rate.

        Deterministic like the rest of this device, so a client can be
        built and tested against the shape of the reply without a board.
        The rate is exact because the interesting deviations are a
        property of the hardware, and inventing one here would put a
        number in the fake that a reader could mistake for a measurement.
        """
        decim, n = 32, 64
        with self._lock:
            sps = (self.rates or {}).get("dac_sps") or 200000
        dt = round(decim * 1024 * 1e6 / (sps * 2.0))
        rate_us = [i * dt for i in range(n)]
        return {"occ_min": 20, "endtx": n * decim, "run_us": rate_us[-1],
                "consumed": n * decim, "hist": [], "trace": [], "decim": 0,
                "rate_decim": decim, "rate_us": rate_us,
                "window_rates": [decim * 1024 * 1e6 / dt] * (n - 1),
                "byte_rate": decim * n * 1024 * 1e6 / rate_us[-1],
                "traced_byte_rate": decim * (n - 1) * 1024 * 1e6
                                    / (rate_us[-1] - rate_us[0])}

    def stats(self):
        with self._lock:
            return {"frames": self._sent_frames, "awg_bytes": self._awg_bytes}


class BoardDevice(Device):
    """The real board, driven through `host/measure.py`.

    It takes an already-open `measure.Board` rather than opening one,
    because opening the control port resets the board over NRSTB and
    re-enumerates the native port. Whoever owns that reset owns the
    lifecycle; the daemon just uses it.

    Playback reuses `measure.Feeder` rather than writing its own writer.
    The feed policy - clock paced, bounded lead, whole 512-byte packets
    - is measured, and three simpler policies were each tried and each
    lost data. It is not to be reinvented here.
    """

    def __init__(self, board, *, measure_mod=None):
        if measure_mod is None:
            import measure as measure_mod
        self.m = measure_mod
        self.board = board
        self._described = None
        self.fd = None
        self.feeder = None
        self.running = False
        self.mode = None
        self.rates = None
        self._rx = 0

    def describe(self, refresh=False):
        """Cached, and cached for a measured reason.

        Finding the track means asking for the banner, and the banner is
        a long console print: eleven underruns per call, every call,
        while playback is running. The track cannot change without a
        reflash, which the daemon does not do, so it is asked once -
        and, if the device is busy, not even then.
        """
        if self._described is not None and not refresh:
            return dict(self._described)
        info = {"kind": "board", "frame_bytes": self.m.FRAME_BYTES,
                "samples_per_frame": self.m.FRAME_SAMPLES}
        if self.running and not refresh:
            info["track"] = None
            info["track_note"] = "not asked: the banner costs underruns "
            return info
        try:
            info["track"] = self.m.which_track(self.board)
        except Exception as e:                      # noqa: BLE001
            info["track"] = None
            info["track_error"] = str(e)
        self._described = dict(info)
        return info

    def start(self, mode, *, dac_sps=None, adc_hz=None, channels=2,
              waveform=None, preset=None):
        if mode not in MODES:
            raise DeviceError(f"unknown mode {mode!r}")
        if self.running:
            raise DeviceError("already running; stop first")

        self.board.poll_console()
        self.fd = self.board.open_native(blocking_writes=(mode != "capture"))
        self.m.drain_until_quiet(self.fd, quiet=0.3, cap=5.0)

        if mode == "capture":
            # `=<dac>,<adc>` applies to L and P only; the numbered
            # presets carry their own rates, so a capture-only stream
            # picks one rather than pretending to set a rate the
            # firmware will ignore. The rate that comes back is read
            # from the frame headers, which is the only honest source.
            self.board.cmd(preset or "1")
        else:
            # One command string, not two: this is the form run_loop
            # uses, and the console has dropped commands sent while it
            # was printing before now.
            self.board.cmd(f"={dac_sps},{adc_hz or dac_sps},{channels}"
                           f"{'P' if mode == 'play' else 'L'}")
            time.sleep(0.2)

        # The feeder starts before the console is read, not after.
        # Reading first cost 0.6 s of a DAC already draining its ring at
        # the requested rate, and the ring ran dry: exactly 11 underruns
        # per run, three runs out of three, where `run_loop` on the same
        # rates gives none. The device is playing from the moment the
        # command lands, so anything between that and the first write is
        # silence the counters are right to complain about.
        if mode in ("play", "loop"):
            if not waveform:
                self._teardown()
                raise DeviceError("play needs a waveform")
            self.feeder = self.m.Feeder(self.fd, waveform, (dac_sps or 0) * 2)
            self.feeder.start()

        text = self.board.drain_console(0.3)
        if "refused" in text:
            self._teardown()
            raise DeviceError(text.strip() or "the device refused the rate")

        self.running = True
        self.mode = mode
        self.rates = {"dac_sps": dac_sps, "adc_hz": adc_hz,
                      "channels": channels, "preset": preset}
        return text

    def read(self, timeout=0.2):
        if self.fd is None:
            time.sleep(min(timeout, 0.05))
            return b""
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return b""
        try:
            data = os.read(self.fd, 262144)
        except OSError:
            return b""
        self._rx += len(data)
        return data

    def console(self):
        return self.board.poll_console()

    def counters(self):
        """The device's own counters, over the console.

        `B` is a short report and measures clean - zero underruns across
        repeated mid-stream calls - unlike the banner. It still costs a
        console round trip, so it is an explicit request rather than
        something a status poll drags in.
        """
        try:
            play = self.m.parse_play(self.board.ask("B", secs=1.0))
            return {"underruns": play.underruns, "spans": play.spans,
                    "partial": play.partial, "rx_bytes": self._rx}
        except Exception:                            # noqa: BLE001
            return {"rx_bytes": self._rx}

    def trace(self):
        """`O`, parsed. Two long lines, so it gets a longer read window.

        Reported whether or not playback is running: the device holds
        the histogram and the trace until the next play_start, so the
        useful moment to ask is after a run rather than during one -
        and asking during one costs underruns at exactly the rates
        where the answer matters.
        """
        o = self.m.parse_occ(self.board.ask("O", secs=2.0))
        return {"occ_min": o.min, "endtx": o.endtx, "run_us": o.run_us,
                "consumed": o.consumed, "hist": list(o.buckets),
                "trace": list(o.trace), "decim": o.decim,
                "rate_decim": o.rate_decim, "rate_us": list(o.rate_us),
                "window_rates": o.window_rates(),
                "byte_rate": o.device_byte_rate(),
                "traced_byte_rate": o.traced_byte_rate()}

    def stats(self):
        return {"rx_bytes": self._rx}

    def stop(self):
        if not self.running:
            return
        try:
            self.board.cmd("0")
        finally:
            self._teardown()
        self.running = False
        self.mode = None

    def _teardown(self):
        if self.feeder is not None:
            try:
                self.feeder.stop()
            except Exception:                        # noqa: BLE001
                pass
            self.feeder = None
        if self.fd is not None:
            # close_native flushes first: the device stops draining bulk
            # OUT when the stream stops, and macOS close() waits for
            # in-flight write URBs that a NAKing pipe never completes.
            try:
                self.board.close_native(self.fd)
            except Exception:                        # noqa: BLE001
                pass
            self.fd = None

    def close(self):
        self.stop()


class FrameSplitter:
    """Byte stream in, whole device frames out.

    The serial port hands over arbitrary slices, and a client is
    promised whole frames. Nothing here parses a frame beyond finding
    its magic and counting to the end of it - the bytes themselves are
    passed on untouched, which is the property the wire protocol rests
    on.

    A stream that starts mid-frame is normal after a resync, so leading
    bytes before the first magic are discarded and counted rather than
    treated as an error.
    """

    def __init__(self, frame_bytes=FRAME_BYTES, magic=FRAME_MAGIC):
        self.frame_bytes = frame_bytes
        self.magic = magic
        self._buf = bytearray()
        self.discarded = 0

    def feed(self, data):
        self._buf += data
        out = []
        while True:
            if len(self._buf) < len(self.magic):
                return out
            if not self._buf.startswith(self.magic):
                i = self._buf.find(self.magic, 1)
                if i < 0:
                    # Keep the last few bytes: the magic may straddle
                    # this chunk and the next.
                    keep = len(self.magic) - 1
                    self.discarded += len(self._buf) - keep
                    del self._buf[:len(self._buf) - keep]
                    return out
                self.discarded += i
                del self._buf[:i]
                continue
            if len(self._buf) < self.frame_bytes:
                return out
            out.append(bytes(self._buf[:self.frame_bytes]))
            del self._buf[:self.frame_bytes]
