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
import struct
import threading
import time
import zlib

import transport

MAGIC = b"DUEC"
# 2: IDENTITY grew the firmware version over its reserved byte, so its
# response is 42 bytes where 1 sent 40. The device refuses a frame whose
# version is not its own (drivers/ctl.c), which is the point: a host and
# a board that disagree fail immediately instead of misparsing.
VERSION = 3
HDR_BYTES = 16
MAX_PAYLOAD = 448

FLAG_RESPONSE = 1 << 0
FLAG_ERROR = 1 << 1

OP_PING = 0x0001
OP_IDENTITY = 0x0002
OP_CAPABILITY = 0x0003
OP_GEN = 0x0010
OP_COUNTERS = 0x0020
OP_OCCUPANCY = 0x0021
OP_RATE_TRACE = 0x0022
OP_STREAM_STATS = 0x0023
OP_LOAD = 0x0024
OP_BENCH = 0x0025
OP_TEMP = 0x0026
OP_HEARTBEAT = 0x0027

LOAD_BUCKETS = 32

ERR_VERSION = 1
ERR_OPCODE = 2
ERR_LENGTH = 3
ERR_CRC = 4
# Implemented and well-formed, but not right now - a capture is armed and
# switching the ADC's channels would corrupt it. Distinct from ERR_OPCODE
# because a retry fixes this one and never fixes that one.
ERR_BUSY = 5

_HDR = struct.Struct("<4sBBHHHI")
_PING = struct.Struct("<III")
_STREAM_STATS = struct.Struct("<23I")
_BENCH = struct.Struct("<9I")
_IDENTITY = struct.Struct("<BBBBBBHHII24s")
_LOAD = struct.Struct("<IIIIBB2x%dI" % LOAD_BUCKETS)
_COUNTERS = struct.Struct("<15I")
_OCC = struct.Struct("<IIIIIBBH")
_RATE_PAGE = struct.Struct("<BBHHH")
_TEMP = struct.Struct("<IIHHHBBII")
#: seq, uptime_ms, period_ms, dropped, then ctl_counters_t whole.
_HEARTBEAT = struct.Struct("<4I" + _COUNTERS.format.lstrip("<"))

