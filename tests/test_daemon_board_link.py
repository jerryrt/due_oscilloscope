"""One control link per board: the daemon must use the board's, not open its own.

Board-free. #79, measured on windows-desk: `measure.Board.ctl()` opens a
`Control` on the command node and keeps it, and `BoardDevice.control()`
opened a second one. POSIX lets two handles hold a tty; Windows grants a
COM port to one, so the daemon's open failed with `Access is denied`, was
cached as "no control channel" for the device's lifetime, and every
`counters()` was refused. On the board: 0 of 3 answered with the board's
link held, 3 of 3 with it released.

The fakes below stand in for the board and its link so the ownership
rules can be pinned without hardware and on a platform where the defect
cannot fire. The acceptance test for the defect itself is the board suite
on Windows.
"""
import threading
import time

import pytest

from daemon import device as devmod


class Link:
    """A command link: answers counters, can be told to fail."""

    def __init__(self):
        self.on_unsolicited = None
        self.closed = 0
        self.fail = None

    def counters(self):
        if self.fail is not None:
            raise self.fail
        return {"underruns": 0, "spans": 0, "partial": 0, "consumed": 7,
                "occ_min": 21, "dev_us": 0}

    def heartbeat(self, period_ms):
        return {"period_ms": period_ms or 0}

    def recv(self, timeout=None):
        time.sleep(timeout or 0.05)
        return None

    def close(self):
        self.closed += 1


class Board:
    """The parts of `measure.Board` the device's control path touches."""

    def __init__(self, link=None, why=None):
        self.link = link
        self.ctl_why = why
        self.ctl_calls = 0
        self.invalidated = 0

    def command_node(self):
        return "COM10"

    def ctl(self):
        self.ctl_calls += 1
        return self.link

    def ctl_invalidate(self):
        self.invalidated += 1
        link, self.link = self.link, None
        if link is not None:
            link.close()

    def poll_console(self):
        return b""

    def cmd(self, text):
        pass


class M:
    FRAME_BYTES = 4096
    FRAME_SAMPLES = 2032

    @staticmethod
    def identity(board):
        return {"track": "b", "ctl_version": 4}


def _device(board):
    return devmod.BoardDevice(board, measure_mod=M())


@pytest.fixture
def no_second_open(monkeypatch):
    """Any attempt to open a Control of the device's own fails the test."""
    def refuse(*a, **kw):
        raise AssertionError("BoardDevice opened a second Control on a "
                             "board that already has a link (#79)")
    monkeypatch.setattr(devmod.control_mod, "Control", refuse)


def test_the_device_uses_the_boards_link_and_opens_no_handle_of_its_own(
        no_second_open):
    link = Link()
    board = Board(link)
    dev = _device(board)
    assert dev.counters()["consumed"] == 7
    assert board.ctl_calls >= 1
    assert link.closed == 0


def test_a_refused_link_says_why_rather_than_that_there_is_no_channel(
        no_second_open):
    """A refusal that says only that there is no channel, while the note
    beside it holds `Access is denied`, is false and points away from the
    cause - so the reason has to reach the caller."""
    why = ("SerialException: could not open port 'COM10': "
           "PermissionError(13, 'Access is denied.', None, 5)")
    dev = _device(Board(None, why=why))
    with pytest.raises(devmod.DeviceError) as e:
        dev.counters()
    assert "Access is denied" in str(e.value), str(e.value)


def test_a_link_that_comes_up_later_is_used_rather_than_cached_as_absent(
        no_second_open):
    """One refusal must not last the device's lifetime - that is what
    turned one transient open into a whole session of refused counters."""
    board = Board(None, why="not yet")
    dev = _device(board)
    with pytest.raises(devmod.DeviceError):
        dev.counters()
    board.link = Link()
    assert dev.counters()["consumed"] == 7


def test_a_broken_link_is_invalidated_on_the_board_not_closed_behind_it(
        no_second_open):
    """A transport failure must reach the board's cache. Closing the link
    from here would leave the board handing back a dead object."""
    link = Link()
    link.fail = OSError("the port went away")
    board = Board(link)
    dev = _device(board)
    with pytest.raises(OSError):
        dev.counters()
    assert board.invalidated == 1, "the board still caches a broken link"
    assert link.closed == 1, "closed twice, or not at all"


def test_closing_the_device_leaves_the_boards_link_open_and_unhooked(
        no_second_open):
    """The board owns the link and keeps using it after the daemon stops;
    the heartbeat hook must not outlive the device on it."""
    link = Link()
    board = Board(link)
    dev = _device(board)
    dev.heartbeat(0)
    assert link.on_unsolicited is not None
    dev.close()
    assert link.closed == 0, "the daemon closed the board's own link"
    assert board.invalidated == 0
    assert link.on_unsolicited is None, "the heartbeat hook outlived the device"


def test_a_link_the_board_replaces_is_followed_and_the_hook_moves_with_it(
        no_second_open):
    """`Board.close_native()`'s wedge ladder ends in `ctl_invalidate()`,
    which closes the link and re-opens a new one on the next `ctl()`. A
    device that kept its cached object handed the pump a closed link for
    ever - the pump swallows the error and asks again."""
    old = Link()
    board = Board(old)
    dev = _device(board)
    try:
        dev.heartbeat(50)
        assert old.on_unsolicited is not None
        board.ctl_invalidate()               # what a software detach does
        new = Link()
        new.consumed_marker = True
        board.link = new
        assert dev.counters()["consumed"] == 7
        assert dev.control() is new, "the device kept the closed link"
        assert new.on_unsolicited is not None, \
            "beats would stop silently after the link was replaced"
        assert old.on_unsolicited is None
    finally:
        dev.close()


def test_the_native_port_closes_under_the_control_lock(no_second_open):
    """The close can invalidate the shared link. The pump takes
    `_ctl_lock` for each recv(), so the lock must be held across the close
    or a read can be in progress on the link being closed."""
    held = []

    class ClosingBoard(Board):
        def close_native(self, fd):
            got = []

            def probe():
                ok = dev._ctl_lock.acquire(blocking=False)
                if ok:
                    dev._ctl_lock.release()
                got.append(ok)

            t = threading.Thread(target=probe)
            t.start()
            t.join()
            held.append(not got[0])

    board = ClosingBoard(Link())
    dev = _device(board)
    dev.fd = object()
    dev.running = True
    dev.stop()
    assert held == [True], "close_native ran without the control lock held"


def test_a_board_without_a_link_of_its_own_still_gets_one_opened(monkeypatch):
    """The old path survives for a board-like object that offers no
    `ctl()`: the device opens and owns the link, and closes it on close."""
    opened = []

    def fake_control(node, timeout=None):
        link = Link()
        opened.append((node, link))
        return link

    monkeypatch.setattr(devmod.control_mod, "Control", fake_control)

    class BareBoard(Board):
        ctl = None

    board = BareBoard()
    dev = _device(board)
    assert dev.counters()["consumed"] == 7
    assert [n for n, _ in opened] == ["COM10"]
    dev.close()
    assert opened[0][1].closed == 1, "an owned link was left open on close"
