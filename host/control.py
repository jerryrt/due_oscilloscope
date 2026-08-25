"""
Client for the native port's control channel.

The channel is a second CDC function on the same cable (see
docs/control-protocol.md); this is the framing on top of it. The wire
format is a contract shared with Track A, so this file is deliberately
the only place the host encodes or decodes it - two decoders drift, and
the whole point of the suite running --track=both is to compare one
decoder's output across two firmwares.

Every request carries an id the response echoes. That is not ceremony:
a late reply to an abandoned request would otherwise be read as the
answer to the next question, and this channel is meant to be polled.
"""

import os
import select
import struct
import termios
import threading
import time
import zlib

MAGIC = b"DUEC"
VERSION = 1
HDR_BYTES = 16
MAX_PAYLOAD = 448

FLAG_RESPONSE = 1 << 0
FLAG_ERROR = 1 << 1

OP_PING = 0x0001
OP_IDENTITY = 0x0002
OP_COUNTERS = 0x0020
OP_OCCUPANCY = 0x0021
OP_RATE_TRACE = 0x0022
OP_LOAD = 0x0024

LOAD_BUCKETS = 32

ERR_VERSION = 1
ERR_OPCODE = 2
ERR_LENGTH = 3
ERR_CRC = 4

_HDR = struct.Struct("<4sBBHHHI")
_PING = struct.Struct("<III")
_IDENTITY = struct.Struct("<BBBBHHII24s")
_LOAD = struct.Struct("<IIIIBB2x%dI" % LOAD_BUCKETS)
_COUNTERS = struct.Struct("<15I")
_OCC = struct.Struct("<IIIIIBBH")
_RATE_PAGE = struct.Struct("<BBHHH")


class ControlError(Exception):
    """The device answered, and the answer was a refusal."""

    def __init__(self, code, text, opcode=None):
        super().__init__(f"device refused (code {code}): {text}")
        self.code = code
        self.text = text
        self.opcode = opcode


class ProtocolError(Exception):
    """The device did not answer, or answered something unreadable."""


def encode(opcode, req_id, payload=b"", flags=0, version=VERSION,
           crc=None):
    """Build one frame.

    version and crc are overridable so tests can send frames a correct
    implementation never would. A parser is only as good as what it
    rejects, and nothing else in the suite could produce a bad one.
    """
    head = _HDR.pack(MAGIC, version, flags, req_id, opcode,
                     len(payload), 0)
    if crc is None:
        crc = zlib.crc32(head[:HDR_BYTES - 4] + payload) & 0xffffffff
    return head[:HDR_BYTES - 4] + struct.pack("<I", crc) + payload


def decode(buf):
    """Split one frame off the front of buf.

    Returns (frame, rest) or (None, buf) when buf does not yet hold a
    whole frame. Resyncs on the magic rather than assuming the buffer
    starts at a frame boundary.
    """
    at = buf.find(MAGIC)
    if at < 0:
        # Keep the last three bytes: the magic may straddle the seam.
        return None, buf[-3:] if len(buf) > 3 else buf
    buf = buf[at:]
    if len(buf) < HDR_BYTES:
        return None, buf
    magic, version, flags, req_id, opcode, length, crc = _HDR.unpack(
        buf[:HDR_BYTES])
    if len(buf) < HDR_BYTES + length:
        return None, buf
    payload = buf[HDR_BYTES:HDR_BYTES + length]
    want = zlib.crc32(buf[:HDR_BYTES - 4] + payload) & 0xffffffff
    frame = Frame(version, flags, req_id, opcode, payload, crc == want)
    return frame, buf[HDR_BYTES + length:]


class Frame:
    __slots__ = ("version", "flags", "req_id", "opcode", "payload",
                 "crc_ok")

    def __init__(self, version, flags, req_id, opcode, payload, crc_ok):
        self.version = version
        self.flags = flags
        self.req_id = req_id
        self.opcode = opcode
        self.payload = payload
        self.crc_ok = crc_ok

    @property
    def is_error(self):
        return bool(self.flags & FLAG_ERROR)

    @property
    def error(self):
        """(code, text) for an error frame."""
        if len(self.payload) < 2:
            return None, ""
        code = struct.unpack_from("<H", self.payload)[0]
        return code, self.payload[2:].decode("utf-8", "replace")

    def __repr__(self):
        return (f"Frame(op=0x{self.opcode:04x} id={self.req_id} "
                f"flags=0x{self.flags:02x} len={len(self.payload)} "
                f"crc_ok={self.crc_ok})")


