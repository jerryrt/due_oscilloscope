#!/usr/bin/env python3
"""
Complete loop: HOST -> USB -> DAC -> wire -> ADC -> USB -> HOST.

The host generates a waveform, streams it to the DAC over bulk OUT, and
simultaneously receives the ADC capture over bulk IN. Because the host
authored the signal, any discrepancy in what comes back is a fault in the
path rather than an unknown property of a signal.

Wiring: DAC0 -> A0, DAC1 -> A1.

DAC samples carry the channel tag in bits [13:12]. The stream interleaves
the waveform on DAC0 with a fixed mid-scale level on DAC1, so DAC0 runs
at half the DAC's sample rate and A1 doubles as a demultiplexing check:
a tone appearing on A1 means the tags are being read wrong.
"""

import argparse
import fcntl
import glob
import math
import os
import select
import struct
import sys
import termios
import threading
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ports import find_ports, open_raw
import rt

HDR = "<4sBBBBIIHHIII"
HDR_LEN = struct.calcsize(HDR)
MAGIC = b"DUE0"


def goertzel(samples, fs, f):
    n = len(samples)
    if n == 0:
        return 0.0
    k = 2.0 * math.cos(2.0 * math.pi * f / fs)
    s1 = s2 = 0.0
    mean = sum(samples) / n
    for x in samples:
        s0 = (x - mean) + k * s1 - s2
        s2, s1 = s1, s0
    p = s1 * s1 + s2 * s2 - k * s1 * s2
    return math.sqrt(max(p, 0.0)) * 2.0 / n


