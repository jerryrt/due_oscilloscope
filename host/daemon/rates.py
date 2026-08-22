"""Rate policy: what the hardware can actually produce, and refusing
what it cannot before the device has to.

Every rate this instrument has is `39 MHz / RC` for an integer RC. A
request between two of them is not an error, but silently rounding it
and then reporting the number that was asked for is: a frame header
once declared the requested rate rather than the one the hardware
makes, and that was a defect. So everything here returns the rate the
hardware will produce, and the caller shows *that*.

The floors are measured values, not derived ones. One channel reaches
886,363 conversions per second and two reach 906,976, because a
two-channel trigger converts its pair back to back and amortises
overhead a lone conversion pays in full - so halving the two-channel
compare value is wrong, and the table exists for that reason.

This duplicates limits the firmware also knows, which is exactly what
the capability report in `docs/frontend.md` is meant to end. Until then
the device remains the authority: these checks only catch what can be
caught early, and a refusal from the board is still forwarded verbatim.
"""

from __future__ import annotations

TC_CLOCK_HZ = 39_000_000

# Trigger floors in RC, per channel count. Measured; see docs/status.md.
ACQ_MIN_RC = {1: 44, 2: 86}

# The DACC's own ceiling, an MCK limit of ~54.7 cycles per conversion.
DAC_MIN_RC = 28

# Slowest useful rate before RC overflows anything sensible.
MAX_RC = 65535


class RateError(ValueError):
    """A rate the hardware cannot produce. The message names the limit."""


def rc_for(hz):
    return TC_CLOCK_HZ // hz if hz else 0


def hz_for(rc):
    return TC_CLOCK_HZ // rc if rc else 0


def snap(hz):
    """(rc, actual_hz) for a requested rate.

    RC is `39 MHz // hz`, the same truncation the firmware does, so the
    rate that comes back is the nearest one **at or above** the request,
    not the nearest one either side: 200,000 gives RC 195 and exactly
    200,000, while 200,001 gives RC 194 and 201,030. Sixteen thousand
    hertz of difference from a request one hertz higher is not a
    rounding error to hide - it is why the caller must display what
    comes back rather than what it asked for.
    """
    if hz is None or hz <= 0:
        raise RateError(f"rate must be positive, got {hz!r}")
    rc = rc_for(hz)
    if rc < 1:
        raise RateError(
            f"{hz} Hz needs RC 0; the fastest rate is "
            f"{hz_for(DAC_MIN_RC)} Hz at RC {DAC_MIN_RC}")
    if rc > MAX_RC:
        raise RateError(f"{hz} Hz needs RC {rc}, above the {MAX_RC} limit")
    return rc, hz_for(rc)


def check_capture(hz, channels):
    """Snap a capture rate and refuse one past the trigger floor.

    Trigger overrun is silent: past the floor the ADC converts every
    other trigger with no status bit set, and the stream keeps flowing
    at half the rate it claims. Refusing here is cheaper than
    discovering it in the data.
    """
    if channels not in ACQ_MIN_RC:
        raise RateError(
            f"{channels} channels is not a mode this firmware has; "
            f"choose {' or '.join(str(k) for k in sorted(ACQ_MIN_RC))}")
    rc, actual = snap(hz)
    floor = ACQ_MIN_RC[channels]
    if rc < floor:
        raise RateError(
            f"{hz} Hz is RC {rc}, past the measured floor of RC {floor} "
            f"for {channels} channel(s) - {hz_for(floor)} Hz. Above it the "
            f"trigger overruns silently and the ADC converts every other "
            f"trigger")
    return rc, actual


def check_dac(hz):
    """Snap a DAC update rate and refuse one past the DACC's ceiling."""
    rc, actual = snap(hz)
    if rc < DAC_MIN_RC:
        raise RateError(
            f"{hz} Hz is RC {rc}, past the DACC ceiling of RC {DAC_MIN_RC} "
            f"- {hz_for(DAC_MIN_RC)} Hz")
    return rc, actual


def describe():
    """The limits as data, for a client that would otherwise hardcode
    them. Replaced by the device's own capability report when the
    firmware grows one."""
    return {
        "tc_clock_hz": TC_CLOCK_HZ,
        "acq_min_rc": dict(ACQ_MIN_RC),
        "acq_max_hz": {str(k): hz_for(v) for k, v in ACQ_MIN_RC.items()},
        "dac_min_rc": DAC_MIN_RC,
        "dac_max_hz": hz_for(DAC_MIN_RC),
        "source": "host table, measured; not reported by the device yet",
    }
