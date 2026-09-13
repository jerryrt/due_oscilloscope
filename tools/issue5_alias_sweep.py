#!/usr/bin/env python3
"""Issue #5: does the comb period follow the trigger RC as a 512-clock alias?

The claim under test, registered here before any row exists:

    The wrap displacement's comb is the alias of the DAC trigger against a
    periodic event of 512 DACC clocks (MCK/2). A DAC0 bin b is a site when
    (2*RC*b) mod 512 lands in a ~20-clock window. The comb's dominant gap
    is therefore the smallest b for which 2*RC*b returns near 0 mod 512 -
    21 at RC 195 because 390*21 = 8190 = 16*512 - 2 - and it CHANGES with
    RC in a way computed from RC alone.

Predictions, from `predict()` below, none of which the rival readings
share ("the lattice is a count of 21", which is the campaign's settled
reading; or "round(4096/RC)"):

    =200000,200000M  RC 195 -> 21   (positive control; the campaign's comb)
    =209677,209677M  RC 186 -> 11
    =197970,197970M  RC 196 -> 17
    =205263,205263M  RC 190 -> 31
    =203125,203125M  RC 192 -> 4, OR no comb at all (only 4 phases exist,
                                 a window catches at most one)

Refutation: a dominant gap of 21 at any RC other than 195. Scored by the
same instrument the campaign used - pair_fold at GEN_TABLE_LEN, sites as
|dev| above a code threshold - and also by position: with the window
fixed at the campaign's width and only its rotation fitted, the fraction
of observed sites the model places.

Registered caveat: the window's WIDTH is the DAC-start-to-ADC-start gap
modulo RC, so a different RC may land a narrow or absent window, exactly
as FWS 4/5 do at RC 195. Each preset therefore runs at FWS 6, 5 and 4. A
comb absent at all three, with RC 195 firing in the same session, is a
null on the margin and not a refutation of the period; a 21-comb is.

    sg dialout -c '.venv/bin/python tools/issue5_alias_sweep.py --bench linux-x1'
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
import measure      # noqa: E402
import provenance   # noqa: E402

P = 512                  # DACC clocks; registered
WINDOW = (-18, 2)        # the campaign's fitted width, registered
SITE_CODES = 4.0         # |dev| threshold for a site, in codes
PRESETS = [200000, 209677, 197970, 205263, 203125]
DEFAULT_FWS = "6,5,4"


def rc_of(hz):
    return 39_000_000 // hz     # exactly what gen_prepare_tioa1 / acq_start do


def signed(p):
    return p - P if p > P // 2 else p


def predict(RC, window=WINDOW):
    """Predicted DAC0-bin sites (phi=0) and dominant gap, from RC alone."""
    lo, hi = window
    sites = [b for b in range(256) if lo <= signed((2 * RC * b) % P) <= hi]
    if len(sites) < 3:
        return sites, None
    g = collections.Counter(y - x for x, y in zip(sites, sites[1:]))
    return sites, g.most_common(1)[0][0]


def fit_rotation(obs, RC, window=WINDOW):
    """Fix the window, fit only its rotation; return (hits, extras, phi)."""
    lo, hi = window
    obs = set(obs)
    best_sc, best = None, (0, 0, 0)
    for phi in range(P):
        m = {b for b in range(256) if lo <= signed((2 * RC * b + phi) % P) <= hi}
        sc = len(m & obs) - len(m - obs)
        if best_sc is None or sc > best_sc:
            best_sc, best = sc, (len(m & obs), len(m - obs), phi)
    return best


def read_profile(prof):
    med = statistics.median(prof)
    dev = [v - med for v in prof]
    sites = [b for b, d in enumerate(dev) if abs(d) > SITE_CODES]
    gaps = collections.Counter(y - x for x, y in zip(sites, sites[1:]))
    dom = gaps.most_common(1)[0][0] if len(sites) >= 3 else None
    return dev, sites, gaps, dom


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "linux-x1"))
    ap.add_argument("--presets", default=",".join(map(str, PRESETS)))
    ap.add_argument("--fws", default=DEFAULT_FWS)
    ap.add_argument("--k", default="0", help="M's start gap =<us>K, per block")
    ap.add_argument("-n", "--runs", type=int, default=7,
                    help="per (preset, fws, k); run 1 is stored flagged, "
                         "excluded from the verdict by index")
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--probes", default="none")
    ap.add_argument("--jumpers", default="copper, ~10 cm, gauge undeclared")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    presets = [int(x) for x in args.presets.split(",")]
    fws_list = [int(x) for x in args.fws.split(",")]
    k_list = [int(x) for x in args.k.split(",")]
    out = args.out or os.path.join(
        ROOT, "records", f"issue5-alias-sweep-{args.bench}.jsonl")

    print("REGISTERED PREDICTIONS (P=512, window %s):" % (WINDOW,))
    for hz in presets:
        RC = rc_of(hz)
        sites, dom = predict(RC)
        print(f"  ={hz},{hz}M  RC {RC:3d}  -> dominant gap {dom}  "
              f"({len(sites)} sites/wrap at phi=0)")

    board = measure.Board(settle=3.0)
    verdicts = []
    try:
        board.stop()
        board.drain_console(0.5)
        prov = provenance.run_fields(board)
        print("provenance: " + ", ".join(f"{k}={v}" for k, v in prov.items()),
              flush=True)
        for hz in presets:
            RC = rc_of(hz)
            preset = f"={hz},{hz}M"
            _, pred = predict(RC)
            for fws in fws_list:
                board.cmd(f"={fws}q")
                txt = board.drain_console(0.5) or ""
                if f"fws: {fws}" not in txt:
                    raise SystemExit(f"FWS readback {txt.strip()[:60]!r}, "
                                     f"asked for {fws}")
                for k in k_list:
                    board.cmd(f"={k}K")
                    txt = board.drain_console(0.5) or ""
                    if f"mimic start delay: {k} us" not in txt:
                        raise SystemExit(f"K readback {txt.strip()[:60]!r}, "
                                         f"asked for {k}")
                    doms = []
                    for i in range(1, args.runs + 1):
                        res = measure.run_capture(board, preset=preset,
                                                  seconds=args.seconds)
                        ps = res.stream
                        vals = ps.series.get(measure.CH_A0)
                        if not vals:
                            print(f"  {preset} f{fws} k{k} run {i}: no samples")
                            continue
                        start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
                        fold = measure.pair_fold(list(vals[start:]))
                        prof = fold.get("profile") or []
                        if not prof:
                            continue
                        dev, sites, gaps, dom = read_profile(prof)
                        hits, extra, phi = fit_rotation(sites, RC)
                        total_abs = round(sum(abs(d) for d in dev), 2)
                        row = {"run": i, "run1": i == 1,
                               "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                               "bench": args.bench, **prov,
                               "probes": args.probes, "jumpers": args.jumpers,
                               "preset": preset, "hz": hz, "rc": RC,
                               "fws": fws, "k_us": k,
                               "hold_ok": bool(fold.get("hold_ok")),
                               "total_abs": total_abs,
                               "n_sites": len(sites), "sites": sites,
                               "gaps": dict(gaps), "dominant_gap": dom,
                               "predicted_gap": pred,
                               "fit_hits": hits, "fit_extras": extra,
                               "fit_phi": phi,
                               "profile": [round(v, 3) for v in prof]}
                        with open(out, "a") as f:
                            f.write(json.dumps(row) + "\n")
                        if i > 1:
                            doms.append(dom)
                        print(f"  {preset} f{fws} k{k} run {i}: hold_ok="
                              f"{row['hold_ok']} total_abs={total_abs:7.1f} "
                              f"sites={len(sites):2d} dom_gap={dom} "
                              f"(pred {pred}) fit {hits}/{len(sites)} "
                              f"extras {extra} phi {phi}  gaps="
                              f"{dict(gaps.most_common(3))}", flush=True)
                    c = collections.Counter(d for d in doms if d is not None)
                    mode = c.most_common(1)[0][0] if c else None
                    verdicts.append((preset, RC, fws, k, pred, mode,
                                     len(doms) - sum(c.values()), dict(c)))
    finally:
        try:
            board.cmd("=4q")
            board.cmd("=0K")
            board.stop()
        finally:
            board.close()

    print("\nVERDICTS (run 1 excluded):")
    print("preset            RC  fws k  predicted  observed-mode  no-comb  census")
    for preset, RC, fws, k, pred, mode, none, c in verdicts:
        tag = ("REFUTED" if mode == 21 and RC != 195
               else "confirmed" if mode == pred
               else "null" if mode is None
               else "MISMATCH")
        print(f"{preset:17s} {RC:3d}  {fws}   {k}   {str(pred):>8}   "
              f"{str(mode):>12}   {none:5d}   {c}  {tag}")
    print(f"\nrows -> {out}")


if __name__ == "__main__":
    main()
