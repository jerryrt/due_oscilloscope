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


# ------------------------------------------------ the image against its source

def test_an_image_older_than_its_sources_is_refused(tmp_path, monkeypatch):
    """Issue #35: a stale image logged under the current commit.

    `enforce_clean_build` runs `--target clean` as a dependency of the
    link. On windows-desk's Ninja the clean deleted the objects the same
    plan was about to link, the build failed, and `flash.py` then
    flashed the *previous* image and `_log_flash` wrote the current
    commit beside its sha. Anyone reading `records/flash-log.jsonl`
    afterwards would conclude the board ran a commit it had never run.

    That is the one thing the flash log must not do, because
    `host/provenance.py` and every baseline are built on believing it.
    So the last thing that touches the image checks it.
    """
    binary = tmp_path / "baremetal_bringup.bin"
    binary.write_bytes(b"\x00" * 16)
    src = tmp_path / "src" / "clock.c"
    src.parent.mkdir()
    src.write_text("int x;\n")
    os.utime(binary, (1000, 1000))
    os.utime(src, (2000, 2000))

    monkeypatch.setattr(flash, "newest_source",
                        lambda b: (str(src), 2000.0))
    with pytest.raises(SystemExit) as e:
        flash.check_not_stale(str(binary), allow=False)
    assert "older than the firmware source" in str(e.value)


def test_a_current_image_is_not_refused(tmp_path, monkeypatch):
    binary = tmp_path / "baremetal_bringup.bin"
    binary.write_bytes(b"\x00" * 16)
    os.utime(binary, (3000, 3000))
    monkeypatch.setattr(flash, "newest_source", lambda b: ("whatever", 2000.0))
    flash.check_not_stale(str(binary), allow=False)     # must not raise


def test_stale_ok_flashes_but_says_so(tmp_path, monkeypatch, capsys):
    """The override exists because a checkout can move an mtime back.

    A false alarm is the safe direction, so it must be escapable - but
    never silently, because the log entry it produces is the thing at
    stake.
    """
    binary = tmp_path / "baremetal_bringup.bin"
    binary.write_bytes(b"\x00" * 16)
    os.utime(binary, (1000, 1000))
    monkeypatch.setattr(flash, "newest_source", lambda b: ("src.c", 2000.0))
    flash.check_not_stale(str(binary), allow=True)      # must not raise
    assert "stale image on request" in capsys.readouterr().out


def test_the_source_list_is_the_provenance_one(tmp_path):
    """One definition of what a firmware image is built from.

    If this script and `host/provenance.py` kept separate lists they
    would drift, and the drift would be invisible: the flash would pass
    a check the provenance report would have failed, or the reverse.
    `bsp/` was missing from the provenance list until 2026-08-30 and
    nothing noticed for months.
    """
    sys.path.insert(0, os.path.join(flash.REPO, "host"))
    import provenance

    # A Track B binary is checked against Track B's sources, and the
    # track comes from the binary's own path.
    b = os.path.join(flash.REPO, "build", "baremetal_bringup.bin")
    assert provenance.track_of_binary(b) == "B"
    newest, at = flash.newest_source(b)
    assert newest is not None and at > 0
    rel = os.path.relpath(newest, flash.REPO)
    assert rel.split(os.sep)[0] in provenance.FW_SOURCE_TRACKS["B"], (
        f"flash.py looked at {rel}, which is not in the provenance "
        f"list for Track B")
