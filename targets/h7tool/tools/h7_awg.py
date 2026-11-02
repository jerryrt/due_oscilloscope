"""Host side of the H7 AWG: waveform building and the voltage cap.

The firmware no longer screens playback codes (invariant 1), so THIS module is where the swing cap
is enforced. `check_codes` refuses, it never clamps: a clamped waveform would play as something
the caller did not ask for. The cap is the owner's setting: +-SWING_LIMIT_CODES around ZERO_CODE,
about +-2 V on the +-10 V stage (stock calibration pairs, docs/13). Every writer to the stream
port must pass its bytes through `check_codes` and write multiples of UNIT_BYTES.
"""
import math
import struct

ZERO_CODE = 2036          # DAC code for 0 V (stock calibration pairs)
SWING_LIMIT_CODES = 330   # owner-set cap, about +-2 V
UNIT_BYTES = 2048         # the device takes whole 4-packet units
MV_PER_CODE = 5.983       # stock calibration slope, mV per DAC code
DAC_CLOCK_HZ = 200_000_000


# The cap can be raised, in steps, by the owner's decision, but never past this ceiling: about +-9.6 V, under the
# +-10 V the output stage is specified for and well inside the H7 scope input's +-13.8 V. Codes, not volts: the
# volts-per-code figure is measured (docs/13).
HARD_LIMIT_CODES = 1600
STOCK_PAIRS = ((500, -9190.0), (1500, -3212.0), (2500, 2771.0), (3500, 8755.0))   # (code, mV), stock calibration


def set_swing_limit(codes):
    """Raise or lower the host-enforced cap. Refuses anything beyond HARD_LIMIT_CODES."""
    global SWING_LIMIT_CODES
    if not 0 < codes <= HARD_LIMIT_CODES:
        raise ValueError(f"swing limit {codes} codes is outside 1..{HARD_LIMIT_CODES}")
    SWING_LIMIT_CODES = int(codes)


def stock_mv(code):
    """The stock calibration's millivolts for a DAC code (piecewise linear, last segments extended)."""
    pts = STOCK_PAIRS
    i = 0 if code <= pts[1][0] else (1 if code <= pts[2][0] else 2)
    (c0, v0), (c1, v1) = pts[i], pts[i + 1]
    return v0 + (code - c0) * (v1 - v0) / (c1 - c0)


def dc(code, n=4096):
    return check_codes(struct.pack(f"<{n}H", *([code] * n)))


class SwingError(ValueError):
    pass


def check_codes(data):
    """Return `data` unchanged if every halfword is inside the cap and the length is whole units."""
    if len(data) % UNIT_BYTES:
        raise ValueError(f"{len(data)} bytes is not a multiple of {UNIT_BYTES}")
    codes = struct.unpack(f"<{len(data) // 2}H", data)
    lo, hi = ZERO_CODE - SWING_LIMIT_CODES, ZERO_CODE + SWING_LIMIT_CODES
    bad = [c for c in codes if c < lo or c > hi]
    if bad:
        raise SwingError(f"{len(bad)} codes outside {lo}..{hi} (first {bad[0]}): refusing to play")
    return data


def period_ticks(fs_hz):
    p = DAC_CLOCK_HZ / fs_hz
    if abs(p - round(p)) > 1e-9:
        raise ValueError(f"{fs_hz} Hz is not an integer divisor of {DAC_CLOCK_HZ}")
    return int(round(p))


def whole_cycles(points_per_cycle, min_samples=4096):
    """Smallest cycle count whose length is a whole number of units (1024 samples) and >= min_samples."""
    k = 1024 // math.gcd(points_per_cycle, 1024)
    while k * points_per_cycle < min_samples:
        k *= 2
    return k


def sine(fs_hz, f_hz, amp_codes, center=ZERO_CODE):
    """A whole-unit buffer of an integer number of sine cycles; the frequency must divide the rate."""
    ppc = fs_hz / f_hz
    if abs(ppc - round(ppc)) > 1e-9:
        raise ValueError("f must divide fs")
    ppc = int(round(ppc)); n = whole_cycles(ppc) * ppc
    return check_codes(struct.pack(f"<{n}H", *[int(round(center + amp_codes * math.sin(2 * math.pi * i / ppc))) for i in range(n)]))


def square(fs_hz, f_hz, amp_codes, center=ZERO_CODE):
    ppc = int(round(fs_hz / f_hz))
    if ppc % 2 or abs(fs_hz / f_hz - ppc) > 1e-9:
        raise ValueError("fs/f must be an even integer")
    n = whole_cycles(ppc) * ppc
    return check_codes(struct.pack(f"<{n}H", *[center + amp_codes if (i % ppc) < ppc // 2 else center - amp_codes for i in range(n)]))
