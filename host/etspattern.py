"""PAM-N patterns for equivalent-time captures: symbols, levels, DAC codes.

`docs/ets-pam.md` is the definition. A pattern is a maximal-length PRBS of
order `n` read `m` bits per symbol, first bit most significant, in
non-overlapping groups that wrap around the sequence, each group a Gray code
decoded to a level index. The order is the smallest in the table that puts
every one of the `N^2` ordered symbol pairs on the wire.

Pure Python and stdlib only, so it runs wherever the reference does.
"""
import math
from dataclasses import dataclass
from fractions import Fraction

import eqtime

#: Fibonacci shift register taps by order, 1-based from the bottom of the
#: register: the feedback is the XOR of the bits at `tap - 1`.
TAPS = {7: (7, 6), 9: (9, 5), 11: (11, 9), 13: (13, 12, 2, 1),
        15: (15, 14), 16: (16, 15, 13, 4), 17: (17, 14)}

#: The order that gives each level count every pair. PAM128 is 16 and not
#: 15: 7 divides 2^15 - 1, so groups of 7 bits start at only one position
#: in seven and most pairs never occur.
PAM_ORDER = {4: 7, 8: 7, 16: 9, 32: 11, 64: 13, 128: 16, 256: 17}

#: The DAC's span over its codes, in millivolts per code (docs/hardware.md).
DAC_LSB_MV = 2214.0 / 4095
DAC_MID = 2048

#: Peak to peak swing by level count: 1 V up to PAM32, 2 V from PAM64.
DEFAULT_SWING_MV = {4: 1000.0, 8: 1000.0, 16: 1000.0, 32: 1000.0,
                    64: 2000.0, 128: 2000.0, 256: 2000.0}

#: Samples wanted in each tick position of a pattern-synchronous fold.
SAMPLES_PER_TICK = 20


def prbs_bits(n):
    """One period of the order-`n` sequence, `2^n - 1` bits.

    The register starts all ones and shifts left; the output is its lowest
    bit. Raises if the taps do not give a maximal sequence.
    """
    mask = (1 << n) - 1
    r = mask
    out = []
    for step in range(mask):
        out.append(r & 1)
        fb = 0
        for t in TAPS[n]:
            fb ^= (r >> (t - 1)) & 1
        r = ((r << 1) | fb) & mask
        if r == mask and step < mask - 1:
            raise ValueError("order %d returns to its seed after %d steps" % (n, step + 1))
    if r != mask:
        raise ValueError("order %d does not return to its seed after %d steps" % (n, mask))
    return out


def gray_decode(g):
    b = 0
    while g:
        b ^= g
        g >>= 1
    return b


def level_codes(pam, swing_mv=None):
    """The DAC code of each of `pam` levels, lowest first, rounded half up.

    In exact rational arithmetic: a float that lands just below a half would
    round the other way, and two implementations would then differ by a code.
    """
    swing = Fraction(DEFAULT_SWING_MV[pam] if swing_mv is None else swing_mv)
    step = swing / ((pam - 1) * Fraction(2214, 4095))
    return [math.floor(DAC_MID + Fraction(2 * i - (pam - 1), 2) * step
                       + Fraction(1, 2)) for i in range(pam)]


@dataclass
class Pattern:
    pam: int
    m: int
    n: int
    bits: int               # 2^n - 1, the binary period
    symbols: list           # level index of each symbol over one period
    codes: list             # DAC code of each level
    swing_mv: float

    @property
    def length(self):
        """Symbols in one period."""
        return len(self.symbols)

    def symbol_codes(self):
        """The DAC code of every symbol of one period."""
        return [self.codes[s] for s in self.symbols]

    def coverage(self):
        """`(levels, pairs)`: the distinct levels and ordered neighbours."""
        n = self.length
        s = self.symbols
        return set(s), {(s[j], s[(j + 1) % n]) for j in range(n)}

    def problems(self):
        """What keeps this from being a full-transition pattern, if anything."""
        out = []
        levels, pairs = self.coverage()
        if len(levels) != self.pam:
            out.append("%d of %d levels occur" % (len(levels), self.pam))
        if len(pairs) != self.pam ** 2:
            out.append("%d of %d symbol pairs occur" % (len(pairs), self.pam ** 2))
        gaps = [b - a for a, b in zip(self.codes, self.codes[1:])]
        if min(gaps) < 2:
            out.append("two levels are %d DAC code(s) apart" % min(gaps))
        return out


def pattern(pam, swing_mv=None, n=None):
    """The pattern for `pam` levels; `n` overrides the order, for tests."""
    m = pam.bit_length() - 1
    if 1 << m != pam or m < 1:
        raise ValueError("%d is not a power of two" % pam)
    n = PAM_ORDER[pam] if n is None else n
    bits = prbs_bits(n)
    total = len(bits)
    period = total // math.gcd(m, total)
    symbols = []
    for j in range(period):
        g = 0
        for i in range(m):
            g = (g << 1) | bits[(m * j + i) % total]
        symbols.append(gray_decode(g))
    swing = DEFAULT_SWING_MV[pam] if swing_mv is None else swing_mv
    return Pattern(pam, m, n, total, symbols, level_codes(pam, swing), swing)


def symbols(pam, n=None):
    """The level index of every symbol of one period."""
    return pattern(pam, n=n).symbols


def dac_codes(pam, swing_mv=None):
    """The ladder: the DAC code of each of `pam` levels, lowest first."""
    return level_codes(pam, swing_mv)


def period_ticks(p, rc_dac):
    """Ticks in one period of the pattern at one DAC update per symbol."""
    return p.length * rc_dac


def capture_seconds(p, rc_dac, rc_adc, per_tick=SAMPLES_PER_TICK):
    """Capture time that puts `per_tick` samples in each tick position.

    One sample every `rc_adc` ticks, and each lands in one of the
    `period_ticks` positions, so that is `per_tick * period_ticks` samples.
    """
    return per_tick * period_ticks(p, rc_dac) * rc_adc / eqtime.TC_CLOCK_HZ
