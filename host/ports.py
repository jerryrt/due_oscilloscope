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
import re
import subprocess
import sys
import time

import transport
from transport import WINDOWS, open_raw          # noqa: F401  (re-exported)

# macOS is the only platform that needs ioreg, and the only one where
# pyserial does not report a USB interface number. Tier 2: see CLAUDE.md.
DARWIN = sys.platform == "darwin"

BANNER_MARK = b"due_oscilloscope"

# The board's USB identity, which reads the same on every OS - unlike a
# device node name, which macOS derives from USB location and Windows
# assigns from an enumeration counter.
VID = 0x2341
PID_CONSOLE = 0x003D                  # programming port, via the 16U2
PID_NATIVE = 0x003E                   # native port, the SAM3X's own USB


def _responds(dev, timeout=1.5):
    try:
        port = open_raw(dev, 115200)
    except OSError:
        return False
    try:
        port.write(b"h")
        end = time.time() + timeout
        buf = b""
        while time.time() < end:
            if transport.wait_any([port], 0.1):
                try:
                    buf += port.read(4096)
                except OSError:
                    break
            if BANNER_MARK in buf:
                return True
        return False
    finally:
        port.close()


def usb_interfaces():
    """Map each serial node to the USB interface behind it.

    Returns {device_path: (serial_number, interface_number)}, or {} if
    the platform will not say - every caller treats that as "no
    information" and falls back rather than failing, because this is an
    aid to identification and not the identification itself.

    One function, because native_order() must not branch on platform:
    the ordering rule is a contract from docs/control-protocol.md
    (samples on interfaces 0/1, commands on 2/3) and it is the same
    everywhere. Only the way the number is obtained differs - pyserial
    on Windows and Linux, ioreg on macOS.
    """
    if not DARWIN:
        # The guard belongs here rather than inside _pyserial_nodes,
        # because this is the function that promises {} on failure.
        try:
            return {d: (ser or "", i)
                    for d, _v, _p, i, ser in _pyserial_nodes()
                    if i is not None}
        except Exception:                                    # noqa: BLE001
            return {}
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


def _pyserial_nodes():
    """(node, vid, pid, interface) for every serial device, or [].

    pyserial's `location` ends in the USB interface number on Windows
    ("1-5:x.0", "1-5:x.2"), which is the same contract IOKit is asked
    for on macOS: interfaces 0/1 carry samples, 2/3 carry commands.
    Note that pyserial's `hwid` does NOT carry the MI_00 that the Win32
    DeviceID has, so matching on that substring finds nothing here.
    """
    try:
        from serial.tools import list_ports
        out = []
        for p in list_ports.comports():
            iface = None
            m = re.search(r"[.:](\d+)$", (p.location or ""))
            if m:
                iface = int(m.group(1))
            out.append((p.device, p.vid, p.pid, iface, p.serial_number))
        return out
    except Exception:                                        # noqa: BLE001
        # Same contract as the ioreg path: an enumeration that will not
        # answer is no information, not an error. Callers fall back.
        return []


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


def native_nodes(exclude=None):
    """The native port's nodes, sample function first.

    One discovery path for every caller. measure.py used to glob
    /dev/cu.usbmodem* itself in two places, which is a second
    implementation of this and macOS-only besides. Ordering is by USB
    interface number - samples on 0/1, commands on 2/3 - which is a
    contract pinned in docs/control-protocol.md rather than a property
    of any one OS's device naming.

    Discovery here never opens a port. Opening the programming port
    asserts NRSTB and resets the board, so a running daemon cannot
    afford to probe.
    """
    if WINDOWS:
        nodes = [d for d, v, p, _i, _s in _pyserial_nodes()
                 if (v, p) == (VID, PID_NATIVE) and d != exclude]
    else:
        nodes = [n for n in glob.glob("/dev/cu.usbmodem*") if n != exclude]
    return native_order(nodes)


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
        if WINDOWS:
            # Identify by USB VID/PID rather than by probing. The
            # programming port is 2341:003D and the native pair
            # 2341:003E; that is stable across every OS, and it avoids
            # opening - and therefore resetting - the board just to find
            # out what it is.
            found = _pyserial_nodes()
            ctl = next((d for d, v, p, _i, _s in found
                        if (v, p) == (VID, PID_CONSOLE)), None)
            rest = native_order([d for d, v, p, _i, _s in found
                                 if (v, p) == (VID, PID_NATIVE)])
            if ctl or rest:
                return (ctl,
                        rest[0] if rest else None,
                        rest[1] if len(rest) > 1 else None)
            if time.time() >= end:
                return None, None, None
            time.sleep(0.5)
            continue

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
