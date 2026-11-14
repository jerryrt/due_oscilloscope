"""Ideal ADS1115 measurement helper: differential voltage -> output code.

License: CC-BY-SA 4.0. Clean-room: built only from FACTS.md (datasheet facts), sec 6.
Ideal means no offset, gain error, noise or INL (FACTS sec 7 figures are not applied).
"""

# FSR (V) -> LSB (V), FACTS sec 6 (PGA table, p15/p26). LSB = FSR / 32768 (the table
# values, e.g. 6.144 V -> 187.5 uV, govern; the datasheet's "FSR / 2^16" counts the
# whole +/-FSR span).
LSB_TABLE = {
    6.144: 187.5e-6,
    4.096: 125e-6,
    2.048: 62.5e-6,
    1.024: 31.25e-6,
    0.512: 15.625e-6,
    0.256: 7.8125e-6,
}
CODE_MIN, CODE_MAX = -32768, 32767  # 16-bit two's complement (FACTS sec 6)


def _key(fsr):
    for k in LSB_TABLE:
        if abs(k - fsr) < 1e-9:
            return k
    raise ValueError(f"FSR {fsr} V is not an ADS1115 setting {sorted(LSB_TABLE)}")


def lsb(fsr):
    """LSB in volts for an FSR setting."""
    return LSB_TABLE[_key(fsr)]


def code(vin, fsr, vdd=None, single_ended=False):
    """Output code for differential input vin (V = V(AINP) - V(AINN)).

    Rounds to nearest (MODELLING CHOICE: the datasheet states no rounding rule) and
    saturates at the 16-bit limits. vdd: when given and below FSR, |vin| is limited to
    vdd (FACTS sec 1, p15: codes beyond are unused). single_ended: negative codes are
    not produced, 0..32767 (FACTS sec 2, Fig 9-2).
    """
    k = _key(fsr)
    if vdd is not None:
        vin = max(-vdd, min(vdd, vin))
    n = int(round(vin / LSB_TABLE[k]))
    lo = 0 if single_ended else CODE_MIN
    return max(lo, min(CODE_MAX, n))


def volts(c, fsr):
    """Input voltage (V) a code represents at an FSR setting."""
    return c * lsb(fsr)
