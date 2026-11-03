"""Device detection and the skips that follow from it (tests/devices.py, ports.h7_state / census). Everything here is board-free: the decisions are
plain functions fed faked states, and the sysfs scan is fed a faked directory."""
import os

import pytest

import devices
import ports

PLATFORM_SEAM_EXEMPT = "the sysfs scan is pointed at a fake directory and find_h7 is replaced; no test here reaches a real OS branch"


@pytest.mark.parametrize("state,require,action", [
    ("running", False, "ok"), ("running", True, "ok"),
    ("boot_loader", False, "skip"), ("boot_loader", True, "fail"),
    ("absent", False, "skip"), ("absent", True, "fail"),
])
def test_an_h7_test_runs_only_on_a_running_unit_and_otherwise_skips_or_fails(state, require, action):
    got, reason = devices.h7_decision(state, require)
    assert got == action
    assert (reason == "") == (action == "ok")


def test_the_skip_names_the_state_and_the_remedy():
    assert "boot loader" in devices.h7_decision("boot_loader", False)[1] and "h7_flash_wait.sh" in devices.h7_decision("boot_loader", False)[1]
    assert "no H7 is attached" in devices.h7_decision("absent", False)[1]
    assert "--require-h7" in devices.h7_decision("absent", True)[1]


def test_skips_are_counted_per_device_and_only_for_the_fixtures_own_phrases():
    reasons = ["Skipped: no board: nothing on the bench", "Skipped: board runs track a, wanted b, and --no-flash was given",
               "Skipped: " + devices.h7_decision("absent", False)[1], "needs numpy (.venv-gui); this skip is NOT a pass", "platform: windows only"]
    line, = devices.summary_lines(reasons)
    assert "Due: 2" in line and "H7: 1" in line and "NOT run" in line
    assert devices.summary_lines(["needs numpy", "platform: windows only"]) == []      # other skips are not claimed


def test_the_header_says_what_is_attached():
    none = {"due": {"programming": None, "native": []}, "h7": "absent", "h7_paths": None}
    both = {"due": {"programming": "/dev/a", "native": ["/dev/b", "/dev/c"]}, "h7": "running", "h7_paths": ("/dev/d", "/dev/e")}
    bl = {"due": {"programming": None, "native": []}, "h7": "boot_loader", "h7_paths": None}
    assert "Due absent" in devices.header_lines(none)[0] and "H7 absent" in devices.header_lines(none)[0]
    assert "/dev/b, /dev/c" in devices.header_lines(both)[0] and "/dev/d" in devices.header_lines(both)[0]
    assert "boot loader" in devices.header_lines(bl)[0]


def _fake_usb(tmp_path, devs):
    for i, (v, p) in enumerate(devs):
        d = tmp_path / f"1-{i}"; d.mkdir()
        (d / "idVendor").write_text(v + "\n", encoding="ascii"); (d / "idProduct").write_text(p + "\n", encoding="ascii")
    return str(tmp_path)


def test_h7_state_tells_running_from_boot_loader_from_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(ports, "find_h7", lambda: None)
    real_isdir, real_listdir, real_open = os.path.isdir, os.listdir, open
    root = _fake_usb(tmp_path, [("0483", "5720"), ("046d", "c52b")])
    redirect = lambda path: path.replace("/sys/bus/usb/devices", root)
    monkeypatch.setattr(os.path, "isdir", lambda p: real_isdir(redirect(p)))
    monkeypatch.setattr(os, "listdir", lambda p: real_listdir(redirect(p)))
    monkeypatch.setattr("builtins.open", lambda p, *a, **k: real_open(redirect(str(p)), *a, **k))
    assert ports.h7_state() == "boot_loader"
    monkeypatch.setattr(ports, "find_h7", lambda: ("/dev/s", "/dev/c"))
    assert ports.h7_state() == "running"                               # a running image wins over a stale boot-loader entry
    monkeypatch.setattr(ports, "find_h7", lambda: None)
    for d in tmp_path.iterdir():
        (d / "idVendor").write_text("1111\n", encoding="ascii")
    assert ports.h7_state() == "absent"


def test_a_host_that_cannot_list_usb_says_unknown_and_never_claims_a_boot_loader(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: False)
    assert ports._usb_present(0x0483, 0x5720) is None
