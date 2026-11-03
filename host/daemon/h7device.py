"""The H7 target behind the daemon (docs/20). Everything H7-specific lives here: finding the unit, its two USB functions, start and
stop through the control channel, configuration, the swing cap, the playback feed and the calibration. The server and the GUI see the
Device surface (device.py) and a device description, nothing else.

Two transports, so the class can be driven by a simulated unit in tests (h7sim.py) and by the real one (`H7Device.open()`):
  stream  .read(timeout) -> bytes, .write(bytes) -> int, .close()      the sample function (frames in, playback samples out)
  control .call(opcode, payload=b"") -> frame with .payload            host/control.py's Control, or a simulation of it
"""
import array
import math
import os
import struct
import sys
import threading
import time

import pacing
import control as ctl
from . import device as devmod
from .device import Device, DeviceError, MODES
from .rates import RateError

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "targets", "h7tool", "tools"))
import h7_awg          # noqa: E402  the swing cap and the playback unit size live in one place
import h7_cal          # noqa: E402

OP_CONFIG, OP_RUN, OP_PLAY, OP_STATUS = 0x0040, 0x0041, 0x0042, 0x0043
#: Playback units written before the DAC timer starts. The unit accepts 1-8; fewer is less runway at the start of a run.
PLAY_PRIME_UNITS = 8
_CFG = struct.Struct("<IIBBBBHH")
_STATUS = struct.Struct("<4B17I")
_STATUS_NAMES = ("adc_period", "dac_period", "frames", "lost", "sent", "tc_missed", "ct_bad", "adc_ovr", "play_units", "play_consumed",
                 "play_underruns", "play_short", "play_min_occ", "play_resumes", "starts", "dma_err", "build")
_COUNTER_NAMES = ("dev_us", "bytes_in", "produced", "consumed", "underruns", "isr_calls", "endtx", "spans", "partial", "occ_min",
                  "svc_calls", "loop_passes", "run_us", "abandoned", "drain_polls")
BASE_HZ = 200_000_000
ADC_MIN_PERIOD = 80          # 2.5 Msps per channel: every trigger converts (docs/10)
DAC_MIN_PERIOD = 40          # 5 MS/s update, the vendor's figure, delivered and fed (docs/15)
MAX_TILED_SAMPLES = 1 << 20


class H7RatePolicy:
    """Rates as integer periods of the 200 MHz base. `rc` in the daemon's replies is that period."""

    RateError = RateError

    def check_capture(self, hz, channels):
        if channels not in (1, 2):
            raise RateError(f"{channels} channels: the H7 scope has 1 or 2")
        period = round(BASE_HZ / float(hz))
        if period < ADC_MIN_PERIOD:
            raise RateError(f"{hz} Hz is a period of {period} ticks, under the {ADC_MIN_PERIOD} the ADC converts every trigger at "
                            f"({BASE_HZ // ADC_MIN_PERIOD} Hz per channel)")
        return period, BASE_HZ / period

    def check_dac(self, hz):
        period = round(BASE_HZ / float(hz))
        if period < DAC_MIN_PERIOD:
            raise RateError(f"{hz} Hz is a period of {period} ticks, under the {DAC_MIN_PERIOD} of the {BASE_HZ // DAC_MIN_PERIOD} Hz update ceiling")
        return period, BASE_HZ / period

    def describe(self):
        return {"base_hz": BASE_HZ, "adc_min_period": ADC_MIN_PERIOD, "adc_max_hz": BASE_HZ // ADC_MIN_PERIOD,
                "dac_min_period": DAC_MIN_PERIOD, "dac_max_hz": BASE_HZ // DAC_MIN_PERIOD,
                "source": "measured on the unit (docs/10, 15); the device refuses what it cannot do"}


