#!/usr/bin/env python3
"""Read a generator sweep's captures within DAC holds and say what the
bad samples correlate with.

    tools/gen_sweep_analyse.py                      # every sidecar in captures/gen-sweep
    tools/gen_sweep_analyse.py --json
    tools/gen_sweep_analyse.py --stamp 20260921T075900

The internal generator holds each DAC level for two ADC samples, so
the two samples of a hold are one converter reading the same voltage
twice, ten microseconds apart. Their difference carries none of the
waveform - no staircase, no slope - only the converter's own error,
which is what a threshold on raw sample-to-sample steps cannot
separate from the riser it sits on. Everything here is computed on
holds.

Per capture, on A0 after the settle:

- parity: which pairing (0,1),(2,3),... or (1,2),(3,4),... is the
  hold, chosen by the smaller median |pair difference|; a tie is
  reported, not broken, and a flat capture is folded at parity 0.
- within-hold difference d = second - first, and its distribution:
  median |d|, the 99th and 99.9th percentiles, and the rate per 1000
  holds above 6, 10, 20 and 45 codes.
- for every hold with |d| above the event threshold: which of the two
  samples is the one off its level, judged against the mean of the
  neighbouring holds; the sign of that sample's error against the
  riser INTO the hold (a sample that has not finished settling lies
  on the old level's side) and against the riser OUT of it (a sample
  that already moved toward the next level lies on that side).
- the event rate binned by the riser magnitude into the hold, by the
  level, and by phase in the cycle; and the DC capture's rate, which
  is the floor with no riser at all.

Nothing is asserted. The tables are the evidence, and the reading of
them is written where readings go.
"""

import argparse
import array
import glob
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
CAPTURES = os.path.join(REPO, "captures", "gen-sweep")
TIE_CODES = 2.0
THRESHOLDS = (6, 10, 20, 45)
EVENT = 10
RISER_BINS = ((0, 4), (4, 8), (8, 16), (16, 32), (32, 64), (64, 128), (128, 512),
              (512, 4096))
LEVEL_BINS = 8
PHASE_BINS = 16
MIN_BIN_HOLDS = 1000      # a rate from fewer holds than this is not printed


def load_u16(path):
    a = array.array("H")
    with open(path, "rb") as fh:
        a.frombytes(fh.read())
    return a


def choose_parity(x):
    med = {}
    for off in (0, 1):
        diffs = [abs(x[i] - x[i + 1]) for i in range(off, len(x) - 1, 2)]
        med[off] = statistics.median(diffs) if diffs else 0.0
    if abs(med[0] - med[1]) < TIE_CODES:
        return 0, "tie", med
    return min(med, key=med.get), "median", med


def holds_of(x, parity):
    n = (len(x) - parity) // 2
    L = [0.0] * n
    d = [0] * n
    first = [0] * n
    second = [0] * n
    for k in range(n):
        a = x[parity + 2 * k]
        b = x[parity + 2 * k + 1]
        L[k] = (a + b) / 2.0
        d[k] = b - a
        first[k] = a
        second[k] = b
    return L, d, first, second


def quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, int(q * len(sorted_vals)))
    return sorted_vals[i]


def phase_anchor(L, period):
    """Index in [0, period) where the folded mean level peaks."""
    if period <= 1 or len(L) < period:
        return 0
    sums = [0.0] * period
    cnt = [0] * period
    for k, v in enumerate(L):
        sums[k % period] += v
        cnt[k % period] += 1
    means = [s / c if c else 0.0 for s, c in zip(sums, cnt)]
    return max(range(period), key=lambda i: means[i])


def _raw_census(x):
    """The census test's own figure on the raw samples, for the record
    beside the within-hold figures: steps above 45 codes after
    collapsing flat runs, and the largest. Needs host/measure.py."""
    try:
        sys.path.insert(0, os.path.join(REPO, "host"))
        import measure
        c = measure.level_census(x)
        return {"count_over_45": c.get("count"), "largest": c.get("max_step")}
    except Exception as exc:                                 # noqa: BLE001
        return {"error": str(exc)}


