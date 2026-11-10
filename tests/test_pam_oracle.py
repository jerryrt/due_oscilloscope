"""The independent PAM pattern oracle against the claims in docs/ets-pam.md.

No board. The comparison with the library's own pattern module is the last
test, and it skips until that module exists and `PATTERN_MODULE` names it.
"""
import importlib
from math import gcd

import pytest

import pam_oracle as o

pytestmark = pytest.mark.smoke

#: The library's module and its names, filled in when it lands.
PATTERN_MODULE = None

#: The table in docs/ets-pam.md: PAM -> (symbols per period, pairs).
TABLE = {4: (127, 16), 8: (127, 64), 16: (511, 256), 32: (2047, 1024),
         64: (8191, 4096), 128: (65535, 16384), 256: (131071, 65536)}


@pytest.mark.parametrize("order", sorted(o.TAPS))
def test_every_register_is_maximal(order):
    bits = o.prbs(order)                     # raises unless it returns after L
    assert len(bits) == 2 ** order - 1
    assert sum(bits) == 2 ** (order - 1)     # a maximal sequence: 2^(n-1) ones
    assert bits[0] == 1                      # all-ones start, output before shift


@pytest.mark.parametrize("pam", sorted(TABLE))
def test_the_table_rows_hold(pam):
    m, order = o.PAM_ORDER[pam]
    assert order >= 2 * m + 1
    assert gcd(m, 2 ** order - 1) == 1
    s = o.symbols(pam)
    length, pairs = TABLE[pam]
    assert len(s) == length
    assert set(s) == set(range(pam))
    assert len({(s[i], s[(i + 1) % length]) for i in range(length)}) == pairs


def test_the_flagged_order_is_really_needed():
    """PAM128 on order 15 loses pairs, as the document says: 7 divides 32,767."""
    assert 32767 % 7 == 0
    assert gcd(7, 32767) == 7


def test_gray_decode_matches_the_documents_example():
    assert [o.gray_decode(g) for g in (0b00, 0b01, 0b11, 0b10)] == [0, 1, 2, 3]


@pytest.mark.parametrize("pam", sorted(TABLE))
def test_levels_rise_with_room_between_them(pam):
    c = o.dac_codes(pam)
    assert len(c) == pam
    assert all(b - a >= 2 for a, b in zip(c, c[1:]))
    assert 0 < c[0] and c[-1] < 4095
    assert c[0] + c[-1] == 2 * o.DAC_MID      # symmetric about mid-scale


def test_the_oracle_detects_a_wrong_tap():
    """Break the thing it guards: a wrong tap must not pass as maximal."""
    saved = o.TAPS[7]
    o.TAPS[7] = (7, 5)
    try:
        with pytest.raises(AssertionError):
            o.prbs(7)
    finally:
        o.TAPS[7] = saved


@pytest.mark.parametrize("pam", sorted(TABLE))
def test_library_matches_oracle(pam):
    if PATTERN_MODULE is None:
        pytest.skip("the library's pattern module has not landed")
    lib = importlib.import_module(PATTERN_MODULE)
    assert list(lib.symbols(pam)) == o.symbols(pam)
    assert list(lib.dac_codes(pam)) == o.dac_codes(pam)