def waveform_to_dac_codes(waveform):
    """The daemon's uploaded waveform (Due-style 12-bit samples) as a whole-unit buffer of H7 DAC codes, or DeviceError.

    A sample's deviation from mid-scale (code - 2048) becomes the same deviation around the H7's zero code, so one code is one
    H7 step (5.98 mV); only DAC0 (tag 0) exists here. The swing cap is applied with h7_awg.check_codes, which refuses and never
    clamps. The buffer is tiled to a whole number of playback units (1024 samples), or refused if that is not possible.
    """
    if not waveform:
        raise DeviceError("play needs a waveform: none was uploaded")
    words = array.array("H"); words.frombytes(bytes(waveform[: len(waveform) // 2 * 2]))
    if any(w >> 12 for w in words):
        raise DeviceError("the H7 has one DAC: waveform samples must be tag 0")
    codes = [h7_awg.ZERO_CODE + (w & 0xFFF) - 2048 for w in words]
    tiles = 1024 // math.gcd(len(codes), 1024)
    if len(codes) * tiles > MAX_TILED_SAMPLES:
        raise DeviceError(f"a waveform of {len(codes)} samples cannot be tiled into whole 1024-sample playback units within {MAX_TILED_SAMPLES}")
    try:
        return h7_awg.check_codes(struct.pack(f"<{len(codes) * tiles}H", *(codes * tiles)))
    except h7_awg.SwingError as e:
        raise DeviceError(f"refused by the swing cap: {e}") from None


class SerialStream:
    """The real stream function. DTR is dropped at once: acquisition is started by the control RUN, not by a port being open.

    A run boundary belongs to the host, as it does for the Due (`BoardDevice.start`: a fresh `open_native` and `drain_until_quiet`): a unit may
    stop in the middle of a frame - the Due's bounded stop aborts the frame in flight on purpose - and the part of it that reached the host
    can sit in the kernel's read path until the next run's first bytes arrive and complete it. `reopen_and_drain` discards that."""

    def __init__(self, path):
        import transport
        self._t = transport
        self._path = path
        self._lock = threading.Lock()          # a read in progress holds the old descriptor: reopen waits for it
        self._open()

    def _open(self):
        self.port = self._t.open_raw(self._path, 115200, dtr=False)
        self.port.drop_dtr()          # opening raised it, and a stale line from an earlier open would start a run on its own

    def read(self, timeout=pacing.GLANCE):
        with self._lock:
            if not self._t.wait_any([self.port], timeout):
                return b""
            try:
                return self.port.read(1 << 20)
            except (BlockingIOError, InterruptedError):
                return b""

    def write(self, data):
        try:
            return self.port.write(data)
        except (BlockingIOError, InterruptedError):
            return 0

    def reopen_and_drain(self):
        """A fresh port, then everything it has to say discarded until it has been silent for pacing.SILENCE (capped). Returns the bytes thrown away."""
        with self._lock:
            try:
                self.port.drop_dtr()
                self.port.close()
            except OSError:
                pass
            self._open()
            stale, last, end = 0, time.time(), time.time() + pacing.QUICK
            while time.time() < end:
                if self._t.wait_any([self.port], pacing.POLL):
                    try:
                        stale += len(self.port.read(1 << 20))
                    except (BlockingIOError, InterruptedError):
                        pass
                    last = time.time()
                elif time.time() - last >= pacing.SILENCE:
                    break
            return stale

    def close(self):
        try:
            self.port.drop_dtr()
            self.port.close()
        except OSError:
            pass


class H7Device(Device):
    accepts_options = True            # a channel mask and options (gain, coupling) are passed by the server
    rate_policy = H7RatePolicy()

    def __init__(self, stream, control, *, calibration=None, adc_period_hint=None):
        self._stream, self._ctl = stream, control
        self._cal = calibration
        self._lock = threading.RLock()            # one control conversation at a time
        self._described = None
        self._readable = True          # closed while a run boundary is being made: the reader must not take bytes the drain means to discard
        self._feeder = None
        self._feed_stop = threading.Event()
        self._rx = 0
        self._awg_written = 0
        self.running = False
        self.mode = None
        self.rates = None
        self.closed = False

    @classmethod
    def open(cls, paths=None):
        """The real unit: stream and control nodes from ports.find_h7(), checked against its IDENTITY."""
        import ports
        paths = paths or ports.find_h7()
        if not paths:
            raise DeviceError("no H7 target found (1209:0001 with interfaces 0 and 2)")
        dev = cls(SerialStream(paths[0]), ctl.Control(paths[1]))
        dev.describe()
        return dev

    # -- the control channel -------------------------------------------------
    def _call(self, opcode, payload=b""):
        with self._lock:
            try:
                return self._ctl.call(opcode, payload)
            except ctl.ControlError as e:
                kind = {ctl.ERR_BUSY: "busy: ", ctl.ERR_LENGTH: "refused: "}.get(e.code, "")
                raise DeviceError(f"{kind}{e}") from None
            except (ctl.ProtocolError, OSError) as e:
                raise DeviceError(f"control channel: {e}") from None

    def _quiesce(self):
        """Stop whatever the unit is doing that this device did not start.

        Opening a tty raises DTR on Linux for an instant, which the image reads as the legacy "start streaming" and which then
        runs for the image's whole window; CONFIG is refused while anything runs. A start is the owner's decision, so a run it
        did not ask for is stopped first (STATUS bytes 0 and 1: running, playing).
        """
        st = self._status()
        if st[0] or st[1]:
            self._halt_unit()

    def _status(self):
        return _STATUS.unpack(self._call(OP_STATUS).payload)

    def _config(self):
        return _CFG.unpack(self._call(OP_CONFIG).payload)

    # -- description ----------------------------------------------------------
    def calibration(self):
        if self._cal is None:
            self._cal = h7_cal.Calibration.load_measured(100)
        return self._cal

    def describe(self, refresh=False):
        if self._described is not None and not refresh:
            return dict(self._described)
        (track, cv, fv, ma, mi, pa, fb, fs, mck, adc, build) = ctl._IDENTITY.unpack(self._call(ctl.OP_IDENTITY).payload)
        if chr(track) != "H" or fv != 4 or cv != ctl.VERSION:
            raise DeviceError(f"not an H7 target this host understands: track {chr(track)!r}, control {cv}, frame {fv}")
        # The gains and couplings are the unit's own, read back, so the volts a client computes follow what is actually set (docs/20, G7).
        cfg = self._config(); gains = {1: cfg[3], 2: cfg[4]}; dc = {1: bool(cfg[5] & 1), 2: bool(cfg[5] & 2)}
        cal = self.calibration()
        chans = [{"id": ch, "label": f"CH{ch}", "calibration": {"zero_code": cal.zero_code(ch, gains[ch]), "codes_per_volt": cal.codes_per_volt(ch, gains[ch]),
                                                                  "gain_code": gains[ch], "source": "factory scale, zero measured on this unit"},
                 "coupling": "dc" if dc[ch] else "ac", "range_v": h7_cal.FULL_SCALE_V[gains[ch]]} for ch in (1, 2)]
        self._described = {"kind": "h7", "track": "h", "frame_bytes": fb, "samples_per_frame": fs, "frame_version": fv,
                           "identity": {"fw": f"{ma}.{mi}.{pa}", "build": build.rstrip(b"\x00").decode("ascii", "replace"), "mck_hz": mck, "adc_clock_hz": adc},
                           "sample": {"bits": 16, "layout": "planar", "full_scale_codes": 65535},
                           "channels": chans,
                           "defaults": {"adc_hz": 1_000_000, "channels": 2},
                           "options": {"gain": list(range(8)), "coupling": ["dc", "ac"], "swing_limit_codes": h7_awg.SWING_LIMIT_CODES},
                           # What a generator panel needs to turn volts about 0 V into the Due-style 12-bit samples `waveform_to_dac_codes` takes
                           # (one sample code is one H7 DAC step) and to refuse, as the host does, what the swing cap would refuse.
                           "generator": {"output": "VOUT", "mv_per_code": h7_awg.MV_PER_CODE, "swing_limit_codes": h7_awg.SWING_LIMIT_CODES}}
        return dict(self._described)

    # -- running ----------------------------------------------------------------
    def _parse_options(self, options, current):
        """Gain and coupling for a start. A setting not named keeps what the unit has now (the description reports exactly that, so a client
        that sends no options runs on the scale it was told); the unit powers up at gain 0, DC. `current` is the unit's CONFIG readback."""
        opts = dict(options or {})
        gain = opts.pop("gain", [current[3], current[4]])
        coupling = opts.pop("coupling", ["dc" if current[5] & 1 else "ac", "dc" if current[5] & 2 else "ac"])
        if opts:
            raise DeviceError(f"unknown options {sorted(opts)}")
        g = list(gain) if isinstance(gain, (list, tuple)) else [gain, gain]
        c = list(coupling) if isinstance(coupling, (list, tuple)) else [coupling, coupling]
        if len(g) != 2 or len(c) != 2 or any(not isinstance(x, int) or not 0 <= x <= 7 for x in g) or any(x not in ("dc", "ac") for x in c):
            raise DeviceError("options: gain is 0-7 (one value or one per channel), coupling is 'dc' or 'ac' (one or two)")
        return g[0], g[1], (1 if c[0] == "dc" else 0) | (2 if c[1] == "dc" else 0)

    def start(self, mode, *, dac_sps=None, adc_hz=None, channels=2, waveform=None, preset=None, channel_mask=None, options=None):
        if self.closed:
            raise DeviceError("device is closed")
        if mode not in MODES:
            raise DeviceError(f"unknown mode {mode!r}")
        if self.running:
            raise DeviceError("already running; stop first")
        pol = self.rate_policy
        self._quiesce()
        self._readable = False
        try:
            self.stale_bytes = self._stream.reopen_and_drain()        # the previous run's tail, if any, is discarded here
        finally:
            self._readable = True
        cur = self._config()
        adc_p = pol.check_capture(adc_hz, channels)[0] if mode in ("capture", "loop") and adc_hz else cur[0]
        dac_p = pol.check_dac(dac_sps)[0] if mode in ("play", "loop") and dac_sps else cur[1]
        mask = channel_mask if channel_mask is not None else (1 if channels == 1 else 3)
        if mask not in (1, 2, 3):
            raise DeviceError(f"channel mask {mask}: 1 (CH1), 2 (CH2) or 3")
        g1, g2, coupling = self._parse_options(options, cur)
        buf = waveform_to_dac_codes(waveform) if mode in ("play", "loop") else None      # refused before anything is configured
        self._call(OP_CONFIG, _CFG.pack(adc_p, dac_p, mask, g1, g2, coupling, h7_awg.ZERO_CODE, 0))
        try:
            if buf is not None:
                self._call(OP_PLAY, bytes([1, PLAY_PRIME_UNITS]))
                self._start_feeder(buf)
            if mode in ("capture", "loop"):
                self._call(OP_RUN, b"\x01")
        except Exception:
            self._halt(); raise
        with self._lock:
            self._described = None                # the gains just set change what a code means: describe() reads them back
            self.running = True; self.mode = mode
            self.rates = {"dac_sps": dac_sps, "adc_hz": adc_hz, "channels": channels, "preset": preset, "channel_mask": mask}

    def _start_feeder(self, buf):
        """Write the buffer round and round. A chunk is whole copies of it (so the phase survives a short write) of about eight playback
        units, and a refused write backs off for 1 ms, not 10: the unit's ring holds 16 units, which is 8 ms at 2 MS/s."""
        chunk = buf * max(1, h7_awg.UNIT_BYTES * 8 // len(buf))
        self._feed_stop.clear()
        def feed():
            i = 0
            while not self._feed_stop.is_set():
                n = self._stream.write(chunk[i:])
                self._awg_written += n
                if n:
                    i = (i + n) % len(chunk)
                else:
                    pacing.pause(pacing.SPIN)
        self._feeder = threading.Thread(target=feed, name="h7-feeder", daemon=True)
        self._feeder.start()

    def _halt(self):
        self._feed_stop.set()
        if self._feeder is not None:
            self._feeder.join(pacing.NORMAL); self._feeder = None
        self._halt_unit()

    def _halt_unit(self):
        for op, body in ((OP_PLAY, bytes([0, 0])), (OP_RUN, b"\x00")):
            try:
                self._call(op, body)
            except DeviceError:
                pass

    def stop(self):
        self._halt()
        with self._lock:
            self.running = False; self.mode = None

    def close(self):
        self.stop()
        self._stream.close()
        if hasattr(self._ctl, "close"):
            self._ctl.close()
        self.closed = True

    # -- stream -------------------------------------------------------------------
    def read(self, timeout=pacing.GLANCE):
        if not self._readable:
            pacing.pause(min(timeout, pacing.POLL))
            return b""
        data = self._stream.read(timeout)
        self._rx += len(data)
        return data

    def stats(self):
        return {"rx_bytes": self._rx, "frames": self._rx // 4096, "awg_bytes": self._awg_written,
                "feeding": self._feeder is not None and self._feeder.is_alive()}

    def counters(self):
        """The Due's counter names, filled as docs/19 says, plus this target's own STATUS under `h7`."""
        vals = ctl._COUNTERS.unpack(self._call(ctl.OP_COUNTERS).payload)
        out = dict(zip(_COUNTER_NAMES, vals))
        st = _STATUS.unpack(self._call(OP_STATUS).payload)
        out["h7"] = dict(zip(("running", "playing", "play_timer", "chmask"), st[:4])) | dict(zip(_STATUS_NAMES, st[4:]))
        return out

    def trace(self):
        raise DeviceError("not implemented on this target: the H7 has no playback-ring trace")

    def load(self):
        raise DeviceError("not implemented on this target: the H7 has no main-loop load monitor")
