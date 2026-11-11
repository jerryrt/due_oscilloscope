#!/usr/bin/env python3
"""Held-code noise on the cross-board path against the same-board paths.

    python3 tools/noise_cross_probe.py --rounds 6 --seconds 14 --out records/x.jsonl

Both Dues hold both DACs level (`=0J` sync off, `=3N` all-DC layout) from
the device's own table and capture at once, one subprocess per board. Arm X
is 2 channels at RC 86 (A0 and A1 of each board, preset M, so the generator
writes the DACs during the capture), arm P is 1 channel at RC 46 (A0 only;
the level is written by a 1 s preset M run first and then held). The first round is dropped by index. Per series: the rms
about the mean, the rms about a straight-line fit, and the Welch spectrum's
flatness. A diagnostic: it reads paths and decides nothing.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))

ARMS = (("X", 86, 2), ("P", 46, 1))
HEAD = 0.1          # as noisetool._drop_head
WINDOW = 4096


def worker(rc, channels, seconds, out):
    import array
    import measure
    import provenance
    b = measure.Board()
    measure.set_sync(b, "off")
    b.ask("=3N", secs=0.5)
    measure.set_gen(b, "dc", 2)
    time.sleep(0.3)
    hz = measure.hz_for(rc)
    assert measure.rc_for(hz) == rc
    if channels == 2:
        # preset M runs the generator, so the DACs are written
        preset = "=%d,%dM" % (hz, hz)
    else:
        # 1 channel is below the 2-channel RC floor, so M is refused: write
        # the level with a short M run at RC 86, which leaves it held
        h86 = measure.hz_for(86)
        measure.run_capture(b, preset="=%d,%dM" % (h86, h86), seconds=1.0)
        preset = "=%d,1a" % hz
    res = measure.run_capture(b, preset=preset, seconds=seconds)
    ps = res.stream
    meta = {"rc": rc, "hz": hz, "channels": channels,
            "declared_hz": ps.declared_rate_hz,
            "ident": b.ask("v", secs=1.0).strip()}
    meta.update(provenance.run_fields(board=b))
    for name, ch in (("a0", measure.CH_A0), ("a1", measure.CH_A1)):
        v = ps.series.get(ch) or []
        if name == "a1" and channels < 2:
            continue
        array.array("H", [int(x) for x in v]).tofile(
            open(out + "." + name, "wb"))
        meta["n_" + name] = len(v)
    b.ask("=0N", secs=0.5)
    with open(out + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f)


def stats(path, fs):
    v = np.fromfile(path, dtype=np.uint16).astype(np.float64)
    v = v[int(len(v) * HEAD):]
    t = np.arange(len(v), dtype=np.float64)
    mean = float(v.mean())
    rms = float(v.std())
    slope, icpt = np.polyfit(t, v, 1)
    rms_dt = float((v - (slope * t + icpt)).std())
    nw = len(v) // WINDOW
    seg = (v[:nw * WINDOW] - mean).reshape(nw, WINDOW) * np.hanning(WINDOW)
    psd = (np.abs(np.fft.rfft(seg, axis=1)) ** 2).mean(axis=0)[1:]
    flat = float(np.exp(np.log(psd).mean()) / psd.mean())
    lo = float(psd[:max(1, len(psd) // 100)].mean() / np.median(psd))
    return {"n": len(v), "mean": mean, "rms": rms, "rms_detrended": rms_dt,
            "flatness": flat, "lowband_over_median": lo, "fs_hz": fs}


def run_arm(rc, channels, seconds, tmp, tag):
    procs = {}
    for dut in ("dut1", "dut2"):
        out = os.path.join(tmp, f"{tag}.{dut}")
        env = dict(os.environ, DUE_DUT=dut)
        procs[dut] = (out, subprocess.Popen(
            [sys.executable, __file__, "--worker", str(rc), str(channels),
             str(seconds), out], env=env))
    res = {}
    for dut, (out, p) in procs.items():
        if p.wait() != 0:
            raise SystemExit(f"{dut} worker failed in {tag}")
        meta = json.load(open(out + ".json", encoding="utf-8"))
        fs = meta["declared_hz"]
        res[dut] = {"meta": meta}
        for ch in ("a0", "a1")[:channels]:
            res[dut][ch] = stats(out + "." + ch, fs)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--worker", nargs=4, metavar=("RC", "CH", "SEC", "OUT"))
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--seconds", type=float, default=14.0)
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.worker:
        worker(int(a.worker[0]), int(a.worker[1]), float(a.worker[2]),
               a.worker[3])
        return
    rows = []
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
        for rnd in range(a.rounds):
            for name, rc, ch in ARMS:
                r = run_arm(rc, ch, a.seconds, tmp, f"r{rnd}{name}")
                rows.append({"round": rnd, "arm": name, "rc": rc,
                             "channels": ch, "seconds": a.seconds,
                             "dropped": rnd == 0, "result": r})
                print(rnd, name, {d: {c: round(r[d][c]["rms"], 3)
                                      for c in ("a0", "a1")[:ch]}
                                  for d in r}, flush=True)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")


if __name__ == "__main__":
    main()
