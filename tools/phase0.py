"""Phase 0: run one metric N times and record what it actually did.

    python3 tools/phase0.py loop,dc-fit,rise --axis reflash --runs 3
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
import noise_metrics as nm                                    # noqa: E402
import metrics as mt                                          # noqa: E402
import settletime as st                                       # noqa: E402
import square_shape as sq                                     # noqa: E402

RECORDS = os.path.join(HERE, "records")

#: The metrics that return a result worth taking a spread of, and
#: whether each needs the bench instrument. `shots` writes PNGs and
#: `wrap`/`reload` have their own repeat machinery, so they are not
#: here; adding one is a line, not a design.
#:
#: The scope-free entries matter more than they look. A metric that
#: needs no instrument can be repeated on any bench, by anyone, without
#: the DS1102E - and `noise-dc` is the first figure of merit this
#: project has that a second board could be measured against directly.
METRICS = {
    "settle": {"fn": dm.cmd_settle, "scope": True, "args": dm.default_args},
    "step": {"fn": dm.cmd_step, "scope": True, "args": dm.default_args},
    "skew": {"fn": dm.cmd_skew, "scope": True, "args": dm.default_args},
    "transfer": {"fn": dm.cmd_transfer, "scope": True,
                 "args": dm.default_args},
    "lin": {"fn": dm.cmd_lin, "scope": True, "args": dm.default_args},
    "clock": {"fn": dm.cmd_clock, "scope": True, "args": dm.default_args},
    "noise-dc": {"fn": nm.cmd_noise_dc, "scope": False,
                 "args": nm.default_args},
    "noise-fast": {"fn": nm.cmd_noise_fast, "scope": False,
                   "args": nm.default_args},
    "noise-host": {"fn": nm.cmd_noise_host, "scope": False,
                   "args": nm.default_args},
}


def loop_default_args(what, **overrides):
    """The Namespace a `loop` run reads: the rung and the run length."""
    ns = argparse.Namespace(rc=mt.LOOP_RC, seconds=None, what=what)
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def needs_scope(metric):
    return METRICS[metric]["scope"]


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
        return METRICS[metric]["fn"](board, inst, args), None
    except SystemExit as e:                       # the metrics' own refusals
        return None, str(e)
    except Exception as e:                                    # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    finally:
        try:
            if inst is not None:
                inst.averaging(None)
            board.stop()
            board.drain_console(0.2)
        except Exception:                                     # noqa: BLE001
            pass


def open_board(track, flash=False, tries=2):
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
            measure.flash(track)
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


def adapt(fn):
    """A scope-free metric `fn(board, args)` in the shape METRICS calls,
    `fn(board, inst, args)`. Phases C, D and E register theirs through it."""
    def metric(board, inst, args):
        return fn(board, args)
    metric.__name__ = getattr(fn, "__name__", "metric")
    return metric


def _loop_metric(board, args):
    return mt.loop_once(board, args.rc, args.seconds)


#: The matched DAC->ADC loop, scope-free, at `--rc` (default RC 225).
METRICS["loop"] = {"fn": adapt(_loop_metric), "scope": False,
                   "args": loop_default_args}


def _sinad_metric(board, args):
    return nm.sinad_once(board, args.rc, args.seconds)


def _dc_fit_metric(board, args):
    return mt.dc_fit_once(board, args.rc, args.seconds)


def _rise_metric(board, args):
    return st.rise_once(board, args.points, args.seconds, args.dac_hz,
                        args.pre)


#: Coherent-sine SINAD, THD and ENOB of the matched loop, scope-free, at
#: `--rc` (default RC 225). A loop figure: the DAC's staircase is in it.
METRICS["sinad"] = {"fn": adapt(_sinad_metric), "scope": False,
                    "args": loop_default_args}


def _tone_sweep_metric(board, args):
    return mt.tone_sweep_once(board, args.rc, args.seconds)


#: Amplitude on A0 and crosstalk on A1 against tone, one loop per tone,
#: scope-free, at `--rc` (default RC 225).
METRICS["tone-sweep"] = {"fn": adapt(_tone_sweep_metric), "scope": False,
                         "args": loop_default_args}


def _loop_skew_metric(board, args):
    return mt.loop_skew_once(board, args.rc, args.seconds)


#: The A1-after-A0 lag of one sine on both DACs, scope-free, at `--rc`.
#: Not `skew`, which is the scope metric. One figure: DAC1's write after
#: DAC0's plus the ADC spacing; the latter alone is about 0.96 us
#: *(derived, check)*, a reference and not a verdict.
METRICS["loop-skew"] = {"fn": adapt(_loop_skew_metric), "scope": False,
                        "args": loop_default_args}


def dc_fit_default_args(what, **overrides):
    """The Namespace a `dc-fit` run reads: the ADC rung and the run length."""
    ns = argparse.Namespace(rc=None, seconds=None, what=what)
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def rise_default_args(what, **overrides):
    """The Namespace a `rise` run reads, the defaults of `settletime.py rise`."""
    ns = argparse.Namespace(points=8, seconds=4.0, dac_hz=st.DAC_HZ, pre=80,
                            what=what)
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


#: The five-code DC sweep and its line, scope-free. `--rc` sets the ADC rate.
METRICS["dc-fit"] = {"fn": adapt(_dc_fit_metric), "scope": False,
                     "args": dc_fit_default_args}
#: The 10-90% rise, scope-free. A fold below full coverage is a refusal,
#: which `run_once` records as an error row and never as a zero.
METRICS["rise"] = {"fn": adapt(_rise_metric), "scope": False,
                   "args": rise_default_args}


def _square_shape_metric(board, args):
    return sq.square_shape_once(board, args.rc or 225, args.seconds or 4.0)


#: The square's shape at DAC RC `--rc` (default 225), points 8, amp 256,
#: scope-free. Minimal on purpose: the frequency/amplitude grid is
#: `tools/square_shape.py grid`.
METRICS["square-shape"] = {"fn": adapt(_square_shape_metric), "scope": False,
                           "args": loop_default_args}


def metrics_of(args):
    """The metrics a run takes, in order: `args.metrics`, else `[args.metric]`."""
    return list(getattr(args, "metrics", None) or [args.metric])


def record_path(args, metric):
    """Where `metric`'s rows go.

    One metric: `--out` as given, else `records/phase0-<metric>.jsonl`.
    Several: `--out` is a prefix and each metric writes
    `<prefix>-<metric>.jsonl` (a trailing `.jsonl` on the prefix is
    dropped), else the default path, so `--report` per metric reads each
    record as if it had been taken alone."""
    if not args.out:
        return os.path.join(RECORDS, f"phase0-{metric}.jsonl")
    if len(metrics_of(args)) == 1:
        return args.out
    base = args.out[:-6] if args.out.endswith(".jsonl") else args.out
    return f"{base}-{metric}.jsonl"


def warm_and_discard(board, inst, args, warm=None):
    """After a flash: wait out the warm-up, then take one run of each metric
    and throw them away. The wait is paid once however many metrics follow.

    On the reflash axis every run follows a flash, so every run is a first
    run inside the post-flash transient and "drop run 0" removes nothing
    from the other seven. The wait and the throwaway run are what make a
    reflash-axis row comparable to an in-place one.
    """
    (warm or repeat.warm_up)()
    for m in metrics_of(args):
        ns = METRICS[m]["args"](m, **args.overrides)
        run_once(board, inst, m, ns)


def take(args):
    """N runs of each metric on one axis, each flushed before the next begins.

    A reflash cycle (flash, warm-up, throwaway run) serves every metric:
    it is paid once per run index and each metric records one row from the
    board it leaves. In place, the metrics run back to back per run index.
    Returns the record's path, or `{metric: path}` for several metrics.
    """
    ms = metrics_of(args)
    paths = {m: record_path(args, m) for m in ms}
    for m, path in paths.items():
        held = repeat.clocks(repeat.load(path))
        if held and set(held) != {measure.MCK_HZ}:
            raise SystemExit(
                f"{path} already holds rows at {sorted(held)} Hz and this "
                f"host is at {measure.MCK_HZ} Hz. A record has one clock: "
                f"pass a fresh --out.")
    recs = {m: repeat.Recorder(path) for m, path in paths.items()}
    inst = None
    if any(needs_scope(m) for m in ms):
        inst = dso.open_scope()
        print(f"scope: {' '.join(inst.identify())}")
    else:
        # Said out loud, because "no instrument" is a property of the
        # metric worth knowing when a figure is quoted: it can be
        # re-taken on a bench that has no scope at all.
        print(f"no instrument needed for {', '.join(ms)}")
    for path in paths.values():
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
                        args.track, flash=reflash)
                    if reflash:
                        print(f"\n[{axis} {i+1}/{args.runs}] reflashed "
                              f"track {args.track} in {time.time()-t0:.0f} s"
                              + (f" ({attempts} attempts)"
                                 if attempts > 1 else ""))
                        warm_and_discard(board, inst, args)
                    if inst is not None:
                        # Before any number is taken, not after: a probe
                        # ratio is asserted and a factor of ten is
                        # silent.
                        dm.verify_probe(board, inst, args.channel,
                                        dm.TRIGGER_PRESETS[args.trigger])

                for metric in ms:
                    p = prov.collect(board=board, inst=inst,
                                     channels=(args.channel,),
                                     extra={"metric": metric, "axis": axis,
                                            "run": i})
                    gaps = prov.missing(p)
                    if gaps:
                        raise SystemExit(
                            f"refusing to record: provenance is missing "
                            f"{gaps}. A measurement without its conditions "
                            f"is not a baseline point.")

                    print(f"\n=== {metric} [{axis}] run {i+1}/{args.runs} "
                          f"===")
                    ns = METRICS[metric]["args"](metric, **args.overrides)
                    t0 = time.time()
                    result, err = run_once(board, inst, metric, ns)
                    recs[metric].add({
                        "metric": metric,
                        "axis": axis,
                        "run": i,
                        "seconds": round(time.time() - t0, 2),
                        "flash_attempts": attempts if reflash else 0,
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
        if inst is not None:
            inst.averaging(None)
            inst.close()
    return paths[ms[0]] if len(ms) == 1 else paths


def report(path, metric, first=False, gates=None):
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
    try:
        repeat.refuse_mixed_clocks(records)
    except repeat.MixedClocks as e:
        raise SystemExit(f"refusing to report {path}: {e}")
    summary = repeat.summarise_all(records, floors_for(metric, records),
                                   first=first)
    thin = repeat.thin_keys(summary)
    if thin:
        ax, k, n = thin[0]
        raise SystemExit(
            f"refusing to report {path}: {k} [{ax}] has {n} kept runs, "
            f"fewer than the {repeat.MIN_KEPT} a gate may be proposed "
            f"from ({len(thin)} key(s) short). Take more runs.")

    for axis, block in summary.items():
        print(f"\n=== {metric} [{axis}] - {block['runs']} runs, "
              f"{block['dropped']} dropped by index, "
              f"{block['failed']} failed ===")
        for e in block["errors"]:
            print(f"  ! {e}")
        print(f"{'key':<34s} {'n':>2s} {'median':>12s} {'spread':>12s} "
              f"{'rel':>8s} {'proposed gate':>14s}")
        print("-" * 86)
        for k, s in block["keys"].items():
            rel = "-" if s.get("spread_rel") is None \
                else f"{s['spread_rel']*100:7.2f}%"
            tol = "-" if s.get("tolerance") is None \
                else f"{s['tolerance']:14.6g}"
            print(f"{k:<34s} {s['n']:2d} {s.get('median', 0):12.6g} "
                  f"{s.get('spread', 0):12.6g} {rel:>8s} {tol:>14s}")

    if gates:
        for ax, k, spread, g in repeat.over_gate(summary, gates):
            print(f"!! spread exceeds gate: {k} [{ax}] observed spread "
                  f"{spread:.6g} > gate {g:.6g}")

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
    with open(out, "w", newline="", encoding="utf-8") as f:
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
    ap.add_argument("metric", metavar="METRIC[,METRIC...]",
                    help="one metric or a comma list, from: "
                         + ", ".join(sorted(METRICS)) + ". With several, "
                         "one reflash cycle (flash, warm-up, throwaway "
                         "run of each) serves all of them and each writes "
                         "its own record")
    ap.add_argument("--runs", type=int, default=8,
                    help="repetitions per axis (default 8, of which run 0 "
                         "is dropped, so a spread rests on seven). Four is "
                         "not enough: two hypotheses on this project looked "
                         "like clean signal at four points and died at "
                         "the fifth")
    ap.add_argument("--keep-first", action="store_true",
                    help="keep run 0 of each axis in the report. It is "
                         "dropped by default: the first run after a board "
                         "start is an outlier that passes every filter")
    ap.add_argument("--rc", type=int, default=None,
                    help="scope-free metrics: repeat at the rate of this RC "
                         "(measure.hz_for), so one metric can be taken at "
                         "each ladder rate")
    ap.add_argument("--axis", default="in-place",
                    choices=("in-place", "reflash", "both"))
    ap.add_argument("--track", default="b", choices=("a", "b", "c"))
    ap.add_argument("--out", default=None,
                    help="record path (default records/phase0-<metric>.jsonl). "
                         "With several metrics it is a prefix, and each "
                         "metric writes <prefix>-<metric>.jsonl; run the "
                         "same command again to append, or --report with "
                         "the same --out to summarise each")
    ap.add_argument("--report", action="store_true",
                    help="summarise an existing record; no bench needed")
    ap.add_argument("--gates", default=None, metavar="FILE.json",
                    help="with --report: a flat {key: current_gate} map; "
                         "a key whose observed spread exceeds its gate "
                         "is reported, nothing is gated")
    ap.add_argument("--channel", type=int, default=1)
    ap.add_argument("--trigger", type=int, default=200_000,
                    choices=sorted(dm.TRIGGER_PRESETS))
    ap.add_argument("--average", type=int, default=None)
    ap.add_argument("--vdiv", type=float, default=None)
    ap.add_argument("--window", type=float, default=None)
    ap.add_argument("--amp", type=int, default=None)
    ap.add_argument("--seconds", type=float, default=None,
                    help="noise metrics: capture length per run")
    ap.add_argument("--code", type=int, default=None,
                    help="noise metrics: DAC code to hold")
    args = ap.parse_args()

    args.metrics = [m for m in args.metric.split(",") if m]
    bad = [m for m in args.metrics if m not in METRICS]
    if bad or not args.metrics or len(set(args.metrics)) != len(args.metrics):
        ap.error(f"METRIC must be a list of distinct names from "
                 f"{sorted(METRICS)}; got {args.metric!r}")
    args.metric = args.metrics[0]
    args.axes = (["in-place", "reflash"] if args.axis == "both"
                 else [args.axis])
    args.overrides = ({"channel": args.channel, "trigger": args.trigger}
                      if any(needs_scope(m) for m in args.metrics) else {})
    for k in ("average", "vdiv", "window", "amp", "seconds", "code", "rc"):
        if getattr(args, k) is not None:
            args.overrides[k] = getattr(args, k)

    if not args.report:
        take(args)
    gates = None
    if args.gates:
        with open(args.gates, encoding="utf-8") as f:
            gates = json.load(f)
    for m in args.metrics:
        report(record_path(args, m), m, first=args.keep_first, gates=gates)


if __name__ == "__main__":
    main()
