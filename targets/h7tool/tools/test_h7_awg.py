import os, struct, sys
import pytest
sys.path.insert(0, os.path.dirname(__file__))
import h7_awg as a


def pack(*codes):
    return struct.pack(f"<{len(codes)}H", *codes)


def unit(code=a.ZERO_CODE, n=a.UNIT_BYTES // 2):
    return pack(*([code] * n))


def test_a_waveform_inside_the_cap_passes_unchanged():
    d = unit(a.ZERO_CODE + a.SWING_LIMIT_CODES)
    assert a.check_codes(d) is d


def test_one_code_over_the_cap_is_refused_not_clamped():
    b = bytearray(unit()); struct.pack_into("<H", b, 1000, a.ZERO_CODE + a.SWING_LIMIT_CODES + 1)
    with pytest.raises(a.SwingError):
        a.check_codes(bytes(b))


def test_one_code_under_the_cap_is_refused():
    b = bytearray(unit()); struct.pack_into("<H", b, 0, a.ZERO_CODE - a.SWING_LIMIT_CODES - 1)
    with pytest.raises(a.SwingError):
        a.check_codes(bytes(b))


def test_a_partial_unit_is_refused():
    with pytest.raises(ValueError):
        a.check_codes(unit()[:-2])


def test_builders_cannot_exceed_the_cap():
    with pytest.raises(a.SwingError):
        a.sine(250_000, 1000, a.SWING_LIMIT_CODES + 5)
    assert len(a.sine(250_000, 1000, 100)) % a.UNIT_BYTES == 0
    assert len(a.square(1_000_000, 10_000, 100)) % a.UNIT_BYTES == 0


def test_sine_has_whole_cycles():
    d = a.sine(2_500_000, 10_000, 100)
    codes = struct.unpack(f"<{len(d) // 2}H", d)
    assert codes[0] == codes[250] == a.ZERO_CODE
