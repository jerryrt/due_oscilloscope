"""The post-flash boot check. No board required.

bossac reports "Verify successful" for a write that lands perfectly and
still leaves the board in ROM SAM-BA - measured at roughly two attempts
in three on macOS on 2026-08-25, with no diagnostic anywhere. The board
then has no native port and answers nothing, which is indistinguishable
from firmware that hangs on boot. In one session it produced three false
conclusions, the worst of which was "this branch does not boot" about a
branch that boots fine; an interleaved control against `main` was what
disproved it, after `main` failed two attempts in three in the same
rotation.

So the check is not a convenience. An image A/B is the core experimental
method in the issue #5 investigation, and a flash that silently does not
run corrupts every one of them.
"""

import os
import pytest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import flash  # noqa: E402

SAMBA_NODE = "/dev/cu.usbmodem141301"


def _nodes(seq):
    """Stand in for samba_nodes(), returning one answer per call so a
    bootloader node can be made to disappear partway through a wait."""
    it = iter(seq)
    last = []

    def f():
        nonlocal last
        try:
            last = next(it)
        except StopIteration:
            pass
        return last
    return f


def test_a_bootloader_node_that_goes_away_is_a_boot(monkeypatch):
    monkeypatch.setattr(flash, "samba_nodes",
                        _nodes([[SAMBA_NODE], [SAMBA_NODE], []]))
    assert flash.wait_for_boot({SAMBA_NODE}, timeout=5.0)


def test_a_bootloader_node_that_stays_is_not_a_boot(monkeypatch):
    monkeypatch.setattr(flash, "samba_nodes", _nodes([[SAMBA_NODE]]))
    assert not flash.wait_for_boot({SAMBA_NODE}, timeout=1.5)


def test_the_board_coming_back_at_a_new_bootloader_path_is_not_a_boot(
        monkeypatch):
    """Re-enumeration need not reuse the device path, so identity of the
    node is not what is being tested - presence of any bootloader is.
    Testing `& watched` alone would call this a boot."""
    monkeypatch.setattr(flash, "samba_nodes",
                        _nodes([[SAMBA_NODE], ["/dev/cu.usbmodem141401"]]))
    assert not flash.wait_for_boot({SAMBA_NODE}, timeout=1.5)


def test_nothing_to_watch_is_not_reported_as_a_failure(monkeypatch):
    """Flashed through the programming port: no bootloader node was ever
    attributed to this board, so there is no negative evidence to be had
    and the check must not invent a failure from its own blindness."""
    monkeypatch.setattr(flash, "samba_nodes", _nodes([[SAMBA_NODE]]))
    assert flash.wait_for_boot(set(), timeout=1.5)


# ------------------------------------------------- a port someone else holds

class _FakeSerial:
    """serial.Serial, refusing to open the first `refuse` times."""
    refuse = 0
    opened = 0

    def __init__(self):
        self.port = None
        self.baudrate = None

    def open(self):
        import serial
        if _FakeSerial.opened < _FakeSerial.refuse:
            _FakeSerial.opened += 1
            raise serial.SerialException(
                "could not open port 'COM7': "
                "PermissionError(13, 'Access is denied.', None, 5)")
        _FakeSerial.opened += 1

    def close(self):
        pass


def test_a_held_port_is_waited_out_rather_than_failed(monkeypatch):
    """A killed test run leaves its Python holding the programming port
    and Windows reports the next open as "Access is denied", which reads
    like a permissions problem and is not one. The handle goes when the
    process does, a moment later than the kill."""
    import serial
    _FakeSerial.refuse, _FakeSerial.opened = 3, 0
    monkeypatch.setattr(serial, "Serial", _FakeSerial)
    s = flash.open_port("COM7", 1200, tries=6, delay=0.0)
    assert s is not None
    assert _FakeSerial.opened == 4          # three refusals then the open


def test_a_port_held_for_ever_says_what_to_do(monkeypatch):
    """Three flashes failed this way in one session and each looked like
    a different problem, so the message has to name the cause."""
    import serial
    _FakeSerial.refuse, _FakeSerial.opened = 99, 0
    monkeypatch.setattr(serial, "Serial", _FakeSerial)
    with pytest.raises(SystemExit) as e:
        flash.open_port("COM7", 1200, tries=3, delay=0.0)
    assert "still held" in str(e.value)
    assert "Stop-Process" in str(e.value)


def test_a_real_failure_is_not_retried(monkeypatch):
    """Only a held handle is worth waiting on. A port that does not exist
    must fail at once rather than after six seconds of hope."""
    import serial

    class _Missing(_FakeSerial):
        def open(self):
            raise serial.SerialException("could not open port 'COM99': "
                                         "FileNotFoundError(2, ...)")

    monkeypatch.setattr(serial, "Serial", _Missing)
    with pytest.raises(serial.SerialException):
        flash.open_port("COM99", 1200, tries=6, delay=0.0)
