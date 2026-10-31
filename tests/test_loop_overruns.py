"""
Host-fed playback must not make the ADC overrun.

The capture ring and the playback ring sit in different SRAM banks, and
with capture alone the converter never overruns. With a host stream
arriving on bulk OUT, the ADC's PDC read of ADC_LCDR used to land late
whenever the USB DMA held the bus matrix, and the converter overwrote a
result nobody had taken: ADC general overruns, flagged in the frame
header, growing with the playback rate and flipping between a handful
and thousands per run at the matched rate. The same DAC rate played from
the device's own table had none, so the cause is the USB DMA's burst
behaviour and not the DAC. `clock_set_mck()` limits its burst length.

Zero is the requirement, so there is no tolerance here.
"""

import pytest

import control
import measure
from helpers import assert_no_underruns, assert_stream_clean, window
import pacing

ADC_HZ = 453488          # the two-channel ceiling at MCK 78


@pytest.mark.parametrize("dac_sps", [100000, 200000, ADC_HZ])
def test_host_fed_playback_does_not_overrun_the_adc(board, seconds, dac_sps):
    res = measure.run_loop(board, dac_sps=dac_sps, adc_hz=ADC_HZ,
                           channels=2, seconds=window(seconds, pacing.LONG))
    assert not res.refused, f"loop refused\n{res.console}"
    assert_stream_clean(res)
    assert_no_underruns(res)

    assert res.stream.max_overrun == 0, (
        f"overrun_count reached {res.stream.max_overrun} with the DAC fed "
        f"at {dac_sps} sps: a conversion was overwritten before the PDC "
        f"read it")
    assert res.stream.overrun_frames == 0, (
        f"{res.stream.overrun_frames} frames flagged discontinuous")

    # The split by cause, where the track counts it. Track A answers
    # CTL_ERR_OPCODE for STREAM_STATS, so the header above is the check
    # that holds on every track and this only sharpens the message.
    ctl = board.ctl()
    if ctl is not None:
        try:
            stats = ctl.stream_stats()
        except control.ControlError:
            return
        assert stats["govre"] == 0, f"{stats['govre']} ADC general overruns"
