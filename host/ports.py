#!/usr/bin/env python3
"""
Locate the Due's two USB ports by probing, not by hardcoded path.

Device node names are derived from USB location, so they change whenever
a cable moves to a different socket or hub. Hardcoding one has already
caused two debugging detours in this project, and a wrong port looks
exactly like dead firmware.

The programming port is identified by the only reliable means available:
it answers. Sending 'h' provokes the firmware banner, and only the port
carrying the command UART will produce it. The native port is then
whichever other usbmodem node is present.
"""

import glob
import os
import select
import struct
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


def find_ports(wait=8.0):
    """Return (control_port, native_port). Either may be None."""
    end = time.time() + wait
    while True:
        nodes = sorted(glob.glob("/dev/cu.usbmodem*"))
        ctl = next((n for n in nodes if _responds(n)), None)
        if ctl:
            native = next((n for n in nodes if n != ctl), None)
            return ctl, native
        if time.time() >= end:
            return None, (nodes[0] if nodes else None)
        time.sleep(0.5)


if __name__ == "__main__":
    c, n = find_ports()
    print(f"control = {c}")
    print(f"native  = {n}")
    sys.exit(0 if c else 1)