# Matches CTL_TEMP_SAMPLES_* in lib/due_shared/src/ctl_wire.h. Passed
# through rather than enforced here: the device clamps and reports what
# it actually averaged, so a host that disagreed would be arguing with
# the only party that knows.
TEMP_SAMPLES_DEFAULT = 256



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
            fd.flush_both()
        except OSError:
            # The platform's own flush error is swallowed inside
            # transport.flush_both(); termios.error is not an OSError
            # would not catch a port that had gone away.
            pass

        done = threading.Event()

        def _close():
            try:
                fd.close()
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
            r = transport.wait_any([self.fd], 0.05)
            if not r:
                break
            try:
                if not self.fd.read(4096):
                    break
            except (BlockingIOError, OSError):
                break
        self._buf = b""

    # -- raw ---------------------------------------------------------
    def send_raw(self, data):
        self.fd.set_blocking(True)
        try:
            n = self.fd.write(data)
        finally:
            self.fd.set_blocking(False)
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
            r = transport.wait_any([self.fd], min(left, 0.1))
            if r:
                try:
                    chunk = self.fd.read(4096)
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

    def stream_stats(self):
        """What `?` prints, without printing it.

        The console form is twenty-four numbers and a uart_flush on a
        board that is streaming when you want to read them - invariant 8,
        and the same reason counters() exists. Nothing that measures
        should go back to `?`.
        """
        f = self.call(OP_STREAM_STATS)
        k = ("dma_frames", "dma_stalls", "frames", "bytes", "run_us",
             "produced", "consumed", "ring_overflow", "resync", "refused",
             "rxbuff_overruns", "govre", "gen_endtx",
             "usb_reset", "usb_setup", "usb_stall", "usb_configured",
             "usb_line_state", "usb_cfg_fail",
             "usb_isr", "usb_devisr", "usb_ep0isr", "usb_devimr")
        return dict(zip(k, _STREAM_STATS.unpack(f.payload)))

    def bench(self):
        """The bench half of `B`, with the division done here.

        The device reports bytes and microseconds. A throughput is
        arithmetic over two of its counters and nothing about it needs a
        Cortex-M3 to do it, least of all one that is mid-benchmark.
        """
        f = self.call(OP_BENCH)
        k = ("mode", "in_bytes", "out_bytes", "elapsed_us",
             "resets", "turn", "dma_in_arms", "dma_out_arms", "loop_passes")
        d = dict(zip(k, _BENCH.unpack(f.payload)))
        us = d["elapsed_us"] or 1
        d["in_mbps"] = d["in_bytes"] / us
        d["out_mbps"] = d["out_bytes"] / us
        return d

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

    def temperature(self, samples=None):
        """The on-die temperature sensor, averaged on the device.

        **Read this before quoting the number.** It is not a
        temperature in degrees and it is not a value for ADVREF noise.

        ADVREF is the reference for the ADC *and* the DAC, so the
        loopback is ratiometric and divides its own reference out
        exactly - a 1% excursion moves the loop by zero codes at every
        code. The sensor is a bandgap-derived *absolute* voltage, so it
        goes as 1/ADVREF and sees fractional reference noise at full
        weight. That is what it is for. Issue #11.

        What it cannot do, in the issue's own words and repeated here
        because this docstring will outlive the thread:

        - **No degrees.** Converting needs the datasheet slope and a
          per-part offset that is uncalibrated on this board. `code` is
          what the converter returned; apply a calibration when one
          exists.
        - **An upper bound, not a value.** One channel cannot separate
          the sensor's own noise from the reference's. A comparison
          *between benches* is a difference in which the sensor's
          contribution is common, which is what makes it useful anyway.
        - **Bandwidth.** The sensor is slow and filtered, so a null
          result does not close the question - the fast part, where
          ratiometric cancellation is weakest, may not reach it at all.

        `samples` is a request. The device clamps it and reports what it
        averaged, which is what comes back in `samples`.
        """
        payload = b""
        if samples is not None:
            payload = struct.pack("<H", int(samples))
        frame = self.call(OP_TEMP, payload)
        (dev_us, code_x16, code_min, code_max, n, channel, _reserved,
         adc_mr, adc_acr) = _TEMP.unpack(frame.payload)
        if not n:
            raise ProtocolError(
                "the device reported a temperature reading averaged over "
                "zero conversions, which it should have refused instead")
        return {
            "dev_us": dev_us,
            # Sixteenths on the wire so the average survives the integer
            # it travels in: 256 samples of a 4-code-rms signal resolve
            # to ~0.25 codes, and rounding to a whole code throws the
            # measurement away.
            "code": code_x16 / 16.0,
            "code_min": code_min,
            "code_max": code_max,
            "samples": n,
            "channel": channel,
            # The conditions, as the hardware held them *during* the
            # conversions. A reading taken at one track/settling time is
            # not comparable with one taken at another.
            "adc_mr": adc_mr,
            "adc_acr": adc_acr,
            "tson": bool(adc_acr & (1 << 4)),
        }

    def _decode_heartbeat(self, payload):
        f = _HEARTBEAT.unpack(payload)
        seq, uptime_ms, period_ms, dropped = f[:4]
        c = f[4:]
        return {
            "seq": seq, "uptime_ms": uptime_ms, "period_ms": period_ms,
            "dropped": dropped,
            "counters": {
                "dev_us": c[0], "bytes_in": c[1], "produced": c[2],
                "consumed": c[3], "underruns": c[4], "isr_calls": c[5],
                "endtx": c[6], "spans": c[7], "partial": c[8],
                "occ_min": c[9], "svc_calls": c[10], "loop_passes": c[11],
                "run_us": c[12], "abandoned": c[13], "drain_polls": c[14],
            },
        }

    def heartbeat(self, period_ms=None):
        """Read the beat setting, or set it. Returns the device's answer.

        `period_ms=0` stops it. Anything else is clamped by the device
        to [CTL_HEARTBEAT_MIN_MS, CTL_HEARTBEAT_MAX_MS] and the reply
        says what it actually took, so the caller never has to assume
        its request was honoured.
        """
        payload = b"" if period_ms is None else struct.pack("<I", period_ms)
        frame = self.call(OP_HEARTBEAT, payload)
        return self._decode_heartbeat(frame.payload)

    def beats(self, seconds, limit=None):
        """Collect unsolicited heartbeats for `seconds`.

        The device sends these on its own schedule with `req_id` zero,
        which every request() drops as "not my answer" - so they have to
        be read somewhere that is looking for them, and this is it.

        The point of the sequence number is what this returns: gaps mean
        beats the endpoint refused because nothing was reading, and no
        beats at all means the main loop stopped, which is the one thing
        a request-response channel can never tell you.
        """
        end = time.time() + seconds
        out = []
        while time.time() < end:
            frame = self.recv(timeout=max(0.0, end - time.time()))
            if frame is None:
                break
            if frame.req_id != 0 or frame.opcode != OP_HEARTBEAT:
                continue
            if not frame.crc_ok:
                raise ProtocolError(f"bad checksum on {frame!r}")
            out.append(self._decode_heartbeat(frame.payload))
            if limit is not None and len(out) >= limit:
                break
        return out

    def capabilities(self):
        """The opcodes this build dispatches, as a set of numbers.

        Issue #7. The device answers what it implements rather than a
        host discovering it by collecting CTL_ERR_OPCODE one call at a
        time - and the device builds the list from the same word its
        dispatch refuses on, so the list and the refusal cannot drift
        apart.

        A list of opcodes rather than a bitmap on purpose: a bitmap is
        silent about every opcode added after the host reading it was
        written, and an unknown bit reads as "not implemented" - the
        same defect as a body of zeroes, which is what this opcode
        exists to remove.

        It answers "does this build dispatch it", which is not "is it
        working right now". CTL_OP_LOAD still reports its own
        `available`, and a part without CYCCNT says so there.
        """
        frame = self.call(OP_CAPABILITY)
        if len(frame.payload) < 2:
            raise ProtocolError("capability reply is %d bytes, need at "
                                "least 2" % len(frame.payload))
        (n,) = struct.unpack_from("<H", frame.payload, 0)
        want = 2 + 2 * n
        # Trailing bytes are tolerated, not rejected. docs/control-protocol.md
        # reserves 0x0003 for a wider capability report - the rate table and
        # the channel map are later slices of the same opcode - and a host
        # that refused a body longer than it understood would break on the
        # firmware that adds them. Short is still an error: that is a body
        # that cannot mean what it says.
        if len(frame.payload) < want:
            raise ProtocolError(
                "capability says %d opcodes but the body is only %d bytes, "
                "need %d" % (n, len(frame.payload), want))
        return set(struct.unpack_from("<%dH" % n, frame.payload, 2))

    def identity(self):
        frame = self.call(OP_IDENTITY)
        (track, ctl_ver, frame_ver, fw_maj, fw_min, fw_pat, frame_bytes,
         frame_samples, mck_hz, adc_clock_hz,
         build) = _IDENTITY.unpack(frame.payload)
        return {
            "track": chr(track).lower(),
            "ctl_version": ctl_ver,
            "frame_version": frame_ver,
            # The firmware version, which is neither wire contract above:
            # it says which build is on the board when both are unchanged.
            "fw_version": f"{fw_maj}.{fw_min}.{fw_pat}",
            "fw": (fw_maj, fw_min, fw_pat),
            "frame_bytes": frame_bytes,
            "frame_samples": frame_samples,
            "mck_hz": mck_hz,
            "adc_clock_hz": adc_clock_hz,
            "build": build.rstrip(b"\x00").decode("ascii", "replace"),
        }
