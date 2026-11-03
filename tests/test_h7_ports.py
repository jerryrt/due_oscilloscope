"""`ports.find_h7` over the location strings each host's enumeration really produces (T7). pyserial reports the USB interface in the
location on Linux ("1-4:1.0") and on Windows ("1-5:x.0", with a literal x); macOS gives only a hub path and the interface comes from
ioreg. The enumeration is faked here, so this runs anywhere; what it cannot show is that the fake matches the real host (read off
pyserial's source for the first two, and the third is the Due's existing ioreg path)."""
import pytest

import ports

PLATFORM_SEAM_EXEMPT = "the enumeration is replaced by fakes in each host's format; no test here reaches a real OS branch"


class Entry:
    def __init__(self, device, location, vid=ports.H7_VID, pid=ports.H7_PID):
        self.device, self.location, self.vid, self.pid, self.serial_number = device, location, vid, pid, "x"


def fake(monkeypatch, entries, ioreg=None):
    import serial.tools.list_ports as lp
    monkeypatch.setattr(lp, "comports", lambda *a, **k: entries)
    monkeypatch.setattr(ports, "DARWIN", ioreg is not None)
    if ioreg is not None:
        import subprocess
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("R", (), {"stdout": ioreg})())


@pytest.mark.parametrize("location_fmt", ["1-4:1.{}", "1-5:x.{}"], ids=["linux", "windows"])
def test_find_h7_reads_the_interface_from_the_location_on_linux_and_windows(monkeypatch, location_fmt):
    fake(monkeypatch, [Entry("PORT2", location_fmt.format(2)), Entry("PORT0", location_fmt.format(0))])      # in the wrong order on purpose
    assert ports.find_h7() == ("PORT0", "PORT2")


def test_find_h7_on_macos_takes_the_interface_from_ioreg_not_the_hub_port(monkeypatch):
    ioreg = "\n".join(l for dev, n in (("/dev/cu.usbmodemH1", 0), ("/dev/cu.usbmodemH3", 2)) for l in (
        "+-o AppleUSBHostInterface  <class IOUSBHostInterface, id 0x1>", f'"bInterfaceNumber" = {n}', '"USB Serial Number" = "x"',
        f'"IOCalloutDevice" = "{dev}"'))
    # pyserial's macOS location ends in the hub port ("20-1.2"): read as an interface it would call both nodes 2
    fake(monkeypatch, [Entry("/dev/cu.usbmodemH1", "20-1.2"), Entry("/dev/cu.usbmodemH3", "20-1.2")], ioreg=ioreg)
    assert ports.find_h7() == ("/dev/cu.usbmodemH1", "/dev/cu.usbmodemH3")


def test_find_h7_ignores_other_devices_and_answers_none_when_a_function_is_missing(monkeypatch):
    fake(monkeypatch, [Entry("DUE", "1-2:1.0", vid=0x2341, pid=0x003E), Entry("H7_0", "1-4:1.0")])
    assert ports.find_h7() is None                                           # only the stream function has enumerated
