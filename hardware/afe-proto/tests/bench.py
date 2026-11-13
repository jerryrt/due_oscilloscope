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
            steps.append((board, tool["tool"], [a.replace("{board}", path) for a in tool["argv"]]))
    for g in cfg["global"]:
        steps.append((g["board"], g["tool"], g["argv"]))
    return steps


def measure(board, tool, argv, runs, mem, timeout):
    outs = [B.run_step(f"{tool}@{board}", argv, mem=mem, timeout=timeout, cwd=REPO) for _ in range(runs + 1)]
    kept = outs[1:]                                    # run 0 dropped by index
    bad = [o for o in kept if o.kind != "OK"]
    row = {"board": board, "tool": tool, "runs": runs, "dropped_first": True}
    if bad:
        row.update(status=bad[0].kind, detail=bad[0].detail or bad[0].result.stderr.strip()[-200:])
        return row
    walls = [o.wall_s for o in kept]
    peaks = [o.peak_rss_kb for o in kept]
    row.update(status="OK",
               wall_s=dict(median=statistics.median(walls), min=min(walls), max=max(walls)),
               peak_rss_kb=dict(median=int(statistics.median(peaks)), min=min(peaks), max=max(peaks)))
    return row


def md(meta, rows):
    lines = [f"# AFE tool bench", "",
             f"image `{meta['image'][:12]}…` installed `{meta['installed'][:12]}…` · machine {meta['machine']} · "
             f"KiCad {meta['versions']['kicad']} · ngspice {meta['versions']['ngspice']} · "
             f"Python {meta['versions']['python']} · numpy {meta['versions']['numpy']} · "
             f"{meta['runs']} runs per step, first dropped by index", "",
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
    return {"meta": {k: meta[k] for k in ("image", "installed", "machine", "versions", "runs")} | {"margin": margin,
            "rule": "median of the measured runs times margin"}, "budgets": b}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--margin", type=float, default=1.5)
    ap.add_argument("--mem", default="3G")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--only", help="substring of tool name")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    cfg = json.loads((HERE / "bench_steps.json").read_text())
    meta = {"image": os.environ.get("DUE_PCB_IMAGE_CONTENT", "unknown"),
            "installed": os.environ.get("DUE_PCB_IMAGE_INSTALLED", "unknown"),
            "machine": os.environ.get("DUE_PCB_MACHINE", "unknown"), "versions": versions(), "runs": a.runs}
    rows = []
    stage = stage_fixtures()
    for board, tool, argv in expand(cfg, stage):
        if a.only and a.only not in tool:
            continue
        r = measure(board, tool, argv, a.runs, a.mem, a.timeout)
        print(json.dumps(r), flush=True)
        rows.append(r)
    import shutil
    shutil.rmtree(stage, ignore_errors=True)
    if not rows:
        sys.exit("bench: no step selected")                    # a bench that measured nothing is not a pass
    if a.write:
        (HERE / "bench-results.json").write_text(json.dumps({"meta": meta, "rows": rows}, indent=1) + "\n")
        (HERE / "bench-results.md").write_text(md(meta, rows))
        (HERE / "budgets.json").write_text(json.dumps(budgets(meta, rows, a.margin), indent=1) + "\n")
    bad = [r for r in rows if r["status"] != "OK"]
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