def analyse_capture(side, event=EVENT):
    a0 = side["files"]["a0"]
    x = load_u16(os.path.join(REPO, a0["path"]))
    start = a0.get("settle_index") or 0
    x = x[start:]
    parity, how, med = choose_parity(x)
    L, d, first, second = holds_of(x, parity)
    n = len(L)
    period = side["points"] if side["shape"] != "dc" else 1
    anchor = phase_anchor(L, period)
    absd = sorted(abs(v) for v in d)
    census = _raw_census(x)
    out = {
        "label": side["label"], "shape": side["shape"], "points": side["points"],
        "expected_output_hz": side.get("expected_output_hz"),
        "holds": n, "parity": parity, "parity_how": how,
        "pair_median_by_parity": {str(k): round(v, 2) for k, v in med.items()},
        "abs_d_median": statistics.median(absd) if absd else None,
        "abs_d_p99": quantile(absd, 0.99), "abs_d_p999": quantile(absd, 0.999),
        "abs_d_max": absd[-1] if absd else None,
        "rate_per_1000_holds": {str(t): round(1000.0 * sum(1 for v in absd if v > t) / n, 3)
                                for t in THRESHOLDS},
        "level_range": [min(L), max(L)] if L else None,
        "raw_census": census,
    }
    # events
    ev = [k for k in range(1, n - 1) if abs(d[k]) > event]
    off_first = off_second = 0
    err_vs_in = {"opposite": 0, "same": 0}     # settling lag would be "opposite"
    err_vs_out = {"same": 0, "opposite": 0}    # early move toward next level would be "same"
    riser_hist = {f"{lo}-{hi}": [0, 0] for lo, hi in RISER_BINS}
    level_hist = [[0, 0] for _ in range(LEVEL_BINS)]
    phase_hist = [[0, 0] for _ in range(PHASE_BINS)]
    riser_sizes = []
    for k in range(1, n - 1):
        r_in = L[k] - L[k - 1]
        r_out = L[k + 1] - L[k]
        ar = abs(r_in)
        for lo, hi in RISER_BINS:
            if lo <= ar < hi:
                riser_hist[f"{lo}-{hi}"][1] += 1
                break
        lb = min(LEVEL_BINS - 1, int(L[k] / 4096.0 * LEVEL_BINS))
        level_hist[lb][1] += 1
        pb = int(((k - anchor) % period) / period * PHASE_BINS) if period > 1 else 0
        phase_hist[pb][1] += 1
        if abs(d[k]) <= event:
            continue
        Lhat = (L[k - 1] + L[k + 1]) / 2.0
        e1 = first[k] - Lhat
        e2 = second[k] - Lhat
        if abs(e1) >= abs(e2):
            off_first += 1
            e = e1
        else:
            off_second += 1
            e = e2
        if r_in:
            err_vs_in["opposite" if e * r_in < 0 else "same"] += 1
        if r_out:
            err_vs_out["same" if e * r_out > 0 else "opposite"] += 1
        for lo, hi in RISER_BINS:
            if lo <= ar < hi:
                riser_hist[f"{lo}-{hi}"][0] += 1
                break
        level_hist[lb][0] += 1
        phase_hist[pb][0] += 1
        riser_sizes.append(ar)
    out.update({
        "event_threshold": event, "events": len(ev),
        "events_per_1000_holds": round(1000.0 * len(ev) / n, 3) if n else None,
        "off_sample": {"first": off_first, "second": off_second},
        "error_vs_riser_in": err_vs_in, "error_vs_riser_out": err_vs_out,
        "rate_by_riser": {k: {"events": v[0], "holds": v[1],
                              "per_1000": round(1000.0 * v[0] / v[1], 2) if v[1] else None}
                          for k, v in riser_hist.items() if v[1]},
        "rate_by_level": [{"events": v[0], "holds": v[1],
                           "per_1000": round(1000.0 * v[0] / v[1], 2) if v[1] else None}
                          for v in level_hist],
        "rate_by_phase": [{"events": v[0], "holds": v[1],
                           "per_1000": round(1000.0 * v[0] / v[1], 2) if v[1] else None}
                          for v in phase_hist],
    })
    return out


