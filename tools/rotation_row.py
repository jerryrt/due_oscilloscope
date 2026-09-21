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

THE IMAGE MAY BE PINNED. The rotation runs every board on ONE image,
matched by artifact hash, while the tree keeps moving for tools and
docs - so `--image-rev d25f9e3` says which commit the board must carry
and the tree's own revision is then recorded beside it rather than
demanded of the board. Without it the image must be the tree's, which
is the right rule for a bench's own image.

THE TAIL TOOL'S EXIT CODE IS NOT SWALLOWED. tools/issue82_arms.py
raised before printing a line on mac-bench, and the first version of
this tool returned its output regardless, so a crashed sub-tool became
an empty measurement and the row exited 0 - a silent partial row. The
row is still written, because the census is the registered comparison,
but its `tail_scale_status` says what happened, the summary line says
`scale MISSING`, and the exit code is 3. One recoverable case is
retried: a "hold parity is a tie" on a quiet board, where the two
parities fit equally because the holds barely move; the tool is run
again with `--parity 0` and the row says so.

EXIT CODES
    0   row written, every measurement present
    2   refused - nothing written; the reason is on stderr
    3   row written, but the tail scale is MISSING; status in the row
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
    # The tool prints the per-threshold rates as a dict WITH SPACES -
    # `A0 tail/s {6: 663.3, 10: 133.4, 15: 34.4} scale 2.27` - so the
    # rates are matched as a brace group, not as a run of non-blanks;
    # the first version of this pattern used \S+ and matched nothing on
    # a real line, and the first rotation row went out with no scale.
    r"^(?P<arm>\S+)\s+run (?P<run>\d+): A0 tail/s \{[^}]*\} scale (?P<a0>[\d.]+)"
    r"\s+A1 tail/s \{[^}]*\} scale (?P<a1>[\d.]+)", re.M)


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


def _run_tail_scale(python, bench, extra=()):
    """(returncode, stdout+stderr) of the tail tool - the code travels
    with the text, because a crash that prints nothing must not read as
    a measurement that found nothing."""
    r = subprocess.run([python, os.path.join(ROOT, "tools", "issue82_arms.py"),
                        "-n", "2", "--bench", bench, *extra],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


PARITY_TIE = "hold parity is a tie"


def take_tail_scale(run_tail_scale, python, bench):
    """The tail tool, once, plus one retry on the tie it cannot
    otherwise get past; returns (scales, status, raw, parity_forced)."""
    rc, text = run_tail_scale(python, bench)
    forced = None
    if rc != 0 and PARITY_TIE in text:
        # A quiet board's holds barely move, so both parities fit the
        # pair spread equally and the tie check cannot tell ambiguous
        # from still. The tool now takes the parity from the command
        # line; 0 is the answer that fits as well as 1 when it is a tie.
        forced = 0
        rc, text2 = run_tail_scale(python, bench, ("--parity", "0"))
        text = text + "\n---- retry with --parity 0 ----\n" + text2
    scales = parse_scales(text)
    if rc != 0:
        last = [l for l in text.strip().splitlines() if l.strip()]
        status = f"tool exit {rc}: {last[-1].strip() if last else ''}"
    elif not scales:
        status = "exit 0 but no scale line parsed"
    else:
        status = "ok" if forced is None else "ok, parity forced 0 after a tie"
    return scales, status, text, forced


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
    want = args.image_rev or rev
    if ident.get("build") != want:
        if args.image_rev:
            raise Refused(f"the image says build={ident.get('build')!r} and "
                          f"the rotation image is pinned at {want}: flash "
                          "the pinned image, so the six cells are one image")
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

    scales, scale_status, scale_text, forced = take_tail_scale(
        run_tail_scale, args.python, bench)

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
        "tail_scale_status": scale_status,
        "tail_scale_parity_forced": forced,
        "image_rev_pinned": args.image_rev,
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
    ap.add_argument("--image-rev", default=None, metavar="REV",
                    help="the pinned rotation image's commit; the board "
                         "must carry it, and the tree may be ahead of it")
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
    missing = not row["tail_scale"]
    scales = (f"scale MISSING ({row['tail_scale_status']})" if missing
              else f"scales {[x['a0_scale_codes'] for x in row['tail_scale']]}")
    print(f"rotation {row['phase']} {row['bench']} serial {row['board_serial']} "
          f"uid {row['board_uid']} idle {row['idle_before_s']}s: largest "
          f"{s.get('largest_min')}-{s.get('largest_max')} (median "
          f"{s.get('largest_median')}), count {s.get('count_min')}-"
          f"{s.get('count_max')}, n={s.get('n')}; {scales}; die "
          f"{[t['code'] for t in row['temperatures']]} -> {args.out}")
    if missing:
        print("rotation_row: the row is written but its tail scale is "
              f"MISSING: {row['tail_scale_status']}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
