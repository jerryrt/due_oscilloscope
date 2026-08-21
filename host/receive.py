#!/usr/bin/env python3
"""
Host receiver for the due_oscilloscope sample stream.

Stdlib only: this machine has no package manager, and the bring-up path
should not need one. Tone detection uses Goertzel rather than an FFT,
which is enough to verify a known generated frequency.

Reads binary frames from the NATIVE port. Control and logs live on the
programming port and are never mixed in here.

usage: receive.py [--port DEV] [--seconds N] [--expect-hz F]
"""

import argparse
import errno
import fcntl
import glob
import math
import os
import select
import struct
import sys
import termios
import time
import zlib

HDR_FMT = "<4sBBBBIIHHIII"
HDR_LEN = struct.calcsize(HDR_FMT)
MAGIC = b"DUE0"

FLAG_OVERRUN = 1 << 0


def find_native_port(programming="141301", wait=10.0):
    """
    Native port is the cu.usbmodem* that is not the programming port.

    It disappears whenever the SAM3X resets, since that CDC is served by
    the SAM3X itself rather than by the 16U2, so wait for it to come back
    after a flash instead of failing immediately.
    """
    deadline = time.time() + wait
    while True:
        cands = [p for p in glob.glob("/dev/cu.usbmodem*")
                 if programming not in p]
        if cands:
            return sorted(cands)[0]
        if time.time() >= deadline:
            sys.exit("no native port found; is the board enumerated?")
        time.sleep(0.25)


