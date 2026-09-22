#!/usr/bin/env python3
"""Are a board's repeated rows in one arrangement stable?

Reads `records/rotation.jsonl` and, for every board and phase with more
than one row, sets the spread of the rows' rested medians against the
widest range any single row saw within itself. Five census runs make
one row; four rows of one arrangement make one stability reading.

The rule, stated once here and nowhere else: a (board, phase) is
**stable** when the across-row spread of `largest_median` is no wider
than the widest within-row range (`largest_max - largest_min`) among
those rows. A board whose rows disagree by more than any one of them
wandered is not stable, whatever its level. Rows taken with less than
the rested idle time are listed and excluded from the verdict.

The same rule is applied to the crossing count, on the rows' count
medians against the widest within-row count range, as a second verdict:
a level can hold while the count moves, and on one board it did. Both
verdicts are about spread, not direction, so a first-to-last drift is
printed for each figure with no verdict attached - a monotone change
inside the within-row range is a thing to read, not a thing to pass.

Also reported, without a verdict: the baseline tail scale on A0 and
A1, and the die code. The tail scale is
the **last** baseline pair in the row - a row whose parity was forced
after a tie carries the aborted first attempt's pair as well, and the
pair that completed is the one that counts.

    tools/rotation_stability.py                 # markdown table
    tools/rotation_stability.py --json          # the same, as data
    tools/rotation_stability.py --phase shield-v3
"""

import argparse
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROTATION = os.path.join(HERE, "..", "records", "rotation.jsonl")
#: Owner-directed cut, 2026-09-21: was 1200 (20 min), the rotation's
#: original declared rest. Lowering it does not shorten any board's
#: actual thermal or electrical settling time - it only changes which
#: already-recorded rows this tool is willing to call "rested". A row
#: taken at 120-1199 s idle now counts that previously did not.
RESTED_S = 120


