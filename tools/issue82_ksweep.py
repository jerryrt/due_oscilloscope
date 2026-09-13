#!/usr/bin/env python3
"""DAC1's one-hold level errors against the ADC-start-to-DAC-start gap (#82).

`=<us>K` is the gap preset M leaves between starting the ADC and starting
the DAC. `h_mimic` busy-waits it on `micros()`, which interpolates SysTick
to 1 us, so a nonzero K starts the DAC K us later - 39 timer clocks a
step - plus up to about one more us of per-run spread, because SysTick's
phase is unrelated to the ADC timer's start. K = 0 takes no wait loop at
all and is a different instruction path, not the zero of the sweep. At
200 ksps a trigger is 5 us and DAC0/DAC1 alternate against A0/A1, so the
DAC1-versus-A1 alignment repeats every 10 us of K: K = 11 must read like
K = 1 if the effect is a phase.

A hold is the two ADC samples of one DAC level. Which two is settled by
the channel's own square edges where it has them - the new level's first
sample is the first sample of a hold, and every edge must agree - and by
the smaller median within-pair difference where it has none, which a
flat channel ties and is then refused. The parity used and the edge
counts are recorded on every row; a capture whose edges disagree is
recorded with no rate.

A hold's level error is the second difference of hold levels, which a
moving sine barely touches and noise touches at about 1.2 codes sd. The
reading is errors beyond 6 and 10 codes per 1000 holds - per hold, not
per second, so it does not depend on the rate - on A1 (the DAC1
population) and A0 (the DAC0 population) apart. Holds within three of a
square edge are excluded.

The arm, registered on #82 before any row: K values at FWS 4, plus one
FWS 6 K = 0 capture per round as the positive control, every round in a
fresh order, round 1 kept in the record and dropped from the summary by
index. Rows: records/issue82-ksweep-<bench>[-<tag>].jsonl, never
overwritten.

    .venv/Scripts/python.exe tools/issue82_ksweep.py --selftest
    .venv/Scripts/python.exe tools/issue82_ksweep.py --ks 0,1,5,10,11 --tag edges
"""
import argparse
import json
import math
import os
import random
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))

BASE = ["=0N", "=1J", "=2,1I"]
THRESH = (6, 10)
EDGE_CODES = 1000
EDGE_GUARD = 3
EDGE_JUMP = 2000
MIN_EDGES = 8
TIE_CODES = 2.0


class ParityError(ValueError):
    pass


def edge_starts(x, jump=EDGE_JUMP):
    """(even, odd) counts of sample indices at which a new square level starts."""
    even = odd = 0
    for i in range(1, len(x)):
        if abs(x[i] - x[i - 1]) > jump:
            if i % 2:
                odd += 1
            else:
                even += 1
    return even, odd


def hold_parity(x):
    """(parity, how, even edges, odd edges). Raises ParityError when unsettled."""
    even, odd = edge_starts(x)
    if even + odd >= MIN_EDGES:
        if even and odd:
            raise ParityError(f"edges disagree on the hold parity: {even} even, {odd} odd")
        return (0 if even else 1), "edges", even, odd
    med = {off: statistics.median(abs(x[i] - x[i + 1]) for i in range(off, len(x) - 1, 2))
           for off in (0, 1)}
    if abs(med[0] - med[1]) < TIE_CODES:
        raise ParityError(f"no edges and the pairings tie ({med[0]} vs {med[1]})")
    return min(med, key=med.get), "median", even, odd


def hold_tail(x):
    """(errors beyond each threshold per 1000 holds, holds counted, parity info)."""
    if len(x) < 16:
        return {t: None for t in THRESH}, 0, {"parity": None, "how": "short"}
    try:
        off, how, even, odd = hold_parity(x)
    except ParityError as e:
        even, odd = edge_starts(x)
        return {t: None for t in THRESH}, 0, {"parity": None, "how": str(e),
                                              "edges_even": even, "edges_odd": odd}
    lv = [(x[i] + x[i + 1]) / 2.0 for i in range(off, len(x) - 1, 2)]
    edges = {h for h in range(1, len(lv)) if abs(lv[h] - lv[h - 1]) > EDGE_CODES}
    errors = []
    for h in range(1, len(lv) - 1):
        if any((h + k) in edges for k in range(-EDGE_GUARD, EDGE_GUARD + 1)):
            continue
        errors.append(lv[h] - (lv[h - 1] + lv[h + 1]) / 2.0)
    info = {"parity": off, "how": how, "edges_even": even, "edges_odd": odd}
    if not errors:
        return {t: None for t in THRESH}, 0, info
    per = {t: round(1000.0 * sum(1 for e in errors if abs(e) > t) / len(errors), 3)
           for t in THRESH}
    return per, len(errors), info


