"""Two Dues on one host. No board required.

A bench that holds two boards has to name which one a run is on, because
nothing in the USB tree pairs a programming port with its native cable.
These hold the rules: ambiguity is refused rather than mixed, a declared
DUT resolves by stable identifiers and not by node name, and a board's
own baseline figures overlay the shared ones without leaking.
"""

import pytest

PLATFORM_SEAM_EXEMPT = "ports discovery is monkeypatched with fake nodes; no test here reaches an OS branch"

import helpers
import ports

pytestmark = pytest.mark.smoke

CTL, NAT = (0x2341, 0x003D), (0x2341, 0x003E)


def _two_boards(monkeypatch):
    nodes = [("/dev/a0", *CTL, 0, "SER-ONE"), ("/dev/a5", *CTL, 0, "SER-TWO"),
             ("/dev/a1", *NAT, 0, "B-01"), ("/dev/a2", *NAT, 2, "B-01"),
             ("/dev/a3", *NAT, 0, "B-01"), ("/dev/a4", *NAT, 2, "B-01")]
    locs = {"/dev/a1": "1-3.3:1.0", "/dev/a2": "1-3.3:1.2",
            "/dev/a3": "1-3.1.1:1.0", "/dev/a4": "1-3.1.1:1.2"}
    monkeypatch.setattr(ports, "_pyserial_nodes", lambda: nodes)
    monkeypatch.setattr(ports, "_locations", lambda: locs)
    monkeypatch.setattr(ports, "dut_registry", lambda: {
        "one": {"control_serial": "SER-ONE", "native_location": "1-3.3"},
        "two": {"control_serial": "SER-TWO", "native_location": "1-3.1.1"}})
    for k in ("DUE_CONTROL_PORT", "DUE_NATIVE_PORT", "DUE_COMMAND_PORT", "DUE_DUT"):
        monkeypatch.delenv(k, raising=False)


def test_two_boards_unnamed_is_refused_not_mixed(monkeypatch):
    _two_boards(monkeypatch)
    with pytest.raises(ports.AmbiguousBoards, match="DUE_DUT"):
        ports.find_all_ports(wait=0)


def test_a_declared_dut_resolves_its_own_pair(monkeypatch):
    _two_boards(monkeypatch)
    assert ports.resolve_dut("one") == ("/dev/a0", "/dev/a1", "/dev/a2")
    assert ports.resolve_dut("two") == ("/dev/a5", "/dev/a3", "/dev/a4")
    monkeypatch.setenv("DUE_DUT", "two")
    assert ports.find_all_ports(wait=0) == ("/dev/a5", "/dev/a3", "/dev/a4")


def test_an_undeclared_name_is_an_error(monkeypatch):
    _two_boards(monkeypatch)
    with pytest.raises(ports.AmbiguousBoards, match="three"):
        ports.resolve_dut("three")


def test_a_board_overlay_replaces_keys_and_never_leaks():
    base = {"noise": {"rms": 1.0, "line": 0.05}, "boards": {"u2": {"noise": {"rms": 1.2}}}}
    assert helpers.overlay_board(base, "u2") == {"noise": {"rms": 1.2, "line": 0.05}}
    assert helpers.overlay_board(base, "u1") == {"noise": {"rms": 1.0, "line": 0.05}}
    assert helpers.overlay_board(base, None) == {"noise": {"rms": 1.0, "line": 0.05}}
    assert base["noise"]["rms"] == 1.0


def test_an_overlay_on_a_missing_section_is_an_error():
    with pytest.raises(KeyError):
        helpers.overlay_board({"noise": {}, "boards": {"u": {"nope": {"x": 1}}}}, "u")


def test_native_nodes_follow_the_pin_when_its_own_pair_detaches(monkeypatch):
    """The bounce path re-lists the native nodes while this board's own
    pair is gone. It must come back empty, not with the other board's."""
    _two_boards(monkeypatch)
    monkeypatch.setenv("DUE_DUT", "two")
    assert ports.native_nodes() == ["/dev/a3", "/dev/a4"]
    gone = [n for n in ports._pyserial_nodes() if n[0] not in ("/dev/a3", "/dev/a4")]
    monkeypatch.setattr(ports, "_pyserial_nodes", lambda: gone)
    assert ports.native_nodes() == []


def test_a_named_dut_carries_its_own_wiring(monkeypatch):
    import provenance
    monkeypatch.setattr(provenance, "bench", lambda: {
        "wiring": "shared", "wiring_since": "2026-01-01",
        "duts": {"two": {"wiring": "crossed", "wiring_since": "2026-11-09"}}})
    monkeypatch.delenv("DUE_DUT", raising=False)
    assert provenance.wiring() == ("shared", "2026-01-01", "declared")
    monkeypatch.setenv("DUE_DUT", "two")
    assert provenance.wiring() == ("crossed", "2026-11-09", "declared")
