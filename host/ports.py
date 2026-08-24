#!/usr/bin/env python3
"""
Locate the Due's two USB ports by probing, not by hardcoded path.

Device node names are derived from USB location, so they change whenever
a cable moves to a different socket or hub. Hardcoding one has already
caused two debugging detours in this project, and a wrong port looks
exactly like dead firmware.

The programming port is identified by the only reliable means available:
it answers. Sending 'h' provokes the firmware banner, and only the port
carrying the command UART will produce it.

The native port is no longer "whichever other node is present": it now
offers two CDC functions on one cable, samples and commands, so there
are two other nodes and picking either by position is a coin flip that
happens to land right. They are told apart by USB interface number,
which is a contract pinned in docs/control-protocol.md - interfaces 0
and 1 carry samples, 2 and 3 carry commands - and IOKit is asked for it
rather than the node name being pattern-matched.
"""

import glob
import os
import re
import select
import struct
import subprocess
import sys
import termios
import time

BANNER_MARK = b"due_oscilloscope"


def open_raw(dev, baud=None, dtr=False):
    fd = os.open(dev, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[0] = a[1] = a[3] = 0
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    if baud:
        a[4] = a[5] = getattr(termios, "B%d" % baud)
    a[6][termios.VMIN] = 0
    a[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    if dtr:
        try:
            import fcntl
            fcntl.ioctl(fd, termios.TIOCMBIS,
                        struct.pack("I", termios.TIOCM_DTR | termios.TIOCM_RTS))
        except OSError:
            pass
    return fd


def _responds(dev, timeout=1.5):
    try:
        fd = open_raw(dev, 115200)
    except OSError:
        return False
    try:
        os.write(fd, b"h")
        end = time.time() + timeout
        buf = b""
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.1)
            if r:
                try:
                    buf += os.read(fd, 4096)
                except OSError:
                    break
            if BANNER_MARK in buf:
                return True
        return False
    finally:
        os.close(fd)


def usb_interfaces():
    """Map each serial node to the USB interface behind it.

    Returns {device_path: (serial_number, interface_number)}. Empty on
    anything that is not macOS, or if ioreg is missing or changes its
    output - every caller treats that as "no information" and falls back
    rather than failing, because this is an aid to identification and
    not the identification itself.
    """
    try:
        out = subprocess.run(
            ["ioreg", "-c", "IOUSBHostInterface", "-r", "-l", "-w", "0",
             "-d", "4"],
            capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return {}

    found = {}
    serial = iface = None
    for line in out.splitlines():
        # A new interface subtree resets the record. Child nodes
        # (AppleUSBACMData, IOSerialBSDClient) must not, because the
        # callout device hangs off them and belongs to this interface.
        if "+-o " in line and "class IOUSBHostInterface" in line:
            serial = iface = None
            continue
        m = re.search(r'"bInterfaceNumber" = (\d+)', line)
        if m:
            iface = int(m.group(1))
            continue
        m = re.search(r'"USB Serial Number" = "([^"]*)"', line)
        if m:
            serial = m.group(1)
            continue
        m = re.search(r'"IOCalloutDevice" = "([^"]*)"', line)
        if m and iface is not None:
            found[m.group(1)] = (serial, iface)
    return found


def native_order(nodes):
    """Sort native nodes so the sample function comes first.

    By interface number where IOKit will say, and by name otherwise.
    The fallback is not arbitrary: the sample function holds the lower
    interface numbers by contract, and macOS derives the node name from
    the interface, so the two orderings agree today. It is a fallback
    rather than the method because that agreement is a property of one
    operating system's naming and not something this project controls.
    """
    ifaces = usb_interfaces()

    def key(n):
        serial, iface = ifaces.get(n, (None, 1 << 16))
        # Serial first so two attached boards keep their own pair
        # together rather than interleaving by interface number.
        return (serial or "", iface, n)

    return sorted(nodes, key=key)


def find_ports(wait=8.0):
    """Return (control_port, native_port).

    native_port is the *sample* node, which is what every existing
    caller means by it. Use find_all_ports() for the command node too.
    """
    ctl, native, _cmd = find_all_ports(wait)
    return ctl, native


def find_all_ports(wait=8.0):
    """Return (programming_port, native_samples, native_commands).

    Any of the three may be None. The third is None against firmware
    built before the control channel existed, which is a board with one
    native node rather than an error.
    """
    end = time.time() + wait
    while True:
        nodes = sorted(glob.glob("/dev/cu.usbmodem*"))
        ctl = next((n for n in nodes if _responds(n)), None)
        if ctl:
            rest = native_order([n for n in nodes if n != ctl])
            return (ctl,
                    rest[0] if rest else None,
                    rest[1] if len(rest) > 1 else None)
        if time.time() >= end:
            rest = native_order(nodes)
            return None, (rest[0] if rest else None), None
        time.sleep(0.5)


if __name__ == "__main__":
    c, n, cmd = find_all_ports()
    print(f"control = {c}")
    print(f"native  = {n}")
    print(f"command = {cmd}")
    sys.exit(0 if c else 1)
