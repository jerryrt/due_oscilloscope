#!/usr/bin/env python3
"""Where are #5's sites in the *table*, not in the fold?

`fold_profile` and `pair_fold` number their bins from wherever the
capture happened to start, so bin 0 is an arbitrary rotation of the
generator's table. Every site position this issue has ever published -
{138, 198, 219} here, {96, 117, 156, 177} on windows-desk, {107, 188,
209} for Track A - is a bin number in that arbitrary frame.

That matters because the strongest conclusion on the issue is built out
of two such numbers. `dfca78d` reads:

    board held, firmware varied  -> same positions, to a constant offset
    firmware held, board varied  -> different positions

and concludes the positions belong to the board. But the first row is
*itself* the rotation moving: Track A and Track B were ten bins apart on
one board, so the frame is known to shift between images. A cross-board
comparison of bin numbers cannot then separate "different sites" from
"same sites, different rotation" - and under a rotation of +21 the two
benches' site sets coincide exactly, both sitting on the same two
residue classes mod 21.

So this measures the rotation instead of assuming it away.

**The reference is the waveform itself**, which costs no wiring and
works on any bench: `shape_code` builds the sine as
`2048 + sin(2*pi*i/period)`, so table index 0 is the rising crossing of
mid-scale and index period/4 is the peak. Folding the *level* series -
the mean of each held DAC pair, which is the same pairing `pair_fold`
differences within - recovers that sine, and its rising crossing is
table index 0.

Preset M's sync is DC, so DAC1 carries no marker; A0 is the reference.

Attestation, printed every run and checked rather than assumed: after
alignment the folded sine must peak near index 64 and trough near 192.
If it does not, the rotation is wrong and **the absolute numbers on that
run must not be used** - `align_ok` says so per run.

    .venv/bin/python tools/issue5_absphase.py -n 12
"""
import argparse
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure  # noqa: E402

POINTS = measure.GEN_TABLE_LEN // 2          # DAC0 points in one table


def _pair(vals):
    """Split the run into held DAC levels, the way pair_fold does.

    Returns (offset, diffs, levels). The parity is chosen by the same
    rule - whichever pairing gives the smaller median |difference| -
    because the two readings must share a frame or the site bins and the
    sine cannot be compared at all. Differencing within the pair cancels
    the staircase and leaves the artifact; averaging within it recovers
    the DAC level the pair was holding.
    """
    best = None
    for off in (0, 1):
        d = [vals[i] - vals[i + 1] for i in range(off, len(vals) - 1, 2)]
        if not d:
            continue
        spread = statistics.median([abs(x) for x in d])
        if best is None or spread < best[0]:
            lv = [(vals[i] + vals[i + 1]) / 2.0
                  for i in range(off, len(vals) - 1, 2)]
            best = (spread, off, d, lv)
    return best


def _fold(series, period):
    sums = [0.0] * period
    cnt = [0] * period
    for i, x in enumerate(series):
        sums[i % period] += x
        cnt[i % period] += 1
    if min(cnt) == 0:
        return None
    return [sums[b] / cnt[b] for b in range(period)]


