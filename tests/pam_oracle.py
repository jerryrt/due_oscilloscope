"""An independent reading of "The pattern" and "The levels" in docs/ets-pam.md.

Written from that section alone. It shares no code with the library that
will carry the same pattern, so the two agree only where the document is
unambiguous. Where the text left a choice, the choice made is named here.
"""
from math import gcd

#: Taps by order, as the document lists them: bit positions are `t - 1`.
TAPS = {7: (7, 6), 9: (9, 5), 11: (11, 9), 13: (13, 12, 2, 1),
        15: (15, 14), 16: (16, 15, 13, 4), 17: (17, 14)}
#: PAM level count to (bits per symbol, PRBS order), from the document's table.
PAM_ORDER = {4: (2, 7), 8: (3, 7), 16: (4, 9), 32: (5, 11),
             64: (6, 13), 128: (7, 16), 256: (8, 17)}
DAC_MID = 2048
#: The document's figure; the DAC's own span would give 0.5372, so this is
#: taken as written.
MV_PER_DAC_CODE = 0.5407
#: 1 V up to PAM32, 2 V from PAM64.
SWING_MV = {4: 1000, 8: 1000, 16: 1000, 32: 1000, 64: 2000, 128: 2000, 256: 2000}


def prbs(order):
    """The 2^order - 1 output bits. Choice: the output is the lowest bit
    *before* the register shifts, so the first bit is 1 (all-ones start)."""
    mask = (1 << order) - 1
    reg = mask
    out = []
    for _ in range(mask):
        out.append(reg & 1)
        fb = 0
        for t in TAPS[order]:
            fb ^= (reg >> (t - 1)) & 1
        reg = ((reg << 1) & mask) | fb
    if reg != mask:
        raise AssertionError("not maximal: register did not return to all ones")
    return out


def gray_decode(g):
    v = 0
    while g:
        v ^= g
        g >>= 1
    return v


def symbols(pam):
    """The level index of every symbol in one period, in order."""
    m, order = PAM_ORDER[pam]
    bits = prbs(order)
    n = len(bits)
    if gcd(m, n) != 1:
        raise ValueError("gcd(m, L) != 1: groups would not start at every bit")
    out = []
    for j in range(n):
        g = 0
        for k in range(m):
            g = (g << 1) | bits[(j * m + k) % n]      # first bit most significant
        out.append(gray_decode(g))
    return out


def dac_codes(pam):
    """DAC code of each level index, level 0 lowest."""
    swing = SWING_MV[pam]
    return [DAC_MID + round((i - (pam - 1) / 2) * swing / (pam - 1) / MV_PER_DAC_CODE)
            for i in range(pam)]


def dac_stream(pam):
    codes = dac_codes(pam)
    return [codes[s] for s in symbols(pam)]
