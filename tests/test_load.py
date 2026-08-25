"""
The main-loop load monitor, and whether it can be believed.

This file exists before anything uses the monitor to diagnose
something, because an instrument that has not been checked against a
known input is a source of confident wrong answers. Everything else
this board reports about how hard it is working is after the fact - an
underrun, an overrun, a ring that ran dry - and all of those say the
loop was too slow somewhere without saying when or for how long.

The check that matters is the stall: the *host* picks a duration the
device was never told, the device is made to block for it, and the
monitor has to report it. Agreeing with a printf or a sweep would only
prove that two unknowns match.

Track B only. Track A has no monitor yet.
"""

import re
import time

import pytest

import control
import ports

pytestmark = pytest.mark.smoke


@pytest.fixture
def link(board, track):
    if track != "b":
        pytest.skip("Track A has no load monitor yet")
    # The board owns the one control link for the session, the same way
    # it owns the console port and for the same reason. A fixture that
    # opened its own used to work; it stopped the day measure.py started
    # using the channel too, because the port does not open twice.
    c = board.ctl()
    if c is None:
        pytest.fail("the board does not present a command port")
    try:
        yield c
    finally:
        # Drained, not closed: the board owns it.
        c.drain()


def clear(board):
    """Reset the worst case. Cumulative counters can be differenced; a
    maximum cannot, so clearing has to be explicit."""
    board.ask("=1l", secs=1.0)
    time.sleep(0.2)


def window(link, secs):
    """(elapsed_s, passes, per_bucket_delta, worst_us) over one interval.

    Timed by the device's own clock rather than the host's: a host that
    is descheduled mid-window would otherwise report a slower loop than
    the device ran.
    """
    a = link.load()
    time.sleep(secs)
    z = link.load()
    dt = (z["dev_us"] - a["dev_us"]) / 1e6
    dp = z["passes"] - a["passes"]
    delta = [h1 - h0 for h0, h1 in zip(a["hist"], z["hist"])]
    return dt, dp, delta, z["max_us"]


def test_the_cycle_counter_is_present_and_counting(link, baseline):
    """CYCCNT is optional on Cortex-M3, so its absence is reported.

    A counter stuck at zero would make every pass read as zero cycles,
    which a host would take for an infinitely fast loop rather than a
    broken instrument. control.load() raises rather than return that,
    so reaching the assert at all is most of the test.
    """
    r = link.load()
    assert r["mck_hz"] == baseline["clock"]["mck_hz"]
    assert r["passes"] > 0
    assert len(r["hist"]) == control.LOAD_BUCKETS


@pytest.mark.parametrize("want_ms", [25, 100, 400])
def test_a_stall_the_host_chose_is_reported(link, board, baseline, want_ms):
    """The load monitor against a number it was not told.

    The stall is asked for on the *console* and read back over the
    *control channel*, so this also shows the two transports agree
    about one device rather than each reporting its own idea of it.

    The injector busy-waits on millis(), so it is itself quantised to
    about a millisecond; the tolerance is that, not the monitor's.
    """
    tol = baseline["load"]["stall_tolerance_ms"]

    clear(board)
    board.cmd("=%dS" % want_ms)
    time.sleep(want_ms / 1000.0 + 0.4)
    board.drain_console(0.3)

    got_ms = link.load()["max_us"] / 1000.0
    assert abs(got_ms - want_ms) <= tol, (
        f"asked the loop to block for {want_ms} ms and the monitor "
        f"reported a worst pass of {got_ms:.3f} ms. Either the monitor "
        f"is wrong or the loop did not block; `l` on the console shows "
        f"which.")


def test_clearing_resets_the_worst_case(link, board):
    """Otherwise one stall would sit in the report for ever.

    Reading must not clear, because two consumers - the console and the
    control channel - would then steal each other's worst case. So the
    clear is a separate act, and this is what says it happened.
    """
    clear(board)
    board.cmd("=200S")
    time.sleep(0.7)
    board.drain_console(0.3)
    assert link.load()["max_us"] > 150000, "the stall was not recorded"

    clear(board)
    assert link.load()["max_us"] < 150000, (
        "clearing did not reset the worst case, so every later reading "
        "would report this stall instead of what was happening then")


def test_the_idle_loop_is_fast_and_uniform(link, board, baseline):
    """What "healthy" looks like, so that "not healthy" means something.

    Nearly every pass lands in a single log2 bucket. That tightness is
    the whole value of the instrument: against a distribution this
    narrow, one pass several buckets to the right is unmistakable.
    """
    floor = baseline["load"]["passes_per_s_floor"]
    frac = baseline["load"]["main_bucket_fraction_floor"]

    clear(board)
    dt, dp, delta, _worst = window(link, 2.0)
    rate = dp / dt
    assert rate >= floor, (
        f"the idle main loop ran {rate/1000:.1f} k passes/s, below the "
        f"{floor/1000:.0f} k floor. Something is blocking it.")
    assert max(delta) / dp >= frac, (
        f"idle passes are spread across buckets {[i for i, n in enumerate(delta) if n]}; "
        f"a healthy idle loop puts them in one.")


def test_capture_does_not_block_the_main_loop(link, board, baseline):
    """The loop keeps running while the ADC streams at its ceiling.

    This is the property the OUT drain depends on, and the one whose
    absence produces a NAKing pipe and a host stuck in close(). Cleared
    *after* the stream is started so that the measurement is steady
    state and not the several milliseconds the start command spends in
    printf.
    """
    floor = baseline["load"]["passes_per_s_floor"]
    ceiling = baseline["load"]["steady_worst_pass_ceiling_us"]

    board.cmd("5")                       # max in-spec capture
    time.sleep(0.8)
    board.drain_console(0.5)
    try:
        clear(board)
        dt, dp, _delta, worst = window(link, 2.0)
    finally:
        board.stop()
        time.sleep(0.3)
        board.drain_console(0.5)

    rate = dp / dt
    assert rate >= floor, (
        f"the main loop ran {rate/1000:.1f} k passes/s while capturing, "
        f"below the {floor/1000:.0f} k floor")
    assert worst <= ceiling, (
        f"a single pass took {worst:.0f} us while capturing, over the "
        f"{ceiling} us ceiling. For that long the loop drained no bulk "
        f"OUT, which is how a host ends up wedged in close().")


def test_the_console_and_the_control_channel_agree(link, board):
    """One device, two transports, one set of numbers.

    They are read seconds apart so the pass counts cannot match
    exactly; what must hold is that the console's figure lies between
    two control-channel readings that bracket it. A transport reporting
    its own private copy would fail that.
    """
    before = link.load()["passes"]
    txt = board.ask("l", secs=2.0)
    after = link.load()["passes"]

    m = re.search(r"passes=(\d+)", txt)
    assert m, f"the console did not report a pass count:\n{txt}"
    console = int(m.group(1))
    assert before <= console <= after, (
        f"the console reported {console} passes, outside the "
        f"{before}..{after} the control channel bracketed it with")
