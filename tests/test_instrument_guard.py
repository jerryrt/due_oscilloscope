"""Counters come off the control channel or they do not come. Issue #51 q3.

`play_counters()` and `occupancy()` used to substitute `B` and `O` on
the console when the control link was unavailable, and say so only in
`.via`. The substitution is gone: they raise instead.

The argument is the one `SerialDevice.load()` has always made one method
over - a counter read that blocks the main loop for 13-20 ms while the
sample path runs is measuring its own instrument as well as the device,
so it is a different experiment rather than a slower one. Handing it
back through the same return value is what let a session hold two
populations with nothing marking the boundary.

**Two things are tested here and they are not the same thing.** That the
functions refuse, which is the change; and that the session hook still
does what its four branches say, which is the part that needs a test
precisely *because* nothing produces its input any more. A guard that
cannot fail is worse than no guard, and after this change the hook can
only fail if someone reintroduces the fallback - so its branches are
driven directly rather than left to be exercised by a world that no
longer exercises them.
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "host"))

import measure                                        # noqa: E402
import conftest as ct                                 # noqa: E402

pytestmark = pytest.mark.smoke


class _NoLink:
    """A board whose command port never answered."""

    ctl_why = "OSError: native port shows 1 node(s), need 2"

    def __init__(self):
        self.console = []

    def ctl(self):
        return None

    def cmd(self, text):                    # pragma: no cover - must not run
        self.console.append(text)

    def drain_console(self, secs):          # pragma: no cover - must not run
        raise AssertionError("the console was read for a counter")


class _DroppingLink:
    """A board whose link opens and then fails as a transport."""

    ctl_why = "OSError: [Errno 5] Input/output error"

    def __init__(self, exc):
        self.exc = exc
        self.invalidated = False
        self.console = []

    def ctl(self):
        return self

    def counters(self):
        raise self.exc

    def occupancy(self):
        raise self.exc

    def ctl_invalidate(self):
        self.invalidated = True

    def cmd(self, text):                    # pragma: no cover - must not run
        self.console.append(text)

    def drain_console(self, secs):          # pragma: no cover - must not run
        raise AssertionError("the console was read for a counter")


@pytest.mark.parametrize("fn", [measure.play_counters, measure.occupancy])
def test_no_control_link_is_a_refusal_not_a_console_read(fn):
    """No link means no number. It must not reach for `B` or `O`.

    `_NoLink.drain_console` raises, so a reintroduced fallback fails
    here as a console read rather than passing quietly with `via`
    set - the assertion is on the behaviour, not on a label.
    """
    board = _NoLink()
    with pytest.raises(measure.BoardError) as e:
        fn(board)
    msg = str(e.value)
    assert "invariant 8" in msg, msg
    assert "ctl_why" in msg, msg
    assert board.console == [], (
        f"a console command was sent while refusing: {board.console}")


@pytest.mark.parametrize("fn", [measure.play_counters, measure.occupancy])
@pytest.mark.parametrize("exc", [OSError("gone"), ValueError("short read")])
def test_a_dropped_link_invalidates_and_raises(fn, exc):
    """A transport failure re-arms the link for the next caller and
    propagates. It does not produce a number by another route."""
    board = _DroppingLink(exc)
    with pytest.raises(type(exc)):
        fn(board)
    assert board.invalidated, "the link was not invalidated for the next caller"
    assert board.console == []


@pytest.mark.parametrize("fn", [measure.play_counters, measure.occupancy])
def test_a_mapping_bug_escapes_rather_than_degrading(fn):
    """A KeyError is a bug in `measure.py`, not a transport failure.

    It must not be caught: swallowing it would invalidate a healthy link
    and report a working instrument as broken. This is what the narrow
    `_LINK_GONE` tuple is for, and it is the distinction the daemon's
    copy of this code did *not* draw until #51 q3.
    """
    board = _DroppingLink(KeyError("underruns"))
    with pytest.raises(KeyError):
        fn(board)
    assert not board.invalidated, (
        "a mapping bug invalidated the link, which blames the transport "
        "for a host-side defect")


# -- the session hook, driven directly -----------------------------------

class _Reporter:
    def __init__(self):
        self.lines = []

    def write_line(self, text, **kw):
        self.lines.append(text)


class _PM:
    def __init__(self, reporter):
        self.reporter = reporter

    def get_plugin(self, name):
        return self.reporter


class _Option:
    mixed_instruments_ok = False


class _Config:
    def __init__(self, reporter):
        self.option = _Option()
        self.pluginmanager = _PM(reporter)


class _Session:
    def __init__(self, reporter):
        self.config = _Config(reporter)
        self.exitstatus = 0


def _run_hook(control, console, ok=False):
    saved = dict(measure.INSTRUMENT_READS)
    measure.INSTRUMENT_READS.clear()
    measure.INSTRUMENT_READS.update({"control": control, "console": console})
    reporter = _Reporter()
    session = _Session(reporter)
    session.config.option.mixed_instruments_ok = ok
    try:
        ct._check_one_instrument(session)
    finally:
        measure.INSTRUMENT_READS.clear()
        measure.INSTRUMENT_READS.update(saved)
    return session.exitstatus, reporter.lines


def test_a_board_free_session_is_silent():
    status, lines = _run_hook(0, 0)
    assert status == 0 and lines == []


def test_a_healthy_session_is_silent():
    status, lines = _run_hook(9, 0)
    assert status == 0 and lines == []


def test_console_only_reports_and_passes():
    """The pre-2026-08-27 image. The console is the only instrument
    there, so it is not a downgrade."""
    status, lines = _run_hook(0, 4)
    assert status == 0
    assert lines and "not a downgrade" in lines[0]


def test_both_instruments_fails_the_run():
    """The state this hook exists for: the link demonstrably existed and
    a console read happened anyway, so it dropped."""
    status, lines = _run_hook(9, 4)
    assert status == 1
    assert lines and "BOTH ways" in lines[0]
    assert "invariant 8" in lines[0]


def test_the_escape_hatch_still_escapes():
    status, lines = _run_hook(9, 4, ok=True)
    assert status == 0 and lines == []


# -- the daemon draws the same distinction ------------------------------

def test_only_a_wire_failure_drops_the_daemons_control_link():
    """`counters`, `trace` and `load` all raise; only some also drop.

    They used to catch bare `Exception` and drop the link on all of it,
    which blames the transport for a host-side defect and hides a
    mapping bug behind an intermittent-looking reconnect. `measure.py`
    already drew this line; the daemon did not.

    `ControlError` is the case that matters most: the device answered
    and refused - `CTL_ERR_OPCODE` for an opcode a track does not
    implement - so the link is demonstrably healthy.
    """
    import control as control_mod
    from daemon import device as devmod

    drops = [OSError("gone"), ValueError("short"),
             control_mod.ProtocolError("no answer")]
    keeps = [control_mod.ControlError(2, "no such opcode"),
             KeyError("underruns"), TypeError("bad mapping")]

    for exc in drops:
        assert devmod._is_transport_failure(exc), (
            f"{type(exc).__name__} is a wire failure and must re-arm the link")
    for exc in keeps:
        assert not devmod._is_transport_failure(exc), (
            f"{type(exc).__name__} is not a wire failure: dropping the link "
            f"for it blames the transport for a host-side defect")
