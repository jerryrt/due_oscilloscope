"""
Physical link health. Runs first, on purpose.

The native-port cable on this bench is marginal: it failed hard twice on
2026-08-21 with VBUS present and D+/D- dead, enumerating nowhere, and
the run-to-run purity variance has the signature of link-level
retransmits. A physical fault must be diagnosed as one rather than
blamed on whatever firmware happened to change that day, so these run
before anything else and their failure messages say "cable" out loud.
"""

import time

import pytest

import measure
from helpers import assert_fresh, assert_stream_clean, window

pytestmark = pytest.mark.smoke


def test_control_port_answers(board, track):
    """The board is there and it is the firmware we asked for."""
    have, banner = measure.which_track(board)
    assert have == track, (
        f"board reports track {have!r}, expected {track!r}\n{banner}")
    assert "SystemCoreClock" in banner or "MCK" in banner, banner


def test_clock_is_mck_78(board, baseline):
    """MCK 78, not 84.

    Chosen so the ADC clock is 19.5 MHz, inside the 20 MHz datasheet
    limit. Every RC in this suite divides 39 MHz because of it, and
    Track A built at the wrong f_cpu reports a silently wrong micros().
    """
    _, banner = measure.which_track(board)
    mck = baseline["clock"]["mck_hz"]
    adc = baseline["clock"]["adc_clock_hz"]
    assert str(mck) in banner, (
        f"banner does not report MCK {mck}; Track A must be built with "
        f"--build-property build.f_cpu=78000000L\n{banner}")
    assert str(adc) in banner, f"banner does not report ADC clock {adc}"


def test_native_port_enumerates(board):
    """The native port is present and can be opened.

    This is the check that separates a dead cable from dead firmware:
    the control port is served by the 16U2 and answers even when the
    SAM3X's own CDC never comes up.
    """
    try:
        fd = board.open_native(wait=12.0)
    except measure.BoardError as e:
        pytest.fail(
            f"native port did not enumerate: {e}. The control port answered, "
            f"so the SAM3X is running - suspect the native cable before any "
            f"firmware change.")
    try:
        assert board.native, "no native node was recorded"
    finally:
        board.close_native(fd)

    # Opening it again, timed. A healthy stack opens in milliseconds;
    # a control request the device answers wrongly turns this into tens
    # of seconds of host retries with every device counter still green,
    # which is what SET_LINE_CODING did before it accepted its data
    # stage. Cheap to check and it names the right suspect.
    t0 = time.time()
    fd = board.open_native(wait=12.0)
    cost = time.time() - t0
    board.close_native(fd)
    assert cost < 5.0, (
        f"opening the native port took {cost:.1f} s. The device is "
        f"answering control requests wrongly or the link is retrying; "
        f"read the SETUP log with `u`.")


def test_link_carries_a_clean_stream(board, seconds):
    """A short capture with no gaps, no CRC failures and no USB resets.

    Run at a modest rate deliberately: at 50 kHz per channel nothing is
    near any ceiling, so anything wrong here is the link itself.
    """
    before, _ = measure.stream_stats(board)
    res = measure.run_capture(board, preset="1", seconds=window(seconds, 2.0))
    assert_fresh(res, window(seconds, 2.0))
    assert_stream_clean(res)

    # These counters are cumulative since boot, and one bus reset at
    # enumeration is normal. What must not happen is another one during
    # the capture.
    after, text = measure.stream_stats(board)
    resets = after.get("rst", 0) - before.get("rst", 0)
    assert resets == 0, (
        f"the USB link reset {resets} times during the capture: suspect the "
        f"cable before any firmware change\n{text}")
    assert after.get("cfgfail", 0) - before.get("cfgfail", 0) == 0, (
        f"endpoint configuration failed during the capture\n{text}")
    assert after.get("stall", 0) - before.get("stall", 0) == 0, (
        f"the device stalled a control request during the capture\n{text}")


@pytest.mark.track_a
def test_core_did_not_rebuild_endpoints(board, track):
    """Track A only: the core rebuilding endpoint config out from under
    the DMA mode reads downstream as data corruption.

    Zero through a normal run. Climbing means the link is resetting.
    """
    if track != "a":
        pytest.skip("Track A only")
    before, _ = measure.stream_stats(board)
    if before.get("rebuilds") is None:
        pytest.skip("this build does not report rebuilds")
    res = measure.run_capture(board, preset="1", seconds=2.0)
    assert res.stream.frames > 0
    after, text = measure.stream_stats(board)
    grew = after["rebuilds"] - before["rebuilds"]
    assert grew == 0, (
        f"the core rebuilt endpoint configuration {grew} times during the "
        f"capture, which reads downstream as data corruption\n{text}")
