"""
Domain 1: sample rate, low to high.

Every rate here is hz_for(RC) for an integer RC, never a round decimal
number. The trigger is a TC compare against RC and the DAC update is
the same timer on another channel, so 39 MHz / RC is the whole set of
rates the hardware has. A request between two of them simply rounds
down, which shifts every derived frequency by up to a percent while
every counter stays green - so the ladders are RC and the Hz are
derived, not the other way round.
"""

import pytest

import measure
from helpers import (assert_fresh, assert_no_underruns, assert_stream_clean,
                     approx_rate, loop_cmd, record, window)

pytestmark = pytest.mark.scope

TWO_CH = [780, 390, 200, 195, 130, 98, 88, 86]
ONE_CH = [390, 195, 98, 65, 50, 45, 44]
AWG    = [195, 98, 65, 44, 39, 32, 28]

# Playback rates where the host feed did not hold the device ring.
#
# Empty, and the reason is worth keeping. The starvation was never a
# scheduling or feed-policy problem: the host's USB stack was
# discarding bytes write() had counted, and the ring drained at exactly
# that rate. RC 65 lost 0.67% of what was written and its ring decayed
# at 0.73% a second; RC 32 lost 0.67% and decayed at 0.79%.
#
# Writing a constant 512 bytes per write() instead of "whatever is due"
# removed it - same sizes on the wire, same pacing, no loss - and all
# three rates now run clean over repeated ladder passes. See
# Feeder.WRITE_SIZE and test_device_receives_every_byte_the_host_sent,
# which is the test that can still see the residual; this one only sees
# underruns, and underruns are what stopped being the symptom.
STARVES = set()
AWG_STARVES = STARVES


def _ladder_run(board, rc, channels, secs, calibration, tolerance=0):
    hz = measure.hz_for(rc)
    res = measure.run_loop(board, dac_sps=hz, adc_hz=hz, channels=channels,
                           seconds=secs)
    assert not res.refused, (
        f"RC {rc} ({hz} Hz, {channels} ch) was refused\n{res.console}")
    assert_fresh(res, secs)
    assert_stream_clean(res)
    assert_no_underruns(res, tolerance=tolerance)

    assert res.stream.declared_rate_hz == hz, (
        f"RC {rc} produces {hz} Hz, header declares "
        f"{res.stream.declared_rate_hz} Hz")

    measured = res.stream.measured_rate_hz()
    assert measured is not None, "no device timestamps to measure against"
    ratio = approx_rate(measured, hz, tol=0.005)
    record(calibration, f"rate_{channels}ch_rc{rc}",
           {"hz": hz, "measured": round(measured), "ratio": round(ratio, 4)})
    return res


@pytest.mark.parametrize("rc", TWO_CH)
def test_two_channel_ladder(board, seconds, calibration, baseline, rc):
    """Matched loop on both channels, 50 k to the 453,488/ch ceiling."""
    _ladder_run(board, rc, 2, window(seconds, 2.0), calibration,
                tolerance=baseline["playback"]["ladder_underrun_tolerance"])


@pytest.mark.parametrize("rc", [
    pytest.param(rc, marks=pytest.mark.xfail(
        rc in STARVES, strict=False,
        reason="host feed does not hold the playback ring at this rate; "
               "see STARVES and docs/status.md"))
    for rc in ONE_CH])
def test_one_channel_ladder(board, seconds, calibration, baseline, rc):
    """A0 alone, up to its own measured floor of RC 44.

    The top of this ladder is *slower* in conversions per second than
    the top of the two-channel one. A trigger that converts a pair back
    to back amortises overhead a lone conversion pays in full.
    """
    _ladder_run(board, rc, 1, window(seconds, 2.0), calibration,
                tolerance=baseline["playback"]["ladder_underrun_tolerance"])


@pytest.mark.awg
@pytest.mark.parametrize("rc", [
    pytest.param(rc, marks=pytest.mark.xfail(
        rc in AWG_STARVES, strict=False,
        reason="host feed does not hold the ring at this rate; see "
               "AWG_STARVES and docs/status.md"))
    for rc in AWG])
def test_awg_ladder_play_only(board, seconds, calibration, baseline, rc):
    """Playback with no capture running.

    Deliberately play-only: with a capture stream alongside, a fault in
    the DAC path can be masked by, or blamed on, the capture path. The
    top of this ladder is the DACC's own ceiling, which is an MCK limit
    of about 54.7 cycles per conversion rather than anything to do with
    the ADC.
    """
    hz = measure.hz_for(rc)
    secs = window(seconds, 2.0)
    res = measure.run_play(board, dac_sps=hz, seconds=secs)
    assert not res.refused, f"RC {rc} ({hz} sps) was refused\n{res.console}"

    under = res.play.underruns
    assert under is not None, f"no play counters came back\n{res.report}"
    tol = baseline["playback"]["ladder_underrun_tolerance"]
    assert under <= tol, (
        f"{under} underruns at RC {rc} ({hz} sps): the DAC repeated a "
        f"buffer, so what reached the pin is not what the host sent")
    assert res.play.consumed, "the DAC consumed nothing at all"

    # The host has to keep up for the underrun count to mean anything.
    fed = res.host_tx_bytes / res.elapsed_s
    want = hz * 2.0
    record(calibration, f"awg_rc{rc}",
           {"sps": hz, "fed_mbs": round(fed / 1e6, 3),
            "underruns": under})
    assert fed >= 0.95 * want, (
        f"host fed {fed/1e6:.3f} MB/s against the {want/1e6:.3f} MB/s that "
        f"{hz} sps needs; under=0 proves nothing if the device was never "
        f"asked for the rate")


@pytest.mark.smoke
def test_every_ladder_rate_is_a_real_divider_value():
    """The ladders are RC, and the Hz are derived from them.

    A rate that does not divide 39 MHz truncates in RC and shifts every
    frequency derived from it. Keeping the ladders in RC makes that
    impossible to write by accident.
    """
    for name, ladder in (("2ch", TWO_CH), ("1ch", ONE_CH), ("awg", AWG)):
        for rc in ladder:
            hz = measure.hz_for(rc)
            assert measure.rc_for(hz) == rc, (
                f"{name} RC {rc} gives {hz} Hz, which rounds back to "
                f"RC {measure.rc_for(hz)}")
            assert measure.TC_CLOCK_HZ // rc == hz
