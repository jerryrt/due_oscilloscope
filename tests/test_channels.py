"""
Domain 3: channels and ceilings.

Mostly contract, so it runs before the long streaming tests. The thing
being pinned down is that the ADC is one converter behind a 16:1
multiplexer: channels sample round robin, so the channel count divides
the aggregate rather than multiplying it, and the per-channel-count
floors are measured values rather than scaled ones.
"""

import pytest

import measure
from helpers import (assert_fresh, assert_no_underruns, assert_stream_clean,
                     loop_cmd, window)


def _accepted(rows):
    return [r for r in rows if not r.refused and r.ratio is not None]


@pytest.mark.parametrize("channels", [2, 1])
def test_sweep_ratio_is_one_above_the_cliff(board, baseline, channels):
    """Every rate the guard accepts converts on every trigger.

    Ratio 0.500 is the signature of the silent cliff: the ADC drops
    every other trigger with no status bit set, which is indistinguish-
    able from clean data at half the rate unless the rate is checked.
    """
    rows, text = measure.sweep_rates(board, channels=channels)
    assert rows, f"the sweep produced no parseable rows\n{text}"

    ok = _accepted(rows)
    assert ok, f"the sweep accepted no rate at all\n{text}"
    for r in ok:
        assert 0.99 <= r.ratio <= 1.01, (
            f"RC {r.rc} ({r.trigger_hz} Hz) measured ratio {r.ratio:.3f}. "
            f"0.500 means every other trigger was dropped silently.\n{r.raw}")
        assert not r.rxbuff, f"RXBUFF overrun at RC {r.rc}\n{r.raw}"
        assert not r.govre, f"general overrun at RC {r.rc}\n{r.raw}"


@pytest.mark.parametrize("channels,key", [(2, "two_ch_floor"),
                                          (1, "one_ch_floor")])
def test_sweep_refuses_only_below_the_floor(board, baseline, channels, key):
    floor = baseline["rc"][key]
    rows, text = measure.sweep_rates(board, channels=channels)
    for r in rows:
        if r.refused:
            assert r.rc < floor, (
                f"RC {r.rc} was refused but the measured floor for "
                f"{channels} channel(s) is {floor}\n{r.raw}")
        else:
            assert r.rc >= floor, (
                f"RC {r.rc} was accepted below the measured floor "
                f"{floor}\n{r.raw}")


@pytest.mark.parametrize("channels,key", [(2, "two_ch_aggregate"),
                                          (1, "one_ch")])
def test_aggregate_conversion_rate_at_the_floor(board, baseline, calibration,
                                                channels, key):
    """What the converter actually delivers, measured from device time."""
    floor = baseline["rc"]["two_ch_floor" if channels == 2 else "one_ch_floor"]
    per_ch = measure.hz_for(floor)
    res = measure.run_capture(board, preset=loop_cmd(per_ch, channels),
                              seconds=2.0)
    assert_fresh(res, 2.0)
    assert_stream_clean(res)

    measured = res.stream.measured_rate_hz()
    assert measured is not None, "no device timestamps to measure against"
    aggregate = measured * channels
    calibration[f"aggregate_{channels}ch"] = round(aggregate)

    want = baseline["rates_hz"][key]
    assert abs(aggregate / want - 1.0) <= 0.005, (
        f"{channels} channel(s) at RC {floor} aggregate {aggregate:.0f} "
        f"conversions/s against a measured baseline of {want}")


def test_one_channel_aggregates_less_than_two(board, baseline, calibration):
    """Measured, not assumed, because the intuition is backwards.

    A two-channel trigger converts its pair back to back and amortises
    the per-trigger overhead that a lone conversion pays in full, so one
    channel reaches 886,363 conversions per second against 906,976 for
    two.
    """
    got = {}
    for channels in (1, 2):
        floor = baseline["rc"]["one_ch_floor" if channels == 1
                               else "two_ch_floor"]
        res = measure.run_capture(
            board, preset=loop_cmd(measure.hz_for(floor), channels),
            seconds=2.0)
        assert_fresh(res, 2.0)
        got[channels] = res.stream.measured_rate_hz() * channels

    calibration["aggregate_1ch_vs_2ch"] = [round(got[1]), round(got[2])]
    assert got[1] < got[2], (
        f"one channel aggregated {got[1]:.0f} conversions/s and two "
        f"aggregated {got[2]:.0f}; one channel must be the slower of the "
        f"two, and a design sized on the opposite is sized wrong")


@pytest.mark.parametrize("channels", [2, 1])
def test_every_sample_tag_is_in_the_mask(board, channels):
    """Tag hygiene. A sample tagged for a channel the mask does not
    enable means the demultiplexing is wrong, and the whole capture is
    attributed to the wrong pins."""
    res = measure.run_capture(board, preset=loop_cmd(200000, channels),
                              seconds=1.5)
    assert_fresh(res, 1.5)
    mask = res.stream.channel_mask
    allowed = {i for i in range(16) if mask & (1 << i)}
    got = set(res.stream.per_channel)
    assert got == allowed, (
        f"samples carried tags {sorted(got)} against a header mask of "
        f"{sorted(allowed)}")
    assert len(allowed) == channels


@pytest.mark.parametrize("channels,dac,adc", [
    (2, 906976, 453488),     # 906,976 conversions/s, two channels round robin
    (1, 886363, 886363),     # the single-channel ceiling, matched each way
])
def test_matched_full_rate_loop(board, seconds, calibration, channels,
                                dac, adc):
    """The full-rate pair, fed and captured at once.

    This is the configuration the instrument is for, and the one where
    the counters have to be read together: under=0 says the DAC never
    repeated a buffer, and gaps=0 says nothing was spliced.
    """
    secs = window(seconds, 3.0)
    res = measure.run_loop(board, dac_sps=dac, adc_hz=adc, channels=channels,
                           seconds=secs)
    assert not res.refused, f"the device refused the pair\n{res.console}"
    assert_fresh(res, secs)
    assert_stream_clean(res)
    assert_no_underruns(res)

    measured = res.stream.measured_rate_hz()
    calibration[f"full_rate_{channels}ch"] = {
        "declared": res.stream.declared_rate_hz,
        "measured": round(measured or 0),
        "host_tx_mbs": round(res.host_tx_bytes / res.elapsed_s / 1e6, 3),
        "host_rx_mbs": round(res.host_rx_bytes / res.elapsed_s / 1e6, 3),
    }
    assert abs(measured / res.stream.declared_rate_hz - 1.0) <= 0.005, (
        f"measured {measured:.0f} Hz/ch against a declared "
        f"{res.stream.declared_rate_hz} Hz/ch")