def rows_from(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def baseline_pair(row):
    """The last two baseline tail-scale entries, as (a0 mean, a1 mean),
    or (None, None) when the row has no completed baseline pair."""
    base = [t for t in row.get("tail_scale") or [] if t.get("arm") == "baseline"]
    if len(base) < 2:
        return None, None
    pair = base[-2:]
    return (round(statistics.fmean(t["a0_scale_codes"] for t in pair), 2),
            round(statistics.fmean(t["a1_scale_codes"] for t in pair), 2))


def die_code(row):
    temps = row.get("temperatures") or []
    codes = [t["code"] for t in temps if t.get("code") is not None]
    return round(statistics.fmean(codes), 1) if codes else None


def row_line(row):
    cs = row.get("census_summary") or {}
    a0, a1 = baseline_pair(row)
    return {
        "bench": row.get("bench"),
        "taken_at": row.get("taken_at"),
        "idle_before_s": row.get("idle_before_s"),
        "rested": (row.get("idle_before_s") or 0) >= RESTED_S,
        "largest_median": cs.get("largest_median"),
        "largest_range": [cs.get("largest_min"), cs.get("largest_max")],
        "count_range": [cs.get("count_min"), cs.get("count_max")],
        "count_median": cs.get("count_median"),
        "a0": a0, "a1": a1,
        "die_code": die_code(row),
        "note": row.get("note"),
    }


def spread_rule(medians, ranges):
    """(verdict, across, within): stable when the medians spread no wider
    than the widest range any one row saw within itself."""
    across = round(max(medians) - min(medians), 2)
    withins = [hi - lo for lo, hi in ranges if lo is not None and hi is not None]
    if not withins:
        return "no verdict", across, None
    within = round(max(withins), 2)
    return ("stable" if across <= within else "NOT stable"), across, within


def judge(lines):
    """The verdicts for one (board, phase) from its row lines: the level
    (largest step) and the crossing count, each by spread_rule, plus a
    first-to-last drift per figure that carries no verdict."""
    rested = [l for l in lines if l["rested"] and l["largest_median"] is not None]
    if len(rested) < 2:
        return {"verdict": "no verdict", "reason": f"{len(rested)} rested row(s)",
                "n_rested": len(rested), "across": None, "within": None}
    meds = [l["largest_median"] for l in rested]
    verdict, across, within = spread_rule(meds, [l["largest_range"] for l in rested])
    if within is None:
        return {"verdict": "no verdict", "reason": "no within-row range",
                "n_rested": len(rested), "across": across, "within": None}
    counts = [l["count_median"] for l in rested]
    if all(c is not None for c in counts):
        cverdict, cacross, cwithin = spread_rule(
            counts, [l["count_range"] for l in rested])
        count_drift = counts[-1] - counts[0]
    else:
        cverdict, cacross, cwithin, count_drift = "no verdict", None, None, None
    return {"verdict": verdict,
            "reason": (f"medians spread {across} against a widest within-row "
                       f"range of {within}"),
            "n_rested": len(rested), "across": across, "within": within,
            "medians": meds,
            "median_of_medians": statistics.median(meds),
            "count_verdict": cverdict, "count_across": cacross,
            "count_within": cwithin, "count_medians": counts,
            "drift": {"largest_median": round(meds[-1] - meds[0], 2),
                      "count_median": count_drift},
            "count_range": [min(l["count_range"][0] for l in rested
                                if l["count_range"][0] is not None),
                            max(l["count_range"][1] for l in rested
                                if l["count_range"][1] is not None)],
            "a0_range": _rng([l["a0"] for l in rested]),
            "a1_range": _rng([l["a1"] for l in rested]),
            "die_code_range": _rng([l["die_code"] for l in rested])}


def _rng(values):
    v = [x for x in values if x is not None]
    return [min(v), max(v)] if v else None


def assess(rows, phase=None):
    groups = {}
    for r in rows:
        if not r.get("board_uid") or not r.get("phase"):
            continue
        if phase and r["phase"] != phase:
            continue
        groups.setdefault((r["board_uid"], r["phase"]), []).append(r)
    out = []
    for (uid, ph), rs in sorted(groups.items()):
        rs = sorted(rs, key=lambda r: r.get("taken_at") or "")
        lines = [row_line(r) for r in rs]
        out.append({"board_uid": uid, "board_serial": rs[0].get("board_serial"),
                    "phase": ph, "rows": lines, **judge(lines)})
    return out


def render(assessments):
    out = []
    for a in assessments:
        head = (f"### `{a['board_uid']}` (`{a['board_serial']}`) — `{a['phase']}` "
                f"— level **{a['verdict']}** ({a['reason']})")
        if a.get("count_verdict") and a["count_verdict"] != "no verdict":
            head += (f"; count **{a['count_verdict']}** (medians spread "
                     f"{a['count_across']} against {a['count_within']})")
        out.append(head)
        out.append("")
        out.append("| # | bench | taken | idle s | largest median | within-row | count median | count | A0 | A1 | die |")
        out.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for i, l in enumerate(a["rows"], 1):
            lo, hi = l["largest_range"]
            c0, c1 = l["count_range"]
            flag = "" if l["rested"] else " (unrested, excluded)"
            out.append(f"| {i} | {l['bench']} | {l['taken_at']} | {l['idle_before_s']}{flag} "
                       f"| {l['largest_median']} | {lo}–{hi} | {l['count_median']} | {c0}–{c1} "
                       f"| {l['a0']} | {l['a1']} | {l['die_code']} |")
        if a.get("across") is not None and a.get("within") is not None:
            d = a["drift"]
            out.append("")
            out.append(f"across-row spread **{a['across']}** vs widest within-row "
                       f"**{a['within']}**; count {a['count_range']}, "
                       f"A0 {a['a0_range']}, A1 {a['a1_range']}, die {a['die_code_range']}; "
                       f"first-to-last drift: largest {d['largest_median']:+}, "
                       f"count median {d['count_median']:+} (no verdict)")
        out.append("")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rotation", default=ROTATION)
    ap.add_argument("--phase", default=None, help="only this arrangement")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    a = assess(rows_from(args.rotation), args.phase)
    if not a:
        print("rotation_stability: no rows", file=sys.stderr)
        return 2
    print(json.dumps(a, indent=2) if args.json else render(a))
    return 0


if __name__ == "__main__":
    sys.exit(main())
