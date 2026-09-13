#!/usr/bin/env python3
"""Build the issue #5 cross-bench report page from the committed records.

    .venv/bin/python tools/issue5_report.py            # -> docs/issue5-report.html
    .venv/bin/python tools/issue5_report.py -o /tmp/p.html

Needs no board. Every number on the page is derived here, from
`records/issue5-*.jsonl`, and the page carries the `repo_rev` its rows
were committed under - so a reader can tell which state of the
investigation they are looking at, and a re-run regenerates the page
rather than re-authoring it.

**Why this exists.** The first version of this page was built by hand
from a one-off script that was never committed. The page outlived the
script, so its numbers could not be re-derived, extended or corrected -
and one of its captions turned out to understate a defect in the data it
was drawing (see `censoring` below). A figure whose derivation is not in
the tree is a figure nobody can check.

The page itself is `tools/issue5_report.tmpl.html`: CSS, markup and the
SVG drawing code, with one placeholder where this script injects the
data. Charts are drawn from that data at view time, so adding a bench
means adding a record, not editing any markup.

## The censoring this page has to report

`issue5_sites.py` stored `found[:6]` until 2026-09-13, and `found` is
ordered by descending |deviation| - so any run with more than six sites
kept the six strongest and dropped the rest with nothing in the row to
say so. At FWS 6 that truncated **every row of every bench**. The
dropped total is still recoverable, because `site_abs` was summed over
all of `found`:

    hidden = site_abs - sum(|v| over the sites the row actually stored)

That is `tools/issue5_onimage_compare.censored()`, checked against
planted profiles in `tests/test_issue5_censoring.py`, and it is what the
`censoring` block of each wait state carries.
"""
import argparse
import collections
import glob
import json
import os
import statistics
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDS = os.path.join(ROOT, "records")
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "issue5_report.tmpl.html")
DEFAULT_OUT = os.path.join(ROOT, "docs", "issue5-report.html")
sys.path.insert(0, os.path.join(ROOT, "tools"))

from issue5_onimage_compare import CENSOR_EPS, censored  # noqa: E402
import issue5_spectrum as spec  # noqa: E402

#: The DAC table is 256 levels held two samples each, so one cycle is
#: 512 samples and the pair-differenced fold has 256 positions.
BINS = 256

#: The site slice `issue5_sites.py` used to apply. A row with exactly
#: this many sites *may* have been truncated; `censored()` says whether
#: it was.
OLD_SITE_CAP = 6

#: The three benches, in the order the page reads them. `file` picks
#: which arm represents a bench: mac-bench is shown probe-free, because
#: its first arm carried two undeclared scope probes that moved every
#: severity figure on that bench.
#: The pinned campaign arms, which store whole profiles. The earlier
#: `issue5-onimage-*` arms stored six sites and are kept in `EXTRA` as
#: history: every FWS 6 row of every one of them was truncated, which is
#: why these exist. See the censoring section.
BENCHES = [
    {"id": "linux-x1", "label": "linux-x1",
     "file": "records/issue5-campaign-linux-x1.jsonl",
     "note": "Linux · copper jumpers"},
    {"id": "windows-desk", "label": "windows-desk",
     "file": "records/issue5-campaign-windows-desk.jsonl",
     "note": "Windows · iron jumpers"},
    {"id": "mac-bench", "label": "mac-bench",
     "file": "records/issue5-campaign-mac-bench.jsonl",
     "note": "macOS · copper jumpers"},
]

#: The jumper crossover: each board's three legs. The wires were
#: exchanged between the linux-x1 and windows-desk boards and then put
#: back; mac-bench was untouched throughout and is the drift control.
CROSSOVER = [
    ("linux-x1", "copper", "iron", "copper",
     ["records/issue5-campaign-linux-x1.jsonl",
      "records/issue5-crossover-linux-x1.jsonl",
      "records/issue5-return-linux-x1.jsonl"]),
    ("windows-desk", "iron", "copper", "iron",
     ["records/issue5-campaign-windows-desk.jsonl",
      "records/issue5-crossover-windows-desk.jsonl",
      "records/issue5-return-windows-desk.jsonl"]),
    ("mac-bench", "copper", "copper", "copper",
     ["records/issue5-campaign-mac-bench.jsonl",
      "records/issue5-crossover-mac-bench.jsonl",
      "records/issue5-return-mac-bench.jsonl"]),
]

#: The positions the crossover turned on, per wait state. Chosen because
#: they are where any board moved by more than the untouched board's
#: drift at that same position - not because they are the largest.
WATCH = [(6, 180), (6, 169), (6, 109), (6, 201), (6, 75), (5, 134), (4, 240)]

