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
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ports import find_ports
import rt


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


def native_port(ctl, wait=10.0):
    """Whichever usbmodem node is not the discovered control port. Never
    a hardcoded path: node names change with every cable move."""
    end = time.time() + wait
    while True:
        c = [p for p in glob.glob("/dev/cu.usbmodem*") if p != ctl]
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

    # Opening the control port resets the board over NRSTB, so the
    # native CDC re-enumerates and its node may briefly not accept an
    # open. Retry rather than racing it.
    nfd = None
    give_up = time.time() + 10.0
    while nfd is None:
        try:
            nfd = op(native_port(CTL), 115200, dtr=True)
        except OSError:
            if time.time() >= give_up:
                sys.exit("native port did not come back after reset")
            time.sleep(0.5)
    termios.tcflush(nfd, termios.TCIFLUSH)

    block = bytes(range(256)) * (args.block // 256)
    want_rx = args.mode in ("in", "duplex", "in-dma", "duplex-dma")
    want_tx = args.mode in ("out", "duplex", "out-dma", "duplex-dma")

    # One thread per direction, and blocking writes. The earlier loop
    # interleaved reads and writes on one thread behind a select()
    # timeout, so each direction stalled while the other's syscall ran
    # and whenever the poll interval overshot - a ceiling made by the
    # host's scheduling, not by the transport, which is the same trap
    # this project already hit once with unequal budgets on the device.
    # With a blocking write the kernel wakes the writer the moment the
    # output queue has room; VMIN=0 keeps reads non-blocking, so
    # clearing O_NONBLOCK affects only the write side. os.read/os.write
    # release the GIL, so the directions genuinely overlap.
    fl = fcntl.fcntl(nfd, fcntl.F_GETFL)
    fcntl.fcntl(nfd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)

    rx_n = [0]
    tx_n = [0]
    rt_notes = {}
    stop = threading.Event()

    def reader():
        # At ~4 MB/s a 5 ms scheduling hole is 20 kB of kernel buffer;
        # the real-time band keeps the drain ahead of it.
        rt_notes["reader"] = rt.promote(period_ms=5.0, computation_ms=0.5,
                                        constraint_ms=2.5)
        while not stop.is_set():
            r, _, _ = select.select([nfd], [], [], 0.05)
            if r:
                try:
                    rx_n[0] += len(os.read(nfd, 262144))
                except OSError:
                    return

    def writer():
        rt_notes["writer"] = rt.promote(period_ms=5.0, computation_ms=0.5,
                                        constraint_ms=2.5)
        while not stop.is_set():
            try:
                tx_n[0] += os.write(nfd, block)
            except OSError:
                return

    threads = []
    if want_rx:
        threads.append(threading.Thread(target=reader, daemon=True))
    if want_tx:
        threads.append(threading.Thread(target=writer, daemon=True))
    t0 = time.time()
    for th in threads:
        th.start()
    time.sleep(args.seconds)
    el = time.time() - t0
    stop.set()
    for th in threads:
        th.join(2.0)
    if any(th.is_alive() for th in threads):
        # A writer wedged on a queue the device stopped draining.
        termios.tcflush(nfd, termios.TCOFLUSH)
        for th in threads:
            th.join(1.0)
    rx, tx = rx_n[0], tx_n[0]

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
    # close() on a tty drains the output queue first, and once '0' stops
    # the device from reading bulk OUT a saturated queue never drains:
    # without this flush the process hangs in close() holding the port.
    try:
        termios.tcflush(nfd, termios.TCIOFLUSH)
    except OSError:
        pass
    os.close(nfd)
    os.close(ctl)

    print(f"# mode={args.mode} block={args.block} elapsed={el:.2f}s")
    for role in sorted(rt_notes):
        print(f"#   {role} thread: {rt_notes[role]}")
    if want_rx:
        print(f"#   host read    {rx:10d} B = {rx/el/1e6:6.3f} MB/s")
    if want_tx:
        print(f"#   host wrote   {tx:10d} B = {tx/el/1e6:6.3f} MB/s")
    for l in out.decode("utf-8", "replace").splitlines():
        if "bench=" in l:
            print("#   device says:", l.strip().lstrip("# "))


if __name__ == "__main__":
    main()
