#!/usr/bin/env python3
"""Does #5's displacement scale with the signal, or sit on top of it?

The open question after #24 was measured device-side: the internal
generator shows ~14 codes and the host-fed ramp ~30, and whether that
doubling is one effect modulated or a second effect on top was not
settled. One property separates the two candidate characters, and it can
be read on either path without knowing the mechanism.

**Is the displacement a fixed number of codes, or a fraction of the
signal?** A settling effect - the ADC catching the converter mid
transition - is proportional to how far the output is moving. An
additive error is not.

The host-fed path already answered: changing `RAMP_STEP` changes the
per-sample step by 2x while `n * slope * step` stays at ~28-30 codes, so
there it is additive. This asks the internal generator the same question
the only way it can be asked there - by moving the generator's amplitude
and leaving everything else alone. Half amplitude is half the slew at
every phase, so a proportional effect halves and an additive one does
not.

    .venv/bin/python tools/issue5_amp.py --rounds 3

`pair_fold` is the instrument, as it is everywhere in #5: gen holds each
DAC level for two ADC samples, so differencing within the pair cancels
the staircase by construction and leaves the artifact at full height, in
codes. Counterbalanced rather than merely interleaved - the artifact is
a per-session draw and the die warms, so a sweep would confound both.
"""
import argparse
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure  # noqa: E402


def one(board, amp, seconds):
    measure.set_gen(board, "sine", points=measure.GEN_TABLE_POINTS, amp=amp)
    res = measure.run_capture(board, preset="M", seconds=seconds)
    ps = res.stream
    vals = ps.series.get(measure.CH_A0)
    if not vals:
        return None
    start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
    vals = list(vals[start:])
    fold = measure.pair_fold(vals)
    # The signal's own extent, so "a fraction of the signal" is a
    # measured fraction and not an assumed one: the DAC is not rail to
    # rail and the amplitude the device adopts is its business.
    span = max(vals) - min(vals)
    return {"amp": amp, "peak": fold["peak"], "z": fold["z"],
            "control_z": fold["control_z"], "phase": fold["peak_phase"],
            "spike": fold["spike"], "spike_z": fold["spike_z"],
            "hold_ok": bool(fold["hold_ok"]),
            "pair_spread": fold["pair_spread"],
            "span_codes": span, "t_wall": time.time()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--amps", default="256,128,64")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    amps = [int(a) for a in args.amps.split(",")]
    board = measure.Board(settle=3.0)
    rows, by = [], {a: [] for a in amps}
    try:
        board.stop()
        board.drain_console(0.5)
        for r in range(args.rounds):
            # Each amplitude gets every position across rounds, so a
            # warm-up trend cannot be read as an amplitude effect.
            order = amps if r % 2 == 0 else list(reversed(amps))
            for pos, amp in enumerate(order):
                row = one(board, amp, args.seconds)
                if row is None:
                    print(f"  round {r} amp {amp}: capture failed", flush=True)
                    continue
                row["round"], row["pos"] = r, pos
                rows.append(row)
                by[amp].append(row)
                print(f"round {r} amp {amp:3d}/256: peak {row['peak']:+7.2f} "
                      f"codes at phase {row['phase']:3d} (z {row['z']:6.1f}, "
                      f"control {row['control_z']:5.1f})  span "
                      f"{row['span_codes']:4d}  hold_ok={row['hold_ok']}",
                      flush=True)
                board.stop()
                board.drain_console(0.3)
    finally:
        # Never leave the generator somewhere the next session has to
        # discover: full scale is what everything else on this board
        # assumes.
        try:
            measure.set_gen(board, "sine", points=measure.GEN_TABLE_POINTS,
                            amp=measure.GEN_AMP_FULL)
            board.stop()
        finally:
            board.close()

    print()
    ref = None
    for amp in amps:
        v = [x for x in by[amp] if x["hold_ok"]]
        if not v:
            continue
        mag = [abs(x["peak"]) for x in v]
        span = statistics.mean(x["span_codes"] for x in v)
        m = statistics.mean(mag)
        if ref is None:
            ref = (m, span)
        print(f"amp {amp:3d}/256: |peak| {m:6.2f} codes"
              f"{' +- %.2f' % statistics.stdev(mag) if len(mag) > 1 else ''}"
              f", n={len(v)}, signal span {span:.0f} codes"
              f"   ->  {m / ref[0]:.2f}x the full-amplitude displacement "
              f"at {span / ref[1]:.2f}x the signal")

    if args.json:
        with open(args.json, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"wrote {len(rows)} rows to {args.json}")


if __name__ == "__main__":
    main()
