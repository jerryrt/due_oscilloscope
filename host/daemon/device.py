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

import collections
import json
import os
import struct
import threading
import time
import zlib

import transport

# Frame layout, shared verbatim with lib/due_shared/src/frame.h and host/measure.py.
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

    def heartbeat(self, period_ms=None, sink=None):
        """Read or set the device's unsolicited beat. `{}` if it has none.

        `period_ms=0` stops it, `None` only reads. `sink` is called with
        each beat as it arrives, which is how the server broadcasts them
        without the device knowing what a client is.

        Default is "this device has no heartbeat", which is the honest
        answer for a recording, a fake, or firmware predating it -
        rather than a body of zeroes that a caller cannot tell from a
        board whose loop has stopped.
        """
        return {}

    def heartbeat_state(self):
        """The newest beat and what it implies, without asking anything.

        Safe on a status poll by construction: beats arrive unbidden, so
        reporting the last one costs the device nothing. That is the
        property `docs/daemon-api.md` promises of `status` and this must
        not be the thing that breaks it.
        """
        return {"supported": False}

    def trace(self):
        """The playback ring's occupancy and the converter's own rate.

        A separate call from `counters` because it is a different device
        command and a much longer reply - two lines of up to 256 values
        each - so it costs more than a poll path can afford. Like
        `counters`, never dragged in by `status`.
        """
        return {}

    def load(self):
        """Main-loop load: how hard the device is working.

        Its own operation for the same reason `trace` is: a different
        device command and a different question. `counters` asks what
        went wrong on the sample path; this asks whether the main loop
        is keeping up at all, which is the question no host-side figure
        can answer.
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
        # A synthetic beat, so the whole board -> daemon -> client path
        # is exercisable with no hardware. `stall_loop` freezes
        # loop_passes while seq and uptime keep advancing, which is
        # exactly what the timer-driven beat does on a real board when
        # the main loop stops - the one behaviour worth being able to
        # test without wedging a board to produce it.
        self._hb_period_ms = 0
        self._hb_seq = 0
        self._hb_passes = 1000
        self._hb_sink = None
        self._hb_thread = None
        self._hb_stop = threading.Event()
        self._hb_stalled = False
        self.stall_loop = False

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
        # The channel outlives a run deliberately - it is what status
        # polling uses between them - so it is released here and not in
        # _teardown.
        self._drop_control()
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

    # -- heartbeat ----------------------------------------------------
    def _hb_run(self):
        prev = None
        frozen = 0
        while not self._hb_stop.is_set():
            self._hb_stop.wait(self._hb_period_ms / 1000.0)
            if self._hb_stop.is_set() or not self._hb_period_ms:
                break
            self._hb_seq += 1
            if not self.stall_loop:
                self._hb_passes += 14284      # a real board's rough rate
            passes = self._hb_passes
            frozen = frozen + 1 if prev == passes else 0
            prev = passes
            self._hb_stalled = frozen >= 2
            hb = {"seq": self._hb_seq,
                  "uptime_ms": int(time.monotonic() * 1000) % 2**32,
                  "period_ms": self._hb_period_ms, "dropped": 0,
                  "counters": {"loop_passes": passes}}
            sink = self._hb_sink
            if sink is not None:
                try:
                    sink(dict(hb), self._hb_stalled)
                except Exception:                    # noqa: BLE001
                    pass

    def heartbeat(self, period_ms=None, sink=None):
        if sink is not None:
            self._hb_sink = sink
        if period_ms is not None:
            # Clamped the way the device clamps, so a client that tests
            # against this learns the same rules the board enforces.
            self._hb_period_ms = (0 if period_ms == 0
                                  else max(20, min(60000, int(period_ms))))
            if self._hb_period_ms and self._hb_thread is None:
                self._hb_stop.clear()
                self._hb_thread = threading.Thread(target=self._hb_run,
                                                   daemon=True)
                self._hb_thread.start()
        return {"seq": self._hb_seq, "uptime_ms": 0,
                "period_ms": self._hb_period_ms, "dropped": 0,
                "counters": {"loop_passes": self._hb_passes}}

    def heartbeat_state(self):
        return {"supported": True, "period_ms": self._hb_period_ms,
                "beats": self._hb_seq, "stalled": bool(self._hb_stalled),
                "late": False, "seq": self._hb_seq,
                "loop_passes": self._hb_passes}

    def load(self):
        """A loop that is comfortably keeping up, deterministically.

        Structurally real like the rest of this device: the shape a
        client parses is the shape a board returns, so the op can be
        exercised without one. Every pass in one bucket is what a
        healthy idle board actually looks like - `Control.load` says so
        - and an outlier several buckets to the right is the thing a
        caller is watching for.
        """
        # The keys are `Control.load`'s, exactly. A fake that invents a
        # field is worse than no fake: this one had `mean_us`, which the
        # device does not return, and the first script written against
        # it failed on a board rather than in the suite.
        mck = 78_000_000
        per_us = mck / 1e6
        hist = [0] * 16
        hist[9] = 140_000
        return {"dev_us": 1_000_000, "passes": 140_000,
                "max_cycles": 1638, "max_us": 1638 / per_us,
                "mck_hz": mck, "hist": hist,
                "hist_us": [(1 << i) / per_us for i in range(len(hist))],
                "via": "fake"}

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

def frame_header(frame):
    """The header fields by name, so nothing above has to know offsets.

    `HDR_FMT` is already written down in three places - here,
    `lib/due_shared/src/frame.h` and `host/measure.py` - and every copy
    is a chance to read a stored frame at the wrong offsets. Anything
    here that wants a field asks for it by name and unpacks once.
    """
    (magic, version, flags, channel_mask, seq, sample_rate_hz,
     timestamp_us, overrun_count, play_consumed,
     header_crc32) = struct.unpack(HDR_FMT, bytes(frame[:HDR_LEN]))
    return {"magic": magic, "version": version, "flags": flags,
            "channel_mask": channel_mask, "seq": seq,
            "sample_rate_hz": sample_rate_hz, "timestamp_us": timestamp_us,
            "overrun_count": overrun_count, "play_consumed": play_consumed,
            "header_crc32": header_crc32}


# The longest a replay will sit still for one gap in a recording.
#
# A hole in a record is real - the recorder counts what the disk made it
# drop, and the sequence numbers in the surviving frames prove it - so
# replaying the hole at its true length is the honest default. Past this
# bound the front end just looks hung, so the wait is truncated instead
# and *counted* in `counters` as `gaps_shortened`. The distortion is
# then visible rather than silent, which is the only version of it this
# project allows.
REPLAY_MAX_GAP_S = 1.0


class FileDevice(Device):
    """A recording, replayed through the same path that read it live.

    `record.start` has written frames verbatim since the daemon had a
    recorder, and until this class nothing anywhere read them back: the
    front end's Record button wrote a format with no reader. This is the
    reader.

    It is a `Device` rather than a loader inside the front end on
    purpose. Everything above this line - the frame splitter, the
    trigger, the measurements, the FFT, the cursors, the CSV export -
    then runs over a recording through exactly the code that runs over
    the board, so a replay shows what the bench showed rather than what
    a second implementation of the same parsing believes it showed.

    Two facts about this project make that worth building rather than
    merely convenient. There are two benches here, wired differently,
    and `docs/HANDOFF.md` says plainly that a figure taken on one is not
    comparable with a figure taken on the other; a recording is the one
    thing one bench can hand the other and have re-analysed by the same
    code, instead of a number quoted in an issue. And numbers quoted as
    prose have been withdrawn twice this week - the reload figures on #5
    were the instrument handing back the previous vertical gain's data -
    where a capture would still have been re-readable by whoever doubted
    it.

    What it will not do is pass for a board. `describe()` says
    `kind="file"` and carries the sidecar's own device block beside it;
    the rates in `status` are the recording's and not whatever the
    caller asked to start at; and `write_awg` refuses, because a
    recording has no generator and accepting a waveform would put the
    DAC's name on samples nothing produced.
    """

    def __init__(self, path, *, pace=True, loop=False, speed=1.0,
                 chunk_bytes=1 << 16):
        if speed <= 0:
            raise DeviceError(f"replay speed must be positive, not {speed}")
        self.path = path
        self.pace = pace
        self.loop = loop
        self.speed = float(speed)
        self._chunk = int(chunk_bytes)
        self._lock = threading.Lock()

        try:
            self.size = os.path.getsize(path)
        except OSError as e:
            # `strerror` rather than the exception: OSError's own text
            # repeats the filename, and this message already carries it.
            raise DeviceError(
                f"cannot read {path}: {e.strerror or e}") from e

        self.sidecar = self._load_sidecar()
        self._check_geometry()

        # A trailing part-frame is a recorder that was killed mid-write.
        # It is reported rather than trimmed in silence: a file that is
        # not a whole number of frames is a file whose end is unknown,
        # and that is worth knowing before a measurement is taken off it.
        self.frames_total = self.size // FRAME_BYTES
        self.truncated_bytes = self.size % FRAME_BYTES
        if self.frames_total == 0:
            raise DeviceError(
                f"{path} holds no whole frames ({self.size} bytes, "
                f"a frame is {FRAME_BYTES})")

        self._fh = None
        self._splitter = None
        self._pending = collections.deque()
        self._hold = None
        self._console = []
        self.closed = False
        self.running = False
        self.mode = None
        self.rates = None
        self.at_end = False
        self.loops = 0
        self.seq_gaps = 0
        self.gaps_shortened = 0
        self.overruns = 0
        self.last_rate_hz = None
        self._replayed = 0
        self._t0 = 0.0
        self._elapsed_us = 0.0
        self._prev_ts = None
        self._prev_seq = None

    # -- the file ----------------------------------------------------
    def _load_sidecar(self):
        """The `.json` beside the frames, if it is there.

        Optional, because a bare frame file is still readable - the
        header carries the rate, which is the one thing that genuinely
        varies and cannot be reconstructed. Everything else the sidecar
        adds is provenance, and provenance that is missing should say so
        rather than be invented.
        """
        try:
            with open(self.path + ".json") as f:
                side = json.load(f)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:
            raise DeviceError(f"{self.path}.json is unreadable: {e}") from e
        if not isinstance(side, dict):
            raise DeviceError(f"{self.path}.json is not a sidecar object")
        return side

    def _check_geometry(self):
        """Refuse a recording this build cannot read, by name.

        The frame is a fixed 4096 bytes because that is 8 x 512 and one
        DMA sends whole packets - `frame.h` calls the geometry
        load-bearing and the ramp test failed 4 runs in 15 when it last
        moved. So a file recorded against a different geometry is not
        something to read best-effort: every sample after the first
        header would land at the wrong offset and still decode to a
        plausible number.
        """
        if not self.sidecar:
            return
        fb = self.sidecar.get("frame_bytes")
        if fb is not None and fb != FRAME_BYTES:
            raise DeviceError(
                f"{self.path} was recorded with {fb}-byte frames; this "
                f"build reads {FRAME_BYTES}. The geometry is compiled in "
                f"(lib/due_shared/src/frame.h) and reading across it "
                f"would misalign every sample")

    def _open(self):
        self._fh = open(self.path, "rb")
        self._splitter = FrameSplitter()
        self._pending.clear()
        self._hold = None
        self._t0 = time.monotonic()
        self._elapsed_us = 0.0
        self._prev_ts = None
        self._prev_seq = None

    def _close_fh(self):
        if self._fh is not None:
            try:
                self._fh.close()
            finally:
                self._fh = None
        self._splitter = None
        self._pending.clear()
        self._hold = None

    def _recorded_rates(self):
        """What the recording was taken at - never what the caller asked.

        A file cannot be asked to convert at a different rate, and
        answering `status` as though it could would put a number in a
        reply that nothing measured. The frame headers carry the
        device's own answer as they go past; the sidecar's is only what
        was requested of it.
        """
        rates = dict((self.sidecar or {}).get("rates") or {})
        rates["source"] = "recording"
        return rates

    # -- control -----------------------------------------------------
    def describe(self):
        rec = (self.sidecar or {}).get("device") or {}
        return {"track": rec.get("track", "file"), "kind": "file",
                "frame_bytes": FRAME_BYTES,
                "samples_per_frame": FRAME_SAMPLES,
                "path": os.path.basename(self.path),
                "frames": self.frames_total,
                "bytes": self.size,
                "truncated_bytes": self.truncated_bytes,
                "sidecar": self.sidecar is not None,
                # The bench the samples actually came from, kept apart
                # from `kind` so that nothing downstream can read
                # replayed samples as a live board of that track.
                "recorded": rec or None,
                "recorded_mode": (self.sidecar or {}).get("mode"),
                "recorded_rates": (self.sidecar or {}).get("rates"),
                "recorded_dropped": (self.sidecar or {}).get("dropped"),
                "recorded_unix": (self.sidecar or {}).get("started_unix")}

    def start(self, mode, *, dac_sps=None, adc_hz=None, channels=2,
              waveform=None, preset=None):
        if self.closed:
            raise DeviceError("device is closed")
        if mode not in MODES:
            raise DeviceError(f"unknown mode {mode!r}")
        if mode == "play":
            # Play means "produce samples", and this device has none to
            # produce. Refusing here rather than running quietly is the
            # same choice FakeDevice makes about never being more
            # permissive than the hardware it stands in for.
            raise DeviceError(
                "a recording cannot play; it has samples to replay, "
                "not a generator")
        if self.running:
            raise DeviceError("already running; stop first")
        with self._lock:
            self._open()
            self.running = True
            self.mode = mode
            self.at_end = False
            self.loops = 0
            self.seq_gaps = 0
            self.gaps_shortened = 0
            self._replayed = 0
            self.rates = self._recorded_rates()
            self._console.append(
                f"replaying {os.path.basename(self.path)}: "
                f"{self.frames_total} frames\n")
            asked = adc_hz or dac_sps
            recorded = self.rates.get("adc_hz") or self.rates.get("dac_sps")
            if asked and recorded and int(asked) != int(recorded):
                # Said out loud rather than accepted in silence: the
                # samples are at the rate they were taken at, and a
                # caller who believes otherwise reads every time axis
                # wrong.
                self._console.append(
                    f"note: asked for {int(asked)} Hz; the recording is "
                    f"{int(recorded)} Hz and that is what it replays at\n")

    def stop(self):
        with self._lock:
            self._close_fh()
            self.running = False
            self.mode = None
            self._console.append("stopped\n")

    def close(self):
        self.stop()
        self.closed = True

    def write_awg(self, data):
        """Refuse, rather than accept a waveform nothing will play.

        The daemon holds an uploaded waveform whether or not the device
        takes it, so staying quiet here would leave a front end
        believing it had armed a generator that does not exist.
        """
        raise DeviceError(
            "a recording has no generator; nothing here can play a "
            "waveform")

    # -- stream ------------------------------------------------------
    def read(self, timeout=0.2):
        with self._lock:
            if not self.running:
                if timeout:
                    time.sleep(min(timeout, 0.01))
                return b""
            if self._hold is None:
                got = self._next()
                if got is None:
                    self._finish()
                    return b""
                frame, hdr = got
                self._hold = (frame, hdr, self._schedule(hdr))
            frame, hdr, due = self._hold
            if self.pace:
                wait = due - time.monotonic()
                if wait > 0:
                    time.sleep(min(wait, timeout))
                    if wait > timeout:
                        # Still not due. The server asks again in a
                        # moment, and the frame stays held so its place
                        # in the recording's own timeline is not lost.
                        return b""
            self._hold = None
            self._count(hdr)
            self._replayed += 1
            return frame

    def _next(self):
        """The next whole frame and its header, or None at the end."""
        for _ in range(2):                    # at most one wrap per call
            while not self._pending:
                chunk = self._fh.read(self._chunk)
                if not chunk:
                    break
                self._pending.extend(self._splitter.feed(chunk))
            if self._pending:
                frame = self._pending.popleft()
                return frame, frame_header(frame)
            if not self.loop:
                return None
            self._rewind()
        return None

    def _rewind(self):
        self.loops += 1
        self._fh.seek(0)
        self._splitter = FrameSplitter()
        self._pending.clear()
        # The pacing origin restarts with the file. Carrying the old one
        # across would make every frame of the second pass due in the
        # past, and replay it as fast as the socket would take it.
        self._t0 = time.monotonic()
        self._elapsed_us = 0.0
        self._prev_ts = None
        # `_prev_seq` deliberately survives the wrap. The sequence
        # numbers jump backwards at the seam and that is a real
        # discontinuity - the two passes were never continuous - so it
        # is counted here and drawn as a break by the front end, rather
        # than smoothed over because this end knows it was a loop.
        self._console.append(f"looped: pass {self.loops + 1}\n")

    def _schedule(self, hdr):
        """When this frame is due, on the clock the device stamped it with.

        Pacing off `timestamp_us` rather than off the nominal rate
        reproduces the run's timing including its irregularities, which
        is the part worth seeing: a stall on the bench was a stall, and
        smoothing it to the nominal rate here would replay a run that
        never happened.
        """
        ts = hdr["timestamp_us"]
        if self._prev_ts is None:
            d_us = 0.0
        else:
            d_us = float((ts - self._prev_ts) & 0xFFFFFFFF)  # uint32 wraps
            if d_us <= 0.0:
                d_us = self._nominal_us(hdr)
            elif d_us > REPLAY_MAX_GAP_S * 1e6:
                self.gaps_shortened += 1
                d_us = REPLAY_MAX_GAP_S * 1e6
        self._prev_ts = ts
        self._elapsed_us += d_us
        return self._t0 + (self._elapsed_us / 1e6) / self.speed

    @staticmethod
    def _nominal_us(hdr):
        """One frame's duration from the header's own rate.

        The fallback for a stream whose timestamps do not advance.
        `sample_rate_hz` is per channel and the frame holds
        `FRAME_SAMPLES` of them interleaved, so the channel count comes
        out of the mask rather than being assumed to be two.
        """
        n_ch = max(1, bin(hdr["channel_mask"]).count("1"))
        rate = hdr["sample_rate_hz"] or 200000
        return FRAME_SAMPLES * 1e6 / float(rate * n_ch)

    def _count(self, hdr):
        if self._prev_seq is not None:
            if ((hdr["seq"] - self._prev_seq) & 0xFFFFFFFF) != 1:
                self.seq_gaps += 1
        self._prev_seq = hdr["seq"]
        self.overruns = hdr["overrun_count"]
        self.last_rate_hz = hdr["sample_rate_hz"]

    def _finish(self):
        self._close_fh()
        self.running = False
        self.mode = None
        self.at_end = True
        self._console.append(
            f"end of {os.path.basename(self.path)}: "
            f"{self._replayed} frames replayed\n")

    # -- reporting ---------------------------------------------------
    def console(self):
        with self._lock:
            out = "".join(self._console)
            self._console = []
            return out

    def counters(self):
        with self._lock:
            return {"frames": self._replayed, "awg_bytes": 0,
                    "underruns": 0,
                    # The device's own running count, carried in the
                    # frames. What the board reported at capture time,
                    # not something recomputed now.
                    "overruns": self.overruns,
                    "seq_gaps": self.seq_gaps,
                    "frames_total": self.frames_total,
                    "loops": self.loops,
                    "at_end": self.at_end,
                    "rate_hz": self.last_rate_hz,
                    "gaps_shortened": self.gaps_shortened,
                    "recorded_dropped": (self.sidecar or {}).get("dropped")}

    def stats(self):
        with self._lock:
            return {"frames": self._replayed,
                    "frames_total": self.frames_total,
                    "loops": self.loops, "at_end": self.at_end,
                    "awg_bytes": 0}

def _is_transport_failure(exc):
    """Did the wire fail, or did this host ask a bad question?

    Only the first may drop the control link. The three readers below
    used to catch bare `Exception` and drop on all of it, which blames
    the transport for a host-side defect: a `KeyError` from a renamed
    counter field would tear down a healthy link and re-open it on the
    next call, hiding a mapping bug behind an intermittent-looking
    reconnect. `measure.py` draws this distinction with `_LINK_GONE`
    and its comment says why; the daemon did not, and that asymmetry is
    what #51 q3 found while removing the console fallback.

    `ControlError` is deliberately excluded. It means the device
    answered and the answer was a refusal - `CTL_ERR_OPCODE` for an
    opcode this track does not implement, say - so the link is healthy
    and dropping it would be wrong.
    """
    if isinstance(exc, (OSError, ValueError)):
        return True
    try:
        import control as control_mod
    except Exception:                                # noqa: BLE001
        return False
    return isinstance(exc, control_mod.ProtocolError)

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
        #: May the reader thread take bytes off `fd` yet? Issue #57.
        #:
        #: Not the same question as `running`, which means a stream is
        #: active and is set once `start()` has finished. Gating the
        #: read on `running` left the descriptor unread for the whole
        #: tail of `start()` - the mode command, a 0.2 s settle, the
        #: feeder, a console drain - while the device was already
        #: producing, and that cost a frame under load.
        self._readable = False
        self.mode = None
        self.rates = None
        self._rx = 0
        self._ctl = None
        self._ctl_tried = False
        self._ctl_note = None
        self._ident = None
        self._ident_tried = False
        # One lock over the control channel. `Control` is one serial fd
        # with a request/response model, so a pump thread reading it
        # while `counters()` is mid-request would have two readers on
        # one port stealing each other's frames. Serialising is enough
        # because a beat that arrives *during* a request is not lost -
        # `Control.on_unsolicited` hands it over from inside
        # `request()`, which is where most of them land once anything
        # is polling.
        self._ctl_lock = threading.RLock()
        self._hb_period_ms = 0
        self._hb_last = None          # newest beat, whole
        self._hb_prev_passes = None
        self._hb_stalled = False
        self._hb_frozen = 0           # consecutive beats with a frozen loop
        self._hb_count = 0
        self._hb_at = None            # monotonic time of the newest beat
        self._hb_sink = None          # set by the server, to broadcast
        self._hb_thread = None
        self._hb_stop = threading.Event()

    def control(self):
        """The native port's command channel, or None.

        Opened lazily and kept, because this is what replaces polling
        the console while the board is working. Measured on this board:
        one `B` blocks the main loop for 13.14 ms and one `O` for
        15.40 ms, and for every one of those milliseconds no bulk OUT is
        drained - which is the NAKing pipe that hangs macOS in close().
        The same readings over this channel cost 146 and 274 us.

        None on firmware with one CDC function. No track is in that
        state - all three enumerate a command port and report ctlver=3 -
        so None is a fault to diagnose. `counters()`, `trace()` and
        `load()` all refuse when it is None rather than reading the same
        numbers off printf at 13-20 ms of blocked main loop apiece.

        A node is not a protocol: whether `command_node()` returns a
        node says only that a second CDC function enumerated, not that
        it answers CTL frames. The two can differ - a control channel
        can enumerate ahead of being implemented - and speaking to a
        node that answers nothing blocks every call until the caller's
        timeout. So this checks the identity line's `ctl_version`
        before opening the node at all: `CLAUDE.md` documents
        `ctlver=0` as "this track has no control channel". `v` is one
        short line rather than the banner, and the answer is cached for
        the same reason `describe` caches the track: it cannot change
        without a reflash.
        """
        if self._ctl is not None or self._ctl_tried:
            return self._ctl
        self._ctl_tried = True
        try:
            import control as control_mod

            node = self.board.command_node()
            if node is None:
                self._ctl_note = "no command port; this firmware has one "\
                                 "CDC function"
                return None
            ident = self._identity()
            if ident is None:
                self._ctl_note = "the board did not answer `v`, so whether "\
                                 "it speaks CTL is unknown; not guessing"
                return None
            if ident.get("ctl_version", 0) < 1:
                self._ctl_note = "the command node enumerates but reports "\
                                 "ctlver=0: this firmware has no control "\
                                 "channel"
                return None
            self._ctl = control_mod.Control(node, timeout=2.0)
        except Exception as e:                       # noqa: BLE001
            self._ctl_note = f"command port unavailable: {e}"
            self._ctl = None
        return self._ctl

    def _identity(self):
        """The board's identity line, asked once and kept.

        Separate from `describe`, which asks `which_track` and may
        decline to ask at all while the device is busy. This one is
        reached only from `control`, costs one line rather than the
        banner, and what it reports cannot change without a reflash.
        """
        if self._ident_tried:
            return self._ident
        self._ident_tried = True
        try:
            self._ident = self.m.identity(self.board)
        except Exception:                            # noqa: BLE001
            self._ident = None
        return self._ident

    def _drop_control(self):
        """Forget the channel, so the next caller reopens it.

        A board reset re-enumerates the native port and the node can
        move, so a cached fd outlives its device. Reopening is cheap;
        reading a stale one is not.
        """
        c, self._ctl = self._ctl, None
        self._ctl_tried = False
        self._ident = None
        self._ident_tried = False
        if c is not None:
            try:
                c.close()
            except Exception:                        # noqa: BLE001
                pass

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
            # `which_track` returns (track, the text it read it from),
            # because tools/ callers want the raw reply. Storing the
            # pair whole put a Python tuple where every consumer expects
            # a string: the front end's Source line rendered
            # `board (track ['b'], '# id: ...\r\n'])`, the label's width
            # hint followed its text and blew the window out to 22,727
            # pixels, and `track != "fake"` elsewhere compared a tuple
            # to a string and was quietly always true. Issue #38.
            track, ident_text = self.m.which_track(self.board)
            info["track"] = track
            info["identity"] = (ident_text or "").strip()
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

        # The reader thread takes the descriptor HERE, not at the end of
        # start(). Issues #44 and #57, which pull in opposite directions
        # and are both right.
        #
        # Two invariants have to hold at once. Only one reader may touch
        # the descriptor - `drain_until_quiet` above and `_read_loop`
        # cannot both have it, which is #44 - and the descriptor must be
        # drained the whole time the device is producing, which is #57.
        #
        # This line is the only instant that satisfies both. Before it,
        # `drain_until_quiet` owns the fd exclusively and the device is
        # not streaming yet. After it, `_read_loop` owns it exclusively:
        # `start()` performs no further reads on the native port - the
        # feeder only writes, and `drain_console` is the programming
        # port, not this one.
        #
        # Gating on `running` instead left ~0.5 s of full-rate stream
        # unread, and windows-desk bisected a lost frame to exactly that
        # (#57: 0 of 10 before, 6 of 10 after, p = 0.011). The frames
        # were being read pre-#44 - by the second reader, which is what
        # made that fix necessary and this one insufficient.
        self._readable = True

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
        # Gated on `_readable`, not on `fd is None` or on `running`.
        #
        # `Server._read_loop` drains this device for the daemon's whole
        # lifetime and asks only this method whether there is anything
        # to read. `start()` assigns `self.fd` and then spends seconds
        # before it is done: `drain_until_quiet` with `cap=5.0`, the
        # `=<dac>,<adc>L` command, a 0.2 s settle, and a console drain.
        #
        # Gating on `fd is None` alone would let the reader thread
        # begin consuming the descriptor the instant `self.fd` is
        # assigned, so for that whole window two threads would split
        # one stream: the drain would not drain, because bytes it
        # means to discard would go to subscribers instead, and frames
        # from the new run arriving inside the window would be eaten by
        # `drain_until_quiet` and thrown away - tens to hundreds of
        # them, at the start of a run.
        #
        # `running` is also the wrong flag, for the opposite reason: it
        # is set at the END of start(), leaving the descriptor unread
        # through the mode command, the settle, the feeder and the
        # console drain - about half a second of full-rate stream that
        # nothing would be taking. `_readable` opens at the one instant
        # that gives exactly one reader AND no unread window: after
        # `drain_until_quiet` returns and before the device is commanded
        # to stream.
        #
        # `FakeDevice.read()` gates on `running`, so a board-free test
        # alone cannot see either failure mode - the fake implements the
        # contract but not the real device's timing.
        #
        # Safe on the way out too: `_teardown()` shuts the gate before
        # it closes the fd.
        if self.fd is None or not self._readable:
            time.sleep(min(timeout, 0.05))
            return b""
        r = transport.wait_any([self.fd], timeout)
        if not r:
            return b""
        try:
            data = self.fd.read(262144)
        except OSError:
            return b""
        self._rx += len(data)
        return data

    def console(self):
        return self.board.poll_console()

    def counters(self):
        """The device's own counters, over the control channel and nowhere else.

        The console alternative, `B`, costs 13.14 ms of blocked main
        loop - measured, not estimated - and drains no bulk OUT for any
        of it, which is how a host ends up stuck in close(); see
        objective 0c. GET_COUNTERS reports the same numbers for 146 us.

        There is deliberately no console fallback, for `load()`'s reason
        one method over: a counter read that blocks the loop for 13 ms
        while the sample path runs is a different experiment from one
        that costs 146 us, not a slower version of it, and substituting
        one for the other inside this method hides the swap from the
        caller. All three tracks carry a control channel, so a missing
        one is a fault rather than a track (#51 q3).

        A failure raises. The server turns that into a refusal, and the
        GUI's poll path already treats a refusal as a dash on a panel.
        """
        c = self.control()
        if c is None:
            raise DeviceError(
                "this device has no control channel, and counters are "
                "not readable any other way without blocking the main "
                "loop for 13 ms while the sample path runs")
        try:
            # Under the lock: the heartbeat pump reads this same fd,
            # and two readers on one port steal each other's frames.
            with self._ctl_lock:
                ct = c.counters()
        except Exception as e:                       # noqa: BLE001
            if _is_transport_failure(e):
                self._drop_control()
            raise
        return {"underruns": ct["underruns"], "spans": ct["spans"],
                "partial": ct["partial"], "consumed": ct["consumed"],
                "occ_min": ct["occ_min"], "dev_us": ct["dev_us"],
                "rx_bytes": self._rx, "via": "control"}

    def load(self):
        """Main-loop load, over the control channel and nowhere else.

        `CLAUDE.md` is explicit that printf is a debug method and not an
        instrument, and that anything read while the sample path is
        running goes over the control channel: one console status
        command blocks the main loop for 13-20 ms, and twenty GET_LOAD
        queries cost 0.29 ms in total. So there is deliberately no
        console fallback here - a load figure taken by a method that
        itself blocks the loop for 15 ms would be measuring the
        instrument.

        Cumulative since boot or since the last clear, so a *rate* comes
        from differencing two of these over whatever interval the caller
        wants. `max_us` is the exception: a maximum cannot be
        differenced, and is the worst pass since the last clear.
        """
        c = self.control()
        if c is None:
            raise DeviceError(
                "this device has no control channel, and load is not "
                "readable any other way without blocking the main loop "
                "it is trying to measure")
        try:
            with self._ctl_lock:                    # see counters()
                out = dict(c.load())
        except Exception as e:                       # noqa: BLE001
            if _is_transport_failure(e):
                self._drop_control()
            raise
        out["via"] = "control"
        return out

    def trace(self):
        """The occupancy histogram, its trace, and the rate trace.

        Over the control channel, for the same reason as `counters`:
        `O` is three long console lines and blocks the main loop for
        15.40 ms, where GET_OCCUPANCY costs 274 us. Asking on the
        console during a run costs underruns at exactly the rates where
        the answer matters; the control channel can be asked whenever
        the answer is wanted, which is why it is the only way in.

        The rate trace is paged: PLAY_RATE_TRACE entries of four bytes
        do not fit a packet, and a response spanning packets can be
        truncated by a single-banked endpoint without saying so.
        """
        c = self.control()
        if c is None:
            raise DeviceError(
                "this device has no control channel, and the occupancy "
                "trace is not readable any other way without blocking "
                "the main loop for 15 ms while the sample path runs")
        try:
            with self._ctl_lock:                    # see counters()
                occ = c.occupancy()
                rate = c.rate_trace()
        except Exception as e:                       # noqa: BLE001
            if _is_transport_failure(e):
                self._drop_control()
            raise
        # Built as an OccHist rather than returned field by field,
        # because the derived rates are methods on it. The console
        # branch that used to stand here supplied `window_rates`,
        # `byte_rate` and `traced_byte_rate` and the control branch
        # beside it did not, so the reply's shape depended on which
        # instrument answered - the same defect one layer up from the
        # one #51 q3 is about. One path now, and it carries all of them.
        o = self.m.OccHist(
            buckets=list(occ["hist"]), min=occ["occ_min"],
            endtx=occ["endtx"], run_us=occ["run_us"],
            consumed=occ["consumed"], trace=list(occ["trace"]),
            decim=occ["decim"], rate_us=list(rate["us"]),
            rate_decim=rate["decim"], via="control")
        return {"occ_min": o.min, "endtx": o.endtx, "run_us": o.run_us,
                "consumed": o.consumed, "hist": list(o.buckets),
                "trace": list(o.trace), "decim": o.decim,
                "rate_decim": o.rate_decim, "rate_us": list(o.rate_us),
                "window_rates": o.window_rates(),
                "byte_rate": o.device_byte_rate(),
                "traced_byte_rate": o.traced_byte_rate(),
                "via": "control"}

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
        # Shut the gate first. The fd is about to close under the
        # reader thread, and it must not be read between here and that.
        self._readable = False
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

    # -- heartbeat ----------------------------------------------------
    def _hb_on_frame(self, frame):
        """One beat, from whichever thread happened to read it.

        Called from the pump when the channel is idle and from inside
        `Control.request()` when a beat lands mid-request. Both hold
        `_ctl_lock`, so the state below is only ever touched by one.
        """
        c = self.control()
        if c is None:
            return
        try:
            hb = c._decode_heartbeat(frame.payload)
        except Exception:                            # noqa: BLE001
            return
        passes = hb.get("counters", {}).get("loop_passes")
        prev = self._hb_prev_passes
        # The whole point of driving the beat from a timer: `seq` and
        # `uptime_ms` come from the ISR and keep advancing, while
        # `loop_passes` comes from the main loop and stops. A beat that
        # arrives with a frozen count is the stall reporting itself.
        if prev is not None and passes is not None and passes == prev:
            self._hb_frozen += 1
        else:
            self._hb_frozen = 0
        self._hb_prev_passes = passes
        # Two in a row, not one: a single repeat is a beat that landed
        # inside one main-loop pass, which at a fast cadence is
        # ordinary rather than a stall.
        self._hb_stalled = self._hb_frozen >= 2
        self._hb_last = hb
        self._hb_at = time.monotonic()
        self._hb_count += 1
        sink = self._hb_sink
        if sink is not None:
            try:
                sink(dict(hb), self._hb_stalled)
            except Exception:                        # noqa: BLE001
                pass

    def _hb_pump(self):
        """Read the control channel while nobody else wants it.

        Short waits under the lock rather than one long one, so a
        `counters()` call is never left queueing behind a beat that may
        not come.
        """
        while not self._hb_stop.is_set():
            c = self.control()
            if c is None:
                self._hb_stop.wait(0.5)
                continue
            try:
                with self._ctl_lock:
                    frame = c.recv(timeout=0.05)
                if frame is not None and frame.req_id == 0:
                    with self._ctl_lock:
                        self._hb_on_frame(frame)
            except Exception:                        # noqa: BLE001
                self._hb_stop.wait(0.2)

    def heartbeat(self, period_ms=None, sink=None):
        c = self.control()
        if c is None:
            return {}
        if sink is not None:
            self._hb_sink = sink
        with self._ctl_lock:
            c.on_unsolicited = self._hb_on_frame
            try:
                state = c.heartbeat(period_ms)
            except Exception as e:                   # noqa: BLE001
                raise DeviceError(f"heartbeat: {e}")
        # The device clamps, so believe its answer rather than the ask.
        self._hb_period_ms = state.get("period_ms", 0)
        if self._hb_period_ms and self._hb_thread is None:
            self._hb_stop.clear()
            self._hb_thread = threading.Thread(target=self._hb_pump,
                                               daemon=True)
            self._hb_thread.start()
        return state

    def heartbeat_state(self):
        hb = self._hb_last
        if not self._hb_period_ms and hb is None:
            c = self.control()
            return {"supported": c is not None, "period_ms": 0}
        age = None if self._hb_at is None else time.monotonic() - self._hb_at
        # Late is not the same as stalled and must not be reported as
        # it: a beat that stopped arriving says the channel or the
        # timer went, and one that arrives with a frozen loop_passes
        # says the main loop went. They have different causes.
        late = (self._hb_period_ms > 0 and age is not None
                and age > max(1.0, 4.0 * self._hb_period_ms / 1000.0))
        return {"supported": True, "period_ms": self._hb_period_ms,
                "beats": self._hb_count, "age_s": age,
                "stalled": bool(self._hb_stalled), "late": bool(late),
                "seq": None if hb is None else hb.get("seq"),
                "uptime_ms": None if hb is None else hb.get("uptime_ms"),
                "dropped": None if hb is None else hb.get("dropped"),
                "loop_passes": None if hb is None else
                hb.get("counters", {}).get("loop_passes")}

    def close(self):
        self._hb_stop.set()
        t = self._hb_thread
        if t is not None:
            t.join(timeout=1.0)
            self._hb_thread = None
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