def open_raw(dev, baud=None, dtr=False):
    """
    Apply every termios change in a single tcsetattr. The programming
    port is bridged by a 16U2 that treats 1200 baud as an erase-and-reset
    command, so leaving the port at a stale speed for even one syscall
    can reset the board mid-test.
    """
    fd = os.open(dev, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[0] = 0
    a[1] = 0
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    a[3] = 0
    if baud is not None:
        a[4] = a[5] = getattr(termios, "B%d" % baud)
    a[6][termios.VMIN] = 0
    a[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    if dtr:
        # The Arduino CDC discards every write until the host sets the
        # control line state, and a /dev/cu.* open does not raise DTR.
        try:
            fcntl.ioctl(fd, termios.TIOCMBIS,
                        struct.pack("I", termios.TIOCM_DTR | termios.TIOCM_RTS))
        except OSError:
            pass
    return fd


def goertzel(samples, fs, ftarget):
    """Single-bin DFT magnitude, normalised to sample count."""
    n = len(samples)
    if n == 0 or fs <= 0:
        return 0.0
    k = 2.0 * math.cos(2.0 * math.pi * ftarget / fs)
    s1 = s2 = 0.0
    mean = sum(samples) / n
    for x in samples:
        s0 = (x - mean) + k * s1 - s2
        s2, s1 = s1, s0
    power = s1 * s1 + s2 * s2 - k * s1 * s2
    return math.sqrt(max(power, 0.0)) * 2.0 / n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None)
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--expect-hz", type=float, default=None,
                    help="expected DAC0 tone, for the Goertzel check")
    ap.add_argument("--control", default=None,
                    help="programming port, for the start command")
    ap.add_argument("--send", default=None,
                    help="command to send on the control port before reading")
    ap.add_argument("--stop", default="0",
                    help="command to send on the control port afterwards")
    ap.add_argument("--uart", action="store_true",
                    help="single-port mode: frames arrive on the control "
                         "port itself, as Track B does over UART")
    ap.add_argument("--uart-baud", type=int, default=115200)
    ap.add_argument("--scan-hz", default=None,
                    help="comma-separated frequencies to test with Goertzel")
    args = ap.parse_args()

    # Order matters. Opening the control port can reset the board, and a
    # reset re-enumerates the native CDC, invalidating any fd opened
    # before it. So: control first, start the stream, then find and open
    # the native port.
    # Resolve ports before anything opens them: the --send block below
    # used to run first and crash on a None control port whenever
    # --control was not given explicitly.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ports import find_ports
    if args.control is None or (args.port is None and not args.uart):
        _ctl, _nat = find_ports()
        if args.control is None:
            args.control = _ctl
        if args.port is None and not args.uart:
            args.port = _nat
    if args.control is None:
        sys.exit("no control port found")

    cfd = None
    if args.send and not args.uart:
        cfd = open_raw(args.control, baud=115200)
        time.sleep(0.2)
        os.write(cfd, args.send.encode())
        time.sleep(0.4)
        # Echo whatever the device says back. A banner here means the
        # board reset rather than accepting the command.
        reply = b""
        t_end = time.time() + 0.6
        while time.time() < t_end:
            try:
                reply += os.read(cfd, 4096)
            except OSError:
                pass
            time.sleep(0.05)
        for line in reply.decode("utf-8", "replace").splitlines():
            if line.strip():
                print("# ctl> " + line.strip())

    if args.uart:
        dev = args.control
        print(f"# uart transport, single port: {dev}")
    else:
        # The board resets when the control port opens, so the native
        # node may still be re-enumerating; find_native_port waits for
        # it, excluding the discovered control port rather than any
        # hardcoded name.
        dev = args.port or find_native_port(programming=args.control)
        print(f"# native port: {dev}")
    # Force a non-1200 line coding. The Arduino CDC arms an auto-reset
    # when the port is closed while its stored rate is 1200, so leaving a
    # stale 1200 here makes the board reset at the end of every run.
    if args.uart:
        # One port carries both the command and the frames.
        fd = open_raw(dev, baud=args.uart_baud)
        time.sleep(0.2)
        if args.send:
            os.write(fd, args.send.encode())
        cfd = fd
    else:
        fd = open_raw(dev, baud=115200, dtr=True)

    # ------------------------------------------------------------------
    # Capture phase: do nothing but read.
    #
    # An earlier version parsed each frame inline, including a per-sample
    # Python loop. At ~0.9 MB/s that is far too slow, so the port stopped
    # being drained, the kernel buffer overflowed, and bytes were lost.
    # The symptom looked exactly like a firmware framing bug: samples
    # attributed to channels that were not enabled, and sequence jumps.
    # It was the receiver all along.
    # ------------------------------------------------------------------
    # Drop anything queued from a previous run before the clock starts.
    # The device restarts its sequence numbering at zero on stream
    # start, so stale bytes appear as one enormous sequence jump and
    # inflate the sample count with data from the last capture.
    time.sleep(0.3)
    try:
        termios.tcflush(fd, termios.TCIFLUSH)
    except OSError:
        pass
    drain_end = time.time() + 0.2
    while time.time() < drain_end:
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                os.read(fd, 262144)
            except OSError:
                break

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import rt
    print(f"# capture thread: {rt.promote(period_ms=5.0, computation_ms=0.5, constraint_ms=2.5)}")

    chunks = []
    t0 = time.time()
    t_end_capture = None
    deadline = t0 + args.seconds
    try:
        while time.time() < deadline:
            r, _, _ = select.select([fd], [], [], 0.2)
            if not r:
                continue
            try:
                chunk = os.read(fd, 262144)
            except OSError as e:
                if e.errno in (errno.ENXIO, errno.EAGAIN):
                    time.sleep(0.02)
                    continue
                raise
            if chunk:
                chunks.append(chunk)
    finally:
        t_end_capture = time.time()
        if cfd is not None:
            try:
                os.write(cfd, args.stop.encode())
                t_drain = time.time() + 1.0
                while time.time() < t_drain:
                    r, _, _ = select.select([fd], [], [], 0.1)
                    if r:
                        try:
                            os.read(fd, 262144)
                        except OSError:
                            break
            finally:
                if cfd is not fd:
                    os.close(cfd)
        os.close(fd)

    # ------------------------------------------------------------------
    # Parse phase
    # ------------------------------------------------------------------
    buf = bytearray(b"".join(chunks))
    captured_bytes = len(buf)
    frames = payload_bytes = 0
    seq_prev = None
    seq_gaps = dropped_frames = crc_bad = 0
    overrun_frames = 0
    first_overrun_count = last_overrun_count = None
    per_ch = {}
    rate_hz = None
    n_ch_declared = 2
    ts_first = ts_last = None
    keep = {}
    pos = 0

    while True:
        i = buf.find(MAGIC, pos)
        if i < 0:
            break
        if len(buf) - i < HDR_LEN:
            break

        hdr = bytes(buf[i:i + HDR_LEN])
        (_m, ver, flags, bits, packing, seq, rate, nsamp,
         chmask, ts, overruns, crc) = struct.unpack(HDR_FMT, hdr)

        if zlib.crc32(hdr[:HDR_LEN - 4]) & 0xFFFFFFFF != crc:
            crc_bad += 1
            pos = i + 4
            continue

        need = HDR_LEN + nsamp * 2
        if len(buf) - i < need:
            break

        body = bytes(buf[i + HDR_LEN:i + need])
        pos = i + need

        frames += 1
        payload_bytes += len(body)
        rate_hz = rate
        n_ch_declared = max(1, bin(chmask).count("1"))
        if ts_first is None:
            ts_first = ts
        ts_last = ts

        if flags & FLAG_OVERRUN:
            overrun_frames += 1
        if first_overrun_count is None:
            first_overrun_count = overruns
        last_overrun_count = overruns

        if seq_prev is not None and seq != seq_prev + 1:
            seq_gaps += 1
            dropped_frames += (seq - seq_prev - 1) & 0xFFFFFFFF
        seq_prev = seq

        vals = struct.unpack("<%dH" % nsamp, body)
        for v in vals:
            ch = (v >> 12) & 0xF
            val = v & 0xFFF
            st = per_ch.setdefault(ch, [0, 4095, 0, 0])
            st[0] += 1
            if val < st[1]:
                st[1] = val
            if val > st[2]:
                st[2] = val
            st[3] += val
            k = keep.setdefault(ch, [])
            if len(k) < 8192:
                k.append(val)

    elapsed = (t_end_capture or time.time()) - t0
    print(f"# elapsed          {elapsed:.2f} s")
    print(f"# frames           {frames}")
    print(f"# captured         {captured_bytes} bytes"
          f"  ({captured_bytes / elapsed / 1e6:.3f} MB/s)")
    print(f"# payload          {payload_bytes} bytes in frames")
    print(f"# header CRC bad   {crc_bad}")
    print(f"# seq gaps         {seq_gaps}  (frames lost: {dropped_frames})")
    print(f"# frames flagged   {overrun_frames}")
    if first_overrun_count is not None:
        print(f"# device overruns  {first_overrun_count} -> {last_overrun_count}")

    if frames >= 2 and ts_first is not None and ts_last != ts_first:
        span_us = (ts_last - ts_first) & 0xFFFFFFFF
        total = sum(st[0] for st in per_ch.values())
        # last frame's samples arrived after ts_last, so use frames-1
        # Use the declared channel count, not the observed one: a
        # single corrupt sample would otherwise invent a channel and
        # skew the rate.
        eff = (total - total / max(frames, 1)) * 1e6 / span_us / n_ch_declared
        print(f"# declared rate    {rate_hz} Hz per channel")
        print(f"# measured rate    {eff:.0f} Hz per channel"
              f"   ratio {eff / rate_hz:.3f}" if rate_hz else "")

    print("# channel   n        min   max   mean")
    for ch in sorted(per_ch):
        n, lo, hi, tot = per_ch[ch]
        label = {7: "A0", 6: "A1"}.get(ch, "?")
        print(f"#   AD{ch} {label}  {n:8d}  {lo:5d} {hi:5d}  {tot / n:7.1f}")

    if args.scan_hz and rate_hz:
        cands = [float(x) for x in args.scan_hz.split(",")]
        print(f"# Goertzel scan (fs = {rate_hz} Hz/ch)")
        for ch in sorted(keep):
            label = {7: "A0", 6: "A1"}.get(ch, "?")
            row = "  ".join(
                f"{f:8.1f}Hz={goertzel(keep[ch], rate_hz, f):7.1f}"
                for f in cands)
            print(f"#   AD{ch} {label}  {row}")

    if args.expect_hz and rate_hz:
        print(f"# Goertzel at {args.expect_hz:.2f} Hz (fs = {rate_hz} Hz/ch)")
        for ch in sorted(keep):
            label = {7: "A0", 6: "A1"}.get(ch, "?")
            mag = goertzel(keep[ch], rate_hz, args.expect_hz)
            print(f"#   AD{ch} {label}  amplitude {mag:8.1f} codes"
                  f"   ({mag * 3300 / 4095:7.1f} mV)")
        print("#   A0 should show the tone; A1 should be near zero")


if __name__ == "__main__":
    main()