class Control:
    """A conversation with the command port.

    Owns the fd. Does not open the sample port and must never be
    pointed at it: writing a command frame into the playback stream
    would be read as samples.
    """

    def __init__(self, path, timeout=1.0):
        from ports import open_raw

        self.path = path
        self.timeout = timeout
        self.fd = open_raw(path, 115200, dtr=True)
        self._buf = b""
        self._next_id = 1

    def close(self, wedge_s=5.0):
        """Flush, then close, and do not hang for ever if it wedges.

        Both halves are doctrine here rather than caution. `close()` on
        a tty drains the kernel output queue first, and a device that
        is not reading can never let those bytes leave - which is
        objective 0c, four times on record on the sample port and the
        reason measure.close_native() flushes before closing. This port
        is written to with deliberate rubbish by the tests, so it is
        the last place to leave that queue full.

        The watchdog is the other half. An unbounded hang here would
        hold the fd, and this project has already learned that turning
        a wedged close into a wedged open costs the bench rather than
        the run.
        """
        if self.fd is None:
            return
        fd, self.fd = self.fd, None
        try:
            termios.tcflush(fd, termios.TCIOFLUSH)
        except (OSError, termios.error):
            # termios.error is not an OSError, so `except OSError`
            # would not catch a port that had gone away.
            pass

        done = threading.Event()

        def _close():
            try:
                os.close(fd)
            finally:
                done.set()

        threading.Thread(target=_close, daemon=True,
                         name="close-control").start()
        if not done.wait(wedge_s):
            raise ProtocolError(
                f"close() on {self.path} has not returned in "
                f"{wedge_s:.0f} s; the command endpoint is not being "
                f"drained. See objective 0c.")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def drain(self, secs=0.25):
        """Read and discard whatever is still coming.

        Called before closing so that a response the caller never asked
        for - a refusal to a deliberately malformed frame, say - is off
        the wire rather than sitting in the receive queue.
        """
        end = time.time() + secs
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if not r:
                break
            try:
                if not os.read(self.fd, 4096):
                    break
            except (BlockingIOError, OSError):
                break
        self._buf = b""

    # -- raw ---------------------------------------------------------
    def send_raw(self, data):
        os.set_blocking(self.fd, True)
        try:
            n = os.write(self.fd, data)
        finally:
            os.set_blocking(self.fd, False)
        if n != len(data):
            raise ProtocolError(f"short write: {n} of {len(data)}")

    def recv(self, timeout=None):
        """Next whole frame, or None on timeout."""
        end = time.time() + (self.timeout if timeout is None else timeout)
        while True:
            frame, self._buf = decode(self._buf)
            if frame is not None:
                return frame
            left = end - time.time()
            if left <= 0:
                return None
            r, _, _ = select.select([self.fd], [], [], min(left, 0.1))
            if r:
                try:
                    chunk = os.read(self.fd, 4096)
                except (BlockingIOError, OSError):
                    chunk = b""
                if chunk:
                    self._buf += chunk

    # -- request/response --------------------------------------------
    def request(self, opcode, payload=b"", timeout=None, **kw):
        """Send one command and return its response frame.

        Raises rather than returning a mismatched reply: an answer to
        someone else's question that reads as an answer to this one is
        the failure req_id exists to prevent, so it must not be
        silently tolerated here either.
        """
        req_id = kw.pop("req_id", None)
        if req_id is None:
            req_id = self._next_id
            self._next_id = self._next_id % 0xffff + 1
        self.send_raw(encode(opcode, req_id, payload, **kw))

        end = time.time() + (self.timeout if timeout is None else timeout)
        while True:
            frame = self.recv(timeout=max(0.0, end - time.time()))
            if frame is None:
                raise ProtocolError(
                    f"no response to opcode 0x{opcode:04x} within "
                    f"{self.timeout if timeout is None else timeout:.1f} s")
            if frame.req_id != req_id:
                # A stale answer to an abandoned request. Drop it and
                # keep waiting rather than returning it as this one's.
                continue
            if not frame.crc_ok:
                raise ProtocolError(f"bad checksum on {frame!r}")
            return frame

    def call(self, opcode, payload=b"", **kw):
        """request(), but a refusal is raised rather than returned."""
        frame = self.request(opcode, payload, **kw)
        if frame.is_error:
            code, text = frame.error
            raise ControlError(code, text, frame.opcode)
        return frame

    # -- commands ----------------------------------------------------
    def ping(self):
        """(dev_us, dev_ms, seq) from the device's own clock."""
        frame = self.call(OP_PING)
        return _PING.unpack(frame.payload)

    def counters(self):
        """What `B` prints, without printing it.

        This is the one polled while the board is working. The console
        form costs 13.14 ms of blocked main loop and drains no bulk OUT
        for any of it, which is how a host ends up wedged in close() -
        see objective 0c. Nothing here should ever go back to `B`.
        """
        frame = self.call(OP_COUNTERS)
        (dev_us, bytes_in, produced, consumed, underruns, isr_calls,
         endtx_seen, spans, partial, occ_min, svc_calls, loop_passes,
         run_us, abandoned, drain_polls) = _COUNTERS.unpack(frame.payload)
        return {
            "dev_us": dev_us, "bytes_in": bytes_in, "produced": produced,
            "consumed": consumed, "underruns": underruns,
            "isr_calls": isr_calls, "endtx": endtx_seen, "spans": spans,
            "partial": partial, "occ_min": occ_min,
            "svc_calls": svc_calls, "loop_passes": loop_passes,
            "run_us": run_us, "abandoned": abandoned,
            "drain_polls": drain_polls,
        }

    def occupancy(self):
        """The playback ring's occupancy histogram and its trace.

        Variable length: the trace is only as long as it has been
        filled. The device says how many entries it sent rather than the
        host inferring it from the frame, so a short read is an error
        here instead of a silently truncated trace.
        """
        frame = self.call(OP_OCCUPANCY)
        (dev_us, occ_min, endtx, run_us, consumed, nbuf, decim,
         trace_n) = _OCC.unpack_from(frame.payload, 0)
        at = _OCC.size
        want = at + nbuf * 4 + trace_n
        if len(frame.payload) != want:
            raise ProtocolError(
                f"occupancy payload is {len(frame.payload)} bytes, "
                f"expected {want} for {nbuf} buckets and {trace_n} "
                f"trace entries")
        hist = list(struct.unpack_from("<%dI" % nbuf, frame.payload, at))
        at += nbuf * 4
        trace = list(frame.payload[at:at + trace_n])
        return {"dev_us": dev_us, "occ_min": occ_min, "endtx": endtx,
                "run_us": run_us, "consumed": consumed, "hist": hist,
                "decim": decim, "trace": trace}

    def rate_trace(self):
        """The consumed-buffer timestamp trace, paged.

        PLAY_RATE_TRACE entries of four bytes do not fit one packet, and
        a response that spans packets can be truncated silently by a
        single-banked endpoint. So the device pages it and this walks
        the pages, trusting the count it reports rather than assuming
        the page size.

        Usually empty: PLAY_RATE_TRACE_ENABLED is 0 by default because
        the trace perturbs the path it measures.
        """
        out = []
        decim = 0
        offset = 0
        while True:
            frame = self.call(OP_RATE_TRACE, struct.pack("<H", offset))
            (decim, _res, total, got_off,
             count) = _RATE_PAGE.unpack_from(frame.payload, 0)
            if got_off != offset:
                raise ProtocolError(
                    f"asked for rate trace at {offset}, device answered "
                    f"for {got_off}")
            if count:
                out.extend(struct.unpack_from(
                    "<%dI" % count, frame.payload, _RATE_PAGE.size))
            offset += count
            if count == 0 or offset >= total:
                break
        return {"decim": decim, "us": out}

    def load(self):
        """Main-loop load: how hard the device is working, right now.

        Cumulative since boot or since the last clear, so a rate comes
        from differencing two of these over whatever interval the caller
        wants. max_us is the exception - a maximum cannot be
        differenced, so it is the worst pass since the last clear.

        The histogram is floor(log2(cycles)) per pass. A healthy idle
        board puts essentially every pass in one bucket; anything that
        blocks the loop shows up as a lone count several buckets to the
        right, which is what makes an outlier legible at a glance.
        """
        frame = self.call(OP_LOAD)
        got = _LOAD.unpack(frame.payload)
        dev_us, passes, max_cycles, mck_hz, available, buckets = got[:6]
        hist = list(got[6:])
        if not available:
            raise ProtocolError(
                "the device reports no cycle counter, so every pass "
                "would read as zero cycles - treat the figures as absent "
                "rather than as a very fast loop")
        if buckets != LOAD_BUCKETS:
            raise ProtocolError(
                f"device reports {buckets} histogram buckets, this host "
                f"expects {LOAD_BUCKETS}")
        per_us = mck_hz / 1e6
        return {
            "dev_us": dev_us,
            "passes": passes,
            "max_cycles": max_cycles,
            "max_us": max_cycles / per_us,
            "mck_hz": mck_hz,
            "hist": hist,
            # Bucket i covers [2^i, 2^(i+1)) cycles.
            "hist_us": [(1 << i) / per_us for i in range(len(hist))],
        }

    def identity(self):
        frame = self.call(OP_IDENTITY)
        (track, ctl_ver, frame_ver, _res, frame_bytes, frame_samples,
         mck_hz, adc_clock_hz, build) = _IDENTITY.unpack(frame.payload)
        return {
            "track": chr(track).lower(),
            "ctl_version": ctl_ver,
            "frame_version": frame_ver,
            "frame_bytes": frame_bytes,
            "frame_samples": frame_samples,
            "mck_hz": mck_hz,
            "adc_clock_hz": adc_clock_hz,
            "build": build.rstrip(b"\x00").decode("ascii", "replace"),
        }
