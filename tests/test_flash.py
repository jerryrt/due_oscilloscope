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
