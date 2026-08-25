"""
Port discovery. No board required.

The native port now offers two CDC functions on one cable - samples and
commands - so "the native port" is two device nodes and picking one by
position is a coin flip that happens to land right on this machine.
These check the rule that replaces position, and in particular that its
fallback is sane, because the fallback is what runs anywhere IOKit is
not available and nothing else in the suite would exercise it.
"""

import ports
import pytest

pytestmark = pytest.mark.smoke


def test_native_order_prefers_the_lower_interface(monkeypatch):
    """Interface number decides, not the node name.

    Named so the name ordering and the interface ordering disagree: if
    this ever starts sorting by name it fails here rather than in an
    hour of streaming against the wrong endpoint.
    """
    monkeypatch.setattr(ports, "usb_interfaces", lambda: {
        "/dev/cu.zzz": ("B-01", 1),
        "/dev/cu.aaa": ("B-01", 3),
    })
    assert ports.native_order(["/dev/cu.aaa", "/dev/cu.zzz"]) == [
        "/dev/cu.zzz", "/dev/cu.aaa"]


def test_native_order_falls_back_to_name(monkeypatch):
    """With no IOKit answer the order is by name, and nothing raises.

    That is the path on any host without ioreg. It agrees with the
    interface order on macOS today only because macOS derives the node
    name from the interface - a property of one OS's naming, which is
    why it is the fallback rather than the method.
    """
    monkeypatch.setattr(ports, "usb_interfaces", lambda: {})
    assert ports.native_order(["/dev/cu.usbmodemB_013",
                              "/dev/cu.usbmodemB_011"]) == [
        "/dev/cu.usbmodemB_011", "/dev/cu.usbmodemB_013"]


def test_native_order_keeps_two_boards_apart(monkeypatch):
    """Two boards do not interleave by interface number.

    Sorting on interface alone would put board A's samples, board B's
    samples, board A's commands, board B's commands - and the first two
    entries would then name two different boards.
    """
    monkeypatch.setattr(ports, "usb_interfaces", lambda: {
        "/dev/cu.one_s": ("B-01", 1),
        "/dev/cu.one_c": ("B-01", 3),
        "/dev/cu.two_s": ("B-02", 1),
        "/dev/cu.two_c": ("B-02", 3),
    })
    got = ports.native_order(["/dev/cu.two_c", "/dev/cu.one_c",
                              "/dev/cu.two_s", "/dev/cu.one_s"])
    assert got == ["/dev/cu.one_s", "/dev/cu.one_c",
                   "/dev/cu.two_s", "/dev/cu.two_c"]


def test_usb_interfaces_survives_an_unreadable_enumeration(monkeypatch):
    """An unreadable enumeration is no information, not an error.

    Every caller falls back, so this must return empty rather than
    propagate: discovery failing outright would make the whole suite
    unrunnable on that host for no gain.

    The contract is the same everywhere; only the source differs. macOS
    asks ioreg, Windows and Linux ask pyserial, so break whichever one
    this platform actually uses.
    """
    def boom(*a, **kw):
        raise OSError("no enumeration here")

    if ports.DARWIN:
        monkeypatch.setattr(ports.subprocess, "run", boom)
    else:
        monkeypatch.setattr(ports, "_pyserial_nodes", boom)
    assert ports.usb_interfaces() == {}
