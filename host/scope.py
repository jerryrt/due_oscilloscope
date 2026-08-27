"""A bench oscilloscope, whichever one is on the bench.

Why this exists. Everything this project knows about issue #5 is what
the *converter under investigation* returned; `docs/HANDOFF.md` records
the consequence - that the voltage at the DAC pin actually moves stays
inference, and every amplitude a lower bound, until an instrument that
is not the ADC says otherwise. This is that instrument.

Three layers, because the bench is not promised to keep the same scope:

    UsbTmc          the transport. USBTMC's bulk protocol, and nothing
                    about any particular instrument.
    Oscilloscope    the interface. What this project asks a scope to do,
                    named once so callers never learn a dialect.
    RigolDS1000E    one driver. Every quirk below lives here, because
                    every one of them is this model's and not USBTMC's.

Adding a second model is a class and a line in DRIVERS. Nothing that
calls `open_scope()` changes, which is the point: tests and tools are
written against `Oscilloscope`, and a DS1102E today must not become a
rewrite when it is something else tomorrow.

Why not pyvisa. macOS has no kernel driver for USBTMC, so raw USB is
required either way, and `libusb-package` carries prebuilt libusb
binaries - which keeps this to a pip install rather than a system
package and a sudo. Both imports are lazy and absence raises
ScopeUnavailable, so a host with neither still collects and runs the
whole suite.
"""
from __future__ import annotations

import struct
import time
import zlib

# A short query answers in well under a second. Long enough to absorb a
# retry, short enough that a wedged instrument fails the run rather than
# hanging it.
DEFAULT_TIMEOUT_MS = 5000


class ScopeUnavailable(Exception):
    """No scope, or no way to reach one. Callers skip on this."""


# ---------------------------------------------------------------------
# Transport: USBTMC. Model-independent.
# ---------------------------------------------------------------------

def usbtmc_header(msgid, tag, size, attrs):
    """One USBTMC bulk header. Twelve bytes, and the count is the trap.

    MsgID, bTag, the one's complement of bTag, one reserved byte, a
    four-byte little-endian transfer size, bmTransferAttributes, then
    three reserved. Eleven bytes is a header the instrument accepts on
    the write and never answers, which presents as a read timeout with
    nothing to suggest the request was malformed.

    Module-level so the shape is checkable with no instrument attached.
    """
    return struct.pack("<BBBBIB3s", msgid, tag, ~tag & 0xFF, 0,
                       size, attrs, b"\x00\x00\x00")


def parse_block(raw):
    """Payload of an IEEE 488.2 definite-length block.

    `#`, one digit giving the width of the length field, that many
    digits of length, then the data: a screen read comes back as
    `#800000600` followed by 600 bytes. Returned unchanged if it is not
    a block, because most queries answer in plain ASCII and a caller
    should not have to know which kind it is about to get.
    """
    if raw[:1] != b"#" or len(raw) < 2 or not raw[1:2].isdigit():
        return raw
    width = int(raw[1:2])
    if width == 0 or len(raw) < 2 + width:
        return raw
    n = int(raw[2:2 + width])
    body = raw[2 + width:]
    return body[:n] if n <= len(body) else body


def bmp_to_png(bmp):
    """An 8-bit palette BMP as PNG bytes. No Pillow.

    The instrument hands back a BMP and nothing else reads BMP happily -
    a browser will, but at 75 kB a shot and 48 shots a sweep that is
    3.6 MB of screenshots to move around. The same image as a palette
    PNG is a few kB, because a scope screen is mostly one background
    colour and that is exactly what DEFLATE is for.

    Pillow would do this in one line and is not a dependency this file
    is worth adding one for: PNG with a palette is a signature, three
    chunks and a CRC, and zlib is already in the standard library.
    """
    if bmp[:2] != b"BM":
        raise ValueError("not a BMP")
    pix_off, = struct.unpack("<I", bmp[10:14])
    hdr, = struct.unpack("<I", bmp[14:18])
    w, h = struct.unpack("<ii", bmp[18:26])
    bpp, = struct.unpack("<H", bmp[28:30])
    comp, = struct.unpack("<I", bmp[30:34])
    if bpp != 8 or comp != 0:
        raise ValueError(f"only uncompressed 8-bit BMP, got {bpp}bpp "
                         f"compression {comp}")
    # BGRA palette entries, and PNG wants RGB.
    pal = bmp[14 + hdr:pix_off]
    plte = bytearray()
    for i in range(0, min(len(pal), 256 * 4), 4):
        plte += bytes((pal[i + 2], pal[i + 1], pal[i]))
    plte += b"\x00" * (768 - len(plte))

    # BMP rows are bottom-up when the height is positive, and padded to
    # a 4-byte boundary. PNG rows are top-down with a filter byte each.
    flip = h > 0
    rows_n = abs(h)
    stride = (w + 3) & ~3
    raw = bytearray()
    for r in range(rows_n):
        src = (rows_n - 1 - r) if flip else r
        start = pix_off + src * stride
        raw += b"\x00" + bmp[start:start + w]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    ihdr = struct.pack(">IIBBBBB", w, rows_n, 8, 3, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"PLTE", bytes(plte))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def _backend():
    try:
        import libusb_package
    except ImportError as e:                                  # pragma: no cover
        raise ScopeUnavailable(f"libusb-package not installed: {e}")
    return libusb_package.get_libusb1_backend()