#: Arms that are not one of the three headline benches but belong in the
#: provenance table, because a reader comparing figures elsewhere will
#: meet them: the superseded probed arm, the first probe-free session,
#: and windows-desk's separate FWS-5 repeat.
EXTRA = [
    ("linux-x1 truncated (superseded)", "records/issue5-onimage-linux-x1.jsonl"),
    ("windows-desk truncated (superseded)", "records/issue5-onimage-windows-desk.jsonl"),
    ("mac-bench truncated, probe-free", "records/issue5-onimage-mac-bench-noprobes2.jsonl"),
    ("mac-bench truncated, probed", "records/issue5-onimage-mac-bench.jsonl"),
]

#: Which arm's FWS-5 median the runs chart rings as the stable figure.
#: windows-desk's pooled 82.5 is carried by one early block; its repeat
#: session reads about 46.5.
REPEAT_RING = {"bench": "windows-desk", "fws": 5,
               "file": "records/issue5-fws5-repeat-windows-desk.jsonl"}


def load(path):
    full = os.path.join(ROOT, path)
    with open(full, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def provenance(rows):
    """Every distinct value of each field that decides comparability.

    A list rather than a value on purpose: if an arm ever mixes two
    images the page shows two entries rather than silently picking one.
    """
    keys = ("fw_repo_rev", "fw_layout", "fw_build_env", "preset", "track",
            "repo_rev")
    return {k: sorted({str(r.get(k)) for r in rows if r.get(k) is not None})
            for k in keys}


def med(xs):
    return round(statistics.median(xs), 4) if xs else None


def per_fws(rows):
    """Everything the page needs about one bench at one wait state."""
    out = {}
    for fws in sorted({r["fws"] for r in rows if r.get("fws") is not None}):
        v = sorted([r for r in rows if r["fws"] == fws],
                   key=lambda r: r["run"])
        totals = [r["total_abs"] for r in v]
        sabs = [r["site_abs"] for r in v]
        rest = [r["total_abs"] - r["site_abs"] for r in v]
        # The floor is what is left once the sites are removed, spread
        # over the positions that are not sites. `n_sites` is the real
        # count where a row carries it and the stored length otherwise -
        # which under-counts on a truncated row, so the floor it gives
        # is a slight over-estimate there. Stated rather than hidden.
        nsit = [r.get("n_sites", len(r["sites"])) for r in v]
        floor = [x / max(1, BINS - n) for x, n in zip(rest, nsit)]

        hidden = [censored(r) for r in v]
        kept = [sum(abs(x) for _p, x, _z in r["sites"]) for r in v]
        ncens = sum(1 for h in hidden if h > CENSOR_EPS)
        # A lower bound on how many sites were dropped: every dropped
        # site is no larger than the smallest one kept, so the dropped
        # total divided by that smallest is a floor on the count.
        bound = []
        for r, h in zip(v, hidden):
            small = min((abs(x) for _p, x, _z in r["sites"]), default=0.0)
            if h > CENSOR_EPS and small > 0:
                bound.append(h / small)

        phases = []
        counts = collections.Counter(b for r in v for b, _x, _z in r["sites"])
        for ph in sorted(counts):
            vals = [x for r in v for b, x, _z in r["sites"] if b == ph]
            phases.append({"phase": ph, "count": counts[ph],
                           "median": med(vals), "min": round(min(vals), 2),
                           "max": round(max(vals), 2)})

        out[str(fws)] = {
            "n": len(v),
            "runs": [{"run": r["run"], "total": r["total_abs"],
                      "sites": r["site_abs"],
                      "hold_ok": bool(r.get("hold_ok"))} for r in v],
            "median_total": med(totals),
            "median_sites": med(sabs),
            "median_rest": med(rest),
            "median_rest_per_position": med(floor),
            "phases": phases,
            "rows_at_6_site_cap": sum(1 for r in v
                                      if len(r["sites"]) >= OLD_SITE_CAP),
            # What the page could not draw, and what it would take to.
            "censoring": {
                "rows": ncens,
                "of": len(v),
                "median_hidden": med([h for h in hidden if h > CENSOR_EPS]),
                "max_hidden": round(max(hidden), 2) if hidden else 0.0,
                "median_kept": med(kept),
                "kept_share_of_sites": (
                    round(statistics.median(kept) / statistics.median(sabs), 4)
                    if sabs and statistics.median(sabs) else None),
                "kept_share_of_total": (
                    round(statistics.median(kept) / statistics.median(totals), 4)
                    if totals and statistics.median(totals) else None),
                "min_hidden_sites": med(bound),
                "stored_depth": max((len(r["sites"]) for r in v), default=0),
                "complete": ncens == 0,
            },
        }
    return out


def spec_lattice12():
    return [12 + 21 * k for k in range(12)]


def spec_lattice7():
    """The seven comb points that hold still - the agreed metric."""
    return [12, 33, 54, 96, 117, 138, 159]


def comb_sum(rows, lattice):
    """Median over runs of |deviation|, summed at the lattice points.

    median-of-abs, not |median|: a position that changes sign between a
    board's two severity modes cancels under the second and reports as
    absent while being large in every run.
    """
    return sum(statistics.median(
        [abs(r["profile"][b] - statistics.median(r["profile"])) for r in rows])
        for b in lattice)


def repo_rev():
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=ROOT, capture_output=True, text=True,
                             check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                               capture_output=True, text=True,
                               check=True).stdout.strip()
        return rev + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def slot_competition(rows, fws, depth):
    """Phases that never once appear together, at the storage depth.

    Two sites that are each drawn often and are *never* drawn in the
    same run look like an either/or in the physics. At a fixed slice
    depth it is more likely to be the slice: they are competing for the
    last slot, and whichever is larger that run is the one written down.
    Reported so the page can say which pairs are suspect rather than
    leaving a reader to infer an anticorrelation.
    """
    v = [r for r in rows if r.get("fws") == fws]
    if not v:
        return []
    counts = collections.Counter(b for r in v for b, _x, _z in r["sites"])
    common = [b for b, k in counts.items() if k >= 0.2 * len(v)]
    out = []
    for i, a in enumerate(sorted(common)):
        for b in sorted(common)[i + 1:]:
            both = sum(1 for r in v
                       if {a, b} <= {p for p, _x, _z in r["sites"]})
            if both == 0 and counts[a] + counts[b] >= len(v):
                out.append({"a": a, "b": b, "a_n": counts[a],
                            "b_n": counts[b], "both": both, "of": len(v),
                            "depth": depth})
    return out


