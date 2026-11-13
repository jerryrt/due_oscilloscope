#!/usr/bin/env python3
"""Measure every tool on every board and write the committed table and the budgets.

    docker/pcb/run.sh -m 3G -t 3000 python3 hardware/afe-proto/tests/bench.py [--runs 5] [--margin 1.5] [--write]

Each step runs RUNS+1 times under the capped runner; run 0 is dropped BY INDEX (the first run after
a start is an outlier, and a filter on what it "looks like" is not enough). The row records the
median, min and max of wall time and peak RSS, the image id, the tool versions and the machine.
Steps that fail, crash, are killed or time out are recorded as such and never averaged in.

With --write the results go to tests/bench-results.json and bench-results.md, and the budgets to
tests/budgets.json: each budget is the measured median times the margin (a stated number, default
1.5), keyed by board and tool, with the image and machine it was measured on. A budget is only
ever set from a run that was clean; tests/test_budget_file.py checks the file against its steps.
"""
import argparse
import json
import math
import os
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
from simtools import budget as B  # noqa: E402


def versions():
    out = {"python": ".".join(map(str, sys.version_info[:3]))}
    try:
        import numpy
        out["numpy"] = numpy.__version__
    except ImportError:
        out["numpy"] = None
    try:
        import scipy
        out["scipy"] = scipy.__version__
    except ImportError:
        out["scipy"] = None
    r = B.capped.subprocess.run(["kicad-cli", "version"], capture_output=True, text=True)
    out["kicad"] = r.stdout.strip() or None
    r = B.capped.subprocess.run(["ngspice", "-v"], capture_output=True, text=True)
    import re
    m = re.search(r"ngspice-([\d.]+)", r.stdout + r.stderr)
    out["ngspice"] = m.group(1) if m else None
    return out


FIXTURES = "hardware/afe-proto/tests/fixtures"


def stage_fixtures():
    """Copy the fixtures to a temp tree. kicad-cli writes a .kicad_prl (and a lock) beside whatever board
    it opens, and the fixtures are checked against a manifest: a bench run must leave them as found."""
    import shutil
    import tempfile
    stage = Path(tempfile.mkdtemp(prefix="bench-fixtures-"))
    shutil.copytree(REPO / FIXTURES, stage / "fixtures")
    return stage


def expand(cfg, stage):
    def fix(a):
        return a.replace(FIXTURES, str(stage / "fixtures"))
    cfg = json.loads(json.dumps(cfg))
    cfg["boards"] = {k: fix(v) for k, v in cfg["boards"].items()}
    for t in cfg["per_board"] + cfg["global"]:
        t["argv"] = [fix(a) for a in t["argv"]]
    steps = []
    for tool in cfg["per_board"]:
        for board, path in cfg["boards"].items():
            steps.append((board, tool["tool"], [a.replace("{board}", path) for a in tool["argv"]], tool.get("expect_exit", 0)))
    for g in cfg["global"]:
        steps.append((g["board"], g["tool"], g["argv"], g.get("expect_exit", 0)))
    return steps


def measure(board, tool, argv, runs, mem, timeout, expect_exit=0):
    outs = [B.run_step(f"{tool}@{board}", argv, mem=mem, timeout=timeout, cwd=REPO, expect_exit=expect_exit)
            for _ in range(runs + 1)]
    kept = outs[1:]                                    # run 0 dropped by index
    bad = [o for o in kept if o.kind != "OK"]
    row = {"board": board, "tool": tool, "runs": runs, "dropped_first": True}
    if expect_exit:
        row["expect_exit"] = expect_exit
    if bad:
        row.update(status=bad[0].kind, detail=bad[0].detail or bad[0].result.stderr.strip()[-200:])
        return row
    walls = [o.wall_s for o in kept]
    peaks = [o.peak_rss_kb for o in kept]
    row.update(status="OK",
               wall_s=dict(median=statistics.median(walls), min=min(walls), max=max(walls)),
               peak_rss_kb=dict(median=int(statistics.median(peaks)), min=min(peaks), max=max(peaks)))
    return row


