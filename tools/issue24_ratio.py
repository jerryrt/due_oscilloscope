#!/usr/bin/env python3
"""Is the comb of 21 counted in DAC updates, or is it a beat?

Every arm on issue #24 has held the DAC:ADC ratio fixed, because the
host-path fold assumes one captured sample per DAC update and a
different ratio breaks it. d1900f2 records that hole: the rate arm
scaled both clocks together, so a beat between the two timers - and
preset M's own comment calls them "two independent timers" - would have
survived it unchanged.

This moves the ratio. The instrument is pair_fold's trick applied to the
ramp: when a DAC level is held for two or more captured samples,
differencing WITHIN the hold cancels the waveform by construction, which
is the only reason the internal arm can read a staircase. One value per
DAC update comes out, and the fold is then over DAC updates whatever the
ratio is - so the comb's spacing is quoted in the same unit in every arm.

    adc 400k, dac 200k   ratio 2, each level held 2 samples
    adc 400k, dac 100k   ratio 4, each level held 4 samples

The ADC is identical in both, so only the DAC rate and the ratio move -
and 35ccd6a already showed the DAC rate alone does not move the spacing
at a fixed ratio. A change here is therefore the ratio's.

    .venv/bin/python tools/issue24_ratio.py -n 6
"""
import argparse
import collections
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure  # noqa: E402


def hold_fold(vals, hold, period):
    """One value per DAC update, with the held level differenced out.

    `hold` captured samples per DAC update. The first two samples of
    each group are differenced; the parity of the group boundary is
    chosen the way pair_fold chooses it, by whichever alignment gives
    the smaller median absolute difference, because a slice trimmed at a
    settle time lands anywhere in the group and the wrong alignment
    differences two DIFFERENT levels and reports the ramp step as noise.

    Returns (profile, spread, offset) or None.
    """
    # The LAST two samples of each held group, not the first two. The
    # DAC is still settling into the first sample after an update, and
    # differencing samples 0 and 1 measures that transient instead of
    # cancelling the level - which is what put 62-123 sites in a fold
    # that reads 1-10 at a ratio of 1.
    lag = hold - 2
    best = None
    for off in range(hold):
        d = [vals[i + lag] - vals[i + lag + 1]
             for i in range(off, len(vals) - hold - 1, hold)]
        if len(d) < 4 * period:
            continue
        spread = statistics.median([abs(x) for x in d])
        if best is None or spread < best[0]:
            best = (spread, off, d)
    if best is None:
        return None
    spread, off, d = best
    sums = [0.0] * period
    cnt = [0] * period
    for i, x in enumerate(d):
        sums[i % period] += x
        cnt[i % period] += 1
    if min(cnt) == 0:
        return None
    return [sums[b] / cnt[b] for b in range(period)], spread, off


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=6)
    ap.add_argument("-s", "--seconds", type=float, default=4.0)
    ap.add_argument("--adc-hz", type=int, default=400000)
    ap.add_argument("--dac-list", default="200000,100000",
                    help="DAC rates to interleave. adc_hz/dac gives the "
                         "hold, and must divide exactly")
    ap.add_argument("--step", type=int, default=measure.RAMP_STEP)
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    period = 4096 // args.step
    dacs = [int(x) for x in args.dac_list.split(",")]
    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        for i in range(1, args.runs + 1):
            dac = dacs[(i - 1) % len(dacs)]
            hold = args.adc_hz // dac
            res = measure.run_loop(board, dac_sps=dac, adc_hz=args.adc_hz,
                                   channels=2, ramp=args.step,
                                   seconds=args.seconds)
            ps = res.stream
            vals = ps.series.get(measure.CH_A0) or []
            start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
            got = hold_fold(list(vals[start:]), hold, period)
            if not got:
                print(f"run {i}: short capture", flush=True)
                continue
            prof, spread, off = got
            found, mad = measure.fold_sites(prof)
            bins = sorted(b for b, _v, _z in found)
            gaps = collections.Counter(bins[k + 1] - bins[k]
                                       for k in range(len(bins) - 1))
            row = {"run": i, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "bench": args.bench, "adc_hz": args.adc_hz,
                   "dac_sps": dac, "hold": hold, "ratio": hold,
                   "period": period, "mad": round(mad, 4),
                   "pair_spread": round(spread, 2),
                   "hold_ok": spread <= 4.0, "parity": off,
                   "n_sites": len(found),
                   "gaps": dict(gaps.most_common(5)),
                   "sites": [[b, round(v, 2)] for b, v, _z in found[:10]]}
            rows.append(row)
            print(f"run {i:2d} dac={dac} hold={hold}: sites "
                  f"{len(found):3d}  spread {spread:5.2f} "
                  f"hold_ok={row['hold_ok']}  gaps "
                  f"{dict(gaps.most_common(4))}", flush=True)
            board.stop()
            board.drain_console(0.3)
    finally:
        try:
            board.stop()
        finally:
            board.close()

    print("\nspacing by ratio, in DAC updates:")
    for dac in dacs:
        rs = [r for r in rows if r["dac_sps"] == dac and r["hold_ok"]]
        if not rs:
            print(f"  dac {dac}: no run passed hold_ok - the pairing did "
                  f"not cancel, so nothing here is readable")
            continue
        tot = collections.Counter()
        for r in rs:
            tot.update(r["gaps"])
        print(f"  dac {dac:7d}  hold {rs[0]['hold']}  n={len(rs)}  "
              f"gaps {dict(tot.most_common(5))}")
    # Do not print both conclusions and let the reader pick. The
    # instrument has to earn a verdict, and on this bench it did not:
    #
    #   hold 2  spread 2-3 codes, 196-199 sites out of 512 bins. The
    #           differencing is not cancelling - a held level should
    #           difference to noise, and 2-3 codes is a third of the
    #           ramp step. Unreadable.
    #   hold 4  spread 1.0, but still 62-123 sites scattered over 8-10
    #           residues mod 21, against 1-10 sites at ratio 1. Likely
    #           the DAC still settling into the first sample of each
    #           held group, which differencing samples 0 and 1 catches
    #           instead of cancelling.
    #
    # A gap histogram on a set that dense produces small gaps in
    # quantity, and reading "8 and 13, which sum to 21" off it is
    # pattern-matching on noise - I did exactly that for a minute.
    readable = []
    for dac in dacs:
        rs = [r for r in rows if r["dac_sps"] == dac and r["hold_ok"]]
        if not rs:
            continue
        med = statistics.median([r["n_sites"] for r in rs])
        sp = statistics.median([r["pair_spread"] for r in rs])
        ok = med <= 30 and sp <= 1.5
        print(f"  dac {dac}: median {med:.0f} sites, spread {sp:.1f}"
              f"  -> {'readable' if ok else 'NOT readable'}")
        if ok:
            readable.append(dac)
    if len(readable) < 2:
        print("\nNo verdict. The fold does not survive the ratio, which "
              "is what this tool exists to report rather than paper "
              "over. A clean version has to cancel the DAC's settling "
              "into the first sample of a held group, not just the "
              "level - differencing the LAST two samples of each group "
              "rather than the first two is the obvious thing to try.")
    else:
        print("\n  compare the gap histograms above: 21 at both ratios "
              "means counted in DAC updates; a spacing that follows the "
              "ratio means a beat between the timers.")
    if args.out:
        with open(args.out, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