#: Draws for the page's permutation nulls. Lower than the tool's own
#: default because the page is regenerated often and the figures it
#: quotes are 1e-3 at coarsest; the tool is where a finer number is
#: taken.
#:
#: `ISSUE5_REPORT_NDRAW` lowers it further for the page's own tests,
#: which check structure - that every chart has a mount and every
#: `DATA.<key>` is written - and never read a p-value. At 5000 those two
#: tests cost 17 s of a suite whose Windows run has just exceeded #50's
#: 300 s ceiling, for numbers they do not look at.
PAGE_NDRAW = int(os.environ.get("ISSUE5_REPORT_NDRAW", "5000"))


def build():
    data = {"bins": BINS, "generated_at_repo_rev": repo_rev(),
            "benches": [], "extra": {}, "slot_competition": [],
            "spectrum": {}, "comb_period": None, "crossover": None}
    for meta in BENCHES:
        rows = load(meta["file"])
        entry = dict(meta)
        entry["provenance"] = provenance(rows)
        entry["fws"] = per_fws(rows)
        data["benches"].append(entry)
        for fws in (4, 5, 6):
            depth = entry["fws"].get(str(fws), {}).get(
                "censoring", {}).get("stored_depth", 0)
            for pair in slot_competition(rows, fws, depth):
                pair["bench"] = meta["id"]
                pair["fws"] = fws
                data["slot_competition"].append(pair)
    for label, path in EXTRA:
        rows = load(path)
        f = per_fws(rows)
        data["extra"][label] = {
            "file": path, "provenance": provenance(rows),
            "fws": {k: {kk: v[kk] for kk in
                        ("n", "median_total", "median_sites", "median_rest",
                         "rows_at_6_site_cap", "censoring")}
                    for k, v in f.items()}}
    # The frequency-domain reading, per bench per wait state, plus the
    # cross-wait-state view on one period. Derived here so the page and
    # `tools/issue5_spectrum.py` cannot disagree: the page imports the
    # tool rather than re-implementing it.
    period, best_r = None, None
    for meta in BENCHES:
        rows = load(meta["file"])
        per = {}
        for fws in (4, 5, 6):
            a = spec.analyse(rows, fws, ndraw=PAGE_NDRAW)
            if a is None:
                continue
            a.pop("spectrum", None)          # 129 numbers a row, not drawn
            # THE COMB IS THE LARGE POPULATION, NOT THE SITE SET. On the
            # truncated rows this distinction was invisible: a row stored
            # its six strongest sites and those six are the large ones, so
            # "the site set is a comb" and "the large sites are a comb"
            # were the same sentence. With whole site lists they are not -
            # FWS 6 has 30+ strong positions and a scan over all of them
            # returns period 3, because the ~2-code population is
            # scattered. Sites are split at 10 codes: the two populations
            # sit at about 29 and 2, so the cut has a five-fold margin
            # either side and is not fitted.
            v6 = [r for r in rows if r["fws"] == fws]
            big = [b for b in a["strong"]
                   if statistics.median(
                       [abs(r["profile"][b] - statistics.median(r["profile"]))
                        for r in v6]) >= 10.0]
            a["large_sites"] = big
            if len(big) >= 3:
                r, p_ = spec.best_comb(big)
                a["large_comb"] = {
                    "period": p_, "R": round(r, 4), "n": len(big),
                    "p_value": spec.comb_pvalue(big, ndraw=PAGE_NDRAW)}
                # Pin the period by the best R across arms, not by
                # demanding R = 1. The R = 1.000 that this campaign
                # published came from the SIX sites a truncated row
                # stored - which are by construction the six strongest
                # and happen to lie on the lattice. On the true large
                # population, 9 or 10 positions, two of them (169 and
                # 247) are OFF it, so R is 0.75 to 0.94 and the comb is
                # 8 of 10 rather than all of them.
                if best_r is None or r > best_r:
                    best_r, period = r, p_
            per[str(fws)] = a
        data["spectrum"][meta["id"]] = {
            "by_fws": per,
            "cross": spec.across_fws({f: spec.analyse(rows, f, ndraw=0)
                                      for f in (4, 5, 6)}),
        }
    data["comb_period"] = period
    data["comb_best_R"] = round(best_r, 4) if best_r is not None else None
    data["predicted_missing"] = (
        spec.predict_missing([12, 33, 117, 138, 159, 180], period)
        if period else None)

    # The crossover, charted on the two SUMS rather than per position.
    #
    # A per-position chart would have to implement the two-state guard to
    # be honest: at FWS 4 position 240 the untouched board's drift is 3.75
    # read as a pooled median and 0.29 read as size-when-large, because
    # its run COUNT moved while its size held. Charting the pooled median
    # there would show a tolerance thirteen times too wide and call a real
    # change noise. The guard belongs to mac-bench's file and the
    # decomposition to windows-desk's, so this page shows the two sums -
    # which are agreed, well defined and have a measured tolerance - and
    # leaves per-position readings to #5.
    def combs(path, drop31=False):
        rows = [r for r in load(path)
                if r["fws"] == 6 and not (drop31 and r["run"] == 31)]
        return {"seven": round(comb_sum(rows, spec_lattice7()), 2),
                "twelve": round(comb_sum(rows, spec_lattice12()), 2),
                "total": round(statistics.median(
                    [r["total_abs"] for r in rows]), 1),
                "n": len(rows)}

    cross = {"boards": []}
    for name, w0, w1, w2, files in CROSSOVER:
        legs = []
        for i, f in enumerate(files):
            c = combs(f, drop31=(name == "linux-x1" and i == 0))
            c["wire"] = (w0, w1, w2)[i]
            c["leg"] = ("baseline", "swapped", "returned")[i]
            legs.append(c)
        cross["boards"].append({"id": name, "legs": legs,
                                "untouched": name == "mac-bench"})
    # The control's own movement across the same three legs is the
    # tolerance every other number here is read against.
    ctl = [b for b in cross["boards"] if b["untouched"]][0]["legs"]
    cross["tolerance"] = {
        k: round(max(abs(ctl[1][k] - ctl[0][k]), abs(ctl[2][k] - ctl[1][k])), 2)
        for k in ("seven", "twelve")}
    data["crossover"] = cross

    rep = load(REPEAT_RING["file"])
    ring = [r["total_abs"] for r in rep if r.get("fws") == REPEAT_RING["fws"]]
    data["repeat_ring"] = dict(REPEAT_RING, median_total=med(ring),
                               n=len(ring))
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", default=DEFAULT_OUT)
    ap.add_argument("--data-only", action="store_true",
                    help="print the derived data as JSON and stop - what "
                         "the page draws, without the page")
    args = ap.parse_args()

    data = build()
    blob = json.dumps(data, separators=(",", ":"), sort_keys=False)
    if args.data_only:
        print(json.dumps(data, indent=1))
        return 0

    with open(TEMPLATE, encoding="utf-8") as fh:
        page = fh.read()
    if "__ISSUE5_DATA__" not in page:
        sys.exit(f"{TEMPLATE}: no __ISSUE5_DATA__ placeholder")
    page = page.replace("__ISSUE5_DATA__", blob)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"wrote {args.out}  ({len(page)} bytes, "
          f"{len(data['benches'])} benches, repo_rev "
          f"{data['generated_at_repo_rev']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
