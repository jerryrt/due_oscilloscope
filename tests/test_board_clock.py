"""A host refuses a board whose clock is not the one it assumes.

Every RC divides MCK/2, so a host on 90 MHz that talks to a 78 MHz image
computes the wrong RC from every rate it names, and the board accepts it.
The identity line carries the board's clock; Board.require_clock reads it
once per board and says what to set.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT / "host"))
import measure  # noqa: E402


def _identity(mck):
    return ("# id: track=B fw=0.2.0 ctlver=4 framever=3 mck=%d adcclk=%d "
            "framebytes=4096 framesamples=2032 build=abc1234\n" % (mck, mck // 4))


class _Stub(measure.Board):
    """A Board with no ports: it answers `v` with what it is told."""

    def __init__(self, reply):
        self.reply, self.asked, self._clock_ok = reply, 0, False

    def poll_console(self):
        pass

    def cmd(self, text):
        assert text == "v"
        self.asked += 1

    def read_console(self, window):
        return self.reply


def test_a_board_on_another_clock_is_refused_with_what_to_set():
    other = 78_000_000 if measure.MCK_HZ != 78_000_000 else 90_000_000
    with pytest.raises(measure.BoardError) as e:
        _Stub(_identity(other)).require_clock()
    msg = str(e.value)
    assert "reflash" in msg and "90 MHz" in msg


def test_a_board_on_the_hosts_clock_passes_and_is_asked_once():
    b = _Stub(_identity(measure.MCK_HZ))
    b.require_clock()
    b.require_clock()
    assert b.asked == 1


def test_an_image_with_no_identity_line_is_let_through_rather_than_refused():
    _Stub("# no identity here\n").require_clock()
