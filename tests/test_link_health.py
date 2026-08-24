"""
Physical link health. Runs first, on purpose.

The native-port cable on this bench is marginal: it failed hard twice on
2026-08-21 with VBUS present and D+/D- dead, enumerating nowhere, and
the run-to-run purity variance has the signature of link-level
retransmits. A physical fault must be diagnosed as one rather than
blamed on whatever firmware happened to change that day, so these run
before anything else and their failure messages say "cable" out loud.
"""

import os
import time

import pytest

import measure
import ports
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


def test_native_port_offers_both_functions(board, track):
    """One cable, two CDC functions: samples and commands.

    The deployed board has only the native port, so a control path that
    lives on the programming port does not exist in deployment at all.
    This is the check that the second function is really there and is
    really the one the numbering pins - interfaces 0 and 1 for samples,
    2 and 3 for commands - rather than two nodes that happen to appear.
    """
    if track != "b":
        pytest.skip("Track A has no control channel yet (it follows Track B)")

    ctl, samples, commands = ports.find_all_ports(wait=12.0)
    assert ctl, "the control port stopped answering"
    assert samples, "no native sample node"
    assert commands, (
        "the native port offers only one CDC function. Track B firmware "
        "should present two; a board flashed with an older build will "
        "fail here, which is the intended reading.")

    ifaces = ports.usb_interfaces()
    if not ifaces:
        pytest.skip("IOKit did not answer; interface numbers unverifiable")

    sam_serial, sam_iface = ifaces[samples]
    cmd_serial, cmd_iface = ifaces[commands]
    assert sam_serial == cmd_serial, (
        f"the two nodes belong to different devices: {sam_serial!r} and "
        f"{cmd_serial!r}. Two boards are attached, or discovery paired "
        f"them wrongly.")
    assert (sam_iface, cmd_iface) == (1, 3), (
        f"interfaces are {sam_iface} and {cmd_iface}, not 1 and 3. The "
        f"numbering is a contract shared with Track A - see "
        f"docs/control-protocol.md - so a change here breaks the host "
        f"against one track or the other.")


def test_command_port_opens_and_closes(board, track):
    """The command port can be opened, written and closed, promptly.

    Its bulk OUT is drained by the main loop even though nothing
    consumes it yet, and that is not decoration: an allocated bulk OUT
    that nobody drains NAKs forever, and macOS's close() waits on write
    URBs that will never complete. Without the drain, adding the
    endpoint would have turned a port that does nothing into a port that
    hangs the machine - so this asserts the close, not just the open.
    """
    if track != "b":
        pytest.skip("Track A has no control channel yet (it follows Track B)")

    _ctl, _samples, commands = ports.find_all_ports(wait=12.0)
    if not commands:
        pytest.skip("no command node; covered by the test above")

    t0 = time.time()
    fd = measure.open_raw(commands, 115200, dtr=True)
    opened = time.time() - t0
    try:
        os.set_blocking(fd, True)
        n = os.write(fd, b"\x00" * 2048)
        assert n == 2048, f"short write of {n} bytes to the command port"
    finally:
        t0 = time.time()
        os.close(fd)
        closed = time.time() - t0

    assert opened < 5.0, f"opening the command port took {opened:.1f} s"
    assert closed < 5.0, (
        f"closing the command port took {closed:.1f} s. The device is not "
        f"draining its bulk OUT, so the host is waiting on write URBs that "
        f"will never complete.")


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
    # rebuilds is reported by `B`, the bench report, not by `?`.
    before = measure.parse_bench(board.ask("B", secs=1.2))
    if before.rebuilds is None:
        pytest.skip("this build does not report rebuilds")
    res = measure.run_capture(board, preset="1", seconds=2.0)
    assert res.stream.frames > 0
    after = measure.parse_bench(board.ask("B", secs=1.2))
    text = after.raw
    grew = after.rebuilds - before.rebuilds
    assert grew == 0, (
        f"the core rebuilt endpoint configuration {grew} times during the "
        f"capture, which reads downstream as data corruption\n{text}")
