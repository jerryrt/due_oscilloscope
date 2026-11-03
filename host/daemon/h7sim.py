"""A simulated H7 unit for board-free tests and the GUI: the REAL firmware control dispatcher (targets/h7tool/fw/ctl_h7.c, compiled for
the host with stub hooks) behind host/control.py's own frame encoder and decoder, plus a synthetic version-4 frame source whose
behaviour follows what the dispatcher reports (running, channel mask, ADC period). So a daemon test that starts, configures and stops
this device exercises the same control code that runs on the unit; only the sample source and the stub state are simulated.

Needs a host C compiler (gcc or cc) to build the dispatcher once; `available()` says whether there is one. A caller that cannot
build it must skip, and a skip is not a pass.
"""
import ctypes
import hashlib
import math
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import zlib

import pacing
import control as ctl
from .h7device import H7Device

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SRC = [os.path.join(_REPO, "targets/h7tool/fw/ctl_h7.c"), os.path.join(_REPO, "targets/h7tool/tools/h7_ctl_stub.c"),
        os.path.join(_REPO, "lib/due_shared/src/crc32.c")]
_INC = [os.path.join(_REPO, p) for p in ("lib/due_shared/src", "lib/wire", "targets/h7tool/fw")]
_lib = None


def available():
    return shutil.which("gcc") is not None or shutil.which("cc") is not None


def build_dispatcher():
    """The compiled dispatcher, built once per source state into the temp directory."""
    global _lib
    if _lib is not None:
        return _lib
    cc = shutil.which("gcc") or shutil.which("cc")
    if cc is None:
        raise RuntimeError("no host C compiler: the simulated H7 cannot be built")
    key = hashlib.sha256(b"".join(open(f, "rb").read() for f in _SRC)).hexdigest()[:12]
    out = os.path.join(tempfile.gettempdir(), f"h7sim_ctl_{key}.so")
    if not os.path.exists(out):
        tmp = out + f".{os.getpid()}"
        subprocess.run([cc, "-std=gnu11", "-shared", "-fPIC", "-O1", "-Werror=implicit"] + ["-I" + i for i in _INC] + ["-o", tmp] + _SRC, check=True)
        os.replace(tmp, out)
    lib = ctypes.CDLL(out)
    lib.ctl_h7_handle.restype = ctypes.c_size_t
    _lib = lib
    return lib


class SimControl:
    """host/control.py's Control, minus the serial port: same `call()`, errors raised the same way."""

    def __init__(self):
        self._lib = build_dispatcher()
        self._id = 1
        self._lock = threading.Lock()
        # One compiled library serves every simulated unit in the process, and it keeps its settings; a new unit powers up at gain 0 on both
        # channels, DC, stopped.
        for op, body in ((0x0042, bytes([0, 0])), (0x0041, b"\x00")):
            self.call(op, body)
        cfg = list(struct.unpack("<IIBBBBHH", self.call(0x0040).payload)); cfg[3] = cfg[4] = 0; cfg[5] = 3
        self.call(0x0040, struct.pack("<IIBBBBHH", *cfg))

    def call(self, opcode, payload=b"", **kw):
        with self._lock:
            req_id = self._id; self._id = self._id % 0xffff + 1
            tx = ctypes.create_string_buffer(512)
            frame = ctl.encode(opcode, req_id, payload, **kw)
            n = self._lib.ctl_h7_handle(ctypes.c_char_p(frame), ctypes.c_size_t(len(frame)), tx)
        f, _ = ctl.decode(tx.raw[:n])
        if f is None or not f.crc_ok or f.req_id != req_id:
            raise ctl.ProtocolError(f"simulated unit gave no valid reply to 0x{opcode:04x}")
        if f.is_error:
            code, text = f.error
            raise ctl.ControlError(code, text, f.opcode)
        return f

    def close(self):
        pass


class SimStream:
    events = None                 # a list the test shares with the control side, to check the order of a run boundary
    """A synthetic sample function. It asks the dispatcher whether the unit is running, so a stop or a refused start has its effect
    here exactly as on the unit. Frames are version 4, planar, 16-bit; CH1 a 1 kHz sine of 1 V and CH2 of 0.5 V, in each channel's
    own calibration so a host that applies the description's calibration recovers the volts."""

    def __init__(self, control, calibration, *, pace=False, tone_hz=1000.0):
        self._ctl, self._cal, self.pace, self.tone_hz = control, calibration, pace, tone_hz
        self.written = bytearray()
        self.write_calls = 0
        self._seq = 0; self._phase = 0.0; self._t = 0.0
        self._st, self._st_t = None, 0.0
        self.closed = False

    def _status(self):
        """The unit's state, asked of the dispatcher at most every 20 ms. A real stream read never touches the control channel; a
        simulated one that did, on every read, would take the control lock in a tight loop and starve the start request that needs it."""
        now = time.monotonic()
        if self._st is None or now - self._st_t > 0.02:
            self._st = struct.unpack("<4B17I", self._ctl.call(0x0043).payload); self._st_t = now
        return self._st

    def read(self, timeout=pacing.GLANCE):
        st = self._status()
        if not st[0]:
            time.sleep(min(timeout, pacing.POLL)); return b""
        mask, period = st[3], st[4]
        cfg = struct.unpack("<IIBBBBHH", self._ctl.call(0x0040).payload); gains = {1: cfg[3], 2: cfg[4]}       # the gain the host set
        rate = BASE / period; ids = [i + 1 for i in range(2) if mask >> i & 1]; per = 2032 // len(ids)
        if self.pace:
            pacing.pause(per / rate)
        payload = bytearray()
        for ch in ids:
            amp = 1.0 if ch == 1 else 0.5
            z, cpv = self._cal.zero_code(ch, gains[ch]), self._cal.codes_per_volt(ch, gains[ch])
            codes = [min(65535, max(0, int(round(z + cpv * amp * math.sin(2 * math.pi * self.tone_hz * (self._t + i / rate)))))) for i in range(per)]
            payload += struct.pack(f"<{per}H", *codes)
        self._t += per / rate
        hdr = struct.pack("<4sBBHIIIII", b"DUE0", 4, 0, mask, self._seq, int(rate), int(self._t * 1e6) & 0xFFFFFFFF, 0, 0)
        hdr += struct.pack("<I", zlib.crc32(hdr) & 0xFFFFFFFF)          # the header CRC the splitter checks, as the firmware writes it
        self._seq += 1
        pacing.pause(pacing.SPIN)                       # yield: a real endpoint delivers a frame per transfer, not per CPU cycle
        return hdr + bytes(payload)

    def reopen_and_drain(self):
        """Nothing is buffered in the simulation; the call is what a test observes."""
        if self.events is not None:
            self.events.append("reopen_and_drain")
        return 0

    def write(self, data):
        """Accept one packet's worth per call and then pause: a real endpoint NAKs when its ring is full, so a writer cannot spin.
        Only the first MiB is kept (tests look at what was sent, not at an unbounded log)."""
        self.write_calls += 1
        take = data[:2048]
        if len(self.written) < (1 << 20):
            self.written += take
        pacing.pause(pacing.SPIN)
        return len(take)

    def close(self):
        self.closed = True


BASE = 200_000_000


def make_sim_device(*, pace=False, calibration=None):
    from h7_cal import Calibration
    cal = calibration or Calibration.load_measured(100)
    c = SimControl()
    return H7Device(SimStream(c, cal, pace=pace), c, calibration=cal)
