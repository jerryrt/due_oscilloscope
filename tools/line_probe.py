#!/usr/bin/env python3
"""Amplitude of the line at fs/4 on A0, with the DAC triggered or not.

    line_probe.py --arm gen|off --rc 86 --runs 10 [--out rows.jsonl]

`gen` holds a DC code through the internal generator, as the noise test
does, so the DACC converts once per sample. `off` uses the capture-only
command `=<adc>,2a`: nothing triggers the DAC. Each row is the single-bin
amplitude in codes at fs/4 (a Goertzel over 262,144 samples, so fs/4 is an
exact bin) and the median of eight bins 80-300 bins away as the floor. Pure
Python on purpose: the venv carries no numpy.
"""
import argparse
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("host", "tools", "tests"):
    sys.path.insert(0, os.path.join(ROOT, sub))
import measure  # noqa: E402
import noisetool  # noqa: E402

N = 262144


def _amp(x, k):
    c = 2 * math.cos(2 * math.pi * k / len(x))
    s1 = s2 = 0.0
    for v in x:
        s1, s2 = v + c * s1 - s2, s1
    return 2 * math.sqrt(s1 * s1 + s2 * s2 - c * s1 * s2) / len(x)


def one(board, arm, rc, seconds):
    hz = measure.hz_for(rc)
    if arm == "gen":
        res = noisetool.hold_gen_dc(board, 2048, "=%d,%dM" % (hz, hz), seconds)
    else:
        res = measure.run_capture(board, preset="=%d,2a" % hz, seconds=seconds)
    fs = res.stream.declared_rate_hz or hz
    x = list(noisetool._series(res, measure.CH_A0))[:N]
    m = sum(x) / len(x)
    x = [v - m for v in x]
    k0 = len(x) // 4
    floor = sorted(_amp(x, k0 + d) for d in (-300, -200, -120, -80, 80, 120, 200, 300))
    return {"arm": arm, "rc": rc, "fs": fs, "n": len(x),
            "peak": _amp(x, k0), "floor": floor[len(floor) // 2]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=("gen", "off"), required=True)
    ap.add_argument("--rc", type=int, default=86)
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--out")
    a = ap.parse_args()
    board = measure.Board()
    out = open(a.out, "a") if a.out else None
    for i in range(a.runs):
        r = one(board, a.arm, a.rc, a.seconds)
        r["run"] = i
        print(json.dumps(r))
        if out:
            out.write(json.dumps(r) + "\n")
            out.flush()


if __name__ == "__main__":
    main()