def measure_pair(board, old, new, runs, mem, timeout):
    """Interleaved old, new, old, new, ...: run 0 of each dropped by index; ratios are of the per-arm medians and
    also per adjacent (old, new) pair, so a load spike shows as a wide range rather than a wrong median."""
    (otool, oargv, oexp), (ntool, nargv, nexp) = old, new
    oo, nn = [], []
    for _ in range(runs + 1):
        oo.append(B.run_step(f"{otool}@{board}", oargv, mem=mem, timeout=timeout, cwd=REPO, expect_exit=oexp))
        nn.append(B.run_step(f"{ntool}@{board}", nargv, mem=mem, timeout=timeout, cwd=REPO, expect_exit=nexp))
    oo, nn = oo[1:], nn[1:]
    if any(o.kind != "OK" for o in oo + nn):
        bad = next(o for o in oo + nn if o.kind != "OK")
        return None, None, {"board": board, "old": otool, "new": ntool, "status": bad.kind, "detail": bad.detail}
    def row(tool, outs, exp):
        r = {"board": board, "tool": tool, "runs": runs, "dropped_first": True, "interleaved_with": (ntool if tool == otool else otool),
             "status": "OK",
             "wall_s": dict(median=statistics.median(o.wall_s for o in outs), min=min(o.wall_s for o in outs), max=max(o.wall_s for o in outs)),
             "peak_rss_kb": dict(median=int(statistics.median(o.peak_rss_kb for o in outs)), min=min(o.peak_rss_kb for o in outs), max=max(o.peak_rss_kb for o in outs))}
        if exp:
            r["expect_exit"] = exp
        return r
    ro, rn = row(otool, oo, oexp), row(ntool, nn, nexp)
    per = [o.wall_s / n.wall_s for o, n in zip(oo, nn)]
    pair = {"board": board, "old": otool, "new": ntool, "status": "OK",
            "wall_ratio_old_over_new": {"median": statistics.median(per), "min": min(per), "max": max(per)},
            "peak_ratio_old_over_new": ro["peak_rss_kb"]["median"] / rn["peak_rss_kb"]["median"]}
    return ro, rn, pair


def md_pairs(pairs):
    out = ["", "## Old / new, interleaved", "",
           "Measured alternately (old, new, old, new, ...) in one run so machine load hits both arms alike: **quote the ratios, not the "
           "absolute wall times** (those are from a loaded machine). Ratio = old / new, so above 1 the new tool is faster or smaller.", "",
           "| board | old | new | wall ratio median (min–max) | peak RSS ratio |", "|---|---|---|---|---|"]
    for p in pairs:
        if p["status"] != "OK":
            out.append(f"| {p['board']} | {p['old']} | {p['new']} | **{p['status']}** | |")
        else:
            w = p["wall_ratio_old_over_new"]
            out.append(f"| {p['board']} | {p['old']} | {p['new']} | {w['median']:.2f} ({w['min']:.2f}–{w['max']:.2f}) | {p['peak_ratio_old_over_new']:.2f} |")
    return "\n".join(out) + "\n"


