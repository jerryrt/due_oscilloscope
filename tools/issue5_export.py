#!/usr/bin/env python3
"""Flatten every issue #5 arm into CSV for analysis outside this repo.

    .venv/bin/python tools/issue5_export.py            # -> analysis/
    .venv/bin/python tools/issue5_export.py -o /tmp/x

Needs no board. Reads `records/issue5-*.jsonl` and writes long-format CSV
that any tool can load - stdlib only, no numpy, no parquet, because the
point is that whatever opens it next need not be this project's venv.

## Why an export rather than analysing in place

The rows are JSONL with a 256-value profile per run, which is the right
storage format and a poor analysis format: every question about a
position across arms means re-deriving the same medians. The campaign's
own history is that of a statistic being computed four different ways by
two benches. A single flat table with one documented convention per
column removes that whole class of disagreement.

It is DERIVED data and is not committed, for the same reason
`records/*.summary.json` and `docs/issue5-report.html` are not: a derived
file in the tree is a second home for a number that already has one, and
this one goes stale the moment an arm lands. The generator is committed;
run it.

## The three tables

`runs.csv`      one row per capture. Provenance, wire, leg, wait state,
                `total_abs`, `site_abs`, `n_sites`, `hold_ok`, `mad`.
                This is the table for "which runs are comparable".

`profiles.csv`  one row per (run, position) - 648 runs x 256 = ~166k
                rows. Carries BOTH conventions explicitly:
                  `dev_signed` = profile[pos] - median(profile)
                  `dev_abs`    = |dev_signed|
                Named because the difference between them produced two
                benches' disagreeing numbers for one quantity, four
                times in one afternoon.

`positions.csv` one row per (arm, wait state, position): the aggregate
                readings, each under its own named convention -
                `med_abs` (median of |dev|, the campaign's metric),
                `abs_med` (|median of dev|, which CANCELS a site that
                changes sign between a board's two modes), plus the
                site incidence and the two-state split.

## Conventions fixed here, once

* Run 1 of every arm is EXCLUDED, by index, never by a filter on what it
  does wrong. It is flagged `run1=1` in `runs.csv` and dropped from
  `profiles.csv` and `positions.csv`.
* `linux-x1`'s run 31 is KEPT and flagged `outlier_note`. Its comb
  collapsed to 28% of its peers and it is the only such run in 72 on
  that board; it is data, not dirt.
* Every profile value is centred on its own run's median before anything
  else, which is what `total_abs` does.
"""
import argparse
import csv
import glob
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDS = os.path.join(ROOT, "records")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#: Which file is which leg of the crossover, and what wire was on the
#: board. Taken from the owner-confirmed declarations on each row rather
#: than inferred, but the LEG is a property of the campaign's design and
#: is stated here because no row carries it.
ARMS = [
    # file glob prefix,            arm label,     leg
    ("issue5-campaign-",           "campaign",    "baseline"),
    ("issue5-crossover-",          "crossover",   "swapped"),
    ("issue5-return-",             "return",      "returned"),
    ("issue5-onimage-",            "onimage",     "superseded"),
    ("issue5-fws5-repeat-",        "fws5-repeat", "superseded"),
]

#: The period-21 lattice through the large FWS 6 sites, and which of its
#: points actually carry one. Emitted as a column so an analysis can
#: filter on it without re-deriving the campaign's conclusions.
LATTICE12 = [12 + 21 * k for k in range(12)]
LARGE_OFF_LATTICE = [169, 247]


def arm_of(name):
    for pref, label, leg in ARMS:
        if name.startswith(pref):
            return label, leg
    return "other", "unknown"


