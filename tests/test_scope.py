"""The bench oscilloscope. Optional, and model-independent where it can be.

Everything this project knows about issue #5 came from the converter
under investigation. `docs/HANDOFF.md` records the consequence: the
voltage at the DAC pin actually moving stays *inference*, and every
amplitude a lower bound, until an instrument that is not the ADC says
otherwise. This is the driver for that instrument.

Two things this file is careful about.

**Optional.** Only the tests marked `dso` need hardware, and they skip
when there is none. `--dso` turns that skip into a failure, for a bench
where the scope is supposed to be attached and its absence is the bug.
Everything else runs on any machine, including one with no pyusb.

**Model-independent.** The tests below exercise the transport, the
discovery, and the interface contract - not one instrument's dialect.
The bench is not promised to keep the same scope, so a test that pins
`RigolDS1000E` behaviour says so in its name.
"""

import struct

import pytest

import scope


# ---------------------------------------------------------------------
# Transport. USBTMC, no instrument, no model.
# ---------------------------------------------------------------------

def test_the_bulk_header_is_twelve_bytes():
    """The trap. Eleven is accepted by the instrument and never
    answered, which presents as a read timeout with nothing to say the
    request was malformed."""
    assert len(scope.usbtmc_header(1, 1, 8, 0x01)) == 12


def test_the_header_carries_msgid_tag_and_size():
    h = scope.usbtmc_header(1, 7, 0x1234, 0x01)
    msgid, tag, tag_inv, rsv, size, attrs = struct.unpack("<BBBBIB", h[:9])
    assert (msgid, tag, size, attrs) == (1, 7, 0x1234, 0x01)
    assert tag_inv == 0xF8                      # one's complement of 7
    assert rsv == 0 and h[9:] == b"\x00\x00\x00"


def test_the_tag_inverse_is_the_complement_for_every_tag():
    for tag in range(1, 256):
        assert scope.usbtmc_header(2, tag, 1024, 0x00)[2] == (~tag & 0xFF), tag


def test_a_definite_length_block_is_unwrapped():
    """`#800000600` then 600 bytes is how a screen read comes back."""
    body = bytes(range(256)) * 3
    assert scope.parse_block(b"#8" + f"{len(body):08d}".encode() + body) == body


def test_plain_ascii_is_returned_unchanged():
    """Most queries answer in ASCII and a caller should not have to know
    which kind of answer it is about to get."""
    assert scope.parse_block(b"1.000e+00") == b"1.000e+00"


def test_a_truncated_block_returns_what_arrived():
    """Short reads must not raise: a partial trace is diagnosable and an
    exception in the transport is not."""
    assert scope.parse_block(b"#800000600" + b"\x01\x02\x03") == b"\x01\x02\x03"


# ---------------------------------------------------------------------
# The interface and the registry. Still no instrument.
# ---------------------------------------------------------------------

def test_every_driver_declares_usb_ids():
    for cls in scope.DRIVERS:
        assert cls.IDS, f"{cls.__name__} claims no USB ids"
        for vid, pid in cls.IDS:
            assert 0 < vid < 0x10000 and 0 <= pid < 0x10000


def test_every_driver_implements_the_interface():
    """A driver that inherits the base and forgets a method fails here
    rather than at the bench, where the scope is plugged in and the
    person is not looking for a typo."""
    required = ["identify", "channel_scale", "channel_offset", "coupling",
                "probe", "timebase", "trigger_edge", "averaging",
                "measure", "waveform", "run", "stop", "close"]
    for cls in scope.DRIVERS:
        assert issubclass(cls, scope.Oscilloscope)
        for name in required:
            assert getattr(cls, name) is not getattr(scope.Oscilloscope, name), \
                f"{cls.__name__} does not override {name}()"


def test_discovery_names_what_it_looked_for():
    """"No scope" and "no driver for this scope" are different problems
    and the message has to tell them apart."""
    class Nothing(scope.Oscilloscope):
        IDS = ((0xDEAD, 0xBEEF),)

    with pytest.raises(scope.ScopeUnavailable) as e:
        scope.open_scope(drivers=(Nothing,))
    assert "dead:beef" in str(e.value).lower()
    assert "Nothing" in str(e.value)


def test_a_missing_dependency_does_not_read_as_a_missing_scope(monkeypatch):
    """The third problem, and it used to wear the second one's message.

    find_device already raises separately for "pyusb not installed" and
    "no such device" - its docstring says why - but open_scope caught
    every ScopeUnavailable and continued, so a machine that had never
    run `pip install -r requirements-dev.txt` was told "no known scope
    found; looked for 1ab1:0588" and sent to check USB cables.

    Monkeypatched rather than conditioned on the real import, because
    the bug is only visible on a host *without* the dependency and this
    test has to fail on a host that has it.
    """
    class Nothing(scope.Oscilloscope):
        IDS = ((0xDEAD, 0xBEEF),)

    def no_pyusb(vid, pid):
        raise scope.ScopeUnavailable("pyusb not installed: no module 'usb'")

    monkeypatch.setattr(scope, "find_device", no_pyusb)
    with pytest.raises(scope.ScopeUnavailable) as e:
        scope.open_scope(drivers=(Nothing,))

    msg = str(e.value)
    assert "not installed" in msg, msg
    assert "missing dependency, not a missing instrument" in msg, msg
    assert "no known scope found" not in msg, (
        "the dependency failure is still wearing the no-scope message: " + msg)


