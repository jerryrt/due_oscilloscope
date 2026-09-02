#!/usr/bin/env python3
"""
Minimal serial probe for bring-up.

Opens the port raw at the requested baud, optionally sends a command
byte, and captures output for a bounded time.

The port itself comes from `host/transport.py`, which is the one seam
the rest of `host/` already goes through: raw termios on POSIX, pyserial
on Windows. So this file imports cleanly on every tier-1 platform,
matching what `CLAUDE.md` quotes as the way to talk to either board.

Never opens the programming port at 1200 baud: that triggers the Due's
erase-and-reset path.

usage: serial_probe.py PORT [--baud N] [--send CHARS] [--seconds N]
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "host"))

import transport                                              # noqa: E402


def open_port(dev, baud):
    if baud == 1200:
        sys.exit("refusing 1200 baud: that triggers erase+reset on the Due")
    return transport.open_raw(dev, baud)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("port", nargs="?", default="auto")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--send", default="")
    p.add_argument("--seconds", type=float, default=3.0)
    p.add_argument("--settle", type=float, default=0.3)
    args = p.parse_args()

    dev = args.port
    if dev == "auto":
        from ports import find_ports
        dev = find_ports()[0] or sys.exit("no control port found")
    port = open_port(dev, args.baud)
    try:
        time.sleep(args.settle)
        if args.send:
            port.write(args.send.encode())

        out = bytearray()
        deadline = time.time() + args.seconds
        while time.time() < deadline:
            if transport.wait_any([port], 0.1):
                chunk = port.read(4096)
                if chunk:
                    out += chunk
        sys.stdout.write(out.decode("utf-8", "replace"))
        sys.stdout.flush()
    finally:
        port.close()


if __name__ == "__main__":
    main()
