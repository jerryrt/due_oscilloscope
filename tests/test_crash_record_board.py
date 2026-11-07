"""The fault record on a board: a deliberate fault is recorded, survives the
reset it ends in, is reported once, and leaves a board that works.

`f` jumps into non-executable RAM (an INVSTATE fault with PC 0x20000000),
which is the same path an accidental fault takes. The board dumps the
frame on the UART, keeps it in RAM that start-up does not clear, detaches
USB and resets; the next boot reports it through `c`.

Three things are held, each able to fail on its own:

 * the record - the fault counts, `c` carries the PC and the status
   registers, and the cause is a software reset;
 * the control - an ordinary `z` restart is NOT reported as a fault, so
   the first assertion cannot be satisfied by a board that always says so;
 * the board after - the native port comes back by itself and a stream
   runs clean, which is what "a software reset leaves USB attached and
   wedges the host" would break.

Opening the programming port with a library that toggles DTR resets the
board through the 16U2 and wipes the record; `measure.Board` opens it
without. A probe of your own must do the same.
"""
import time

import pytest

import measure
import pacing

# Every test here faults or restarts the board; see conftest.py.
pytestmark = pytest.mark.disruptive

INVSTATE = 0x00020000


def _crash(board):
    text = board.ask("c", secs=pacing.LISTEN)
    rec = measure.parse_crash(text)
    assert rec is not None, f"`c` said nothing parseable: {text!r}"
    return rec


# The handler resets for a fault only while fewer than three came in a
# row without 5 s of healthy running between them (CRASHREC_HEALTHY_MS);
# the third halts and blinks, by design, and a halted board answers
# nothing. `c` cannot show the streak clearing - it prints what the boot
# found, not the live record - so the test keeps its own clock: when the
# board last restarted, by a fault or by `z`. Uptime restarts at either.
HEALTHY_S = 5.0
_last_restart = None


def _restarted():
    global _last_restart
    _last_restart = time.monotonic()


def _let_the_board_be_healthy():
    """Wait out whatever is left of the healthy period, and no more.

    The host sees the banner after the board has started it, so the time
    measured here is never longer than the board's uptime: the wait can
    be a little long and cannot be short. Three tests faulting in a row
    gave the board seconds between faults, and the third one tripped the
    guard - the guard working, reported as a failure of the test.
    """
    if _last_restart is None:
        return
    left = HEALTHY_S + 0.5 - (time.monotonic() - _last_restart)
    if left > 0:
        pacing.pause(left)


def _restart(board):
    """`z`, with the restart noted."""
    said = board.reset()
    _restarted()
    return said


def _fault(board):
    """Send `f`; return what the console said until the banner came back."""
    _let_the_board_be_healthy()
    board.poll_console()
    board.cmd("f")
    said = board.drain_console(0, quiet=pacing.LISTEN, cap=pacing.SLOW)
    # A fault detaches USB and re-enumerates it, which a plain `z` does
    # not, so the cached command link now points at a node that is gone.
    board.ctl_invalidate()
    _restarted()
    return said


def _loop_is_clean(board):
    res = measure.run_loop(board, dac_sps=200000, adc_hz=200000, channels=2,
                           tone=1000.0, seconds=pacing.SHORT, square=1000.0)
    ps = res.stream
    assert ps.frames, "no frames after the fault: the native port did not come back"
    assert ps.crc_bad == 0 and ps.seq_gaps == 0, (
        f"stream after the fault: crc_bad {ps.crc_bad}, gaps {ps.seq_gaps}")


def test_a_deliberate_fault_is_recorded_and_the_board_comes_back(board):
    before = _crash(board)
    said = _fault(board)
    assert "HARD FAULT" in said, f"the handler did not report: {said!r}"
    assert "resetting" in said, (
        "the handler did not reset, so the host would be left with a dead "
        f"board: {said!r}")
    assert "due_oscilloscope" in said, (
        f"no banner after the fault: the board did not restart: {said!r}")
    after = _crash(board)
    assert after["fault"] == 1, after
    assert after["reset"] == "software", after
    assert after["count"] == before["count"] + 1, (before, after)
    assert after["pc"] == 0x20000000, after
    assert after["cfsr"] & INVSTATE, after
    _loop_is_clean(board)


def test_an_ordinary_restart_is_not_a_fault(board):
    _fault(board)                       # make sure a record has existed
    _restart(board)
    rec = _crash(board)
    assert rec["fault"] == 0, (
        f"a plain restart was reported as a fault: {rec}")
    assert rec["reset"] == "software", rec
    assert rec["count"] >= 1, "the lifetime count was lost by a plain restart"


def test_a_fault_during_a_stream_recovers(board):
    board.poll_console()
    board.cmd("3")                      # start a capture stream
    pacing.pause(1.0)
    before = _crash(board)["count"]
    _fault(board)
    rec = _crash(board)
    assert rec["fault"] == 1 and rec["count"] == before + 1, rec
    _loop_is_clean(board)