# ---------------------------------------------------------------------
# One model's dialect. Named so, because it is not general.
# ---------------------------------------------------------------------

def test_rigol_wants_plain_decimal_not_exponent():
    """`%g` writes 1e-05 and this firmware ignores it in silence - write
    accepted, setting unchanged, readback stale. Exponent is not the fix
    either: the instrument replies `5.000e-06` and does not reliably
    accept that back. The test that first appeared to show exponent
    working was reading a setting already at the target, so every value
    that "worked" was one the scope already held."""
    fmt = scope.RigolDS1000E.fmt_number
    assert fmt(1e-5) == "0.000010000000"
    assert fmt(0.5) == "0.500000000000"
    assert fmt(-1.6) == "-1.600000000000"
    assert "e" not in fmt(2e-9)                 # the whole point


class FakeIo:
    """Records what was written; answers whatever the test lines up.

    Enough of UsbTmc's surface for a driver to run against, so the
    conventions every driver must honour are testable on a machine with
    no scope and no pyusb.
    """

    def __init__(self, answers):
        self.answers = list(answers)
        self.written = []

    def write(self, cmd, timeout=None, settle=0.0):
        self.written.append(cmd)

    def ask(self, cmd, **kw):
        return self.answers.pop(0) if self.answers else "0"

    def close(self):
        pass


def test_a_setter_returns_the_readback_not_the_request():
    """The convention that stops a caller proceeding on a value the
    instrument never adopted. Here the scope is asked for 1e-5 and
    reports 5e-6 - quantised, clamped, or simply not applied - and the
    setter must say 5e-6."""
    io = FakeIo(["5.000e-06"])
    inst = scope.RigolDS1000E(io)
    assert inst.timebase(1e-5) == 5e-6
    assert any("0.000010000000" in w for w in io.written)


def test_a_setter_stops_polling_once_the_value_agrees():
    """It must not keep asking after the instrument has caught up."""
    io = FakeIo(["1.000e-05"])
    inst = scope.RigolDS1000E(io)
    assert inst.timebase(1e-5) == 1e-5
    assert io.answers == []


def test_a_measurement_that_could_not_be_made_is_none():
    """9.9e37 is a float and a plausible voltage; any comparison written
    to catch a wrong number passes it straight through."""
    assert scope.RigolDS1000E(FakeIo(["9.9e37"])).measure("FREQ") is None
    assert scope.RigolDS1000E(FakeIo(["76300.0"])).measure("FREQ") == 76300.0


def test_measure_all_carries_the_gaps_through():
    """It is measure() in a loop, so an unreadable one has to stay None
    rather than become a number on the way out - a sweep prints these
    straight into a table."""
    io = FakeIo(["2.32", "2.82", "0.50", "9.9e37"])
    got = scope.RigolDS1000E(io).measure_all()
    assert got == {"VPP": 2.32, "VMAX": 2.82, "VMIN": 0.50, "FREQ": None}


def test_measure_all_is_not_the_drivers_to_implement():
    """Convenience on the interface, not dialect. A driver that
    overrides it has almost certainly misread where the seam is."""
    for cls in scope.DRIVERS:
        assert cls.measure_all is scope.Oscilloscope.measure_all


def test_rigol_no_reading_is_not_a_voltage():
    """`:MEAS:FREQ?` answers 9.9e37 with nothing connected. Returned as
    a float it passes any comparison meant to catch a wrong number."""
    assert scope.RigolDS1000E.NO_READING > 1e30


# ---------------------------------------------------------------------
# The instrument itself. Skips without one; --dso makes absence fatal.
# ---------------------------------------------------------------------

# The `dso` fixture lives in conftest.py now: more than one file needs
# it, and opening the instrument twice is a USBTMC claim conflict rather
# than a second handle.


@pytest.mark.dso
def test_it_identifies_itself(dso):
    maker, model, serial, firmware = dso.identify()
    assert maker and model and serial and firmware


@pytest.mark.dso
def test_the_driver_claims_the_instrument_it_opened(dso):
    """Discovery matches on the *IDN model string as well as the USB id,
    because families share product ids."""
    assert dso.matches(dso.identify())


@pytest.mark.dso
def test_a_setter_returns_a_live_reading(dso):
    """The contract is checked against a fake below; this only confirms
    a real instrument answers at all."""
    was = dso.timebase()
    try:
        assert dso.timebase(1e-5) > 0
    finally:
        dso.timebase(was)


@pytest.mark.dso
def test_the_probe_ratio_is_readable(dso):
    """It is a setting, not a measurement. A 10x probe against a scope
    set to 1x reads every voltage ten times small and nothing in the
    data says so, so a caller has to be able to assert it."""
    assert dso.probe(1) in (1.0, 10.0, 100.0, 1000.0)