def find_device(vid, pid):
    """One USB device by id, or raise ScopeUnavailable.

    Raises rather than returning None because every caller wants to skip
    with a reason, and "no pyusb" and "no scope" are different reasons a
    None cannot carry.
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


class UsbTmc:
    """USBTMC over the first bulk endpoint pair. Not thread-safe."""

    def __init__(self, dev):
        import usb.util
        self.dev = dev
        try:
            self.dev.set_configuration()
        except Exception:
            # Already configured by an earlier open. Not an error: the
            # instrument keeps its configuration across process exits and
            # re-setting it would disturb the scope's own state.
            pass
        itf = self.dev.get_active_configuration()[(0, 0)]
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

    def _tag_next(self):
        self._tag = (self._tag % 255) + 1     # bTag is 1..255; 0 reserved
        return self._tag

    def write(self, cmd, timeout=DEFAULT_TIMEOUT_MS, settle=0.0):
        payload = cmd.encode() + b"\n"
        pkt = usbtmc_header(1, self._tag_next(), len(payload), 0x01) + payload
        pkt += b"\x00" * (-len(pkt) % 4)
        self._out.write(pkt, timeout=timeout)
        if settle:
            time.sleep(settle)

    def read_raw(self, size=1 << 16, timeout=DEFAULT_TIMEOUT_MS):
        self._out.write(usbtmc_header(2, self._tag_next(), size, 0x00),
                        timeout=timeout)
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

    def close(self):
        try:
            import usb.util
            usb.util.dispose_resources(self.dev)
        except Exception:                                     # pragma: no cover
            pass


# ---------------------------------------------------------------------
# Interface: what this project asks of a scope.
# ---------------------------------------------------------------------

class Oscilloscope:
    """The operations a driver must provide. Callers use only these.

    Deliberately small. It covers what is needed to point an instrument
    at a DAC pin and read a transient off it, and nothing else: the
    moment this grows a method because one model happens to have it, the
    abstraction has stopped being one.

    Two conventions every driver honours, both learned the expensive way
    on the first instrument:

      * **A setter returns what the instrument holds afterwards**, never
        what it was asked for. Scopes quantise to a 1-2-5 sequence,
        clamp against other settings, and sometimes do not apply a write
        at all - and report none of it. A caller needing an exact value
        compares.

      * **A measurement that could not be made is None**, not a
        sentinel. Instruments answer things like 9.9e37, which is a
        float, is a plausible voltage to any comparison written to catch
        a wrong number, and sails straight through it.
    """

    #: (vendor id, product id) pairs this driver claims.
    IDS = ()

    def matches(self, idn):                                   # pragma: no cover
        """True if this driver should own an instrument reporting `idn`.

        The USB id gets a driver as far as the device; the *IDN model
        string separates families that share a product id.
        """
        return True

    def identify(self):                                       # pragma: no cover
        """(manufacturer, model, serial, firmware)."""
        raise NotImplementedError

    def channel_scale(self, ch, volts_per_div=None):          # pragma: no cover
        raise NotImplementedError

    def channel_offset(self, ch, volts=None):                 # pragma: no cover
        raise NotImplementedError

    def coupling(self, ch, mode=None):                        # pragma: no cover
        raise NotImplementedError

    def probe(self, ch, ratio=None):                          # pragma: no cover
        """The attenuation the scope has been *told*, not what is fitted.

        A 10x probe against a scope set to 1x reads every voltage ten
        times small and nothing in the data says so. Exposed so a caller
        can assert it rather than assume it.
        """
        raise NotImplementedError

    def timebase(self, seconds_per_div=None):                 # pragma: no cover
        raise NotImplementedError

    def trigger_edge(self, source=None, level=None, slope=None,
                     sweep=None):                             # pragma: no cover
        raise NotImplementedError

    def ext_trigger_autoset(self, levels=None, couplings=("AC", "DC"),
                            slope="POS", settle=0.3):         # pragma: no cover
        """Find a level and coupling on which EXT actually triggers.

        Why this is not a constant. The DAC swings 0.52-2.82 V, so the
        obvious level is 1.67 V - and the DS1102E's EXT input clamps at
        1.2 V, which no readback complains about: it silently accepts
        1.67 and holds 1.20. Then the probe ratio moves the whole
        signal, and a x10 probe puts the crossing at 0.167 V and the
        swing at 230 mV, which is the instrument's own sensitivity
        floor. Measured here: the window is 0.1-0.2 V DC-coupled and
        0.0-0.1 V AC-coupled, and a sweep at 0.0/0.3/0.6/1.0/1.2 steps
        over it and reports "EXT does not work".

        So the level is discovered, not assumed. Returns the settings
        that triggered, or None - and None means no signal is reaching
        the input, which is a cable fault and not a level to guess
        harder at.
        """
        if levels is None:
            # Ordered outward from zero, because that is where a working
            # setup is: AC coupling centres the sync on 0 V, and the
            # first candidate hits on a x1 probe. An evenly-spaced sweep
            # of the whole range instead costs ~44 s of instrument time
            # per call, which is longer than the window it was being
            # called inside - it kept sweeping after the output had
            # stopped and collided with the next acquisition.
            levels = [0.0]
            for step in (0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 0.8, 1.2):
                levels += [step, -step]
        for coup in couplings:
            self.trigger_coupling(coup)
            for lev in levels:
                self.trigger_edge(source="EXT", slope=slope, level=lev,
                                  sweep="NORMAL")
                self.run()
                time.sleep(settle)
                if self.triggered():
                    return {"coupling": coup, "level": lev, "slope": slope}
        return None

    def menu_display(self, on=None):                          # pragma: no cover
        """Show or hide the instrument's soft-key menu.

        For screenshots. Every SCPI write that touches a menu leaves it
        on screen, and it covers about a fifth of the graticule - so a
        shot taken after setting the timebase has the timebase menu
        sitting over the right-hand divisions of the trace.
        """
        raise NotImplementedError

    def channel_enable(self, ch, on=None):                    # pragma: no cover
        """Show or hide a channel's trace.

        Worth having for screenshots: an unconnected input draws a flat
        line at whatever it is picking up, and a reader cannot tell that
        from a real signal that happens to be flat.
        """
        raise NotImplementedError

    def screenshot(self):                                     # pragma: no cover
        """The instrument's screen, as PNG bytes.

        The screen and not a re-plot of :WAV:DATA?, because they are not
        the same picture: the screen carries the graticule, the trigger
        marker, the scale factors and the on-screen measurements, which
        is most of what makes a screenshot worth keeping.
        """
        raise NotImplementedError

    def timebase_offset(self, seconds=None):                  # pragma: no cover
        """Where the trigger sits relative to the screen centre.

        Needed to look at what happens *after* an edge: the trigger
        point is centre by default, which spends half the record on
        what came before. Negative moves the trigger left.
        """
        raise NotImplementedError

    def trigger_coupling(self, mode=None):                    # pragma: no cover
        """DC, AC, HF or LF on the trigger path only.

        Not the channel's coupling: this one decides what the trigger
        comparator sees, and for EXT it is the difference between a
        usable setup and one that never fires - the DAC's 1.67 V
        midpoint is above the 1.2 V the input can threshold, and AC
        coupling is what brings the crossing back into range.
        """
        raise NotImplementedError

    def triggered(self):                                      # pragma: no cover
        """True when the instrument has actually acquired on a trigger.

        A predicate rather than a status string, because the string is
        this instrument's - a DS1102E says "T'D" - and callers must not
        learn one scope's spelling.
        """
        raise NotImplementedError

    def averaging(self, count=None):                          # pragma: no cover
        """Acquisition averaging - the scope's version of folding.

        Same argument and the same sqrt(n) as `measure.fold_profile()`:
        the artifact under investigation is a few millivolts, and
        averaging a few hundred triggered acquisitions is what brings it
        out of the noise.
        """
        raise NotImplementedError

    def measure(self, what, ch=1):                            # pragma: no cover
        raise NotImplementedError

    def waveform(self, ch=1):                                 # pragma: no cover
        """The displayed trace as volts, oldest sample first."""
        raise NotImplementedError

    def run(self):                                            # pragma: no cover
        raise NotImplementedError

    def stop(self):                                           # pragma: no cover
        raise NotImplementedError

    def measure_all(self, ch=1, names=("VPP", "VMAX", "VMIN", "FREQ")):
        """Several measurements in one call, each None where unreadable.

        Convenience, not dialect: it is `measure()` in a loop, and it
        exists because a caller that wants four numbers should not have
        to remember that any of them can be absent.
        """
        return {n: self.measure(n, ch) for n in names}

    def close(self):                                          # pragma: no cover
        raise NotImplementedError

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


# ---------------------------------------------------------------------
# Driver: Rigol DS1000E. Everything here is this model's dialect.
# ---------------------------------------------------------------------

class RigolDS1000E(Oscilloscope):
    """Verified against a DS1102E, firmware 00.04.02.01.00, 2026-08-26.

    Nothing here is written from the programming guide alone; every
    command below answered on that instrument, and each behaviour
    documented in this class cost a debugging round.
    """

    IDS = ((0x1AB1, 0x0588),)          # Rigol, DS1000E series

    #: What this model returns from a measurement it could not make.
    NO_READING = 9.9e37

    #: Screen data is one byte per point and *inverted* - a larger byte
    #: is a lower voltage - referenced to the channel's scale and
    #: offset. Checked against the instrument's own :MEAS: readings on a
    #: known square: waveform() and :MEAS:VPP? agreed within 20 mV
    #: through entirely separate paths.
    _CENTRE_BYTE = 240
    _BYTES_PER_DIV = 25.0
    _DIVS_TO_ZERO = 4.6

    def __init__(self, io):
        self.io = io

    def matches(self, idn):
        return "DS1" in (idn[1] if len(idn) > 1 else "")

    # -- dialect ------------------------------------------------------

    @staticmethod
    def fmt_number(v):
        """Plain decimal, because exponent notation is ignored.

        `%g` writes 1e-05 and this firmware ignores it in silence: the
        write is accepted, the setting does not move, and the readback
        returns the old value. Exponent is not the fix either - the
        instrument *replies* `5.000e-06` but does not reliably accept
        that form back. The test that appeared to prove otherwise was
        reading a setting already at the target, so every value that
        "worked" was one the scope already held. Alternating between two
        values so each write has to change something, plain decimal
        takes every time.
        """
        return f"{float(v):.12f}"

    def _apply(self, cmd, query, value, tol=1e-3, timeout=2.0):
        """Write a numeric setting, then wait until it is reported back.

        A fixed post-write delay is the wrong shape for this instrument:
        0.05 s was too short for `:CHAN:PROB`, 0.1 s was enough for that
        and too short for `:TIM:SCAL`, which wanted about a second. A
        constant sized for the slowest command taxes every other one.

        Polling instead returns what the instrument holds when the wait
        ends, which is the honest answer whether the value was applied,
        quantised, or clamped - and a stale readback can no longer be
        mistaken for a failed write.
        """
        self.io.write(f"{cmd} {self.fmt_number(value)}")
        deadline = time.time() + timeout
        while True:
            got = float(self.io.ask(query))
            if abs(got - value) <= max(tol, abs(value) * tol):
                return got
            if time.time() >= deadline:
                return got
            time.sleep(0.1)

    # -- interface ----------------------------------------------------

    def identify(self):
        parts = self.io.ask("*IDN?").split(",")
        while len(parts) < 4:
            parts.append("")
        return tuple(p.strip() for p in parts[:4])

    @property
    def model(self):
        return self.identify()[1]

    def channel_scale(self, ch, volts_per_div=None):
        if volts_per_div is not None:
            return self._apply(f":CHAN{ch}:SCAL", f":CHAN{ch}:SCAL?",
                               volts_per_div)
        return float(self.io.ask(f":CHAN{ch}:SCAL?"))

    def channel_offset(self, ch, volts=None):
        if volts is not None:
            return self._apply(f":CHAN{ch}:OFFS", f":CHAN{ch}:OFFS?",
                               volts, tol=1e-2)
        return float(self.io.ask(f":CHAN{ch}:OFFS?"))

    def coupling(self, ch, mode=None):
        if mode is not None:
            self.io.write(f":CHAN{ch}:COUP {mode}", settle=0.1)
        return self.io.ask(f":CHAN{ch}:COUP?")

    def probe(self, ch, ratio=None):
        if ratio is not None:
            return self._apply(f":CHAN{ch}:PROB", f":CHAN{ch}:PROB?", ratio)
        return float(self.io.ask(f":CHAN{ch}:PROB?"))

    def timebase(self, seconds_per_div=None):
        if seconds_per_div is not None:
            return self._apply(":TIM:SCAL", ":TIM:SCAL?", seconds_per_div)
        return float(self.io.ask(":TIM:SCAL?"))

    def trigger_edge(self, source=None, level=None, slope=None, sweep=None):
        """Configure or read back the edge trigger.

        The DAC's PDC reload is DAC0's rising mid-scale crossing, so an
        edge trigger there is a trigger on the table wrap itself - which
        is what makes a once-per-2.56 ms event findable at all.
        """
        if source is not None:
            self.io.write(":TRIG:MODE EDGE", settle=0.1)
            self.io.write(f":TRIG:EDGE:SOUR {source}", settle=0.1)
        if slope is not None:
            self.io.write(f":TRIG:EDGE:SLOP {slope}", settle=0.1)
        if sweep is not None:
            # AUTO sweeps even when nothing triggers, which is why an
            # untriggered trace crawls across the screen instead of
            # sitting still. Under NORMAL a stationary trace is evidence
            # the trigger is finding the edge and a blank screen is
            # evidence it is not; AUTO says neither.
            self.io.write(f":TRIG:EDGE:SWE {sweep}", settle=0.1)
        if level is not None:
            self._apply(":TRIG:EDGE:LEV", ":TRIG:EDGE:LEV?", level, tol=1e-2)
        return {"mode": self.io.ask(":TRIG:MODE?"),
                "source": self.io.ask(":TRIG:EDGE:SOUR?"),
                "slope": self.io.ask(":TRIG:EDGE:SLOP?"),
                "sweep": self.io.ask(":TRIG:EDGE:SWE?"),
                "level": float(self.io.ask(":TRIG:EDGE:LEV?")),
                "status": self.io.ask(":TRIG:STAT?")}

    def menu_display(self, on=None):
        if on is not None:
            self.io.write(f":DISP:MNUS {'ON' if on else 'OFF'}", settle=0.2)
        return self.io.ask(":DISP:MNUS?") in ("ON", "1")

    def channel_enable(self, ch, on=None):
        if on is not None:
            self.io.write(f":CHAN{ch}:DISP {'ON' if on else 'OFF'}",
                          settle=0.15)
        return self.io.ask(f":CHAN{ch}:DISP?") in ("ON", "1")

    def screenshot(self):
        # 320x234, 8-bit palette, ~75 kB. The transfer is slow enough
        # that the default timeout is not generous: give it its own.
        bmp = parse_block(self.io.ask_raw(":DISP:DATA?", size=1 << 18,
                                          settle=1.0, timeout=15000))
        return bmp_to_png(bmp)

    def timebase_offset(self, seconds=None):
        if seconds is not None:
            self._apply(":TIM:OFFS", ":TIM:OFFS?", seconds, tol=1e-9)
        return float(self.io.ask(":TIM:OFFS?"))

    def trigger_coupling(self, mode=None):
        if mode is not None:
            self.io.write(f":TRIG:EDGE:COUP {mode}", settle=0.15)
        return self.io.ask(":TRIG:EDGE:COUP?")

    #: What this model calls "acquired on a trigger". The apostrophe is
    #: not a typo and is why this is a driver detail rather than a
    #: string any caller should hold.
    TRIGGERED = ("T'D", "TD")

    def triggered(self):
        return self.io.ask(":TRIG:STAT?") in self.TRIGGERED

    def averaging(self, count=None):
        if count is None:
            self.io.write(":ACQ:TYPE NORMAL", settle=0.1)
            return None
        self.io.write(":ACQ:TYPE AVERAGE", settle=0.1)
        self.io.write(f":ACQ:AVER {int(count)}", settle=0.1)
        return int(float(self.io.ask(":ACQ:AVER?")))

    #: Mnemonics this model answers. Checked before the query, because
    #: an unknown one does not return an error - it returns *nothing*,
    #: and the read then times out and reads as a hung instrument. `VAVG`
    #: cost a run that way; the name here is `VAVERAGE`.
    MEASUREMENTS = frozenset((
        "VPP", "VMAX", "VMIN", "VAMP", "VTOP", "VBASE", "VAVERAGE",
        "VRMS", "OVERSHOOT", "PRESHOOT", "FREQUENCY", "RISETIME",
        "FALLTIME", "PERIOD", "PWIDTH", "NWIDTH", "PDUTYCYCLE",
        "NDUTYCYCLE", "FREQ",
    ))

    def level(self, ch=1):
        """Mean level of the trace, in volts, from the samples.

        Not `:MEAS:VAVERAGE?`, which answers to **three significant
        figures**: near 2.7 V that is a 10 mV step, or about 19 DAC
        codes, and no amount of vertical gain improves it because the
        limit is the response format rather than the screen. The trace
        itself is 600 8-bit samples, and a level dithered by the pin's
        own ~20 mV of noise averages far below one level.

        Use this for any level that matters. `measure("VAVERAGE")` is
        still the right call for a quick look.
        """
        v = self.waveform(ch)
        return (sum(v) / len(v)) if v else None

    def measure(self, what, ch=1):
        if what not in self.MEASUREMENTS:
            raise ValueError(
                f"{what!r} is not a measurement this model answers; an "
                f"unknown mnemonic returns nothing and times out. "
                f"Known: {', '.join(sorted(self.MEASUREMENTS))}")
        v = float(self.io.ask(f":MEAS:{what}? CHAN{ch}"))
        return None if v >= self.NO_READING / 10 else v

    def waveform(self, ch=1, points="NORMAL"):
        self.io.write(f":WAV:POIN:MODE {points}", settle=0.1)
        raw = parse_block(self.io.ask_raw(f":WAV:DATA? CHAN{ch}", settle=0.4))
        scal = self.channel_scale(ch)
        offs = self.channel_offset(ch)
        return [(self._CENTRE_BYTE - b) * scal / self._BYTES_PER_DIV
                - (offs + scal * self._DIVS_TO_ZERO) for b in raw]

    def run(self):
        self.io.write(":RUN", settle=0.2)

    def stop(self):
        self.io.write(":STOP", settle=0.2)

    def close(self):
        self.io.close()


# ---------------------------------------------------------------------
# Discovery.
# ---------------------------------------------------------------------

#: Every driver this project knows. A new model is a class above and an
#: entry here; nothing that calls open_scope() changes.
DRIVERS = (RigolDS1000E,)


def open_scope(drivers=DRIVERS):
    """The first known scope on the bus, wrapped in its driver.

    Raises ScopeUnavailable naming every id it looked for, so the
    failure says what was expected rather than only what was missing -
    the difference between "plug the scope in" and "this model has no
    driver yet".
    """
    tried = []
    blocked = None
    for cls in drivers:
        for vid, pid in cls.IDS:
            tried.append(f"{vid:04x}:{pid:04x} ({cls.__name__})")
            try:
                dev = find_device(vid, pid)
            except ScopeUnavailable as e:
                # find_device's docstring already makes the point: "no
                # pyusb" and "no scope" are different reasons. They were
                # being flattened here - every ScopeUnavailable became
                # `continue`, so a machine that had simply never run
                # `pip install -r requirements-dev.txt` was told "no
                # known scope found" and went looking at USB cables.
                #
                # A missing import cannot be fixed by plugging something
                # in, so it is kept and reported instead of the generic
                # message. Still not raised on the spot: a later driver
                # might use a different transport, and this one is only
                # the answer if nothing else works.
                if "not installed" in str(e) and blocked is None:
                    blocked = e
                continue
            inst = cls(UsbTmc(dev))
            if inst.matches(inst.identify()):
                return inst
            inst.close()
    if blocked is not None:
        # Both facts, not one. The dependency is the actionable half,
        # and the ids are still what says whether this model has a
        # driver at all - dropping them would trade one lost distinction
        # for another.
        raise ScopeUnavailable(
            f"cannot look for a scope: {blocked}. This is a missing "
            f"dependency, not a missing instrument - "
            f"pip install -r requirements-dev.txt. Would have looked "
            f"for " + ", ".join(tried))
    raise ScopeUnavailable("no known scope found; looked for " +
                           ", ".join(tried))