def build_waveform(tone_hz, dac_total_sps, cycles=20):
    """
    Every sample tagged for DAC0, so DAC0 updates at the full rate.

    An earlier version interleaved DAC0 with a fixed level on DAC1 to get
    a demultiplexing check for free. The DACC accepted it -- TAG, MAXS,
    TRGEN and both channel enables all read back correct, and the ring
    held exactly the alternating tags the host sent -- but the analog
    result behaved as though both samples reached channel 0. Rather than
    keep chasing that, drive one channel: it is what an arbitrary
    waveform generator needs, and it doubles DAC0's update rate.
    """
    per_cycle = int(round(dac_total_sps / tone_hz))
    out = bytearray()
    for i in range(per_cycle * cycles):
        code = int(round(2047.5 + 2047.0 * math.sin(2.0 * math.pi * i / per_cycle)))
        code = max(0, min(4095, code))
        out += struct.pack("<H", (0 << 12) | (code & 0xFFF))
    return bytes(out), dac_total_sps / per_cycle


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--tone", type=float, default=1000.0)
    ap.add_argument("--dac-sps", type=int, default=200000)
    ap.add_argument("--adc-hz", type=int, default=200000)
    ap.add_argument("--dc", type=int, default=None,
                    help="send a constant DAC0 code instead of a tone")
    ap.add_argument("--scan", action="store_true",
                    help="sweep candidate frequencies to find the energy")
    ap.add_argument("--burst", type=int, default=16384,
                    help="bytes written per empty-queue event")
    ap.add_argument("--diag", action="store_true",
                    help="trigger the firmware's snapshot diagnostic mid-run")
    args = ap.parse_args()

    ctl, nat = find_ports()
    if not ctl:
        sys.exit(f"ports not found (control={ctl} native={nat})")
    print(f"# control={ctl}  native={nat}")

    if args.dc is not None:
        # Constant on DAC0, mid-scale on DAC1. If A0 does not move to the
        # matching level, the DAC is not consuming host data at all,
        # which separates a data-path fault from a timing one.
        wave = struct.pack("<H", (0 << 12) | (args.dc & 0xFFF)) * 4000
        tone = 0.0
    else:
        wave, tone = build_waveform(args.tone, args.dac_sps)
    print(f"# waveform: {len(wave)} B block, DAC0 tone {tone:.2f} Hz "
          f"at {args.dac_sps} sps (single channel)")

    # Opening the control port resets the board over NRSTB, which also
    # re-enumerates the native port: open control first, keep it open,
    # and only then look for the native node, whose name may have changed.
    cfd = open_raw(ctl, 115200)
    time.sleep(3.0)
    fd = None
    give_up = time.time() + 12.0
    while fd is None:
        nats = [n for n in glob.glob("/dev/cu.usbmodem*") if n != ctl]
        try:
            if nats:
                fd = open_raw(nats[0], 115200, dtr=True)
        except OSError:
            pass
        if fd is None:
            if time.time() >= give_up:
                sys.exit("native port did not re-enumerate after reset")
            time.sleep(0.5)
    if nats[0] != nat:
        print(f"# native re-enumerated as {nats[0]}")
    nat = nats[0]

    # Drain until the native port has been silent for a full second. A
    # stream from a previous run keeps flowing into the kernel's input
    # buffer long after the run ends, and analysing those stale frames is
    # exactly how a working loop was once diagnosed as "frozen at mid
    # scale": the flat startup of an old capture, read as live data. One
    # tcflush is not enough; the buffer refills as long as the device is
    # still streaming.
    stale = 0
    quiet = time.time()
    while time.time() - quiet < 1.0:
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try:
                stale += len(os.read(fd, 65536))
                quiet = time.time()
            except OSError:
                pass
    if stale:
        print(f"# drained {stale} stale bytes from the native port")

    os.write(cfd, f"={args.dac_sps},{args.adc_hz}L".encode())
    time.sleep(0.2)

    # Feed from a dedicated real-time thread, gated on tty writability.
    #
    # Three simpler policies were each tried and measured before this
    # one; the failures are worth keeping because every one of them
    # looked plausible:
    #
    #   - select()-paced writes in the shared main loop starved on loop
    #     granularity: ~1% rate shortfall, a few underruns per second.
    #   - free-running blocking writes from a thread saturated the
    #     queue, and macOS's CDC-ACM output path then silently dropped
    #     ~128-byte chunks that write() had already counted: ~75 clean
    #     phase jumps per second on the DAC, every counter green.
    #   - clock-paced writes at the exact byte rate still dropped, at
    #     any tested lead: the loss tracks writing into a queue that is
    #     actively draining, not queue depth as such.
    #
    # The only policy measured clean is the writability gate: select()
    # reports a tty writable when its output queue falls below the
    # low-water mark, so every write lands in a nearly empty queue and
    # the burst is what rides out scheduling gaps. What the original
    # main-loop version got wrong was latency, not policy - and the
    # real-time band fixes the latency, waking this thread within the
    # millisecond of low-water instead of on the next 50 ms poll. The
    # device's own 8 KB ring covers 20 ms, so the cadence has margin.
    # os.write releases the GIL, so the reader is never held up.
    tx_count = [0]
    rt_note = [None]
    stop = threading.Event()

    byte_rate = args.dac_sps * 2

    def feeder():
        rt_note[0] = rt.promote(period_ms=10.0, computation_ms=1.0,
                                constraint_ms=5.0)
        pos = 0
        while not stop.is_set():
            # Write only when TIOCOUTQ reports the queue truly empty,
            # not merely below low-water: the residual glitches at the
            # low-water gate (~1.6/s) vanish when every burst lands in
            # an empty queue. The device's 8 KB ring covers ~20 ms, so
            # sleeping half the remaining drain time and re-polling
            # never lets the far end starve.
            try:
                q = struct.unpack("i", fcntl.ioctl(
                    fd, termios.TIOCOUTQ, b"\0\0\0\0"))[0]
            except OSError:
                return
            if q > 0:
                time.sleep(max(0.001, q / byte_rate / 2))
                continue
            block = wave[pos:pos + args.burst]
            while len(block) < args.burst:
                block += wave[:args.burst - len(block)]
            try:
                n = os.write(fd, block)
            except OSError:
                return
            if n > 0:
                tx_count[0] += n
                pos = (pos + n) % len(wave)

    th = threading.Thread(target=feeder, daemon=True)
    th.start()

    chunks = []
    ctl_out = b""
    diag_sent = False
    t0 = time.time()
    while time.time() - t0 < args.seconds:
        # The diagnostic must sample while both directions are live, so it
        # is triggered mid-run, not before or after.
        if args.diag and not diag_sent and time.time() - t0 > 1.5:
            os.write(cfd, b"D")
            diag_sent = True
        r, _, _ = select.select([fd, cfd], [], [], 0.05)
        if cfd in r:
            try:
                ctl_out += os.read(cfd, 65536)
            except OSError:
                pass
        if fd in r:
            try:
                chunks.append(os.read(fd, 262144))
            except OSError:
                pass
    el = time.time() - t0

    # The device keeps consuming until '0' below, so a final blocking
    # write completes on its own; the flush is only a backstop against a
    # writer wedged on a queue nobody is draining.
    stop.set()
    th.join(2.0)
    if th.is_alive():
        termios.tcflush(fd, termios.TCOFLUSH)
        th.join(1.0)
    tx = tx_count[0]

    os.write(cfd, b"B")
    time.sleep(0.5)
    rep = b""
    tend = time.time() + 1.5
    while time.time() < tend:
        r, _, _ = select.select([fd, cfd], [], [], 0.1)
        for f in r:
            try:
                d = os.read(f, 65536)
                if f == cfd:
                    rep += d
            except OSError:
                pass
    os.write(cfd, b"0")
    # '0' stops the device from draining bulk OUT, so any bytes still in
    # the kernel's output queue can never leave - and close() on a tty
    # drains that queue before returning. Without this flush the process
    # hangs in close() forever, holding the port and leaving the board
    # streaming into the void for the next run to trip over.
    try:
        termios.tcflush(fd, termios.TCIOFLUSH)
    except OSError:
        pass
    os.close(fd)
    os.close(cfd)

    # ---- parse ----
    buf = b"".join(chunks)
    flist = []
    crc_bad = 0
    p = 0
    while True:
        i = buf.find(MAGIC, p)
        if i < 0 or len(buf) - i < HDR_LEN:
            break
        h = bytes(buf[i:i + HDR_LEN])
        (_m, ver, fl, bits, pk, seq, srate, ns, cm, ts, ov, crc) = struct.unpack(HDR, h)
        if zlib.crc32(h[:HDR_LEN - 4]) & 0xFFFFFFFF != crc:
            crc_bad += 1
            p = i + 4
            continue
        need = HDR_LEN + ns * 2
        if len(buf) - i < need:
            break
        flist.append((seq, ts, ov, srate,
                      struct.unpack("<%dH" % ns, buf[i + HDR_LEN:i + need])))
        p = i + need

    if not flist:
        sys.exit("no frames received")

    # A fresh stream starts at seq 0. A capture that begins far from it
    # is stale data from an earlier run still sitting in the kernel
    # buffer, and everything computed from it would describe the past.
    if flist[0][0] > 10:
        print(f"# WARNING: capture starts at seq {flist[0][0]}, not 0 - "
              f"stale data from a previous stream; results are unreliable")
    gaps = sum(1 for a, b in zip(flist, flist[1:]) if b[0] != a[0] + 1)
    frames = len(flist)
    rate = flist[0][3]
    ts0 = flist[0][1]
    dev_span = (flist[-1][1] - ts0) / 1e6

    per_ch = {}
    keep = {}
    keep_t0 = ts0 + 1_000_000     # spectral window: from 1 s of device time
    for (seq, ts, ov, srate, body) in flist:
        settled = ts >= keep_t0
        for v in body:
            ch = (v >> 12) & 0xF
            val = v & 0xFFF
            st = per_ch.setdefault(ch, [0, 4095, 0, 0])
            st[0] += 1
            st[1] = min(st[1], val); st[2] = max(st[2], val); st[3] += val
            if settled:
                k = keep.setdefault(ch, [])
                if len(k) < 16384:
                    k.append(val)

    print(f"# elapsed        {el:.2f} s")
    print(f"# feeder thread  {rt_note[0]}")
    print(f"# host  -> DAC   {tx} B = {tx/el/1e6:.3f} MB/s")
    print(f"# ADC   -> host  {len(buf)} B = {len(buf)/el/1e6:.3f} MB/s")
    print(f"#   combined     {(tx+len(buf))/el/1e6:.3f} MB/s")
    print(f"# frames {frames}  seq {flist[0][0]}..{flist[-1][0]}  "
          f"crc_bad {crc_bad}  seq gaps {gaps}  "
          f"device span {dev_span:.2f} s  max overrun {max(f[2] for f in flist)}")
    for l in rep.decode("utf-8", "replace").splitlines():
        if "play:" in l or "bench=" in l:
            print("#", l.strip().lstrip("# "))
    if ctl_out:
        print("# --- control port during run ---")
        for l in ctl_out.decode("utf-8", "replace").splitlines():
            if l.strip():
                print(l if l.startswith("#") else "# " + l)
    print("# channel   n        min   max   mean")
    for ch in sorted(per_ch):
        n, lo, hi, tot = per_ch[ch]
        lab = {7: "A0", 6: "A1"}.get(ch, "?")
        print(f"#   AD{ch} {lab}  {n:8d}  {lo:5d} {hi:5d}  {tot/n:7.1f}")
    if rate:
        print(f"# Goertzel at {tone:.2f} Hz (fs = {rate} Hz/ch)")
        for ch in sorted(keep):
            lab = {7: "A0", 6: "A1"}.get(ch, "?")
            m = goertzel(keep[ch], rate, tone)
            print(f"#   AD{ch} {lab}  amplitude {m:8.1f} codes")
        print("#   A0 should carry the tone the host sent; A1 should be flat")
        # Amplitude against device time, so a late or intermittent tone
        # shows as what it is instead of averaging into a small number.
        a0t = [(ts, v & 0xFFF)
               for (seq, ts, ov, srate, body) in flist
               for v in body if (v >> 12) & 0xF == 7]
        W = 8192
        if len(a0t) > W:
            print("# A0 amplitude by device time:")
            rows = []
            for s in range(0, len(a0t) - W, W * 3):
                w = [v for _, v in a0t[s:s + W]]
                rows.append(f"{(a0t[s][0]-ts0)/1e6:5.2f}s:{goertzel(w, rate, tone):6.1f}")
            for j in range(0, len(rows), 5):
                print("#   " + "  ".join(rows[j:j + 5]))
        for ch in (7, 6):
            if ch in keep and len(keep[ch]) >= 40:
                lab = {7: "A0", 6: "A1"}[ch]
                print(f"# first 40 settled samples on AD{ch} {lab}:")
                print("#   " + " ".join(f"{v:4d}" for v in keep[ch][:20]))
                print("#   " + " ".join(f"{v:4d}" for v in keep[ch][20:40]))
        if args.scan and 7 in keep:
            print("# frequency scan on A0 (find where the energy actually is)")
            cands = [tone, tone/2, tone/4, 390.6, 195.3, 97.7,
                     2000.0, 4000.0, 8000.0, 12500.0, 25000.0]
            rows = sorted(((goertzel(keep[7], rate, f), f) for f in cands),
                          reverse=True)
            for mag, f in rows:
                print(f"#     {f:9.1f} Hz  {mag:8.1f} codes")


if __name__ == "__main__":
    main()
