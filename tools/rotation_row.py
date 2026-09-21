#!/usr/bin/env python3
"""One machine-comparable row for the board-rotation experiment.

    .venv/bin/python tools/rotation_row.py --phase before --idle-seconds 1200
    .venv/bin/python tools/rotation_row.py --phase after  --idle-seconds 1200 \
        --note "board arrived from mac-bench"

Three boards rotate across three benches, and the question is whether a
converter tail follows the board or stays with the bench. That is a
six-cell table, and each cell is six census runs, a tail scale, three
die-temperature reads, an identity line and the bench's conditions -
about thirty figures a bench would otherwise copy by hand out of six
pytest logs. Hand-copied lines are how the wrap-displacement comparison
went wrong for four sessions: figures that only agreed after someone
adjusted them, and figures nobody could trace to the run that produced
them. So one command takes the cell and writes one row.

WHAT A ROW REFUSES, because a rotation row nobody can attribute is worse
than none: no programming port (no `board_serial`); a dirty tree (the
image carries a delta hash no other bench can match); a board that is
not Track B; an image whose `build` is not the tree's own commit; and a
run whose idle time was not declared - `--idle-seconds` is required
even when it is 0, because the whole afternoon that led here was a warm
board read as a different board, and the state a rested figure was
taken in must be said, never assumed.

The census runs are the #87 protocol exactly - pytest as a subprocess,
the same node id, `-rA` so the `census:` line is captured on a pass -
and the aggregation drops run 1 BY INDEX, the documented rule, with the
full six kept beside the n=5 summary so nobody has to trust the drop.
The tail scale comes from tools/issue82_arms.py, whose own rows go to
its default file; the scale figures are read off its stdout and the
path it wrote is recorded.

Every step's raw output stays in the row. The row is appended to
records/rotation.jsonl and is the record; the printed line is a
courtesy.
"""

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))

SCHEMA = "rotation/1"
OUT = os.path.join(ROOT, "records", "rotation.jsonl")
CENSUS_TEST = ("tests/test_integrity.py::"
               "test_device_generated_waveform_is_continuous")
PHASES = ("before", "after")

_CENSUS = re.compile(
    r"^census: (?P<count>\d+) steps > (?P<threshold>\d+) codes "
    r"\(allowance (?P<allowance>\d+)\), largest (?P<largest>[\d.]+), "
    r"gap (?P<gap_lo>\d+)\.\.(?P<gap_hi>\d+), fold z (?P<fold_z>[\d.]+) "
    r"control (?P<fold_control_z>[\d.]+) peak (?P<fold_peak>-?[\d.]+)\s*$",
    re.M)
_VERDICT = re.compile(r"^(?:=+ )?(\d+) (passed|failed)\b", re.M)
_SCALE = re.compile(
    r"^(?P<arm>\S+)\s+run (?P<run>\d+): A0 tail/s \S+ scale (?P<a0>[\d.]+)"
    r"\s+A1 tail/s \S+ scale (?P<a1>[\d.]+)", re.M)


def parse_census(text):
    """The `census:` line as numbers, plus the verdict; None if absent.

    The line is printed on every run since 27d6a38, pass or fail, and
    only reaches stdout under -rA on a pass - which is why the census
    command below carries that flag.
    """
    m = _CENSUS.search(text)
    if not m:
        return None
    row = {k: (float(v) if "." in v or k in ("largest", "fold_z",
                                             "fold_control_z", "fold_peak")
               else int(v))
           for k, v in m.groupdict().items()}
    v = _VERDICT.findall(text)
    row["verdict"] = v[-1][1] if v else None
    row["line"] = m.group(0).strip()
    return row


def summarise(census_rows):
    """The n-1 summary: run 1 dropped BY INDEX, never by value.

    The first run after a flash or a rest is the documented outlier on
    every bench, and it has been dropped by a filter on what it was
    thought to do wrong before - which let a first run that happened to
    look normal survive into four analyses. Index, not value.
    """
    kept = [r for r in census_rows[1:] if r]
    if not kept:
        return {"n": 0}
    largest = [r["largest"] for r in kept]
    count = [r["count"] for r in kept]
    return {
        "n": len(kept),
        "dropped": "run 1 by index",
        "largest_min": min(largest), "largest_median": statistics.median(largest),
        "largest_max": max(largest),
        "count_min": min(count), "count_median": statistics.median(count),
        "count_max": max(count),
        "verdicts": [r["verdict"] for r in kept],
    }


def parse_scales(text):
    return [{"arm": m["arm"], "run": int(m["run"]),
             "a0_scale_codes": float(m["a0"]), "a1_scale_codes": float(m["a1"])}
            for m in _SCALE.finditer(text)]


# --- the hardware steps, each replaceable for a test -----------------------