def render(results, sides):
    o = []
    s0 = sides[0]
    c = s0.get("conditions", {})
    o.append(f"## Generator sweep, {s0['bench']}, board `{c.get('board_uid')}` "
             f"(`{c.get('board_serial')}`), image `{s0['identity'].get('build')}`")
    o.append(f"note: {s0.get('note')}")
    o.append("")
    o.append("### Per capture, within holds (A0, after the settle)")
    o.append("")
    o.append("| capture | out Hz | census >45 / largest | holds | parity | median \\|d\\| | p99 | p99.9 | max | >6 /1000 | >10 /1000 | >20 /1000 | >45 /1000 | off sample 1st:2nd | err vs riser in (opp:same) | err vs riser out (same:opp) |")
    o.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        rt = r["rate_per_1000_holds"]
        rc = r["raw_census"]
        o.append(f"| {r['label']} | {r['expected_output_hz']:.0f} | {rc.get('count_over_45')} / {rc.get('largest')} | {r['holds']} | {r['parity']} ({r['parity_how']}) "
                 f"| {r['abs_d_median']} | {r['abs_d_p99']} | {r['abs_d_p999']} | {r['abs_d_max']} "
                 f"| {rt['6']} | {rt['10']} | {rt['20']} | {rt['45']} "
                 f"| {r['off_sample']['first']}:{r['off_sample']['second']} "
                 f"| {r['error_vs_riser_in']['opposite']}:{r['error_vs_riser_in']['same']} "
                 f"| {r['error_vs_riser_out']['same']}:{r['error_vs_riser_out']['opposite']} |")
    o.append("")
    o.append(f"### Event rate (|d| > {EVENT}) by riser magnitude into the hold, per 1000 holds")
    o.append("")
    keys = [f"{lo}-{hi}" for lo, hi in RISER_BINS]
    o.append("| capture | " + " | ".join(keys) + " |")
    o.append("|---|" + "---|" * len(keys))
    for r in results:
        cells = []
        for k in keys:
            b = r["rate_by_riser"].get(k)
            if not b:
                cells.append("—")
            elif b["holds"] < MIN_BIN_HOLDS:
                cells.append(f"({b['events']}/{b['holds']}, too few)")
            else:
                cells.append(f"{b['per_1000']} ({b['events']}/{b['holds']})")
        o.append(f"| {r['label']} | " + " | ".join(cells) + " |")
    o.append("")
    o.append("### Event rate by level (eighths of full scale), per 1000 holds")
    o.append("")
    o.append("| capture | " + " | ".join(f"{i}/8" for i in range(LEVEL_BINS)) + " |")
    o.append("|---|" + "---|" * LEVEL_BINS)
    for r in results:
        o.append(f"| {r['label']} | " + " | ".join(
            (f"{b['per_1000']}" if b["holds"] >= MIN_BIN_HOLDS else "—") for b in r["rate_by_level"]) + " |")
    o.append("")
    o.append("### Event rate by phase in the cycle (16 bins, 0 = peak level), per 1000 holds")
    o.append("")
    o.append("| capture | " + " | ".join(str(i) for i in range(PHASE_BINS)) + " |")
    o.append("|---|" + "---|" * PHASE_BINS)
    for r in results:
        if r["shape"] == "dc":
            continue
        o.append(f"| {r['label']} | " + " | ".join(
            (f"{b['per_1000']}" if b["holds"] >= MIN_BIN_HOLDS else "—") for b in r["rate_by_phase"]) + " |")
    return "\n".join(o)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--captures", default=CAPTURES)
    ap.add_argument("--stamp", default=None, help="only sidecars carrying this stamp")
    ap.add_argument("--event", type=int, default=EVENT)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    paths = sorted(glob.glob(os.path.join(args.captures, "*.json")))
    if args.stamp:
        paths = [p for p in paths if args.stamp in os.path.basename(p)]
    sides = []
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            sides.append(json.load(fh))
    sides.sort(key=lambda s: (s.get("taken_at", ""), s.get("order", 0)))
    if not sides:
        print("gen_sweep_analyse: no sidecars", file=sys.stderr)
        return 2
    results = [analyse_capture(s, args.event) for s in sides]
    if args.json:
        print(json.dumps(results, indent=1))
    else:
        print(render(results, sides))
    return 0


if __name__ == "__main__":
    sys.exit(main())
