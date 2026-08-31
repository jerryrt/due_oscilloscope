"""One reader on the stream during `start()`, not two. Issue #44.

`Server._read_loop` drains the device for the daemon's whole lifetime
and asks only `device.read()` whether there is anything to take. So
whatever `read()` gates on decides when that thread is allowed to touch
the descriptor.

`BoardDevice.start()` assigns `self.fd` and then spends seconds before
it is finished: `drain_until_quiet(cap=5.0)`, the `=<dac>,<adc>L`
command, a 0.2 s settle, and a console drain. While `read()` gated only
on `fd is None`, the reader thread was inside that window with it, and
**two threads split one stream**.

Both consequences are real and the second is #44's headline:

- the drain does not drain - bytes it was meant to discard reach
  subscribers instead;
- frames from the new run that arrive inside the window are consumed by
  `drain_until_quiet` and discarded. Tens to hundreds, at the start of a
  run, which is the phenomenon this issue is named for.

**`FakeDevice` has always gated on `running`.** That is why the whole
board-free tier could not see this: the fake implements the contract and
the real device did not, so every daemon test ran against the one that
was right. A test that only ever exercises the stand-in cannot find a
divergence between the stand-in and the thing.

So this asserts the gate on **both** implementations, from the outside,
by the behaviour rather than by reading the source: a device that is not
running hands the reader nothing, whatever its descriptor says.
"""

import os
import sys

import pytest

pytestmark = pytest.mark.smoke

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "host"))


class _Fd:
    """A descriptor that would hand over data if anyone asked it.

    The point of the test is that nobody asks. If `read()` ever reaches
    this, the gate is open when it should be shut and `used` says so.

    `log` is optional and only the ordering cases pass one: they need to
    know *when* the descriptor was read, not merely whether.
    """

    def __init__(self, log=None):
        self.used = False
        self.log = log

    def _note(self):
        self.used = True
        if self.log is not None:
            self.log.append("fd-read")

    def fileno(self):
        self._note()
        return 0

    def read(self, _n):
        self._note()
        return b"x" * 4096


def _board_device_not_running():
    """A BoardDevice past `self.fd = ...` and short of `running = True`.

    Built without `__init__` on purpose. Constructing a real one opens
    ports; what is under test is a two-line gate, and the state that
    reaches it is exactly these three attributes.
    """
    from daemon import device as dev

    d = object.__new__(dev.BoardDevice)
    d.fd = _Fd()
    d.running = False
    # The gate is `_readable`, not `running` - issue #57. `running` is
    # set at the END of start(), and gating the read on it left ~0.5 s
    # of full-rate stream unread while the device was already producing,
    # which cost a frame under load on a host that does not absorb it.
    # `_readable` opens the instant `drain_until_quiet` releases the
    # descriptor, which is the only point with exactly one reader and no
    # unread window.
    d._readable = False        # drain_until_quiet still owns the fd
    d._rx = 0
    return d


def test_board_device_reads_nothing_before_start_finishes():
    d = _board_device_not_running()
    assert d.read(timeout=0.01) == b""
    assert not d.fd.used, (
        "BoardDevice.read() touched the descriptor while start() was "
        "still draining it - that is two threads on one stream, and the "
        "frames drain_until_quiet eats are issue #44's lost frames")
    assert d._rx == 0


def test_the_gate_is_readable_and_not_only_the_descriptor():
    """A live descriptor is not sufficient; `_readable` is required.

    Written as its own case because the first gate here passed a test
    that only ever set `fd = None`. Every value below is the
    *permissive* one except the flag, so nothing else can be what stops
    it.
    """
    d = _board_device_not_running()
    assert d.fd is not None
    assert d.read(timeout=0.01) == b""


def test_fake_device_still_refuses_before_it_runs():
    """The stand-in and the thing still agree on the observable.

    They no longer gate on the same *flag* - `BoardDevice` opens at
    `_readable`, which has no meaning for a fake with no descriptor -
    but the behaviour a caller sees is the one that matters: a device
    that is not streaming hands the reader nothing.
    """
    from daemon import device as dev

    f = dev.FakeDevice()
    assert not f.running
    assert f.read(timeout=0.01) == b""


# --- the other half of the gate, which the cases above do not cover ----
#
# Everything above asserts the gate is SHUT early. None of it asserts the
# gate is OPEN in time, and that omission has a bisect against it: gating
# on `running` passed every case above and left ~0.5 s of full-rate
# stream unread, which windows-desk bisected to a lost frame (#57, 0 of
# 10 against 6 of 10, p = 0.011).
#
# A test that only checks one direction of a two-sided invariant reads as
# coverage and is not. So this checks the order directly.


