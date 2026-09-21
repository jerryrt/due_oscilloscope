#!/usr/bin/env python3
"""Sweep the internal generator and keep every capture, raw, with its
provenance.

    tools/gen_sweep.py --note "shield v3, wires unchanged" --idle-seconds 1200

The device plays its own table (`=<shape>,<pts>W`, preset M, no USB
in the DAC path) at one trigger rate, and the sweep walks the point
count from 256 down to 4: the frequency ladder the generator supports
at that rate, `f = trigger / (2 * points)`. Every hold is two ADC
samples whatever the point count, so what the ladder varies is the
size of the riser between holds - the slope - at fixed timing. A DC
capture is the control, and the first condition is repeated at the end
so drift across the sweep is readable.

WHAT IS KEPT, per condition, under captures/gen-sweep/ (git-ignored):
`<bench>-<uid tail>-<stamp>-<label>-a0.u16` and `-a1.u16`, the raw
12-bit codes exactly as the stream carried them, and one `.json`
sidecar with the identity line the board answered, the generator's own
readback of what it was told, the trigger rate declared and measured,
the settle index, the device timestamps of every frame, the stream's
health (frames, sequence gaps, CRC failures, overruns), three die
temperature reads, the full provenance block and the sha256 of both
raw files. One manifest row per capture, the sidecar without the
timestamps, is appended to records/gen-sweep-<bench>.jsonl, so the
committed record names every file and what was true when it was taken.

The tool refuses to run on a board that is not Track B, on a tree whose
dirt is outside records/, or without a declared idle time - the same
refusals tools/rotation_row.py makes, for the same reasons. Nothing is
analysed here: tools/gen_sweep_analyse.py reads the sidecars.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(REPO, "host"))

CAPTURES = os.path.join(REPO, "captures", "gen-sweep")
RECORDS = os.path.join(REPO, "records")
PRESET = "=200000,200000M"          # DAC 200 kHz, ADC 200 kHz, two channels
BASE = ("=0N", "=1J", "=2,1I")      # layout normal, sync per cycle, core bias
POINTS = (256, 128, 64, 32, 16, 8, 4)
SHAPES = {"sine": 0, "square": 1, "ramp": 2, "triangle": 3, "dc": 4}
GEN_LINE = re.compile(r"# gen shape .*?Hz", re.S)


class Refused(Exception):
    pass


def _dirty_paths():
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                         capture_output=True, text=True, check=False, cwd=REPO).stdout
    return [l[3:].split(" -> ")[-1].strip() for l in out.splitlines() if len(l) > 3]


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def conditions_for(args):
    """Every condition in sweep order: (label, shape, points)."""
    conds = []
    for shape in args.shapes:
        pts = [1] if shape == "dc" else args.points
        for p in pts:
            conds.append((f"{shape}-{p:03d}", shape, p))
    if args.dc_control and "dc" not in args.shapes:
        conds.append(("dc-001", "dc", 1))
    if args.repeat_first and conds:
        lab, sh, p = conds[0]
        conds.append((lab + "-again", sh, p))
    return conds


def read_temps(board, n=3, gap_s=2.0):
    link = board.ctl()
    out = []
    for i in range(n):
        if i:
            time.sleep(gap_s)
        t = link.temperature(samples=256)
        out.append({k: t.get(k) for k in ("code", "code_min", "code_max",
                                          "samples", "dev_us")})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--note", required=True,
                    help="the arrangement in words: shield, wires, anything a "
                         "reader must know that no field carries")
    ap.add_argument("--idle-seconds", type=int, required=True,
                    help="declared, not performed: how long the board idled "
                         "before the first capture")
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--preset", default=PRESET)
    ap.add_argument("--shapes", nargs="+", default=["sine"], choices=sorted(SHAPES))
    ap.add_argument("--points", nargs="+", type=int, default=list(POINTS))
    ap.add_argument("--no-dc-control", dest="dc_control", action="store_false")
    ap.add_argument("--no-repeat-first", dest="repeat_first", action="store_false")
    ap.add_argument("--out", default=CAPTURES)
    ap.add_argument("--bench", default=None)
    args = ap.parse_args(argv)

    import measure
    import provenance

    bench = args.bench or os.environ.get("DUE_BENCH") or provenance.bench().get("bench")
    if not bench:
        print("gen_sweep: refused: no bench name (bench.json or --bench)", file=sys.stderr)
        return 2
    paths = _dirty_paths()
    bad = [p for p in paths if not p.startswith("records/")]
    if bad:
        print(f"gen_sweep: refused: tree dirty outside records/: {', '.join(bad)}",
              file=sys.stderr)
        return 2

    os.makedirs(args.out, exist_ok=True)
    manifest = os.path.join(RECORDS, f"gen-sweep-{bench}.jsonl")
    conds = conditions_for(args)
    stamp = time.strftime("%Y%m%dT%H%M%S")

    board = measure.Board(settle=3.0)
    try:
        board.stop()
        board.drain_console(0.5)
        ident_line = board.ask("v", secs=1.0).strip()
        ident = measure.parse_identity(ident_line)
        if ident.get("track") != "b":
            raise Refused(f"board answers track={ident.get('track')!r}; this arm is Track B")
        if not ident.get("uid"):
            raise Refused("the identity line carries no uid; flash an image that reports one")
        prov = provenance.conditions(board=board, ident=ident)
        if not prov.get("board_serial"):
            raise Refused("no programming port enumerated, so no board_serial")
        uid8 = ident["uid"][-8:]
        print(f"gen_sweep: {bench} board {ident['uid']} serial {prov['board_serial']} "
              f"build {ident.get('build')} -> {args.out}")
        temps_before = read_temps(board)
        for c in BASE:
            board.cmd(c)
            board.drain_console(0.3)

        for n, (label, shape, pts) in enumerate(conds, 1):
            p = measure.gen_points_for(pts) if shape != "dc" else pts
            readback = measure.set_gen(board, SHAPES[shape], p)
            gen_line = GEN_LINE.search(readback)
            gen_line = gen_line.group(0).strip() if gen_line else readback.strip()
            t0 = time.time()
            res = measure.run_capture(board, preset=args.preset, seconds=args.seconds)
            ps = res.stream
            base = os.path.join(args.out, f"{bench}-{uid8}-{stamp}-{label}")
            files = {}
            for tag, name in ((measure.CH_A0, "a0"), (measure.CH_A1, "a1")):
                series = ps.series.get(tag)
                path = f"{base}-{name}.u16"
                with open(path, "wb") as fh:
                    fh.write(series.tobytes() if series is not None else b"")
                files[name] = {"path": os.path.relpath(path, REPO),
                               "samples": len(series) if series is not None else 0,
                               "sha256": sha256_of(path), "dtype": "<u2",
                               "settle_index": (ps._index_at(tag, measure.SETTLE_US)
                                                if series is not None else None)}
            trig_hz = measure.hz_for(measure.rc_for(200000))
            side = {
                "schema": "gen-sweep/1",
                "bench": bench, "label": label, "order": n, "of": len(conds),
                "shape": shape, "points": p,
                "expected_output_hz": (measure.gen_output_hz(trig_hz, p)
                                       if shape != "dc" else 0.0),
                "trigger_hz_nominal": trig_hz,
                "preset": args.preset, "base_cmds": list(BASE),
                "gen_readback": gen_line,
                "identity_line": ident_line, "identity": ident,
                "seconds_requested": args.seconds, "elapsed_s": res.elapsed_s,
                "taken_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t0)),
                "idle_before_s": args.idle_seconds if n == 1 else 0,
                "declared_rate_hz": ps.declared_rate_hz,
                "measured_rate_hz": ps.measured_rate_hz(),
                "frames": ps.frames, "seq_gaps": ps.seq_gaps, "crc_bad": ps.crc_bad,
                "dropped_frames": ps.dropped_frames,
                "overrun_frames": ps.overrun_frames, "max_overrun": ps.max_overrun,
                "channel_mask": ps.channel_mask, "n_channels": ps.n_channels,
                "per_channel": {str(k): {"n": v.n, "lo": v.lo, "hi": v.hi,
                                         "mean": v.mean}
                                for k, v in (ps.per_channel or {}).items()},
                "files": files,
                "note": args.note,
                "conditions": prov,
                "temperatures_before_sweep": temps_before,
            }
            marks = {str(tag): list(map(list, ps.marks.get(tag, [])))
                     for tag in (measure.CH_A0, measure.CH_A1)}
            with open(base + ".json", "w", encoding="utf-8") as fh:
                json.dump({**side, "marks": marks}, fh)
            side["sidecar"] = os.path.relpath(base + ".json", REPO)
            with open(manifest, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(side, sort_keys=True) + "\n")
            a0 = files["a0"]
            print(f"  [{n}/{len(conds)}] {label:14s} {gen_line.split('->')[-1].strip():>28s}  "
                  f"a0 n={a0['samples']} frames={ps.frames} gaps={ps.seq_gaps} "
                  f"crc={ps.crc_bad} overruns={ps.overrun_frames}")
        temps_after = read_temps(board)
        with open(manifest, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"schema": "gen-sweep/1", "bench": bench,
                                 "label": "sweep-end", "stamp": stamp,
                                 "temperatures_after_sweep": temps_after,
                                 "taken_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
                                sort_keys=True) + "\n")
        print(f"gen_sweep: {len(conds)} captures; manifest {os.path.relpath(manifest, REPO)}")
        return 0
    except Refused as e:
        print(f"gen_sweep: refused: {e}", file=sys.stderr)
        return 2
    finally:
        try:
            measure.set_gen(board, SHAPES["sine"], 256)
            for c in BASE:
                board.cmd(c)
                board.drain_console(0.3)
            board.stop()
        finally:
            board.close()


if __name__ == "__main__":
    sys.exit(main())
