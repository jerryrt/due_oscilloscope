#!/usr/bin/env python3
"""
USB transport benchmark for either track.

Drives the device's flood / sink / duplex modes and measures each
direction from the host side, so the host's own throughput is visible
alongside what the device counted. A mismatch between the two is the
signal that the host, not the device, is the limit.

The measurement lives in measure.py; this script is the command line and
the report.

usage: usbbench.py [in|out|duplex|in-dma|out-dma|duplex-dma] [--seconds N]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import measure


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=sorted(measure.BENCH_CMD))
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--block", type=int, default=16384)
    args = ap.parse_args()

    board = measure.Board(settle=0.3)
    try:
        res = measure.run_bench(board, mode=args.mode, seconds=args.seconds,
                                block=args.block)
    finally:
        board.close()

    print(f"# mode={res.mode} block={res.block} elapsed={res.elapsed_s:.2f}s")
    for role in sorted(res.rt_notes):
        print(f"#   {role} thread: {res.rt_notes[role]}")
    if res.want_rx:
        print(f"#   host read    {res.host_rx_bytes:10d} B = "
              f"{res.rx_mbs:6.3f} MB/s")
    if res.want_tx:
        print(f"#   host wrote   {res.host_tx_bytes:10d} B = "
              f"{res.tx_mbs:6.3f} MB/s")
    for l in res.report.splitlines():
        if "bench=" in l:
            print("#   device says:", l.strip().lstrip("# "))


if __name__ == "__main__":
    main()
