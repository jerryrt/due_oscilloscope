"""
The wire contract: what the header promises, and what the device refuses.

Cheap and first, because a contract regression is worth catching before
the long streaming tests have started running. Refusals get as much
attention as successes: an over-fast trigger is dropped with no status
bit set, so the guard is the only thing standing between that and
corrupt data presented as clean.
"""

import pytest

import measure
from helpers import assert_fresh, loop_cmd, window

pytestmark = pytest.mark.smoke


def test_frame_header_is_self_consistent(board, baseline, seconds):
    """One shape for the whole run, and the shape the protocol says."""
    res = measure.run_capture(board, preset="3",
                              seconds=window(seconds, 2.0))
    assert_fresh(res, window(seconds, 2.0))
    ps = res.stream

    f = baseline["frame"]
    assert ps.version == 1
    assert ps.bits_per_sample == 12
    assert ps.packing == 0, "0 = 12-bit right aligned in 16-bit LE"
    assert ps.n_samples == f["samples"]
    assert measure.HDR_LEN == f["header_bytes"]
    assert measure.HDR_LEN + ps.n_samples * 2 == f["bytes"], (
        "the frame must stay a whole number of 512-byte USB packets")
    assert ps.crc_bad == 0
    assert ps.inconsistent == 0, (
        f"{ps.inconsistent} frames declared a different rate, mask or size "
        f"than the run started with")


@pytest.mark.parametrize("rc", [780, 390, 195, 130, 98, 86])
def test_declared_rate_is_the_rate_the_hardware_makes(board, rc):
    """header.sample_rate_hz == 39 MHz / RC.

    The trigger is a TC compare against RC, so those are the only rates
    that exist: the suite asks for hz_for(rc) throughout rather than
    round decimal numbers, because a request between two RC values just
    rounds down to one of them. What is checked here is that the header
    then declares the rate the hardware makes and not the one that was
    asked for - a header repeating the request would make every
    frequency the host derives from it wrong by the same fraction, with
    nothing to show for it.
    """
    hz = measure.hz_for(rc)
    res = measure.run_capture(board, preset=loop_cmd(hz), seconds=1.2)
    assert res.stream.frames, f"no frames at RC {rc} ({hz} Hz): {res.console}"
    assert res.stream.declared_rate_hz == hz, (
        f"RC {rc} produces {hz} Hz, header declares "
        f"{res.stream.declared_rate_hz} Hz")
    assert measure.rc_for(hz) == rc, (
        f"{hz} Hz does not round-trip to RC {rc}; the ladder must be "
        f"expressed in RC, not in Hz")


@pytest.mark.parametrize("channels,key_floor,key_cliff", [
    (2, "two_ch_floor", "two_ch_cliff"),
    (1, "one_ch_floor", "one_ch_cliff"),
])
def test_floor_accepted_and_cliff_refused(board, baseline, channels,
                                          key_floor, key_cliff):
    """The measured floor works; one RC past it is refused.

    The floors are a table of measured values, never a scaled one. One
    channel's floor is RC 44 and not half of the two-channel 86: a
    two-channel trigger converts its pair back to back and amortises the
    per-trigger overhead that a lone conversion pays in full.
    """
    floor_rc = baseline["rc"][key_floor]
    cliff_rc = baseline["rc"][key_cliff]

    ok, text = measure.probe_loop(board, adc_hz=measure.hz_for(floor_rc),
                                  channels=channels)
    assert ok, (f"RC {floor_rc} ({measure.hz_for(floor_rc)} Hz) on "
                f"{channels} channel(s) was refused\n{text}")

    ok, text = measure.probe_loop(board, adc_hz=measure.hz_for(cliff_rc),
                                  channels=channels)
    assert not ok, (
        f"RC {cliff_rc} ({measure.hz_for(cliff_rc)} Hz) on {channels} "
        f"channel(s) was accepted. It is past the measured cliff, where "
        f"every other trigger is dropped with no status bit set, so the "
        f"stream would read as clean data at half the rate\n{text}")
    assert "max" in text, (
        f"a refusal must name the limit it refused against\n{text}")


def test_one_channel_is_not_twice_two_channel(baseline):
    """The arithmetic that looks obvious and is wrong.

    Halving the two-channel RC 86 gives 43, which measures ratio 0.500
    with every status bit clear. The measured one-channel floor is 44,
    and one channel therefore converts *slower* in total than two.
    """
    rc = baseline["rc"]
    rates = baseline["rates_hz"]
    assert rc["one_ch_floor"] != rc["two_ch_floor"] // 2
    assert rates["one_ch"] < rates["two_ch_aggregate"], (
        "one channel aggregates fewer conversions per second than two; a "
        "test that assumes otherwise encodes the bug")


def test_channel_mask_matches_what_was_asked_for(board):
    for channels, expect in ((2, {measure.CH_A0, measure.CH_A1}),
                             (1, {measure.CH_A0})):
        res = measure.run_capture(board, preset=loop_cmd(200000, channels),
                                  seconds=1.2)
        assert res.stream.frames, (
            f"no frames on {channels} channel(s): {res.console}")
        mask = res.stream.channel_mask
        got = {i for i in range(16) if mask & (1 << i)}
        assert got == expect, (
            f"{channels} channel(s) requested, header mask {mask:#06x} "
            f"means {sorted(got)}, expected {sorted(expect)}")
        assert set(res.stream.per_channel) == expect, (
            f"samples arrived tagged {sorted(res.stream.per_channel)}, "
            f"header mask says {sorted(expect)}")
