#!/usr/bin/env python3
"""Calibrate what each test costs on THIS host, and audit a run against it.

How long a test takes is a property of the host as much as of the test: a
slower USB stack, a busier machine, a different clock all move it. A fixed
margin that is right on one bench is wrong on another, so the budget for a
test is that host's own repeated measurement and its own spread, never a
number written down for all of them.

    pytest --track=b --junitxml=run.xml ...             # a pass, per track
    python3 tools/timing_audit.py calibrate run.xml --bench linux-x1 --track b
    python3 tools/timing_audit.py audit run.xml --bench linux-x1 --track b

`calibrate` appends one row of every test's duration to
records/timing-<bench>-<track>.jsonl. `audit` compares a run against the
rows already there and prints what to look at:

    SLOW   a test over its median by more than its tolerance
    NEW    a test with no calibration, so nothing says what it should cost
    GONE   a calibrated test that did not run

The tolerance is host/repeat.py's - twice the half-width of that test's
own spread, never below a floor - and the first calibration pass is dropped
by index once there are three, as every repeated measurement here is.
Everything it says is a warning: the exit status is 0 unless --strict.
"""
import argparse
import json
import pathlib
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "host"))
import provenance  # noqa: E402
import repeat  # noqa: E402

#: A test is never held to a tighter budget than this, in seconds: below it
#: the spread is the clock and the scheduler, not the test.
FLOOR_S = 0.5
#: Passes needed before the first is dropped and a spread means anything.
MIN_PASSES = 3


def durations(junit_xml):
    """{test id: seconds} of every test that ran, from a JUnit file."""
    out = {}
    for case in ET.fromstring(junit_xml).iter("testcase"):
        if case.find("skipped") is not None:
            continue
        name = f"{case.get('classname', '')}::{case.get('name', '')}"
        out[name] = out.get(name, 0.0) + float(case.get("time", 0.0))
    return out


def record_path(bench, track, root=HERE):
    return pathlib.Path(root) / "records" / f"timing-{bench}-{track}.jsonl"


def load_rows(path):
    p = pathlib.Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def budgets(rows):
    """{test id: (median, tolerance)} from calibration rows.

    The first row is dropped once there are MIN_PASSES, so a test measured
    in two passes has no budget yet rather than one derived from a first run.
    """
    kept = rows[1:] if len(rows) >= MIN_PASSES else []
    series = {}
    for row in kept:
        for test, sec in row["tests"].items():
            series.setdefault(test, []).append(sec)
    out = {}
    for test, vals in series.items():
        stats = repeat.summarise(vals)
        tol = repeat.suggest_tolerance(stats, floor=FLOOR_S)
        if tol is not None:
            out[test] = (stats["median"], tol)
    return out


def audit(run, rows):
    """(findings, total) for a run {test: seconds} against calibration rows."""
    bud = budgets(rows)
    findings = []
    for test, sec in sorted(run.items()):
        if test not in bud:
            findings.append(("NEW", test, sec, None, None))
            continue
        med, tol = bud[test]
        if sec > med + tol:
            findings.append(("SLOW", test, sec, med, tol))
    for test in sorted(set(bud) - set(run)):
        findings.append(("GONE", test, None, bud[test][0], bud[test][1]))
    return findings, sum(run.values())


def row_conditions(bench, track):
    """What a row says about where it was taken: every condition the other
    record writers carry, with the bench and track this run was asked for."""
    rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                         text=True, cwd=HERE).stdout.strip()
    row = dict(provenance.conditions(tool="timing_audit"))
    row.update({"bench": bench, "track": track, "commit": rev})
    return row


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("what", choices=("calibrate", "audit"))
    ap.add_argument("junit")
    ap.add_argument("--bench", required=True)
    ap.add_argument("--track", required=True, choices=("a", "b", "c"))
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the audit has any finding")
    ap.add_argument("--root", default=str(HERE), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    run = durations(pathlib.Path(a.junit).read_text(encoding="utf-8"))
    path = record_path(a.bench, a.track, a.root)
    if a.what == "calibrate":
        row = dict(row_conditions(a.bench, a.track), tests=run)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        n = len(load_rows(path))
        print(f"{len(run)} tests, {sum(run.values()):.0f} s -> {path.name} "
              f"(pass {n}; a budget needs {MIN_PASSES})")
        return 0
    rows = load_rows(path)
    if len(rows) < MIN_PASSES:
        print(f"{path.name} has {len(rows)} pass(es); a budget needs {MIN_PASSES}. "
              "Run `calibrate` on more passes first.")
        return 0
    findings, total = audit(run, rows)
    for kind, test, sec, med, tol in findings:
        if kind == "SLOW":
            print(f"SLOW  {sec:6.1f} s  median {med:5.1f} +{tol:4.1f}  {test}")
        elif kind == "NEW":
            print(f"NEW   {sec:6.1f} s  no calibration          {test}")
        else:
            print(f"GONE         -     median {med:5.1f}            {test}")
    cal = [sum(r["tests"].values()) for r in rows[1:]]
    stats = repeat.summarise(cal)
    tol = repeat.suggest_tolerance(stats, floor=FLOOR_S) or 0.0
    over = total > stats["median"] + tol
    print(f"{len(findings)} finding(s); total {total:.0f} s against this host's "
          f"{stats['median']:.0f} s +{tol:.0f}{'  OVER' if over else ''}")
    return 1 if a.strict and (findings or over) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