def md(meta, rows):
    lines = [f"# AFE tool bench", "",
             f"image `{meta['image'][:12]}…` installed `{meta['installed'][:12]}…` · machine {meta['machine']} · "
             f"KiCad {meta['versions']['kicad']} · ngspice {meta['versions']['ngspice']} · "
             f"Python {meta['versions']['python']} · numpy {meta['versions']['numpy']} · "
             f"{meta['runs']} runs per step, first dropped by index"
             + (f" · remeasured in a later run in the same image: {', '.join(meta['remeasured_later'])}" if meta.get("remeasured_later") else ""), "",
             "| board | tool | status | wall median (s) | wall max (s) | peak RSS median (MB) | peak max (MB) |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["status"] != "OK":
            lines.append(f"| {r['board']} | {r['tool']} | **{r['status']}** | | | | |")
        else:
            lines.append(f"| {r['board']} | {r['tool']} | OK | {r['wall_s']['median']:.2f} | {r['wall_s']['max']:.2f} | "
                         f"{r['peak_rss_kb']['median']/1024:.0f} | {r['peak_rss_kb']['max']/1024:.0f} |")
    return "\n".join(lines) + "\n"


def budgets(meta, rows, margin):
    b = {}
    for r in rows:
        if r["status"] != "OK":
            continue
        b.setdefault(r["board"], {})[r["tool"]] = {
            "peak_rss_kb": int(math.ceil(r["peak_rss_kb"]["median"] * margin)),
            "wall_s": round(r["wall_s"]["median"] * margin, 2),
            "machine": meta["machine"]}
    return {"meta": {k: meta[k] for k in ("image", "installed", "machine", "versions", "runs", "remeasured_later") if k in meta} | {"margin": margin,
            "rule": "median of the measured runs times margin"}, "budgets": b}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--margin", type=float, default=1.5)
    ap.add_argument("--mem", default="3G")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--only", help="substring of tool name")
    ap.add_argument("--pairs", action="store_true",
                    help="measure the old/new pairs of bench_steps.json interleaved; replaces those tools' rows and "
                         "adds the ratio table (implies --merge)")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--merge", action="store_true",
                    help="with --only: replace just those rows in the existing results (same image and machine required) "
                         "and record which tools were remeasured in a later run")
    a = ap.parse_args()
    cfg = json.loads((HERE / "bench_steps.json").read_text())
    meta = {"image": os.environ.get("DUE_PCB_IMAGE_CONTENT", "unknown"),
            "installed": os.environ.get("DUE_PCB_IMAGE_INSTALLED", "unknown"),
            "machine": os.environ.get("DUE_PCB_MACHINE", "unknown"), "versions": versions(), "runs": a.runs}
    rows = []
    pair_rows = []
    stage = stage_fixtures()
    if a.pairs:
        a.merge = True
        by = {(b, t): (t, argv, exp) for b, t, argv, exp in expand(cfg, stage)}
        for old_t, new_t in cfg["pairs"]:
            for board in sorted({b for b, t in by if t == old_t} & {b for b, t in by if t == new_t}):
                ro, rn, pr = measure_pair(board, by[(board, old_t)], by[(board, new_t)], a.runs, a.mem, a.timeout)
                print(json.dumps(pr), flush=True)
                pair_rows.append(pr)
                if ro:
                    rows += [ro, rn]
        expanded = []
    else:
        expanded = expand(cfg, stage)
    for board, tool, argv, expect in expanded:
        if a.only and a.only not in tool:
            continue
        r = measure(board, tool, argv, a.runs, a.mem, a.timeout, expect)
        print(json.dumps(r), flush=True)
        rows.append(r)
    import shutil
    shutil.rmtree(stage, ignore_errors=True)
    if not rows and not a.pairs:
        sys.exit("bench: no step selected")                    # a bench that measured nothing is not a pass
    if a.merge:
        old = json.loads((HERE / "bench-results.json").read_text())
        for k in ("image", "installed", "machine"):
            if old["meta"][k] != meta[k]:
                sys.exit(f"bench --merge: {k} differs from the existing results ({old['meta'][k]} vs {meta[k]})")
        again = {(r["board"], r["tool"]) for r in rows}
        keep = [r for r in old["rows"] if (r["board"], r["tool"]) not in again]
        meta["remeasured_later"] = sorted(set(old["meta"].get("remeasured_later", [])) | {t for _, t in again})
        rows = keep + rows
        if not a.pairs:
            pair_rows = old.get("pairs", [])
        else:
            kept_pairs = [p for p in old.get("pairs", []) if (p["board"], p["old"]) not in {(q["board"], q["old"]) for q in pair_rows}]
            pair_rows = kept_pairs + pair_rows
    if a.write and not str(meta["image"]).startswith("sha256:"):
        sys.exit(f"bench: image is {meta['image']!r}, not a pinned digest: refusing to write results or budgets of record "
                 "(run through docker/pcb/run.sh with no DUE_PCB_IMAGE)")
    if a.write:
        (HERE / "bench-results.json").write_text(json.dumps({"meta": meta, "rows": rows, "pairs": pair_rows}, indent=1) + "\n")
        (HERE / "bench-results.md").write_text(md(meta, rows) + (md_pairs(pair_rows) if pair_rows else ""))
        (HERE / "budgets.json").write_text(json.dumps(budgets(meta, rows, a.margin), indent=1) + "\n")
    bad = [r for r in rows if r["status"] != "OK"] + [p for p in pair_rows if p["status"] != "OK"]
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
