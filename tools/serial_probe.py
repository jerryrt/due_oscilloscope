#!/usr/bin/env python3
"""
Minimal serial probe for bring-up. Stdlib only: no pyserial dependency,
which matters because this host has no package manager installed.

Opens the port raw at the requested baud, optionally sends a command
byte, and captures output for a bounded time.

Never opens the programming port at 1200 baud: that triggers the Due's
erase-and-reset path.

usage: serial_probe.py PORT [--baud N] [--send CHARS] [--seconds N]
"""

import argparse
import os
import select
import sys
import termios
import time


def open_port(dev, baud):
    if baud == 1200:
        sys.exit("refusing 1200 baud: that triggers erase+reset on the Due")
    fd = os.open(dev, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    speed = getattr(termios, "B%d" % baud)
    a[0] = 0                                              # iflag: raw
    a[1] = 0                                              # oflag: raw
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL   # cflag: 8N1
    a[3] = 0                                              # lflag: raw
    a[4] = speed                                          # ispeed
    a[5] = speed                                          # ospeed
    a[6][termios.VMIN] = 0
    a[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd


def main():
    p = argparse.ArgumentParser()
    p.add_argument("port")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--send", default="")
    p.add_argument("--seconds", type=float, default=3.0)
    p.add_argument("--settle", type=float, default=0.3)
    args = p.parse_args()

    fd = open_port(args.port, args.baud)
    try:
        time.sleep(args.settle)
        if args.send:
            os.write(fd, args.send.encode())

        out = bytearray()
        deadline = time.time() + args.seconds
        while time.time() < deadline:
            r, _, _ = select.select([fd], [], [], 0.1)
            if r:
                chunk = os.read(fd, 4096)
                if chunk:
                    out += chunk
        sys.stdout.write(out.decode("utf-8", "replace"))
        sys.stdout.flush()
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
