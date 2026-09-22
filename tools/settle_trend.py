#!/usr/bin/env python3
"""One long continuous capture, binned, repeated - does the crossing rate
climb across its OWN duration, and does a single capture reproduce.

    python3 tools/settle_trend.py
    python3 tools/settle_trend.py --repeats 10 --out records/settle-trend-<bench>.jsonl

WHY THIS EXISTS. The standing protocol for "is this board settled"
rests a long time (1200 s, `tools/rotation_row.py`'s RESTED_S) and then
takes several SHORT (~3 s) captures, each its own fresh board open. That
answers "does the metric change round to round after a rest" - it
cannot answer "does the metric change across ONE run's own duration",
because six short captures inside one round are six separate resets
(opening the control port resets the board on macOS - CLAUDE.md's ports
table), not six seconds into a continuously active board. This tool
takes ONE open, ONE continuous capture, and slices it into time bins
AFTER the fact, so a climb across the bins is a climb during activity,
not six fresh starts.

WHAT "count" IS: `measure.level_census()`, the exact function
`tests/test_integrity.py::test_device_generated_waveform_is_continuous`
(the standing rotation census) uses, same default threshold
(`STEP_SPLICE_CODES`). Nothing reimplemented - two tools computing "the
same thing" two different ways is how this project's tracks stay
independent oracles for silicon, and a network of one-off scripts is
the opposite of that for a host-side metric everyone needs to agree on.

RATE, NOT RAW COUNT, is what a bin reports and what --repeats compares.
Bins and repeats are not guaranteed the same sample count (a dropped
frame, a shorter final bin), and this project has already paid for that
lesson once tonight (docs/noise.md's gen_sweep tables: `1000.0 per 1000`
read as a spike and was 17 events in 17 holds). `count_per_1e6` is the
number every comparison should use; raw `count` and `n` are kept so a
reader can always recover the denominator.

A SHORT BIN UNDERCOUNTS ITS OWN RATE - measured in
tests/test_settle_trend.py, not assumed. `level_census()` counts
TRANSITIONS between detected levels, one fewer than the level count, so
a bin with only a handful of levels reports a rate biased low relative
to the asymptotic one - a synthetic 3-cycle chunk read 41,667/1e6
against 49,975/1e6 for the same pattern at 1000 cycles, a 20% bias from
the edge alone. `--bin-seconds` far shorter than the signal's own
period reproduces this for real, not from anything the board did.
Default bins here run to hundreds of thousands of samples, where the
bias is negligible; narrowing `--bin-seconds` for finer time resolution
should be paired with checking the level count stayed large.

ONE CAPTURE CAN BE A WILD OUTLIER AND NOT REPRODUCE - measured, not
assumed. A single fresh 30 s capture on mac-bench's board read
count=3261 (rate 5.6e-4/sample); three more taken immediately after,
same board, same everything, read 458/362/385 (rate 6-8e-5/sample) -
7-9x lower and consistent with each other. That capture was never seen
again. This is exactly the failure mode `--repeats` exists to catch:
one repeat can mislead in either direction, and this tool reports every
repeat's numbers rather than only a pooled figure, so an outlier repeat
is visible instead of averaged away. Read the per-repeat table before
trusting a mean.

PORTABLE BY DEFAULT. `measure.Board(settle=3.0)` with ordinary
auto-discovery - the normal case, one board on a bench. --control /
--native-location-prefix / --expect-uid exist only for a bench running
more than one Track B board at once, where ports.native_nodes() cannot
tell them apart (every Track B native port reports the fixed firmware
serial "B-01" regardless of die - see records/wiring-mac-bench-two-dut-
2026-09-21.jsonl and 86804d6). Pass all three together or none; pinning
verifies the uid the control port answers before trusting anything.

Idle before the first capture is short by design (default 10 s, not
the standing protocol's 1200 s) - this tool exists to test whether that
matters, not to assume it does not.
"""
import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "host"))

DEFAULT_SECONDS = 300.0
DEFAULT_BIN_SECONDS = 30.0
DEFAULT_IDLE_SECONDS = 10.0
PRESET = "M"  # the device's own internal generator - no USB in the DAC
              # path, the same preset the standing census test uses.


