#!/usr/bin/env python3
"""How much of a held-code noise or SINAD figure is the station, not the board.

A noise or SINAD bound written from one clean board's best runs says
nothing about how much a re-seated jumper, a probe on the pin or a second
session moves the figure, and that has to be known before a bound can be
set for many boards. This measures it: the same two figures the board
tier gates (`tests/test_noise_board.py`, `tests/test_sinad_board.py`),
taken repeatedly under a named *condition*, so the spread inside a
condition (runs) and between conditions (re-seats, probes on or off)
can be compared.

    sudo .venv/bin/python tools/station_repeat.py run --label seat1 --runs 7
    .venv/bin/python tools/station_repeat.py summary

`run` appends one JSON line per run and rc to
`records/station-repeat-<host>.jsonl`; nothing is dropped at record time.
`summary` drops run 1 of every (label, rc) by index - the first run after
a start is an outlier here, and a filter on what it looks like would let
a quiet one through - and reports mean, sd and range per condition, then
the spread of the condition means.

The label is whatever the person changed: `seat1`, `probes-off`. The tool
does not know the wiring; the row carries the board's uid, build and
the host, and the label says the rest.
"""
import argparse
import json
import math
import os
import platform
import statistics
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.path.insert(0, os.path.join(HERE, "tests"))

CODE = 2048
WINDOW = 4096
# The figures a row carries, per measurement. Everything else the
# analysis returns is left out so two rows are always comparable.
NOISE_KEYS = ("rms_lsb", "split.line_power_fraction", "n_lines")
SINAD_KEYS = ("sinad_db", "enob", "thd_db", "noise_floor_rms_lsb",
              "signal_rms_lsb")


def default_path():
    host = platform.node().split(".")[0] or "host"
    return os.path.join(HERE, "records", f"station-repeat-{host}.jsonl")


def _pick(d, keys):
    return {k: d.get(k) for k in keys}


def measure_once(board, rc):
    """One noise run and one SINAD run at ADC rate code `rc`."""
    import noise_metrics as nm
    import pacing
    flat = nm._run(board, CODE, pacing.SHORT, WINDOW, preset="5", rc=rc)
    sin = nm.sinad_once(board, rc)
    return {"noise": _pick(flat, NOISE_KEYS), "sinad": _pick(sin, SINAD_KEYS)}


def cmd_run(args):
    import measure
    import provenance
    path = args.out or default_path()
    rcs = [measure.rc_for(200000), 86]
    board = measure.Board(settle=3.0)
    try:
        cond = provenance.conditions(board=board, tool="station_repeat")
        with open(path, "a", encoding="utf-8") as fh:
            for run in range(1, args.runs + 1):
                for rc in rcs:
                    row = {"label": args.label, "run": run, "rc": rc,
                           "t": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                           "note": args.note}
                    row.update(measure_once(board, rc))
                    row["conditions"] = cond
                    fh.write(json.dumps(row) + "\n")
                    fh.flush()
                    n, s = row["noise"], row["sinad"]
                    print(f"{args.label} run {run} rc {rc}: "
                          f"rms {n['rms_lsb']:.3f}  "
                          f"sinad {s['sinad_db']:.2f} dB", flush=True)
    finally:
        board.close()
    print(f"# appended to {path}")


def summarise(rows):
    """{(label, rc): {metric: stats}} with run 1 of each group dropped."""
    groups = {}
    for r in rows:
        groups.setdefault((r["label"], r["rc"]), []).append(r)
    out = {}
    for key, rs in groups.items():
        kept = [r for r in rs if r["run"] != 1]
        stats = {"n": len(kept)}
        for part, keys in (("noise", ("rms_lsb",)),
                           ("sinad", ("sinad_db", "noise_floor_rms_lsb"))):
            for k in keys:
                vals = [r[part][k] for r in kept
                        if r[part].get(k) is not None
                        and not math.isnan(r[part][k])]
                if not vals:
                    continue
                stats[k] = {
                    "mean": statistics.fmean(vals),
                    "sd": statistics.stdev(vals) if len(vals) > 1 else 0.0,
                    "min": min(vals), "max": max(vals)}
        out[key] = stats
    return out


def between(summary, metric):
    """Spread of the condition means, per rc: the station's re-seat term."""
    per_rc = {}
    for (label, rc), st in summary.items():
        if metric in st:
            per_rc.setdefault(rc, []).append(st[metric]["mean"])
    return {rc: (statistics.stdev(v) if len(v) > 1 else 0.0, len(v))
            for rc, v in per_rc.items()}


def cmd_summary(args):
    path = args.out or default_path()
    with open(path, encoding="utf-8") as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
    summary = summarise(rows)
    print(f"# {path}: {len(rows)} rows, run 1 of each condition dropped")
    for metric in ("rms_lsb", "sinad_db", "noise_floor_rms_lsb"):
        print(f"\n{metric}")
        print(f"  {'label':<14}{'rc':>5}{'n':>3}{'mean':>9}{'sd':>8}"
              f"{'min':>9}{'max':>9}")
        for (label, rc), st in sorted(summary.items()):
            if metric in st:
                m = st[metric]
                print(f"  {label:<14}{rc:>5}{st['n']:>3}{m['mean']:>9.3f}"
                      f"{m['sd']:>8.3f}{m['min']:>9.3f}{m['max']:>9.3f}")
        for rc, (sd, k) in sorted(between(summary, metric).items()):
            print(f"  sd of {k} condition means at rc {rc}: {sd:.3f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="measure under one named condition")
    r.add_argument("--label", required=True)
    r.add_argument("--runs", type=int, default=7,
                   help="n+1: run 1 is dropped by the summary")
    r.add_argument("--note", default="")
    r.add_argument("--out")
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("summary", help="spread within and between conditions")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_summary)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