def table_zero(levels_profile):
    """Table index 0: the sine's rising crossing of its own centre.

    Interpolated between the two bins that straddle the crossing, then
    reported as the integer bin nearest it, because a site is a bin and
    a fraction of one is not a thing this can use. Returns
    (phase0, amplitude, peak_bin, trough_bin).
    """
    p = len(levels_profile)
    centre = (max(levels_profile) + min(levels_profile)) / 2.0
    amp = (max(levels_profile) - min(levels_profile)) / 2.0
    best = None
    for b in range(p):
        a, c = levels_profile[b], levels_profile[(b + 1) % p]
        if a <= centre < c:                    # rising crossing
            frac = (centre - a) / (c - a) if c != a else 0.0
            # Prefer the steepest rising crossing: noise can make a
            # flat stretch cross several times, and the sine crosses
            # its centre exactly twice.
            if best is None or (c - a) > best[0]:
                best = (c - a, (b + frac) % p)
    if best is None:
        return None
    phase0 = int(round(best[1])) % p
    peak = max(range(p), key=lambda b: levels_profile[b])
    trough = min(range(p), key=lambda b: levels_profile[b])
    return phase0, amp, peak, trough


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=12)
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        for i in range(1, args.runs + 1):
            res = measure.run_capture(board, preset="M", seconds=args.seconds)
            ps = res.stream
            vals = ps.series.get(measure.CH_A0) or []
            start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
            tail = list(vals[start:])
            got = _pair(tail)
            if not got or len(tail) < 8 * POINTS:
                print(f"run {i}: no samples", flush=True)
                continue
            spread, off, diffs, levels = got
            dprof = _fold(diffs, POINTS)
            lprof = _fold(levels, POINTS)
            if dprof is None or lprof is None:
                print(f"run {i}: short fold", flush=True)
                continue
            found, mad = measure.fold_sites(dprof)
            z = table_zero(lprof)
            if z is None:
                print(f"run {i}: no crossing", flush=True)
                continue
            phase0, amp, peak, trough = z
            # The check that makes the rotation a measurement rather
            # than a hope: a sine aligned at 0 peaks a quarter later.
            dpeak = ((peak - phase0) % POINTS - POINTS // 4)
            dtrough = ((trough - phase0) % POINTS - 3 * POINTS // 4)
            align_ok = (abs(dpeak) <= POINTS // 32
                        and abs(dtrough) <= POINTS // 32
                        and amp > 200.0)
            abs_sites = [[(b - phase0) % POINTS, round(v, 2), round(zz, 1)]
                         for b, v, zz in found[:8]]
            row = {"run": i, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "bench": args.bench, "parity": off,
                   "pair_spread": round(spread, 2),
                   "hold_ok": spread <= 4.0,
                   "phase0": phase0, "sine_amp_codes": round(amp, 1),
                   "peak_bin": peak, "trough_bin": trough,
                   "peak_err": dpeak, "trough_err": dtrough,
                   "align_ok": align_ok,
                   "mad": round(mad, 4),
                   "sites_bin": [[b, round(v, 2)] for b, v, _ in found[:8]],
                   "sites_table": abs_sites}
            rows.append(row)
            print(f"run {i:2d}: phase0={phase0:3d} amp={amp:6.1f} "
                  f"align_ok={str(align_ok):5s} (peak err {dpeak:+3d}, "
                  f"trough err {dtrough:+3d})  hold_ok={row['hold_ok']}\n"
                  f"        bin   " +
                  ", ".join(f"{b}:{v:+.2f}" for b, v, _ in found[:5]) +
                  "\n        table " +
                  ", ".join(f"{b}:{v:+.2f}" for b, v, _ in abs_sites[:5]),
                  flush=True)
            board.stop()
            board.drain_console(0.3)
    finally:
        try:
            board.stop()
        finally:
            board.close()

    good = [r for r in rows if r["align_ok"]]
    print(f"\n{len(good)} of {len(rows)} runs aligned")
    if good:
        p0 = [r["phase0"] for r in good]
        print(f"phase0 across runs: {min(p0)} .. {max(p0)}  "
              f"(a moving rotation makes the absolute reading the only "
              f"comparable one)")
        seen = sorted({b for r in good for b, _v, _z in r["sites_table"]})
        print("\ntable index   present   values            mod 21")
        for b in seen:
            vs = [v for r in good for bb, v, _z in r["sites_table"]
                  if bb == b]
            if len(vs) < max(2, len(good) // 4):
                continue
            print(f"  {b:3d}         {len(vs):2d}/{len(good)}   "
                  f"{min(vs):+7.2f} .. {max(vs):+7.2f}   {b % 21:2d}")
    if args.json:
        with open(args.json, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"\nwrote {len(rows)} rows to {args.json}")


if __name__ == "__main__":
    main()