class _Recorder:
    """A board and a measure module that write down what happened."""

    def __init__(self, log):
        self.log = log
        self.RAMP_STEP = 0

    # -- board ---------------------------------------------------------
    def poll_console(self):
        return ""

    def open_native(self, blocking_writes=False):
        self.log.append("open")
        return _Fd(self.log)

    def cmd(self, text):
        self.log.append("cmd")

    def drain_console(self, secs=0.0):
        self.log.append("drain_console")
        return ""

    # -- measure module ------------------------------------------------
    def drain_until_quiet(self, fd, quiet=0.0, cap=0.0):
        # Reads the descriptor, as the real one does. That read has to
        # be visible or the "no reads after the gate opens" case below
        # would be asserting over an empty list and passing for free.
        fd.read(4096)
        self.log.append("drain_until_quiet")


def _start_a_capture():
    """Run BoardDevice.start() against stubs and return the event log."""
    from daemon import device as dev

    log = []
    rec = _Recorder(log)
    d = object.__new__(dev.BoardDevice)
    d.m = rec
    d.board = rec
    d.fd = None
    d.feeder = None
    d.running = False
    d._readable = False
    d.mode = None
    d.rates = None
    d._rx = 0
    d._ctl = None
    d._described = None

    # The gate opening is what this test is about, so record it as an
    # event rather than inspecting the flag afterwards - afterwards it is
    # True either way and the whole question is *when*.
    class _Watch:
        def __set_name__(self, owner, name):
            pass

    real_cmd = rec.cmd

    def cmd_and_note(text):
        if d._readable:
            log.append("gate-already-open")
        real_cmd(text)

    rec.cmd = cmd_and_note
    d.start("capture", preset="1")
    return log, d


def test_the_gate_is_open_before_the_device_is_told_to_stream():
    """Nothing may command the device while the descriptor is unread.

    This is #57. The device begins producing the moment `cmd()` lands,
    so if the gate is still shut there, every frame until it opens has
    no reader at all - and on a host that does not absorb the backlog,
    one of them does not survive.
    """
    log, d = _start_a_capture()
    assert "gate-already-open" in log, (
        "start() commanded the device while BoardDevice.read() was still "
        "refusing to read: the stream has no reader for the rest of "
        "start(). That is issue #57, bisected to 0 of 10 against 6 of 10")


def test_the_drain_finishes_before_the_gate_opens():
    """And the other side of it: never two readers. That is #44.

    `drain_until_quiet` owns the descriptor exclusively; the reader
    thread may not be taking bytes off it at the same time. Together
    with the case above this pins the gate to a single instant.
    """
    log, d = _start_a_capture()
    # Check presence before ordering: without this the assertion below
    # raises ValueError instead of saying what went wrong, which is a
    # worse failure than the one it is written to report.
    assert "gate-already-open" in log, (
        f"the gate never opened before the device was commanded, so "
        f"there is no ordering to check - see the previous test. "
        f"Order was {log}")
    assert log.index("drain_until_quiet") < log.index("gate-already-open"), (
        f"the gate opened before drain_until_quiet finished, so two "
        f"readers share the descriptor - issue #44. Order was {log}")
    assert d._readable is True


def test_start_reads_nothing_from_the_port_after_the_gate_opens():
    """Once the reader thread has the descriptor, `start()` lets go.

    The fix opens the gate when `drain_until_quiet` returns, and that is
    only single-reader for as long as `start()` does no further native
    reads afterwards. Today it does none - the feeder writes, and
    `drain_console` is the programming port - but windows-desk named
    this as the thing that would break silently:

        the earlier sketch rested on "start() does no native reads after
        cmd()", which is true today and which a future settle-read would
        break silently.

    It is true of the landed fix too. So it is checked rather than
    relied on: a `time.sleep`-and-read added to `start()` for any good
    reason at all would put two readers back on one descriptor and no
    other test here would notice.
    """
    log, _d = _start_a_capture()
    assert "gate-already-open" in log, log
    opened = log.index("gate-already-open")
    late = [i for i, ev in enumerate(log) if ev == "fd-read" and i > opened]
    assert not late, (
        f"start() read the native port after handing it to the reader "
        f"thread, so two readers share it - issue #44 returning by a "
        f"different door. Order was {log}")