def _pin(measure_mod, ports_mod, control, prefix, expect_uid):
    """Scope port discovery to ONE board by USB location, verified
    against its own uid. Only used when the three pin arguments are
    given; see the module docstring for why a multi-board bench needs
    this and a single-board one does not."""
    import serial.tools.list_ports as lp
    VID, PID_NATIVE = 0x2341, 0x003E

    def nodes_at(loc_prefix):
        cur = [p.device for p in lp.comports()
              if p.vid == VID and p.pid == PID_NATIVE
              and (p.location or "").startswith(loc_prefix)]
        ifaces = ports_mod.usb_interfaces()

        def key(d):
            _ser, i = ifaces.get(d, (None, 1 << 16))
            return (i, d)
        return sorted(cur, key=key)

    found = nodes_at(prefix)
    if len(found) != 2:
        raise SystemExit(f"REFUSING: location prefix {prefix!r} shows "
                         f"{len(found)} native node(s) ({found}), "
                         "expected 2 (samples + commands)")

    def scoped(exclude=None):
        return [d for d in nodes_at(prefix) if d != exclude]

    ports_mod.native_nodes = scoped
    measure_mod.find_ports = lambda wait=8.0: (control, scoped()[0])

    board = measure_mod.Board(settle=1.0)
    board.stop()
    board.drain_console(0.5)
    ident = measure_mod.parse_identity(board.ask("v", secs=1.5))
    got = (ident or {}).get("uid")
    if got != expect_uid:
        board.close()
        raise SystemExit(f"REFUSING: control port {control} answered "
                         f"uid={got}, expected {expect_uid}")
    print(f"pinned: control={control} native-location={prefix!r} "
         f"uid={got}", flush=True)
    return board


def figure(measure, chunk):
    """count/rate/fold summary of one slice, board-free once given the
    census and fold results - kept as a plain function rather than a
    closure so it is directly testable (tests/test_settle_trend.py)
    without a board or a capture, matching tests/test_wiring_probe.py's
    own reasoning for staying board-free where the logic allows it."""
    c = measure.level_census(chunk)
    f = measure.pair_fold(chunk)
    nc = len(chunk)
    return {
        "n": nc,
        "count": c["count"],
        "count_per_1e6": round(c["count"] / nc * 1e6, 2) if nc else None,
        "max_step": c["max_step"],
        "fold_z": round(f["z"], 2),
        "fold_control_z": round(f["control_z"], 2),
    }


def one_capture(measure, board, seconds, bin_seconds, repeat_idx):
    """One continuous capture, binned. Returns (bins, whole) where each
    bin and the whole-capture figure carry count, n, and count_per_1e6 -
    never a bare rate with no denominator next to it."""
    t0 = time.time()
    res = measure.run_capture(board, preset=PRESET, seconds=seconds)
    wall = time.time() - t0

    ps = res.stream
    vals = ps.series[measure.CH_A0]
    start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
    vals = vals[start:]
    n = len(vals)

    whole = figure(measure, vals)
    whole.update({"frames": res.frames, "seq_gaps": res.seq_gaps,
                 "crc_bad": res.crc_bad, "wall_s": round(wall, 1)})

    bin_n = max(1, int(n * bin_seconds / seconds))
    bins = []
    i = 0
    binno = 0
    while i < n:
        chunk = vals[i:i + bin_n]
        if len(chunk) < bin_n // 2:
            break
        row = figure(measure, chunk)
        row.update({"bin": binno, "t_start_s": round(i / n * seconds, 1),
                   "repeat": repeat_idx})
        bins.append(row)
        i += bin_n
        binno += 1

    return bins, whole


