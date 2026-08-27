#!/usr/bin/env python3
"""
Complete loop: HOST -> USB -> DAC -> wire -> ADC -> USB -> HOST.

The host generates a waveform, streams it to the DAC over bulk OUT, and
simultaneously receives the ADC capture over bulk IN. Because the host
authored the signal, any discrepancy in what comes back is a fault in the
path rather than an unknown property of a signal.

Wiring: DAC0 -> A0, DAC1 -> A1.

Every DAC sample is tagged for channel 0, so DAC0 updates at the full
rate; A1 then doubles as a demultiplexing check, since a tone appearing
there means the tags are being read wrong.

The measurement itself lives in measure.py. This script is the command
line and the report; the library is what the test suite imports.
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
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--tone", type=float, default=1000.0)
    ap.add_argument("--dac-sps", type=int, default=200000)
    ap.add_argument("--adc-hz", type=int, default=200000)
    ap.add_argument("--adc-channels", type=int, default=2, choices=(1, 2),
                    help="ADC channels to capture; 1 = A0 alone at the "
                         "full single-channel conversion rate")
    ap.add_argument("--dc", type=int, default=None,
                    help="send a constant DAC0 code instead of a tone")
    ap.add_argument("--square", type=float, default=None, metavar="HZ",
                    help="send a full-scale square at HZ instead of a tone")
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

    wave, tone = measure.build_selected(args.dac_sps, tone=args.tone,
                                        dc=args.dc, square=args.square)
    print(f"# waveform: {len(wave)} B block, DAC0 tone {tone:.2f} Hz "
          f"at {args.dac_sps} sps (single channel)")

    def notify(event, **kw):
        if event == "native" and kw.get("changed"):
            print(f"# native re-enumerated as {kw['path']}")
        elif event == "stale":
            print(f"# drained {kw['bytes']} stale bytes from the native port")

    # Opening the control port resets the board over NRSTB, which also
    # re-enumerates the native port: open control first, keep it open,
    # and only then look for the native node, whose name may have changed.
    board = measure.Board(control=ctl, native=nat, settle=3.0)
    try:
        res = measure.run_loop(board, dac_sps=args.dac_sps,
                               adc_hz=args.adc_hz, channels=args.adc_channels,
                               tone=args.tone, seconds=args.seconds,
                               dc=args.dc, square=args.square,
                               diag=args.diag, notify=notify)
    finally:
        board.close()

    ps = res.stream
    if not ps.frames:
        sys.exit("no frames received")

    # A fresh stream starts at seq 0. A capture that begins far from it
    # is stale data from an earlier run still sitting in the kernel
    # buffer, and everything computed from it would describe the past.
    if ps.first_seq > 10:
        print(f"# WARNING: capture starts at seq {ps.first_seq}, not 0 - "
              f"stale data from a previous stream; results are unreliable")

    el = res.elapsed_s
    tx, rx = res.host_tx_bytes, res.host_rx_bytes
    print(f"# elapsed        {el:.2f} s")
    print(f"# feeder thread  {res.rt_note}")
    print(f"# host  -> DAC   {tx} B = {tx/el/1e6:.3f} MB/s")
    print(f"# ADC   -> host  {rx} B = {rx/el/1e6:.3f} MB/s")
    print(f"#   combined     {(tx+rx)/el/1e6:.3f} MB/s")
    print(f"# frames {ps.frames}  seq {ps.first_seq}..{ps.last_seq}  "
          f"crc_bad {ps.crc_bad}  seq gaps {ps.seq_gaps}  "
          f"device span {ps.dev_span_s:.2f} s  max overrun {ps.max_overrun}")
    for l in res.report.splitlines():
        if "play:" in l or "bench=" in l:
            print("#", l.strip().lstrip("# "))
    if res.console:
        print("# --- control port during run ---")
        for l in res.console.splitlines():
            if l.strip():
                print(l if l.startswith("#") else "# " + l)

    print("# channel   n        min   max   mean")
    for ch in sorted(ps.per_channel):
        st = ps.per_channel[ch]
        print(f"#   AD{ch} {st.label}  {st.n:8d}  {st.lo:5d} {st.hi:5d}  "
              f"{st.mean:7.1f}")

    rate = ps.declared_rate_hz
    keep = ps.settled
    if rate:
        print(f"# Goertzel at {tone:.2f} Hz (fs = {rate} Hz/ch)")
        for ch in sorted(keep):
            m = goertzel(keep[ch], rate, tone)
            print(f"#   AD{ch} {label_for(ch)}  amplitude {m:8.1f} codes")
        print("#   A0 should carry the tone the host sent; A1 should be flat")
        # Amplitude against device time, so a late or intermittent tone
        # shows as what it is instead of averaging into a small number.
        W = 8192
        rows = [f"{t:5.2f}s:{a:6.1f}"
                for t, a in ps.window_amplitudes(measure.CH_A0, tone,
                                                 size=W, stride=W * 3)]
        if rows:
            print("# A0 amplitude by device time:")
            for j in range(0, len(rows), 5):
                print("#   " + "  ".join(rows[j:j + 5]))
        for ch in (measure.CH_A0, measure.CH_A1):
            if ch in keep and len(keep[ch]) >= 40:
                print(f"# first 40 settled samples on AD{ch} {label_for(ch)}:")
                print("#   " + " ".join(f"{v:4d}" for v in keep[ch][:20]))
                print("#   " + " ".join(f"{v:4d}" for v in keep[ch][20:40]))
        if args.scan and measure.CH_A0 in keep:
            print("# frequency scan on A0 (find where the energy actually is)")
            cands = [tone, tone/2, tone/4, 390.6, 195.3, 97.7,
                     2000.0, 4000.0, 8000.0, 12500.0, 25000.0]
            rows = sorted(((goertzel(keep[measure.CH_A0], rate, f), f)
                           for f in cands), reverse=True)
            for mag, f in rows:
                print(f"#     {f:9.1f} Hz  {mag:8.1f} codes")


if __name__ == "__main__":
    main()