def _board_steps():
    """Identity, three temperature reads and the conditions, on an open
    board, then the board closed so the census subprocesses can have it."""
    import measure
    import provenance
    board = measure.Board(settle=3.0)
    try:
        board.stop()
        board.drain_console(0.5)
        text = board.ask("v", secs=1.0)
        ident = measure.parse_identity(text)
        temps = []
        link = board.ctl()
        for i in range(3):
            if i:
                time.sleep(10.0)
            t = link.temperature(samples=256)
            temps.append({"code": t.get("code"), "code_min": t.get("code_min"),
                          "code_max": t.get("code_max"),
                          "samples": t.get("samples"),
                          "adc_mr": t.get("adc_mr"), "adc_acr": t.get("adc_acr"),
                          "dev_us": t.get("dev_us")})
        cond = provenance.conditions(board=board, ident=ident)
    finally:
        try:
            board.stop()
        finally:
            board.close()
    return {"identity_line": text.strip(), "ident": ident, "temperatures": temps,
            "conditions": cond}


def _run_census(python):
    r = subprocess.run([python, "-m", "pytest", "--track=b", "-m", "board",
                        "-q", "-p", "no:cacheprovider", "-rA", CENSUS_TEST],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.stdout + r.stderr


def _run_tail_scale(python, bench):
    r = subprocess.run([python, os.path.join(ROOT, "tools", "issue82_arms.py"),
                        "-n", "2", "--bench", bench],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.stdout + r.stderr


class Refused(Exception):
    pass


def collect_row(args, board_steps=None, run_census=None, run_tail_scale=None):
    """The whole cell, in protocol order; raises Refused with the reason.

    The three hardware steps resolve at call time so a test can replace
    them on the module and still go through main().
    """
    board_steps = board_steps or _board_steps
    run_census = run_census or _run_census
    run_tail_scale = run_tail_scale or _run_tail_scale
    steps = board_steps()
    cond = steps["conditions"]
    ident = steps["ident"] or {}

    if not cond.get("board_serial"):
        raise Refused("no programming port enumerated, so no board_serial: "
                      "a rotation row that cannot say which Due wrote it is "
                      "worse than none")
    rev = cond.get("repo_rev") or ""
    if not rev or "-dirty" in rev or "+" in rev:
        raise Refused(f"repo_rev is {rev!r}: the tree is dirty, so the image "
                      "carries a delta hash no other bench can match. Commit "
                      "or stash, rebuild, reflash, then take the row")
    if ident.get("track") != "b":
        raise Refused(f"the board answers track={ident.get('track')!r}; the "
                      "rotation is Track B on every bench")
    if ident.get("build") != rev:
        raise Refused(f"the image says build={ident.get('build')!r} and the "
                      f"tree is {rev}: flash this tree's image first, so the "
                      "six cells are one image")

    bench = args.bench or cond.get("bench")
    census_text = []
    census = []
    for i in range(6):
        text = run_census(args.python)
        census_text.append(text)
        c = parse_census(text)
        if c:
            c["run"] = i + 1
        census.append(c)

    scale_text = run_tail_scale(args.python, bench)
    scales = parse_scales(scale_text)

    return {
        "schema": SCHEMA,
        "tool": "tools/rotation_row.py",
        "taken_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "phase": args.phase,
        "idle_before_s": args.idle_seconds,
        "note": args.note,
        "bench": bench,
        "board_serial": cond.get("board_serial"),
        "board_uid": ident.get("uid"),
        "identity_line": steps["identity_line"],
        "identity": ident,
        "temperatures": steps["temperatures"],
        "census": census,
        "census_summary": summarise(census),
        "census_raw": census_text,
        "tail_scale": scales,
        "tail_scale_rows_went_to":
            f"records/issue82-arms-{bench}.jsonl (that tool's default)",
        "tail_scale_raw": scale_text,
        "conditions": cond,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", choices=PHASES, required=True,
                    help="before the board moved, or after it arrived")
    ap.add_argument("--idle-seconds", type=int, required=True,
                    help="how long the board sat idle before this row; 0 "
                         "is allowed and is recorded as 0")
    ap.add_argument("--note", default="",
                    help='free text, e.g. "board arrived from mac-bench"')
    ap.add_argument("--bench", default=None,
                    help="override the bench name conditions() declares")
    ap.add_argument("--python", default=sys.executable,
                    help="interpreter for the census and tail-scale "
                         "subprocesses (default: this one)")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)
    if args.idle_seconds < 0:
        ap.error("--idle-seconds must be 0 or more")

    try:
        row = collect_row(args)
    except Refused as e:
        print(f"rotation_row: refused: {e}", file=sys.stderr)
        return 2

    with open(args.out, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    s = row["census_summary"]
    print(f"rotation {row['phase']} {row['bench']} serial {row['board_serial']} "
          f"uid {row['board_uid']} idle {row['idle_before_s']}s: largest "
          f"{s.get('largest_min')}-{s.get('largest_max')} (median "
          f"{s.get('largest_median')}), count {s.get('count_min')}-"
          f"{s.get('count_max')}, n={s.get('n')}; scales "
          f"{[x['a0_scale_codes'] for x in row['tail_scale']]}; die "
          f"{[t['code'] for t in row['temperatures']]} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
