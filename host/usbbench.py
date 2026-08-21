#!/usr/bin/env python3
"""
USB transport benchmark for either track.

Drives the device's flood / sink / duplex modes and measures each
direction from the host side, so the host's own throughput is visible
alongside what the device counted. A mismatch between the two is the
signal that the host, not the device, is the limit.

usage: usbbench.py [in|out|duplex] [--seconds N] [--block N]
"""

import argparse
import fcntl
import glob
import os
import select
import struct
import sys
import termios
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ports import find_ports


def op(dev, baud=None, dtr=False):
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
        fcntl.ioctl(fd, termios.TIOCMBIS,
                    struct.pack("I", termios.TIOCM_DTR | termios.TIOCM_RTS))
    return fd


def native_port(wait=10.0):
    end = time.time() + wait
    while True:
        c = [p for p in glob.glob("/dev/cu.usbmodem*") if "141301" not in p]
        if c:
            return sorted(c)[0]
        if time.time() >= end:
            sys.exit("no native port")
        time.sleep(0.25)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["in", "out", "duplex",
                                     "in-dma", "out-dma", "duplex-dma"])
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--block", type=int, default=16384)
    args = ap.parse_args()

    cmd = {"in": b"F", "out": b"R", "duplex": b"X",
           "in-dma": b"G", "out-dma": b"T", "duplex-dma": b"Y"}[args.mode]

    CTL, NATIVE = find_ports()
    if not CTL:
        sys.exit('no control port found')
    ctl = op(CTL, 115200)
    time.sleep(0.3)
    os.write(ctl, cmd)
    time.sleep(0.4)

    nfd = op(NATIVE or native_port(), 115200, dtr=True)
    termios.tcflush(nfd, termios.TCIFLUSH)

    block = bytes(range(256)) * (args.block // 256)
    rx = tx = 0
    want_rx = args.mode in ("in", "duplex", "in-dma", "duplex-dma")
    want_tx = args.mode in ("out", "duplex", "out-dma", "duplex-dma")

    t0 = time.time()
    while time.time() - t0 < args.seconds:
        r, w, _ = select.select([nfd] if want_rx else [],
                                [nfd] if want_tx else [], [], 0.1)
        # Symmetric budgets: an unequal read/write size here biases the
        # duplex result just as much as an unequal budget on the device.
        if r:
            try:
                rx += len(os.read(nfd, len(block)))
            except OSError:
                pass
        if w:
            try:
                tx += os.write(nfd, block)
            except OSError:
                pass
    el = time.time() - t0

    time.sleep(0.3)
    os.write(ctl, b"B")
    time.sleep(0.6)
    out = b""
    t1 = time.time()
    while time.time() - t1 < 1.5:
        # keep draining so a blocked device can still answer
        r, _, _ = select.select([nfd, ctl], [], [], 0.1)
        for f in r:
            try:
                d = os.read(f, 262144)
                if f == ctl:
                    out += d
            except OSError:
                pass
    os.write(ctl, b"0")
    os.close(nfd)
    os.close(ctl)

    print(f"# mode={args.mode} block={args.block} elapsed={el:.2f}s")
    if want_rx:
        print(f"#   host read    {rx:10d} B = {rx/el/1e6:6.3f} MB/s")
    if want_tx:
        print(f"#   host wrote   {tx:10d} B = {tx/el/1e6:6.3f} MB/s")
    for l in out.decode("utf-8", "replace").splitlines():
        if "bench=" in l:
            print("#   device says:", l.strip().lstrip("# "))


if __name__ == "__main__":
    main()
