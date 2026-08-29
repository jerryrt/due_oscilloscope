#!/usr/bin/env python3
"""#24's displacement, measured with #5's instrument, in the same units.

Issue #5 closed within tolerance on "1-8 codes against the DAC's ~25
code standing noise, so no user can see it". Issue #24 measures the same
shape - one sample per DAC table wrap, phase stable within a run - at
~17-30 codes. Those two numbers decide whether #5's closing bound holds,
and they were taken with different instruments, so they could not be
compared: one is `fold_profile`'s spike on the internal generator, the
other is a ramp's position arithmetic on the host-fed path.

This runs #5's instrument on #24's capture. `measure.fold_profile` is
threshold-free by construction - it folds the run at a period it is told
and reports the average deviation per phase, so an artifact under the
per-sample noise still shows in the mean of the several hundred wraps
sharing its phase - and its `spike` statistic subtracts each bin's own
neighbours, which is what lets it work with a waveform underneath.

One thing has to be added for a ramp. The sawtooth's wrap is a
full-scale step, so the two bins either side of it carry a neighbour
residual that dwarfs anything else in the profile. They are masked, the
way the discontinuity analysis already excludes them, and the spike is
taken over what is left.

    .venv/bin/python tools/issue24_fold.py -n 8

Reported in ADC codes, which is what both issues' figures are in, with
the fold's own control period alongside: a real lock reads high at the
table period and low at a period the signal is not locked to.
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


def masked_spike(vals, period, mask_wrap=True):
    """Largest one-bin neighbour residual, with the ramp's wrap masked.

    Returns (spike_codes, phase, z, n_per_bin). The z is against the MAD
    of the surviving residuals, so the artifact cannot inflate its own
    significance.
    """
    if len(vals) < 4 * period:
        return None
    base = statistics.median(vals)
    sums = [0.0] * period
    counts = [0] * period
    for i, x in enumerate(vals):
        b = i % period
        sums[b] += x - base
        counts[b] += 1
    if min(counts) == 0:
        return None
    means = [sums[b] / counts[b] for b in range(period)]

    # One bin wide against its own neighbours: the sawtooth is smooth
    # across adjacent bins and the artifact is not.
    resid = [means[b] - (means[(b - 1) % period]
                         + means[(b + 1) % period]) / 2.0
             for b in range(period)]

    keep = list(range(period))
    if mask_wrap:
        # The wrap is where the folded profile falls by most of its span.
        drops = [means[b] - means[(b - 1) % period] for b in range(period)]
        w = min(range(period), key=lambda b: drops[b])
        masked = {(w + k) % period for k in (-2, -1, 0, 1, 2)}
        keep = [b for b in range(period) if b not in masked]
    if len(keep) < 8:
        return None

    vals_keep = [resid[b] for b in keep]
    centre = statistics.median(vals_keep)
    mad = statistics.median([abs(v - centre) for v in vals_keep]) * 1.4826
    mad = mad or 1e-9
    phase = max(keep, key=lambda b: abs(resid[b] - centre))
    spike = resid[phase] - centre
    return spike, phase, abs(spike) / mad, min(counts)


def gen_arm(board, i, args):
    """The other half of the comparison: the device's own table, with no
    host in the DAC path at all.

    `pair_fold` is issue #5's instrument and this is issue #5's preset.
    gen holds each DAC level for two ADC samples, so differencing within
    the pair cancels the staircase by construction and leaves a
    one-sample artifact at full height - in codes, which is the unit
    both issues quote.
    """
    res = measure.run_capture(board, preset="M", seconds=args.seconds)
    ps = res.stream
    vals = ps.series.get(measure.CH_A0) or []
    start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
    f = measure.pair_fold(list(vals[start:]))
    row = {"run": i, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "arm": "gen", "bench": args.bench,
           "preset": "M", "period": f.get("period"),
           "spike_codes": round(f.get("spike", 0.0), 3),
           "spike_phase": f.get("spike_phase"),
           "spike_z": round(f.get("spike_z", 0.0), 1),
           "peak_codes": round(f.get("peak", 0.0), 3),
           "peak_z": round(f.get("z", 0.0), 1),
           "control_spike_z": round(f.get("control_spike_z", 0.0), 1),
           "n_per_bin": f.get("n_per_bin"),
           "hold_ok": f.get("hold_ok"),
           "pair_spread": f.get("pair_spread"),
           "seq_gaps": ps.seq_gaps, "crc_bad": ps.crc_bad}
    print(f"run {i}: gen   preset M       "
          f"spike={row['spike_codes']} codes at phase {row['spike_phase']} "
          f"(z={row['spike_z']}), peak={row['peak_codes']} "
          f"(z={row['peak_z']})  hold_ok={row['hold_ok']} "
          f"spread={row['pair_spread']}", flush=True)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=8)
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--dac-sps", type=int, default=200000)
    ap.add_argument("--step", type=int, default=measure.RAMP_STEP)
    ap.add_argument("--arms", default="host",
                    help="host, gen, or host,gen - interleaved run by run "
                         "so warm-up and weather cannot favour one")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    period = 4096 // args.step          # captured samples per table wrap
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        for i in range(1, args.runs + 1):
            arm = arms[(i - 1) % len(arms)]
            if arm == "gen":
                rows.append(gen_arm(board, i, args))
                board.stop()
                board.drain_console(0.3)
                continue
            res = measure.run_loop(board, dac_sps=args.dac_sps,
                                   adc_hz=200000, channels=2,
                                   ramp=args.step, seconds=args.seconds)
            ps = res.stream
            vals = ps.series.get(measure.CH_A0) or []
            start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
            tail = list(vals[start:])
            ev = measure.ramp_discontinuities(ps, step=args.step)

            got = masked_spike(tail, period)
            ctl = masked_spike(tail, period + 1)
            row = {"run": i, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "arm": "host", "bench": args.bench,
                   "dac_sps": args.dac_sps,
                   "ramp_step": args.step, "period": period,
                   "events": len(ev),
                   "seq_gaps": ps.seq_gaps, "crc_bad": ps.crc_bad,
                   "under": res.play.underruns if res.play else None}
            if got:
                spike, phase, z, n = got
                row.update({"spike_codes": round(spike, 3),
                            "spike_phase": phase, "spike_z": round(z, 1),
                            "n_per_bin": n})
            if ctl:
                row.update({"control_period": period + 1,
                            "control_spike_codes": round(ctl[0], 3),
                            "control_spike_z": round(ctl[2], 1)})
            rows.append(row)
            print(f"run {i}: host  ev={row['events']:6d}  "
                  f"spike={row.get('spike_codes')} codes at phase "
                  f"{row.get('spike_phase')} (z={row.get('spike_z')}, "
                  f"n/bin={row.get('n_per_bin')})   control "
                  f"{row.get('control_spike_codes')} codes "
                  f"(z={row.get('control_spike_z')})", flush=True)
            board.stop()
            board.drain_console(0.3)
    finally:
        try:
            board.stop()
        finally:
            board.close()

    print()
    for a in arms:
        got = [r["spike_codes"] for r in rows
               if r.get("arm") == a and r.get("spike_codes") is not None]
        if got:
            mags = sorted(abs(v) for v in got)
            print(f"{a:5s}: {len(got)} runs, |spike| "
                  f"{mags[0]:.1f}-{mags[-1]:.1f} codes, "
                  f"median {mags[len(mags) // 2]:.1f}")
    if args.out:
        with open(args.out, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
