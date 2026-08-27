"""Phase 0: run one metric N times and record what it actually did.

    python3 tools/phase0.py settle --runs 7
    python3 tools/phase0.py settle --runs 7 --axis reflash
    python3 tools/phase0.py settle --runs 7 --axis both
    python3 tools/phase0.py settle --report          # no bench needed

`docs/measurement-suite.md` item 2, and the thing that has to exist
before any figure this project quotes is a baseline rather than a
snapshot. It drives the `dso_metrics` commands unchanged - through
`default_args`, so a recorded number is the same number the CLI prints -
and adds the three things a repeatability run needs and a one-shot does
not.

**A provenance gate.** A run records its conditions or it does not
record. `host/provenance.py` says which fields are required and this
refuses rather than writing something unattributable, because a figure
that outlives the thing it described has cost this project twice.

**Per-run flush.** Every run is on disk, fsynced, before the next one
starts. `--calibrate` wrote at session end, a session hung at 90%, and
twelve minutes of bench time produced nothing at all.

**Both axes, separately.** In place, and across a reflash. Which axis a
metric's tolerance comes from is a *result* of this and not an input to
it: some metrics do not care and interleaving a reflash buys them
nothing, and some change with the binary. The report says which, per
key, as a ratio of the two spreads.

What this deliberately does not do is decide anything. It prints the
spread, and a tolerance that states its own derivation, for a human to
promote into `tests/baseline.json`. Nothing here writes a tolerance into
the baseline: that file is a record under review and this is a machine
with seven data points.
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))
sys.path.insert(0, os.path.join(HERE, "tools"))

import measure                                                # noqa: E402
import provenance as prov                                     # noqa: E402
import repeat                                                 # noqa: E402
import scope as dso                                           # noqa: E402
import dso_metrics as dm                                      # noqa: E402

RECORDS = os.path.join(HERE, "records")

#: The metrics that return a result worth taking a spread of. `shots`
#: writes PNGs and `wrap`/`reload` have their own repeat machinery, so
#: they are not here; adding one is a line, not a design.
METRICS = {
    "settle": dm.cmd_settle,
    "step": dm.cmd_step,
    "skew": dm.cmd_skew,
    "transfer": dm.cmd_transfer,
    "lin": dm.cmd_lin,
    "clock": dm.cmd_clock,
}


def floors_for(metric, records):
    """Resolution floors, taken from the runs themselves.

    A spread finer than the instrument's own quantum is not a property
    of the converter, and a tolerance derived from it would claim a
    precision nothing here has. `settle` reports the sample interval and
    the screen level it measured with, so the floor comes from the same
    capture as the number rather than from a constant somebody tuned
    once - which is how a threshold in samples came to be calibrated
    against a 600-point record and found 17,580 edges in a clean sine.

    Returns `{}` for a metric that does not report its own resolution.
    Better an unfloored tolerance, visibly derived from spread alone,
    than a floor invented to look thorough.
    """
    if metric != "settle":
        return {}
    dt = repeat.summarise(repeat.series(records, "dt_s")).get("median")
    q = repeat.summarise(repeat.series(records, "quantum_v")).get("median")
    floors = {}
    for k in repeat.keys(records):
        if k.endswith(("_s", "_us")) and dt:
            floors[k] = dt
        elif k.endswith("_v") and q:
            floors[k] = q
    return floors


def run_once(board, inst, metric, args):
    """One measurement, with the instrument left as it was found.

    A metric that raises has still changed the scope's vertical and the
    board's generator, and the next run must not inherit either. The
    cleanup is in a `finally` for that reason: a failed run is a data
    point about repeatability and the runs after it have to stay
    comparable.
    """
    try:
        return METRICS[metric](board, inst, args), None
    except SystemExit as e:                       # the metrics' own refusals
        return None, str(e)
    except Exception as e:                                    # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    finally:
        try:
            inst.averaging(None)
            board.stop()
            board.drain_console(0.2)
        except Exception:                                     # noqa: BLE001
            pass


def open_board(track, flash=False, build=False, tries=2):
    """A board, optionally reflashed first.

    Flashing is the across-reflash axis and it is the expensive one:
    every run pays the flash, the re-enumeration and the settle. What it
    buys is the only evidence that says whether a metric's spread is a
    property of the measurement or of the binary.

    A flash that reports success can still leave the board in SAM-BA
    with no application running - `measure.flash` says as much in its
    own docstring, and it happened on the first reflash run here: the
    native port vanished, `which_track` answered None, and flashing
    again from a shell fixed it in one go. So a board that does not
    identify is reflashed rather than reported as a wrong track, and the
    number of attempts goes into the record, because a run that needed
    two flashes is not quite the same point as one that needed one.
    """
    attempts = 0
    while True:
        attempts += 1
        if flash:
            measure.flash(track, build=build)
        b = measure.Board(settle=3.0)
        have, _ = measure.which_track(b)
        if have == track:
            break
        b.close()
        if not flash or attempts >= tries:
            raise SystemExit(
                f"board reports track {have!r}, wanted {track!r} after "
                f"{attempts} flash attempt(s). Phase 0 will not record a "
                f"spread across two different binaries.")
        print(f"  board did not identify after flashing (got {have!r}); "
              f"flashing again")
    b.stop()
    b.drain_console(0.5)
    return b, attempts


def take(args):
    """N runs on one axis, each flushed before the next begins."""
    path = args.out or os.path.join(RECORDS, f"phase0-{args.metric}.jsonl")
    rec = repeat.Recorder(path)
    inst = dso.open_scope()
    print(f"scope: {' '.join(inst.identify())}")
    print(f"record: {path}")
    board = None
    try:
        for axis in args.axes:
            for i in range(args.runs):
                reflash = axis == "reflash"
                if board is None or reflash:
                    if board is not None:
                        board.close()
                        board = None
                    t0 = time.time()
                    board, attempts = open_board(
                        args.track, flash=reflash, build=args.build)
                    if reflash:
                        print(f"\n[{axis} {i+1}/{args.runs}] reflashed "
                              f"track {args.track} in {time.time()-t0:.0f} s"
                              + (f" ({attempts} attempts)"
                                 if attempts > 1 else ""))
                    # Before any number is taken, not after: a probe
                    # ratio is asserted and a factor of ten is silent.
                    dm.verify_probe(board, inst, args.channel,
                                    dm.TRIGGER_PRESETS[args.trigger])

                p = prov.collect(board=board, inst=inst,
                                 channels=(args.channel,),
                                 extra={"metric": args.metric, "axis": axis,
                                        "run": i})
                gaps = prov.missing(p)
                if gaps:
                    raise SystemExit(
                        f"refusing to record: provenance is missing {gaps}. "
                        f"A measurement without its conditions is not a "
                        f"baseline point.")

                print(f"\n=== {args.metric} [{axis}] run {i+1}/{args.runs} "
                      f"===")
                ns = dm.default_args(args.metric, **args.overrides)
                t0 = time.time()
                result, err = run_once(board, inst, args.metric, ns)
                rec.add({
                    "metric": args.metric,
                    "axis": axis,
                    "run": i,
                    "seconds": round(time.time() - t0, 2),
                    "flash_attempts": attempts if axis == "reflash" else 0,
                    "values": repeat.flatten(result) if result else {},
                    "error": err,
                    "args": {k: v for k, v in vars(ns).items()
                             if isinstance(v, (int, float, str, bool))},
                    "provenance": p,
                })
                if err:
                    print(f"  run failed: {err}")
    finally:
        if board is not None:
            try:
                board.stop()
                measure.set_sync(board, "cycle")
            finally:
                board.close()
        inst.averaging(None)
        inst.close()
    return path


def report(path, metric):
    """What the runs say, and the question Phase 0 was built to answer.

    Printed and written beside the record. The comparison table is the
    point: a ratio near 1 means the reflash axis bought nothing for that
    key and its tolerance can come from the cheap axis, and a ratio well
    above 1 means the opposite and says so before anybody writes a
    number down.
    """
    records = repeat.load(path)
    if not records:
        raise SystemExit(f"no runs in {path}")
    summary = repeat.summarise_all(records, floors_for(metric, records))

    for axis, block in summary.items():
        print(f"\n=== {metric} [{axis}] - {block['runs']} runs, "
              f"{block['failed']} failed ===")
        for e in block["errors"]:
            print(f"  ! {e}")
        print(f"{'key':<34s} {'n':>2s} {'median':>12s} {'spread':>12s} "
              f"{'rel':>8s} {'tolerance':>12s}")
        print("-" * 84)
        for k, s in block["keys"].items():
            rel = "-" if s.get("spread_rel") is None \
                else f"{s['spread_rel']*100:7.2f}%"
            tol = "-" if s.get("tolerance") is None \
                else f"{s['tolerance']:12.6g}"
            print(f"{k:<34s} {s['n']:2d} {s.get('median', 0):12.6g} "
                  f"{s.get('spread', 0):12.6g} {rel:>8s} {tol:>12s}")

    rows = repeat.compare_axes(summary, "in-place", "reflash")
    if rows:
        print(f"\n=== does the reflash axis buy anything? ===")
        print(f"{'key':<34s} {'in-place':>12s} {'reflash':>12s} {'x':>8s}")
        print("-" * 70)
        for r in rows:
            ratio = "-" if r["ratio"] is None else f"{r['ratio']:8.2f}"
            print(f"{r['key']:<34s} {r['in-place_spread']:12.6g} "
                  f"{r['reflash_spread']:12.6g} {ratio:>8s}")
        print("\nA ratio near 1 means that key does not care about the "
              "binary and its\ntolerance can come from the cheap axis. "
              "Well above 1 means it does.")

    out = os.path.splitext(path)[0] + ".summary.json"
    with open(out, "w") as f:
        json.dump({"metric": metric, "summary": summary,
                   "axis_comparison": rows,
                   "taken_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
                  f, indent=2, sort_keys=True)
    print(f"\nsummary written to {out}")
    print("Nothing here has been promoted into tests/baseline.json. "
          "That is a human's\ncall, and this is a machine with "
          f"{max(b['runs'] for b in summary.values())} data points.")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("metric", choices=sorted(METRICS))
    ap.add_argument("--runs", type=int, default=7,
                    help="repetitions per axis (default 7). Four is not "
                         "enough: two hypotheses on this project looked "
                         "like clean signal at four points and died at "
                         "the fifth")
    ap.add_argument("--axis", default="in-place",
                    choices=("in-place", "reflash", "both"))
    ap.add_argument("--track", default="b", choices=("a", "b"))
    ap.add_argument("--build", action="store_true",
                    help="rebuild before each reflash")
    ap.add_argument("--out", default=None,
                    help="record path (default records/phase0-<metric>.jsonl)")
    ap.add_argument("--report", action="store_true",
                    help="summarise an existing record; no bench needed")
    ap.add_argument("--channel", type=int, default=1)
    ap.add_argument("--trigger", type=int, default=200_000,
                    choices=sorted(dm.TRIGGER_PRESETS))
    ap.add_argument("--average", type=int, default=None)
    ap.add_argument("--vdiv", type=float, default=None)
    ap.add_argument("--window", type=float, default=None)
    ap.add_argument("--amp", type=int, default=None)
    args = ap.parse_args()

    args.axes = (["in-place", "reflash"] if args.axis == "both"
                 else [args.axis])
    args.overrides = {"channel": args.channel, "trigger": args.trigger}
    for k in ("average", "vdiv", "window", "amp"):
        if getattr(args, k) is not None:
            args.overrides[k] = getattr(args, k)

    path = args.out or os.path.join(RECORDS, f"phase0-{args.metric}.jsonl")
    if not args.report:
        path = take(args)
    report(path, args.metric)


if __name__ == "__main__":
    main()
