#!/usr/bin/env python3
"""Does the comb of 21 land on DAC1 as well, or only on DAC0?

There is a degeneracy in how the lattice has been quoted, and it is
mine. a68e774 concluded the period is 21 *DAC0 output changes* rather
than 21 converter conversions, from the two arms disagreeing about what
a bin is: gen NORMAL gives one DAC0 level per two DACC conversions,
build_ramp gives one per one, and both read 21.

**That inference does not hold, because 21 is odd.** A period of 21
DACC conversions puts events at DAC0-level indices 0, 10.5, 21, 31.5,
42 ... - and the half-integers are DAC1 conversions, which an A0 fold
cannot see. What survives into a DAC0 fold is 0, 21, 42: a comb of 21,
exactly what 21 DAC0 writes predicts. The two hypotheses are
indistinguishable in A0 for any odd period.

A1 separates them, and on this bench the wiring is already there -
DAC1 goes to A1, and preset M drives DAC1 with a fixed level, so A1 is
a flat channel and a flat channel is the best detector this issue has.

    comb on A1  -> the period counts DACC conversions, both channels
    A1 clean    -> it is DAC0's own output stage

Same instrument as A0, one channel over: DAC1 is held for two A1
samples exactly as DAC0 is held for two A0 samples, so pair_fold's
differencing cancels the hold and leaves a one-sample artifact at full
height.

The A0 arm is folded in the same capture, so "A1 is clean" is only
reported against a capture where A0 is not - an absence measured while
the thing is absent everywhere is not evidence.

    .venv/bin/python tools/issue5_a1.py -n 12
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
sys.path.insert(0, os.path.join(ROOT, "tools"))
from issue5_absphase import _fold, _pair, table_zero_dft  # noqa: E402


def comb_gaps(bins):
    return collections.Counter(bins[i + 1] - bins[i]
                               for i in range(len(bins) - 1))


def rotation(vals, start):
    """Table index 0, from A0's own waveform.

    Without this every site here is a bin in a frame whose zero is the
    capture start, and comparing bins across two configurations is the
    error retracted in dfbb34f - the frame moves between images, and it
    moves between channel counts for the same reason. A0 carries the
    sine, so it carries the reference; see tools/issue5_absphase.py.

    The one residue is parity: pair_fold picks the pairing per channel,
    so A1's frame can sit one bin from A0's. One bin, and it is recorded
    rather than corrected.
    """
    got = _pair(list(vals[start:]))
    if not got:
        return None, 0.0
    _spread, _off, _d, levels = got
    prof = _fold(levels, measure.GEN_TABLE_LEN // 2)
    if prof is None:
        return None, 0.0
    return table_zero_dft(prof)


def read(vals, start):
    tail = list(vals[start:])
    if len(tail) < 8 * measure.GEN_TABLE_LEN:
        return None
    f = measure.pair_fold(tail)
    prof = f.get("profile") or []
    found, mad = measure.fold_sites(prof)
    bins = sorted(b for b, _v, _z in found)
    # Threshold-free, because the site SET redraws every capture and a
    # count of sites is a count of whatever cleared z this time. The
    # total absolute deviation over the whole folded profile does not
    # care which sites drew, only how much displacement there is, and it
    # is the statistic two arms can actually be compared on.
    pmed = statistics.median(prof) if prof else 0.0
    total_abs = sum(abs(v - pmed) for v in prof)
    return {"total_abs": round(total_abs, 2),
            "sites": [[b, round(v, 2), round(z, 1)] for b, v, z in found[:8]],
            "n_sites": len(found), "bins": bins,
            "gaps21": comb_gaps(bins).get(21, 0),
            "hold_ok": bool(f.get("hold_ok")),
            "pair_spread": round(f.get("pair_spread", 0.0), 2),
            "mad": round(mad, 4),
            "flat_sd": round(statistics.pstdev(tail[:20000]), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=12)
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--amp-alt", default="",
                    help="alternate DAC0 amplitudes run by run, e.g. "
                         "256,64. This is the clean crosstalk arm: if "
                         "A1's displacement is A0's swing carried "
                         "through an unsettled sample-and-hold, it must "
                         "scale with A0's amplitude. Channel count, both "
                         "rates and the whole ADC load are identical "
                         "between the arms, which is exactly what the "
                         "channel-count arm could not manage. "
                         "Interleaved, because the configuration redraws "
                         "every capture")
    ap.add_argument("--nch-alt", action="store_true",
                    help="alternate 2 and 3 channels run by run. "
                         "Interleaved rather than blocked because this "
                         "configuration drifts on tens-of-minutes "
                         "scales, and sequential blocks cannot separate "
                         "an arm effect from the weather - which has "
                         "killed two false asymmetries on this project "
                         "already")
    ap.add_argument("--nch", type=int, default=2,
                    help="ADC channels in preset M. The sequencer "
                         "converts in channel-index order, so 2 gives "
                         "A1 then A0 - A1 immediately after A0 - and 3 "
                         "gives A2, A1, A0, which puts the bare pin "
                         "between them and takes A0 out of A1's "
                         "predecessor slot. That is the arm separating "
                         "a DAC artifact on A1 from ADC multiplexer "
                         "crosstalk out of A0's sample-and-hold")
    ap.add_argument("--sync", default=None,
                    help="gen sync mode for the run, restored on exit. "
                         "'off' puts DC on DAC1, which makes A1 the flat "
                         "channel flat_census's docstring assumed it "
                         "already was - and a flat channel's MAD is a "
                         "fraction of a square's, which is what buys the "
                         "detection margin the comb question needs "
                         "without 110-second captures")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        if args.sync is not None:
            print(measure.set_sync(board, args.sync).strip(), flush=True)
        for i in range(1, args.runs + 1):
            if args.nch_alt:
                args.nch = 2 if (i % 2) else 3
            amp = None
            if args.amp_alt:
                amps = [int(x) for x in args.amp_alt.split(",")]
                amp = amps[(i - 1) % len(amps)]
                measure.set_gen(board, "sine",
                                points=measure.GEN_TABLE_POINTS, amp=amp)
            preset = ("M" if args.nch == 2
                      else f"=200000,200000,{args.nch}M")
            res = measure.run_capture(board, preset=preset,
                                      seconds=args.seconds)
            ps = res.stream
            out = {}
            a0v = ps.series.get(measure.CH_A0) or []
            phase0, fund = rotation(
                a0v, ps._index_at(measure.CH_A0, measure.SETTLE_US)) \
                if a0v else (None, 0.0)
            chans = [("a0", measure.CH_A0), ("a1", measure.CH_A1)]
            if args.nch >= 3:
                chans.append(("a2", measure.CH_A2))
            for name, tag in chans:
                vals = ps.series.get(tag) or []
                if not vals:
                    continue
                out[name] = read(vals, ps._index_at(tag, measure.SETTLE_US))
            if "a0" not in out or "a1" not in out or not all(out.values()):
                print(f"run {i}: short capture", flush=True)
                continue
            row = {"run": i, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "bench": args.bench, "nch": args.nch,
                   "sync": args.sync, "amp": amp, "phase0": phase0,
                   "fundamental_codes": round(fund, 1),
                   "a0": out["a0"], "a1": out["a1"]}
            if "a2" in out:
                row["a2"] = out["a2"]
            rows.append(row)
            P = measure.GEN_TABLE_LEN // 2
            for name, _t in chans:
                r = out[name]
                if phase0 is not None:
                    r["sites_table"] = [[(b - phase0) % P, v, z]
                                        for b, v, z in r["sites"]]
                tab = r.get("sites_table") or r["sites"]
                print(f"run {i:2d} {name.upper()}: sites {r['n_sites']:3d}  "
                      f"gaps21 {r['gaps21']:3d}  sd {r['flat_sd']:7.1f}  "
                      f"hold_ok={r['hold_ok']}  p0={phase0}  table "
                      + ", ".join(f"{b}:{v:+.2f}"
                                  for b, v, _ in tab[:4]), flush=True)
            board.stop()
            board.drain_console(0.3)
    finally:
        try:
            # Put the sync back. Every other instrument on this issue
            # assumes the default, and a tool that changes it and exits
            # reconfigures the next person's baseline silently.
            if args.sync is not None:
                measure.set_sync(board, "cycle")
            if args.amp_alt:
                measure.set_gen(board, "sine",
                                points=measure.GEN_TABLE_POINTS,
                                amp=measure.GEN_AMP_FULL)
            board.stop()
        finally:
            board.close()

    on = [r for r in rows if r["a0"]["gaps21"] >= 3]
    print(f"\n{len(rows)} runs; A0 comb on in {len(on)}")
    if on:
        print("captures where A0 carries the comb - the only ones where "
              "A1's answer means anything:")
        for r in on:
            print(f"  run {r['run']:2d}  A0 gaps21 {r['a0']['gaps21']:3d} "
                  f"sites {r['a0']['n_sites']:3d}   ||   "
                  f"A1 gaps21 {r['a1']['gaps21']:3d} "
                  f"sites {r['a1']['n_sites']:3d}")
        tot0 = sum(r["a0"]["gaps21"] for r in on)
        tot1 = sum(r["a1"]["gaps21"] for r in on)
        print(f"\ngaps of 21, summed over those captures: "
              f"A0 {tot0}, A1 {tot1}")

        # The power check, before the conclusion and gating it.
        #
        # A1 reads a full-scale square and A0 a sine, and the two do not
        # have the same noise floor - A1's MAD runs about 1.8x A0's. The
        # comb's sites are about 1 code. If 6*MAD on A1 is above that,
        # A1 CANNOT SEE a comb of the same size and its silence means
        # nothing, which is the trap this issue has fallen into twice.
        comb = [abs(v) for r in on for _b, v, _z in r["a0"]["sites"]
                if abs(v) < 3.0]
        floor1 = measure.FOLD_Z_DIRTY * statistics.median(
            [r["a1"]["mad"] for r in on])
        floor0 = measure.FOLD_Z_DIRTY * statistics.median(
            [r["a0"]["mad"] for r in on])
        smallest = min(comb) if comb else 0.0
        typical = statistics.median(comb) if comb else 0.0
        print(f"\ndetection floor at z={measure.FOLD_Z_DIRTY}: "
              f"A0 {floor0:.2f} codes, A1 {floor1:.2f} codes")
        print(f"A0 comb sites: {smallest:.2f} smallest, "
              f"{typical:.2f} typical")
        # A margin, not a bare comparison. A comb 6% above the floor is
        # detectable in principle and not in practice, and "A1 could
        # have seen it" read off a 6% margin is the same mistake as
        # reading a null from a test with no power - one step further
        # down the same path. Two-to-one or it does not count.
        if typical < 2.0 * floor1:
            need = max(6, int(args.seconds * (2.0 * floor1 / typical) ** 2
                              + 0.5)) if typical else 0
            print("\nINCONCLUSIVE. A1's floor is not far enough below "
                  "the comb for its silence to be evidence. The floor "
                  f"falls as 1/sqrt(wraps), so -s {need} would give the "
                  "2:1 margin this asks for.")
        else:
            # The floor is not the only way to be blind. A1 draws its
            # OWN comb, gated per capture like A0's, so "A1 was silent
            # in the captures where A0 drew" is a statement about A1's
            # draw and not about whether A1 can carry one. Measured over
            # 46 sync-off captures: A0 draws in 8, A1 in 16, and the two
            # co-occur 2 times against 2.8 expected under independence.
            #
            # This tool concluded the opposite from three captures, and
            # the mistake was reading an absence without asking how
            # often the thing is present at all. So the verdict is over
            # ALL captures now, per channel, and it says so.
            a0n = sum(1 for r in rows if r["a0"]["gaps21"] >= 3)
            a1n = sum(1 for r in rows if r["a1"]["gaps21"] >= 3)
            print(f"\ncombs drawn over all {len(rows)} captures: "
                  f"A0 {a0n}, A1 {a1n}")
            if a1n == 0 and a0n >= 5:
                print("A1 never draws one while A0 does: the comb is "
                      "DAC0's.")
            elif a1n:
                print("BOTH channels draw combs. The period is not "
                      "DAC0-specific - it is each channel's own "
                      "updates, gated independently.")
            else:
                print("too few draws either way; run more captures.")
    else:
        print("A0 never drew the comb, so this run says nothing about A1. "
              "Run again - p(on) is about 0.2 per stream.")
    if args.json:
        with open(args.json, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"wrote {len(rows)} rows to {args.json}")


if __name__ == "__main__":
    main()
