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


def table_zero_dft(levels_profile):
    """Table index 0 from the whole profile, not from one crossing.

    The crossing estimate below uses two bins, and this waveform gives
    it a reason to be wrong: the DAC is not rail-to-rail, the sine's
    trough is asked for at code 23, and a compressed trough raises
    `(max+min)/2` and drags the crossing with it. The attestation
    catches it - Track B's trough landed 5 bins from where an aligned
    sine puts it while Track A's landed on 0 - which is the attestation
    doing its job and also a warning not to trust the number it passed.

    The fundamental is estimated over all 256 bins instead. Clipping at
    one extreme still biases it, but by far less than it biases a single
    crossing, and the two estimates disagreeing is itself the signal
    that the profile is not a clean sine.

    `level[i] = C + A*sin(2*pi*(i - phase0)/N)`, so phase0 comes
    straight from the argument of the k=1 bin.
    """
    import cmath
    n = len(levels_profile)
    x = sum(levels_profile[i] * cmath.exp(-2j * cmath.pi * i / n)
            for i in range(n))
    # sin(2*pi*(i-p)/N) has k=1 argument -(pi/2) - 2*pi*p/N.
    p = (-cmath.phase(x) - cmath.pi / 2.0) * n / (2.0 * cmath.pi)
    return int(round(p)) % n, 2.0 * abs(x) / n


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


def align_ok_pre(peak, trough, phase0, n):
    """Is this single-cycle run aligned well enough to carry forward?"""
    return (abs((peak - phase0) % n - n // 4) <= n // 32
            and abs((trough - phase0) % n - 3 * n // 4) <= n // 32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=12)
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--points-plan", default="",
                    help="generator resolution per block, e.g. "
                         "256x3,128x6,256x3 - the wrap-versus-waveform "
                         "discriminator. At 128 the table holds two "
                         "sine cycles inside one 256-entry PDC wrap, so "
                         "a wrap-locked site keeps its entry and a "
                         "waveform-locked one appears at i and i+128. "
                         "Bracket it with 256 blocks: the rotation is "
                         "only measurable from a single-cycle table and "
                         "is carried into the 128 block from the "
                         "bracket either side of it")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    pplan = []
    if args.points_plan:
        for part in args.points_plan.split(","):
            a, n = part.lower().split("x")
            pplan.extend([int(a)] * int(n))

    board = measure.Board(settle=3.0)
    rows = []
    carried = None
    try:
        board.stop()
        board.drain_console(0.5)
        runs = max(args.runs, len(pplan))
        for i in range(1, runs + 1):
            pts = pplan[i - 1] if i <= len(pplan) else None
            if pts is not None and (i == 1 or pplan[i - 2] != pts):
                measure.set_gen(board, "sine", points=pts,
                                amp=measure.GEN_AMP_FULL)
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
            phase0_x, amp, peak, trough = z
            phase0, amp_f = table_zero_dft(lprof)
            # A multi-cycle table has no k=1 fundamental, so the
            # rotation is not measurable from it. Carry the bracket's
            # instead, and say so in the row rather than letting a
            # carried number read like a measured one.
            src = "measured"
            if pts is not None and pts != POINTS:
                src = "carried"
                if carried is None:
                    print(f"run {i}: no bracket - run a {POINTS}-point "
                          f"block first", flush=True)
                    continue
                phase0, phase0_x = carried, carried
            elif align_ok_pre(peak, trough, phase0, POINTS):
                carried = phase0
            # The two estimates must agree, or the profile is not the
            # sine this reads it as and neither number is usable.
            dphase = ((phase0 - phase0_x + POINTS // 2) % POINTS
                      - POINTS // 2)
            # The check that makes the rotation a measurement rather
            # than a hope: a sine aligned at 0 peaks a quarter later.
            dpeak = ((peak - phase0) % POINTS - POINTS // 4)
            dtrough = ((trough - phase0) % POINTS - 3 * POINTS // 4)
            # A two-cycle table peaks twice, so the quarter-period
            # attestation is a single-cycle test and does not apply.
            align_ok = (abs(dphase) <= 2 and amp > 200.0
                        and (src == "carried"
                             or (abs(dpeak) <= POINTS // 32
                                 and abs(dtrough) <= POINTS // 32)))
            abs_sites = [[(b - phase0) % POINTS, round(v, 2), round(zz, 1)]
                         for b, v, zz in found[:8]]
            row = {"run": i, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "bench": args.bench, "parity": off,
                   "points": pts or POINTS, "phase0_source": src,
                   "pair_spread": round(spread, 2),
                   "hold_ok": spread <= 4.0,
                   "phase0": phase0, "phase0_crossing": phase0_x,
                   "phase0_disagree": dphase,
                   "fundamental_codes": round(amp_f, 1),
                   "sine_amp_codes": round(amp, 1),
                   "peak_bin": peak, "trough_bin": trough,
                   "peak_err": dpeak, "trough_err": dtrough,
                   "align_ok": align_ok,
                   "mad": round(mad, 4),
                   "sites_bin": [[b, round(v, 2)] for b, v, _ in found[:8]],
                   "sites_table": abs_sites,
                   "level_profile": [round(v, 2) for v in lprof]}
            rows.append(row)
            print(f"run {i:2d}: phase0={phase0:3d} (crossing {phase0_x:3d}, "
                  f"d={dphase:+d}) amp={amp:6.1f} "
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
            # Leave the generator where every other instrument on this
            # issue expects to find it. A tool that changes resolution
            # and exits is a tool that silently reconfigures the next
            # person's baseline.
            if pplan:
                measure.set_gen(board, "sine",
                                points=measure.GEN_TABLE_POINTS,
                                amp=measure.GEN_AMP_FULL)
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