def load(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def split_two_states(vals):
    """Largest-gap split, with a minimum per side. Returns (n_large, size).

    The minimum matters: without one, a distribution with no two states
    puts a single run on one side and "size when large" becomes the
    maximum of the sample rather than a state's median. That produced a
    false verdict during the campaign. 4 a side matches
    `issue5_modes.MIN_SIDE`, which is the project's existing answer to
    the same question, so there is one home for it.
    """
    v = sorted(vals)
    n = len(v)
    if n < 8:
        return 0, None
    best = max(((v[i + 1] - v[i], i) for i in range(3, n - 4)), default=None)
    if best is None:
        return 0, None
    _gap, i = best
    large = v[i + 1:]
    if len(large) < 4 or len(v) - len(large) < 4:
        return 0, None
    return len(large), statistics.median(large)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", default=os.path.join(ROOT, "analysis"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    # Only the arms this campaign defines. `records/issue5-*.jsonl` also
    # holds a dozen older tools' records with entirely different schemas -
    # no `run`, no `profile` - and a glob that swallowed them produced a
    # KeyError rather than a silently wrong table, which is the good
    # failure but still the wrong glob.
    files = []
    for pref, _l, _g in ARMS:
        files += sorted(glob.glob(os.path.join(RECORDS, pref + "*.jsonl")))
    files = sorted(set(files))
    runs_out, prof_out, pos_out = [], [], []

    for path in files:
        name = os.path.basename(path)
        arm, leg = arm_of(name)
        rows = load(path)
        if not rows:
            continue
        bench = rows[0].get("bench", "?")
        rows = [r for r in rows if isinstance(r, dict) and "run" in r]
        if not rows:
            continue
        for r in rows:
            is1 = 1 if r["run"] == 1 else 0
            runs_out.append({
                "file": name, "bench": bench, "arm": arm, "leg": leg,
                "run": r["run"], "run1": is1, "fws": r.get("fws"),
                "preset": r.get("preset"), "probes": r.get("probes"),
                "jumpers": r.get("jumpers"),
                "total_abs": r.get("total_abs"), "site_abs": r.get("site_abs"),
                "n_sites": r.get("n_sites", len(r.get("sites", []))),
                "sites_stored": len(r.get("sites", [])),
                "hold_ok": int(bool(r.get("hold_ok"))),
                "mad": r.get("mad"), "argmax_phase": r.get("argmax_phase"),
                "argmax_peak": r.get("argmax_peak"),
                "has_profile": int(bool(r.get("profile"))),
                "fw_repo_rev": r.get("fw_repo_rev"),
                "repo_rev": r.get("repo_rev"), "track": r.get("track"),
                "fw_cc": r.get("fw_cc"), "fw_layout": r.get("fw_layout"),
                "t": r.get("t"),
                "outlier_note": ("comb collapsed to 28%; only such run in 72"
                                 if bench == "linux-x1" and arm == "campaign"
                                 and r["run"] == 31 else ""),
            })

        keep = [r for r in rows if r["run"] != 1 and r.get("profile")]
        for r in keep:
            med = statistics.median(r["profile"])
            for pos, raw in enumerate(r["profile"]):
                d = raw - med
                prof_out.append({
                    "bench": bench, "arm": arm, "leg": leg, "fws": r["fws"],
                    "run": r["run"], "pos": pos,
                    "dev_signed": round(d, 4), "dev_abs": round(abs(d), 4),
                })

        by = {}
        for r in keep:
            by.setdefault(r["fws"], []).append(r)
        for fws, g in sorted(by.items()):
            for pos in range(256):
                sg = [x["profile"][pos] - statistics.median(x["profile"])
                      for x in g]
                sa = [abs(v) for v in sg]
                nsite = sum(1 for x in g
                            if any(b == pos for b, _v, _z in x["sites"]))
                nl, sz = split_two_states(sa)
                pos_out.append({
                    "bench": bench, "arm": arm, "leg": leg, "fws": fws,
                    "pos": pos, "n_runs": len(g),
                    "med_abs": round(statistics.median(sa), 4),
                    "abs_med": round(abs(statistics.median(sg)), 4),
                    "mean_signed": round(statistics.fmean(sg), 4),
                    "min_abs": round(min(sa), 4), "max_abs": round(max(sa), 4),
                    "site_runs": nsite,
                    "two_state_n_large": nl,
                    "two_state_size": round(sz, 4) if sz is not None else "",
                    "on_lattice21": int(pos in LATTICE12),
                    "large_off_lattice": int(pos in LARGE_OFF_LATTICE),
                    "pos_mod_21": pos % 21,
                })

    def dump(fn, recs):
        p = os.path.join(args.out, fn)
        with open(p, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(recs[0].keys()))
            w.writeheader()
            w.writerows(recs)
        print(f"  {fn:16s} {len(recs):7d} rows  {os.path.getsize(p)/1e6:.1f} MB")

    print(f"writing to {args.out}")
    dump("runs.csv", runs_out)
    dump("profiles.csv", prof_out)
    dump("positions.csv", pos_out)

    # The README travels with the data, because the data is not committed
    # and a CSV whose column conventions are documented only in the
    # generator is a CSV whose conventions get re-guessed. It is a
    # committed template rather than a string in here so it can be read
    # and reviewed as prose.
    tmpl = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "issue5_export_README.md.in")
    with open(tmpl, encoding="utf-8") as fh:
        readme = fh.read()
    out = os.path.join(args.out, "README.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(readme)
    print(f"  {'README.md':16s} {len(readme.splitlines()):7d} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