def selftest():
    """Recover a known count of injected hold errors from synthetic captures.

    Levels are exact floats with no noise, so an injected error's two
    neighbours read half of it with the opposite sign, plus the sine's own
    second difference of under 0.04 codes. An 11-code error on the sine
    leaves -5.5 beside it and an 8-code one -4, both clear of 6; the
    square is flat, so its 12-code errors leave exactly -6. The square is
    built starting on an odd sample, so only its edges can pair it
    correctly: its two pairings tie on the median. What is checked is the
    counting, the pairing from edges and from the median, and the edge
    guard - not noise tolerance.
    """
    rng = random.Random(82)
    n_holds = 60000
    slots = list(range(1000, n_holds - 1000, 7))
    big = set(rng.sample(slots, 40))
    mid = set(rng.sample(sorted(set(slots) - big), 25))
    sine, square = [], []
    for h in range(n_holds):
        level = 2048.0 + 1000.0 * math.sin(2 * math.pi * h / 1024)
        level += 11.0 if h in big else 8.0 if h in mid else 0.0
        edge_lv = 3200.0 if (h // 64) % 2 else 800.0
        edge_err = 12.0 if h in big else 0.0
        sine += [level, level]
        square += [edge_lv + edge_err, edge_lv + edge_err]
    ok = True

    per, holds, info = hold_tail([sine[0]] + sine)
    got10 = round(per[10] * holds / 1000.0)
    got6 = round(per[6] * holds / 1000.0)
    ok = ok and got10 == len(big) and got6 == len(big) + len(mid) and info["parity"] == 1
    print(f"sine, odd start: >10 {got10} of {len(big)}, >6 {got6} of {len(big) + len(mid)}"
          f", parity {info['parity']} by {info['how']}")

    def clear(h):
        return not any((h + k) % 64 == 0 for k in range(-EDGE_GUARD, EDGE_GUARD + 1))
    want_sq = sum(1 for h in big if clear(h))
    per_sq, holds_sq, info_sq = hold_tail([square[0]] + square)
    got_sq = round(per_sq[10] * holds_sq / 1000.0) if per_sq[10] is not None else None
    ok = (ok and got_sq == want_sq and 0 < want_sq < len(big)
          and info_sq["parity"] == 1 and info_sq["how"] == "edges")
    print(f"square, odd start: >10 {got_sq} of {want_sq} clear of edges, "
          f"parity {info_sq['parity']} by {info_sq['how']} "
          f"({info_sq.get('edges_even')} even / {info_sq.get('edges_odd')} odd edges)")

    flat = [2048.0] * 4000
    per_f, holds_f, info_f = hold_tail(flat)
    ok = ok and info_f["parity"] is None and holds_f == 0
    print(f"flat, no edges: parity {info_f['parity']} ({info_f['how']})")

    torn = list(square)
    torn.insert(len(torn) // 2, torn[len(torn) // 2])
    per_t, holds_t, info_t = hold_tail(torn)
    ok = ok and info_t["parity"] is None and holds_t == 0
    print(f"square with one sample slipped: parity {info_t['parity']} ({info_t['how']})")

    print("SELFTEST " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def summarise(rows, rounds_dropped=1):
    kept = [r for r in rows if r["round"] > rounds_dropped]
    arms = sorted({(r["fws"], r["k_us"]) for r in kept})
    med = {}
    print("\narm          A1 >6  A1 >10  A0 >6  A0 >10  A1 parity   per 1000 holds, "
          f"median of rounds > {rounds_dropped}")
    for fws, k in arms:
        rs = [r for r in kept if r["fws"] == fws and r["k_us"] == k]
        good = [r for r in rs if r["a1_6"] is not None and r["a0_6"] is not None]
        par = sorted({r["a1_parity"] for r in rs}, key=str)
        if not good:
            print(f"FWS {fws} K {k:2d}  no readable capture  parity {par}  n={len(rs)}")
            continue
        m = {key: statistics.median(r[key] for r in good)
             for key in ("a1_6", "a1_10", "a0_6", "a0_10")}
        med[(fws, k)] = (m, [r["a1_6"] for r in good])
        print(f"FWS {fws} K {k:2d}  {m['a1_6']:6.2f} {m['a1_10']:7.2f} "
              f"{m['a0_6']:6.2f} {m['a0_10']:7.2f}  {par}   n={len(good)}/{len(rs)}")
    base = med.get((4, 0))
    ctrl = med.get((6, 0))
    if base and ctrl and base[0]["a1_6"]:
        print(f"\ncontrol: FWS 6 / FWS 4 at K 0 on A1 >6 = "
              f"{ctrl[0]['a1_6'] / base[0]['a1_6']:.3f}")
    sweep = [med[(4, k)][0]["a1_6"] for k in range(1, 11) if (4, k) in med]
    if len(sweep) > 1 and min(sweep) > 0:
        print(f"sweep over K 1..10 present: A1 >6 max/min = {max(sweep) / min(sweep):.2f}")
    if (4, 1) in med and (4, 11) in med:
        lo, hi = min(med[(4, 1)][1]), max(med[(4, 1)][1])
        print(f"wrap: K 11 median {med[(4, 11)][0]['a1_6']:.2f} against K 1 "
              f"round range {lo:.2f}..{hi:.2f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true",
                    help="check the readout on synthetic captures; no board")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("-s", "--seconds", type=float, default=5.0)
    ap.add_argument("--ks", default=",".join(str(k) for k in range(12)))
    ap.add_argument("--tag", default="", help="suffix for the record's name")
    ap.add_argument("--seed", type=int, default=8200)
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    import provenance  # noqa: E402
    bench = os.environ.get("DUE_BENCH") or provenance.bench().get("bench")
    if not bench:
        sys.exit("REFUSING: no bench. Set DUE_BENCH or declare one in bench.json.")
    suffix = f"-{args.tag}" if args.tag else ""
    out = os.path.join(ROOT, "records", f"issue82-ksweep-{bench}{suffix}.jsonl")
    if os.path.exists(out):
        sys.exit(f"REFUSING: {out} already exists; move it aside or pass another --tag.")

    import measure  # noqa: E402
    arms = [(4, int(k)) for k in args.ks.split(",")] + [(6, 0)]
    rows = []
    board = measure.Board(settle=3.0)
    try:
        board.stop()
        board.drain_console(0.5)
        prov = provenance.run_fields(board)
        print("provenance: " + ", ".join(f"{k}={v}" for k, v in prov.items()))
        for c in BASE:
            board.cmd(c)
            board.drain_console(0.3)
        with open(out, "x", encoding="utf-8", newline="\n") as fh:
            for rnd in range(1, args.rounds + 1):
                order = list(arms)
                random.Random(args.seed + rnd).shuffle(order)
                for fws, k in order:
                    board.cmd(f"={fws}q")
                    board.cmd(f"={k}K")
                    board.drain_console(0.3)
                    res = measure.run_capture(board, preset="=200000,200000M",
                                              seconds=args.seconds)
                    ps = res.stream
                    start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
                    a0 = (ps.series.get(measure.CH_A0) or [])[start:]
                    a1 = (ps.series.get(measure.CH_A1) or [])[start:]
                    t0, n0, i0 = hold_tail(a0)
                    t1, n1, i1 = hold_tail(a1)
                    row = {"round": rnd, "round1": rnd == 1, "fws": fws, "k_us": k,
                           "t": time.strftime("%Y-%m-%dT%H:%M:%S"), "bench": bench,
                           **prov, "preset": "=200000,200000M", "base": BASE,
                           "seconds": args.seconds, "settle_index": start,
                           "a0_6": t0[6], "a0_10": t0[10], "a0_holds": n0,
                           "a0_parity": i0["parity"], "a0_parity_by": i0["how"],
                           "a1_6": t1[6], "a1_10": t1[10], "a1_holds": n1,
                           "a1_parity": i1["parity"], "a1_parity_by": i1["how"],
                           "a1_edges_even": i1.get("edges_even"),
                           "a1_edges_odd": i1.get("edges_odd")}
                    rows.append(row)
                    fh.write(json.dumps(row) + "\n")
                    fh.flush()
                    print(f"round {rnd} FWS {fws} K {k:2d}: A1 >6 {t1[6]} >10 {t1[10]}"
                          f" parity {i1['parity']} ({i1.get('edges_even')}e/{i1.get('edges_odd')}o)"
                          f" | A0 >6 {t0[6]} >10 {t0[10]} parity {i0['parity']}"
                          f"  (holds {n1}/{n0})", flush=True)
    finally:
        try:
            for c in ("=4q", "=0K", *BASE):
                board.cmd(c)
                board.drain_console(0.3)
            board.stop()
        finally:
            board.close()
    summarise(rows)
    print(f"rows -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
