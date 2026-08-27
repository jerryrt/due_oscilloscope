"""The bench oscilloscope. Board-free parts run everywhere.

Everything this project knows about issue #5 came from the converter
under investigation. `docs/HANDOFF.md` records that the voltage at the
DAC pin actually moving stays *inference*, and every amplitude a lower
bound, until an instrument that is not the ADC says otherwise. This is
the driver for that instrument.

The framing tests need no scope and no board, and they exist because
getting the header wrong costs a debugging round with no diagnostic:
the instrument accepts a malformed write and simply never answers.
"""

import struct

import pytest

import scope


# ---------------------------------------------------------------------
# Framing. No hardware.
# ---------------------------------------------------------------------

def test_the_bulk_header_is_twelve_bytes():
    """The trap. Eleven is accepted by the scope and never answered."""
    assert len(scope.usbtmc_header(1, 1, 8, 0x01)) == 12


def test_the_header_carries_msgid_tag_and_size():
    h = scope.usbtmc_header(1, 7, 0x1234, 0x01)
    msgid, tag, tag_inv, rsv, size, attrs = struct.unpack("<BBBBIB", h[:9])
    assert (msgid, tag, size, attrs) == (1, 7, 0x1234, 0x01)
    assert tag_inv == 0xF8                      # one's complement of 7
    assert rsv == 0 and h[9:] == b"\x00\x00\x00"


def test_the_tag_inverse_is_the_complement_for_every_tag():
    for tag in range(1, 256):
        h = scope.usbtmc_header(2, tag, 1024, 0x00)
        assert h[2] == (~tag & 0xFF), tag


def test_a_definite_length_block_is_unwrapped():
    """`#800000600` then 600 bytes is how a screen read comes back."""
    body = bytes(range(256)) * 3                # 768 bytes
    raw = b"#8" + f"{len(body):08d}".encode() + body
    assert scope.parse_block(raw) == body


def test_plain_ascii_is_returned_unchanged():
    """Most queries answer in ASCII, and the caller should not have to
    know which kind of answer it is about to get."""
    assert scope.parse_block(b"1.000e+00") == b"1.000e+00"


def test_a_truncated_block_returns_what_arrived():
    """Short reads must not raise: a partial trace is diagnosable and an
    exception in the transport is not."""
    raw = b"#800000600" + b"\x01\x02\x03"
    assert scope.parse_block(raw) == b"\x01\x02\x03"


def test_an_exponent_needs_a_mantissa():
    """`%g` renders 1e-5 as "1e-05", which this firmware ignores in
    silence: the write is accepted, the setting does not move, and the
    readback returns the old value. Its own replies are formatted
    "1.000e-05" and that form is accepted, so _num() matches it.

    Board-free because the lesson is the string, and because the cost of
    getting it wrong is a setting that looks applied and is not."""
    assert scope._num(1e-5) == "1.000e-05"
    assert scope._num(0.5) == "5.000e-01"
    assert scope._num(-1.6) == "-1.600e+00"
    assert "e" in scope._num(2e-9)


def test_no_reading_is_not_a_voltage():
    """`:MEAS:FREQ?` answers 9.9e37 with nothing connected. Returned as
    a float it passes through any comparison meant to catch a wrong
    number."""
    assert scope.NO_READING > 1e30


# ---------------------------------------------------------------------
# The instrument itself. Skips where there is no scope.
# ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def dso():
    try:
        s = scope.Scope()
    except Exception as e:                      # ScopeUnavailable, or pyusb
        pytest.skip(f"no scope: {e}")
    yield s
    s.close()


def test_it_identifies_itself(dso):
    maker, model, serial, firmware = dso.identify()
    assert "Rigol" in maker
    assert model.startswith("DS")
    assert serial and firmware


def test_a_setter_reports_what_the_instrument_holds(dso):
    """Setters return the readback, never the request.

    This firmware quantises to the 1-2-5 sequence, clamps against other
    settings, and sometimes does not apply a write at all - and it
    reports none of that. Returning the request would let a caller
    proceed on a value the scope never adopted, which is the failure
    this driver exists to make impossible.
    """
    was = dso.timebase()
    try:
        got = dso.timebase(1e-5)
        assert got == dso.timebase()          # what it says is what it holds
        assert got > 0
    finally:
        dso.timebase(was)


def test_the_probe_ratio_is_readable(dso):
    """It is a setting, not a measurement - a caller has to be able to
    assert it, because a 10x probe on a scope set to 1x reads every
    voltage ten times small and nothing in the data says so."""
    assert dso.probe(1) in (1.0, 10.0, 100.0, 1000.0)