def spread_line(all_whole):
    """The repeat-to-repeat spread summary, or "" if there is not
    enough to compare. A plain function so it is testable without a
    board (tests/test_settle_trend.py) - it very nearly was not one,
    which is how the bug below survived a real run before anyone
    noticed it.

    is not None, not a bare truthy check on count_per_1e6 - a
    genuinely clean repeat (count=0, a real and common result on a
    quiet board) has count_per_1e6 == 0.0, which is falsy. The first
    version of this filtered on truthiness and silently dropped every
    such repeat, undercounting "N repeats" in the printed line and
    hiding exactly the quiet-board case it exists to report honestly.
    Found running this for real on mac-bench's second (quiet) board:
    5 of 10 repeats read exactly 0 events and vanished from the
    summary with no indication anything had been dropped - the same
    shape of mistake this project already paid for once tonight in
    docs/noise.md's gen_sweep tables, a rate read with no denominator
    next to it to say what had and had not been counted.
    """
    rates = [w["count_per_1e6"] for w in all_whole
            if w["count_per_1e6"] is not None]
    if len(rates) <= 1:
        return ""
    lo, hi = min(rates), max(rates)
    return (f"{len(rates)} repeats: count_per_1e6 ranges {lo:.2f} to "
           f"{hi:.2f} ({hi/lo if lo else float('inf'):.1f}x spread). "
           "A repeat far outside the others is the outlier-capture "
           "hazard this tool was built to catch, not evidence by "
           "itself - read the per-repeat table above before trusting "
           "a pooled figure.")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeats", type=int, default=1,
                    help="independent captures, back to back (the "
                    "owner's team-wide spec is 10 - see the module "
                    "docstring for why one is not enough)")
    ap.add_argument("--seconds", type=float, default=DEFAULT_SECONDS,
                    help="length of ONE continuous capture")
    ap.add_argument("--bin-seconds", type=float, default=DEFAULT_BIN_SECONDS)
    ap.add_argument("--idle-seconds", type=float,
                    default=DEFAULT_IDLE_SECONDS,
                    help="wait before the FIRST capture only; repeats "
                    "run back to back with no wait between them, "
                    "because the question is activity, not rest")
    ap.add_argument("--control", default=None)
    ap.add_argument("--native-location-prefix", default=None)
    ap.add_argument("--expect-uid", default=None)
    ap.add_argument("--out", default=None,
                    help="append bin + whole-capture rows to this JSONL")
    ap.add_argument("--bench", default=None)
    args = ap.parse_args(argv)

    if bool(args.control) + bool(args.native_location_prefix) \
            + bool(args.expect_uid) not in (0, 3):
        ap.error("--control, --native-location-prefix and --expect-uid "
                 "must be given all together or not at all")

    if args.repeats < 1:
        # No board needed to run zero captures - lets --help-adjacent
        # argument checking (this test file's partial-pin case, or a
        # future CI dry run) verify the CLI without a board attached.
        print("--repeats < 1: nothing to do, no board opened")
        return 0

    import measure
    import ports
    import provenance

    if args.control:
        board = _pin(measure, ports, args.control,
                    args.native_location_prefix, args.expect_uid)
    else:
        board = measure.Board(settle=3.0)
        board.stop()
        board.drain_console(0.5)

    ident = measure.parse_identity(board.ask("v", secs=1.5))
    decl = provenance.bench()
    fields = provenance.run_fields(ident=ident)
    fields.update({"bench": args.bench or decl.get("bench"),
                   "tool": "tools/settle_trend.py"})

    print(f"idle {args.idle_seconds}s before the first capture "
         f"(not the standing protocol's 1200s - that is the question "
         f"this tool asks)", flush=True)
    time.sleep(args.idle_seconds)

    all_bins, all_whole = [], []
    try:
        for r in range(args.repeats):
            bins, whole = one_capture(measure, board, args.seconds,
                                      args.bin_seconds, r)
            whole["repeat"] = r
            all_bins += bins
            all_whole.append(whole)
            print(f"repeat {r}: n={whole['n']} count={whole['count']} "
                 f"({whole['count_per_1e6']:.2f}/1e6) "
                 f"max_step={whole['max_step']:.1f} "
                 f"fold_z={whole['fold_z']:.1f} "
                 f"frames={whole['frames']} gaps={whole['seq_gaps']} "
                 f"crc={whole['crc_bad']} wall={whole['wall_s']}s",
                 flush=True)
            for b in bins:
                print(f"  bin {b['bin']:>2} t={b['t_start_s']:>6.1f}s "
                     f"n={b['n']:>9} count={b['count']:>5} "
                     f"({b['count_per_1e6']:>7.2f}/1e6) "
                     f"max_step={b['max_step']:>6.1f} "
                     f"fold_z={b['fold_z']:>5.1f}", flush=True)
    finally:
        board.close()

    spread = spread_line(all_whole)
    if spread:
        print("\n" + spread)

    if args.out:
        with open(args.out, "a", encoding="utf-8", newline="\n") as fh:
            for w in all_whole:
                row = dict(w)
                row.update(fields)
                row["schema"] = "settle-trend/1"
                row["kind"] = "whole"
                fh.write(json.dumps(row, sort_keys=True) + "\n")
            for b in all_bins:
                row = dict(b)
                row.update(fields)
                row["schema"] = "settle-trend/1"
                row["kind"] = "bin"
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        print(f"wrote {len(all_whole)} whole-capture rows and "
             f"{len(all_bins)} bin rows to {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
