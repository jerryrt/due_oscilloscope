"""A Rigol DS1000E on the bench, over USBTMC.

Why this exists. Everything this project knows about issue #5 is what
the *converter* returned; `docs/HANDOFF.md` records that the central
claim - that the voltage at the pin actually moves - stays inference,
and every amplitude a lower bound, until an instrument that is not the
ADC says otherwise. This is that instrument.

Why not pyvisa. USBTMC's bulk protocol is a twelve-byte header and a
payload, and speaking it directly keeps the dependency to pyusb plus the
libusb binaries that ship inside `libusb-package` - no system libusb, no
`sudo`, no VISA stack to install per host. That matters because the
suite has to run unchanged on a machine with no scope attached.

Both imports are optional and failure is a *skip*, not an error: a host
without pyusb, or without a scope, must still collect and run the rest
of the suite.

Verified against a DS1102E, firmware 00.04.02.01.00, on 2026-08-26.
Everything below answered on that instrument; nothing here is written
from the programming guide alone.

Two traps, both paid for once already:

  * **The bulk header is twelve bytes**, not eleven. MsgID, bTag,
    ~bTag, reserved, a four-byte length, bmTransferAttributes, and three
    reserved. Pack eleven and the scope accepts the write, answers
    nothing, and the read times out with no diagnostic.

  * **`:MEAS:...?` returns 9.9e37 when it has no reading**, not an
    error. Parsed as a float that is 9.9e37 volts, and it will sail
    through any comparison written to catch a wrong number. `measure()`
    returns None for it instead.

And one that is not this module's to solve but belongs in the same
breath: `:CHAN<n>:PROB?` is what the *scope has been told* the probe is,
not what is clipped to the board. A 10x probe against a scope set to 1x
reads every voltage ten times small, and nothing in the data says so.
probe() is provided so a caller can assert it rather than assume it.
"""
from __future__ import annotations

import struct
import time

# Rigol's USB vendor ID, and the DS1000E-series product ID. A DS1102E
# reports 1AB1:0588; other Rigol families use other product IDs and are
# not claimed to work here.
RIGOL_VID = 0x1AB1
DS1000E_PID = 0x0588

# The scope answers a short query in well under a second. Long enough to
# absorb one retry, short enough that a wedged instrument fails the run
# rather than hanging it.
DEFAULT_TIMEOUT_MS = 5000

# What a DS1000E returns from a measurement it could not make.
NO_READING = 9.9e37

# How long the instrument needs after a state-changing write before a
# query reflects it. Empirical on a DS1102E: 0.05 s was not enough and
# 0.05 s more was.
POST_WRITE_S = 0.1


def _num(v):
    """Format a number the way this firmware will accept it.

    `%g` writes 1e-05, which a DS1102E ignores silently - the write is
    accepted, the setting does not change, and the readback returns the
    old value. Exponent notation is not the fix either: the instrument
    *replies* `5.000e-06` but does not reliably accept that form back,
    and a test that appeared to show it working was reading a setting
    already at the target. Plain decimal is what it takes.

    Even then a write does not always take. Setters here therefore
    return what the instrument *holds afterwards* rather than what was
    asked for: the value is quantised to the 1-2-5 sequence, clamped to
    a range that depends on other settings, and occasionally simply not
    applied. A caller that needs a specific value must compare.
    """
    return f"{float(v):.12f}"


class ScopeUnavailable(Exception):
    """No scope, or no way to reach one. Callers skip on this."""


def _backend():
    try:
        import libusb_package
    except ImportError as e:                                  # pragma: no cover
        raise ScopeUnavailable(f"libusb-package not installed: {e}")
    return libusb_package.get_libusb1_backend()


def find_scope(vid=RIGOL_VID, pid=DS1000E_PID):
    """The scope's USB device, or raise ScopeUnavailable.

    Deliberately raises rather than returning None: every caller wants
    to skip with a reason, and "no scope" and "no pyusb" are different
    reasons that a None cannot carry.
    """
    try:
        import usb.core
    except ImportError as e:                                  # pragma: no cover
        raise ScopeUnavailable(f"pyusb not installed: {e}")
    dev = usb.core.find(idVendor=vid, idProduct=pid, backend=_backend())
    if dev is None:
        raise ScopeUnavailable(
            f"no USB device {vid:04x}:{pid:04x} - scope off or unplugged")
    return dev


def usbtmc_header(msgid, tag, size, attrs):
    """One USBTMC bulk header. Twelve bytes, and the count is the trap.

    MsgID, bTag, the one's complement of bTag, one reserved byte, a
    four-byte little-endian transfer size, bmTransferAttributes, then
    three reserved. Eleven bytes is a header the scope accepts on the
    write and never answers, which presents as a read timeout with
    nothing to suggest the request was malformed.

    Module-level so the shape can be checked without an instrument
    attached - that failure cost a debugging round and should not be
    reachable again on a host with no scope.
    """
    return struct.pack("<BBBBIB3s", msgid, tag, ~tag & 0xFF, 0,
                       size, attrs, b"\x00\x00\x00")


