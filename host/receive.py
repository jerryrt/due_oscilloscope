#!/usr/bin/env python3
"""
Host receiver for the due_oscilloscope sample stream.

Reads binary frames from the NATIVE port. Control and logs live on the
programming port and are never mixed in here, except in --uart mode
where the one port carries both.

Stdlib only: this machine has no package manager, and the bring-up path
should not need one. Tone detection uses Goertzel rather than an FFT,
which is enough to verify a known generated frequency.

The measurement lives in measure.py; this script is the command line and
the report.

usage: receive.py [--port DEV] [--seconds N] [--expect-hz F]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import measure
from measure import goertzel, label_for
from ports import find_ports


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
    # before it. So resolve both ports before anything opens one.
    if args.control is None or (args.port is None and not args.uart):
        _ctl, _nat = find_ports()
        if args.control is None:
            args.control = _ctl
        if args.port is None and not args.uart:
            args.port = _nat
    if args.control is None:
        sys.exit("no control port found")

    def notify(event, **kw):
        if event == "native":
            print(f"# native port: {kw['path']}")
        elif event == "rt":
            print(f"# capture thread: {kw['note']}")

    if args.uart:
        print(f"# uart transport, single port: {args.control}")

    board = measure.Board(control=args.control, native=args.port, settle=0.2)
    try:
        res = measure.run_capture(board, preset=args.send,
                                  seconds=args.seconds,
                                  expect_hz=args.expect_hz,
                                  stop=args.stop if args.send else None,
                                  notify=notify, uart=args.uart)
    finally:
        board.close()

    # The device's own console during the run. It arrives after the
    # capture now rather than before it, because the stream is started
    # only once the native port is open and drained - which is what
    # makes the first captured frame the first frame of the run.
    for line in res.console.splitlines():
        if line.strip():
            print("# ctl> " + line.strip())

    ps = res.stream
    el = res.elapsed_s
    print(f"# elapsed          {el:.2f} s")
    print(f"# frames           {ps.frames}")
    print(f"# captured         {res.host_rx_bytes} bytes"
          f"  ({res.host_rx_bytes / el / 1e6:.3f} MB/s)")
    print(f"# payload          {ps.payload_bytes} bytes in frames")
    print(f"# header CRC bad   {ps.crc_bad}")
    print(f"# seq gaps         {ps.seq_gaps}  (frames lost: {ps.dropped_frames})")
    print(f"# frames flagged   {ps.overrun_frames}")
    if ps.first_overrun is not None:
        print(f"# device overruns  {ps.first_overrun} -> {ps.last_overrun}")

    rate_hz = ps.declared_rate_hz
    eff = ps.measured_rate_hz()
    if eff is not None:
        print(f"# declared rate    {rate_hz} Hz per channel")
        print(f"# measured rate    {eff:.0f} Hz per channel"
              f"   ratio {eff / rate_hz:.3f}" if rate_hz else "")

    print("# channel   n        min   max   mean")
    for ch in sorted(ps.per_channel):
        st = ps.per_channel[ch]
        print(f"#   AD{ch} {st.label}  {st.n:8d}  {st.lo:5d} {st.hi:5d}  "
              f"{st.mean:7.1f}")

    keep = ps.settled
    if args.scan_hz and rate_hz:
        cands = [float(x) for x in args.scan_hz.split(",")]
        print(f"# Goertzel scan (fs = {rate_hz} Hz/ch)")
        for ch in sorted(keep):
            row = "  ".join(f"{f:8.1f}Hz={goertzel(keep[ch], rate_hz, f):7.1f}"
                            for f in cands)
            print(f"#   AD{ch} {label_for(ch)}  {row}")

    if args.expect_hz and rate_hz:
        print(f"# Goertzel at {args.expect_hz:.2f} Hz (fs = {rate_hz} Hz/ch)")
        for ch in sorted(keep):
            mag = goertzel(keep[ch], rate_hz, args.expect_hz)
            print(f"#   AD{ch} {label_for(ch)}  amplitude {mag:8.1f} codes"
                  f"   ({mag * 3300 / 4095:7.1f} mV)")
        print("#   A0 should show the tone; A1 should be near zero")


if __name__ == "__main__":
    main()