def parse_block(raw):
    """Payload of an IEEE 488.2 definite-length block.

    `#` then one digit giving the width of the length field, then that
    many digits of length, then the data: a DS1000E screen read comes
    back as `#800000600` followed by 600 bytes. Returned unchanged if it
    is not a block, because some queries answer in plain ASCII and a
    caller should not have to know which.
    """
    if not raw[:1] == b"#" or len(raw) < 2 or not raw[1:2].isdigit():
        return raw
    width = int(raw[1:2])
    if width == 0 or len(raw) < 2 + width:
        return raw
    n = int(raw[2:2 + width])
    body = raw[2 + width:]
    return body[:n] if n <= len(body) else body


class Scope:
    """One DS1000E. Not thread-safe; one owner at a time."""

    def __init__(self, dev=None):
        import usb.util
        self.dev = dev if dev is not None else find_scope()
        try:
            self.dev.set_configuration()
        except Exception:
            # Already configured by a previous open. Not an error: the
            # instrument keeps its configuration across process exits,
            # and re-setting it would reset the scope's own state.
            pass
        cfg = self.dev.get_active_configuration()
        itf = cfg[(0, 0)]
        self._out = usb.util.find_descriptor(
            itf, custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_OUT)
        self._in = usb.util.find_descriptor(
            itf, custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_IN)
        if self._out is None or self._in is None:
            raise ScopeUnavailable("no bulk endpoint pair on interface 0")
        self._tag = 0

    # ---- USBTMC transport -------------------------------------------

    def _tag_next(self):
        # bTag cycles 1..255; zero is reserved.
        self._tag = (self._tag % 255) + 1
        return self._tag

    def _header(self, msgid, size, attrs):
        return usbtmc_header(msgid, self._tag_next(), size, attrs)

    def write(self, cmd, timeout=DEFAULT_TIMEOUT_MS):
        """One SCPI command. EOM set, padded to a four-byte boundary.

        The settle afterwards is not politeness. A query issued straight
        after a state-changing write returns the value the instrument
        held *before* it: measured here setting `:CHAN1:PROB 10` and
        reading `:CHAN1:PROB?` back as 1.0, while the channel's V/div had
        already rescaled by ten - so the write had landed and the
        readback had not caught up. A caller that sets and verifies would
        conclude the write failed and set it again.
        """
        payload = cmd.encode() + b"\n"
        pkt = self._header(1, len(payload), 0x01) + payload
        pkt += b"\x00" * (-len(pkt) % 4)
        self._out.write(pkt, timeout=timeout)
        time.sleep(POST_WRITE_S)

    def read_raw(self, size=1 << 16, timeout=DEFAULT_TIMEOUT_MS):
        """Request and return one response payload, header stripped."""
        self._out.write(self._header(2, size, 0x00), timeout=timeout)
        data = self._in.read(size + 64, timeout=timeout).tobytes()
        n = struct.unpack("<I", data[4:8])[0]
        return data[12:12 + n]

    def ask_raw(self, cmd, size=1 << 16, timeout=DEFAULT_TIMEOUT_MS,
                settle=0.05):
        self.write(cmd, timeout=timeout)
        # The instrument needs a moment between the command and the read
        # request; without it the read is issued before the response is
        # queued and times out.
        time.sleep(settle)
        return self.read_raw(size=size, timeout=timeout)

    def ask(self, cmd, **kw):
        return self.ask_raw(cmd, **kw).decode(errors="replace").strip()

    def ask_float(self, cmd, **kw):
        return float(self.ask(cmd, **kw))

    def _apply(self, cmd, query, value, tol=1e-3, timeout=2.0):
        """Write a numeric setting, then wait until it is reported back.

        A fixed delay after the write is the wrong shape for this
        instrument: 0.05 s was too short for `:CHAN:PROB`, 0.1 s was
        enough for it and too short for `:TIM:SCAL`, which needed about
        a second. Guessing a constant large enough for the slowest
        command taxes every other one.

        So poll instead, and return what the instrument holds when the
        wait ends - which is the honest answer whether the value was
        applied, quantised to the 1-2-5 sequence, or clamped against
        some other setting. A caller that needs an exact value compares;
        it can no longer be misled by a stale readback into thinking the
        write failed.
        """
        self.write(f"{cmd} {_num(value)}")
        deadline = time.time() + timeout
        while True:
            got = self.ask_float(query)
            if abs(got - value) <= max(tol, abs(value) * tol):
                return got
            if time.time() >= deadline:
                return got
            time.sleep(0.1)

    # ---- identity ----------------------------------------------------

    def identify(self):
        """(manufacturer, model, serial, firmware)."""
        parts = self.ask("*IDN?").split(",")
        while len(parts) < 4:
            parts.append("")
        return tuple(p.strip() for p in parts[:4])

    @property
    def model(self):
        return self.identify()[1]

    # ---- vertical, horizontal, trigger -------------------------------

    def channel_scale(self, ch, volts_per_div=None):
        if volts_per_div is not None:
            return self._apply(f":CHAN{ch}:SCAL", f":CHAN{ch}:SCAL?",
                               volts_per_div)
        return self.ask_float(f":CHAN{ch}:SCAL?")

    def channel_offset(self, ch, volts=None):
        if volts is not None:
            return self._apply(f":CHAN{ch}:OFFS", f":CHAN{ch}:OFFS?",
                               volts, tol=1e-2)
        return self.ask_float(f":CHAN{ch}:OFFS?")

    def coupling(self, ch, mode=None):
        if mode is not None:
            self.write(f":CHAN{ch}:COUP {mode}")
            return mode
        return self.ask(f":CHAN{ch}:COUP?")

    def probe(self, ch, ratio=None):
        """The attenuation the scope *believes*, not the one fitted.

        Read it and assert it. A 10x probe against a scope set to 1x
        reports every voltage ten times small and the data does not say
        so anywhere.
        """
        if ratio is not None:
            return self._apply(f":CHAN{ch}:PROB", f":CHAN{ch}:PROB?",
                               ratio)
        return self.ask_float(f":CHAN{ch}:PROB?")

    def timebase(self, seconds_per_div=None):
        if seconds_per_div is not None:
            return self._apply(":TIM:SCAL", ":TIM:SCAL?",
                               seconds_per_div)
        return self.ask_float(":TIM:SCAL?")

    def trigger_edge(self, source=None, level=None, slope=None, sweep=None):
        """Configure or read back the edge trigger.

        The reload of the DAC's PDC is DAC0's rising mid-scale crossing,
        so an edge trigger on that channel is a trigger on the wrap
        itself - which is what makes a once-per-2.56 ms event findable
        at all.
        """
        if source is not None:
            self.write(":TRIG:MODE EDGE")
            self.write(f":TRIG:EDGE:SOUR {source}")
        if slope is not None:
            self.write(f":TRIG:EDGE:SLOP {slope}")
        if sweep is not None:
            # AUTO sweeps even when nothing triggers, which is why an
            # untriggered trace crawls across the screen instead of
            # sitting still. NORMAL sweeps only on a real trigger, so a
            # stationary trace is itself evidence the trigger is finding
            # the edge - and a blank screen is evidence it is not.
            self.write(f":TRIG:EDGE:SWE {sweep}")
        if level is not None:
            self._apply(":TRIG:EDGE:LEV", ":TRIG:EDGE:LEV?",
                        level, tol=1e-2)
        return {"mode": self.ask(":TRIG:MODE?"),
                "source": self.ask(":TRIG:EDGE:SOUR?"),
                "slope": self.ask(":TRIG:EDGE:SLOP?"),
                "sweep": self.ask(":TRIG:EDGE:SWE?"),
                "level": self.ask_float(":TRIG:EDGE:LEV?"),
                "status": self.ask(":TRIG:STAT?")}

    def averaging(self, count=None):
        """Acquisition averaging - the scope's version of folding.

        Same argument and the same sqrt(n): the artifact is a few
        millivolts and averaging a few hundred triggered acquisitions is
        what brings it out of the noise. `count=None` returns to NORMAL.
        """
        if count is None:
            self.write(":ACQ:TYPE NORMAL")
            return None
        self.write(":ACQ:TYPE AVERAGE")
        self.write(f":ACQ:AVER {int(count)}")
        return int(self.ask_float(":ACQ:AVER?"))

    # ---- readings ----------------------------------------------------

    def measure(self, what, ch=1):
        """One measurement, or None where the scope had no reading.

        `:MEAS:FREQ? CHAN1` answers 9.9e37 with nothing connected. That
        is not an error and not a frequency; returning it as a float
        puts 9.9e37 into whatever the caller does next.
        """
        v = self.ask_float(f":MEAS:{what}? CHAN{ch}")
        return None if v >= NO_READING / 10 else v

    def waveform(self, ch=1, points="NORMAL"):
        """The displayed trace as volts, oldest sample first.

        Screen data is one byte per point, *inverted* - larger byte
        means lower voltage - and referenced to the channel's own scale
        and offset. The conversion below is the DS1000E's documented one
        and was checked against a known square on this bench rather than
        taken on trust.
        """
        self.write(f":WAV:POIN:MODE {points}")
        time.sleep(0.1)
        raw = parse_block(self.ask_raw(f":WAV:DATA? CHAN{ch}", settle=0.4))
        scal = self.channel_scale(ch)
        offs = self.channel_offset(ch)
        return [(240 - b) * scal / 25.0 - (offs + scal * 4.6) for b in raw]

    def close(self):
        try:
            import usb.util
            usb.util.dispose_resources(self.dev)
        except Exception:                                     # pragma: no cover
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
