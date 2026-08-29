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

**And the host arm now reports its whole profile, not its argmax.**
`tools/issue5_sites.py` reads the internal generator per site, and that
reading is what showed the sites do not share an amplitude dependency -
one scales with the signal, one is flat, one grows as it shrinks. The
host-fed path had never been read the same way, so #24's "additive,
~28-30 codes regardless of RAMP_STEP" was a single number over an
unknown mixture. `masked_sites` supplies the table; `masked_spike`
stays for continuity with the rows already recorded, with its own
docstring now saying what it is.
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


def _masked_resid(vals, period, mask_wrap=True):
    """The folded neighbour residual with the ramp's wrap masked out.

    Returns (resid, keep, centre, mad, n_per_bin), the common work
    behind both `masked_spike` and `masked_sites`. The MAD is taken
    over the surviving bins only, so the artifact cannot inflate its
    own significance.
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

    # The wrap is where the folded profile falls by most of its span. It
    # is also the ramp's table index 0, which is the whole reason to
    # find it even when it is not being masked - see wrap_relative().
    drops = [means[b] - means[(b - 1) % period] for b in range(period)]
    w = min(range(period), key=lambda b: drops[b])

    keep = list(range(period))
    if mask_wrap:
        masked = {(w + k) % period for k in (-2, -1, 0, 1, 2)}
        keep = [b for b in range(period) if b not in masked]
    if len(keep) < 8:
        return None

    vals_keep = [resid[b] for b in keep]
    centre = statistics.median(vals_keep)
    mad = statistics.median([abs(v - centre) for v in vals_keep]) * 1.4826
    return resid, keep, centre, mad or 1e-9, min(counts), w


def wrap_relative(b, wrap, period):
    """A site's position as a ramp table index, not a capture-frame bin.

    **Every site position #5 and #24 have published is a bin in a frame
    whose zero is wherever the capture started** (`0bb9bd3`), so two
    readings of the same site differ by a rotation nobody measured - and
    on the internal path recovering it costs an alignment argument
    against the sine's own shape.

    The host-fed ramp does not need one. Its wrap is a full-scale step
    at table index 0, present in every capture and already located here
    to be masked, so subtracting it converts a bin straight into a table
    index. The one free absolute reference either path has.
    """
    return (b - wrap) % period


def masked_spike(vals, period, mask_wrap=True):
    """Largest one-bin neighbour residual, with the ramp's wrap masked.

    Returns (spike_codes, phase, z, n_per_bin).

    **This is an argmax, and on this artifact an argmax is a
    hypothesis.** Reading it as "the displacement" is what had the two
    benches reporting the same statistic two different ways for a day -
    see `masked_sites`, and quote the site table beside this number.
    """
    got = _masked_resid(vals, period, mask_wrap)
    if got is None:
        return None
    resid, keep, centre, mad, n, _wrap = got
    phase = max(keep, key=lambda b: abs(resid[b] - centre))
    spike = resid[phase] - centre
    return spike, phase, abs(spike) / mad, n


def masked_sites(vals, period, mask_wrap=True, z_min=measure.FOLD_Z_DIRTY):
    """Every bin that stands out on the host-fed path, not just the largest.

    `tools/issue5_sites.py` does this for the *internal* generator, and
    the host-fed ramp had never been read the same way - so #24's
    "additive, ~28-30 codes regardless of RAMP_STEP" was one number over
    an unknown mixture of sites, exactly the reading that turned out to
    be wrong on the internal path (site 198 scales with the signal, 138
    is flat, 177 grows as it shrinks).

    Two differences from `issue5_sites.sites()`, and both are forced by
    the waveform. That tool reads bins straight off the profile because
    `pair_fold` leaves no waveform underneath; here a sawtooth is still
    there, so the *neighbour residual* is the right basis - which also
    means a real single-bin site casts a -A/2 shadow into each
    neighbour. Adjacent bins are therefore folded into the strongest of
    the group rather than counted as sites of their own.

    Returns (sites, mad, n_per_bin) with sites as (phase, codes, z),
    strongest first.

    **Its power, measured rather than assumed.** On a synthetic sawtooth
    (512 bins, 60 wraps, 3-code noise) it recovers three injected sites
    at -30.0 / +12.0 / -6.0 as -30.50 / +11.81 / -6.22 at exactly their
    phases, where `masked_spike` reports only the largest; and it finds
    **0 false sites in 5120 bins** across ten un-injected runs.

    The one regime it cannot read is **two real sites on adjacent bins**:
    injected -25.0 at bin 200 and +25.0 at 201 come back as one site of
    +36.8 at 201 plus +12.5 at 199. Shadow-absorption and the neighbour
    residual cannot tell a real neighbour from a shadow, so an adjacent
    pair merges and its magnitude is wrong. The sites this artifact
    actually shows sit ~21 bins apart, so that is not the operating
    regime - but a merged pair must never be read as one site, and this
    tool cannot warn you that it happened.
    """
    got = _masked_resid(vals, period, mask_wrap)
    if got is None:
        return None
    resid, keep, _centre, _mad, n, wrap = got
    sites, mad = measure.fold_sites(resid, z_min=z_min, keep=keep,
                                    absorb=True)
    return sites, mad, n, wrap


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
    ap.add_argument("--channels", type=int, default=2,
                    help="ADC channels. adc_hz is per channel, so A0's "
                         "own rate and the fold are unchanged by this - "
                         "what changes is whether the sequencer walks a "
                         "multiplexer between A0 conversions. That is "
                         "the arm that asks whether the artifact is the "
                         "DAC's or the ADC's, which this issue has "
                         "assumed rather than tested")
    ap.add_argument("--adc-hz", type=int, default=200000,
                    help="ADC trigger rate. Scaled WITH --dac-sps it "
                         "keeps one captured sample per DAC update, so "
                         "the fold still locks, while changing the "
                         "wall-clock time one update takes. That is the "
                         "arm that tells a comb counted in DAC updates "
                         "from one sitting at a fixed frequency: the "
                         "first keeps its spacing, the second scales it")
    ap.add_argument("--step", type=int, default=measure.RAMP_STEP)
    ap.add_argument("--period", type=int, default=0,
                    help="captured samples per table wrap, overriding "
                         "4096/step. Needed when adc_hz is not equal to "
                         "dac_sps: the default assumes one captured "
                         "sample per DAC update, and at a ratio of 2 "
                         "there are two. That ratio is the one thing "
                         "the earlier rate arm did NOT vary - it scaled "
                         "both clocks together, which holds the ratio "
                         "fixed, so a beat between the DAC and ADC "
                         "timers would have survived it unchanged")
    ap.add_argument("--arms", default="host",
                    help="host, gen, or host,gen - interleaved run by run "
                         "so warm-up and weather cannot favour one")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    period = args.period or (4096 // args.step)          # captured samples per table wrap
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
                                   adc_hz=args.adc_hz,
                                   channels=args.channels,
                                   ramp=args.step, seconds=args.seconds)
            ps = res.stream
            vals = ps.series.get(measure.CH_A0) or []
            start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
            tail = list(vals[start:])
            ev = measure.ramp_discontinuities(ps, step=args.step)

            got = masked_spike(tail, period)
            ctl = masked_spike(tail, period + 1)
            sites = masked_sites(tail, period)
            row = {"run": i, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "arm": "host", "bench": args.bench,
                   "dac_sps": args.dac_sps,
                   "adc_hz": args.adc_hz,
                   "channels": args.channels,
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
            if sites:
                found, site_mad, _, wrap = sites
                # Both coordinates are recorded: the bin, so these rows
                # compare with everything already published, and the
                # table index, which is the one that survives a rotation.
                row["sites"] = [[b, round(v, 3), round(z, 1)]
                                for b, v, z in found]
                row["sites_table"] = [[wrap_relative(b, wrap, period),
                                       round(v, 3), round(z, 1)]
                                      for b, v, z in found]
                row["wrap_bin"] = wrap
                row["site_mad"] = round(site_mad, 3)
            rows.append(row)
            print(f"run {i}: host  ev={row['events']:6d}  "
                  f"spike={row.get('spike_codes')} codes at phase "
                  f"{row.get('spike_phase')} (z={row.get('spike_z')}, "
                  f"n/bin={row.get('n_per_bin')})   control "
                  f"{row.get('control_spike_codes')} codes "
                  f"(z={row.get('control_spike_z')})", flush=True)
            if row.get("sites") is not None:
                shown = ", ".join(f"{t}:{v:+.2f}(z{z:.0f})"
                                  for t, v, z in row["sites_table"][:8])
                print(f"          sites n={len(row['sites'])} "
                      f"mad={row['site_mad']} wrap={row['wrap_bin']}  "
                      f"table {shown or '-'}", flush=True)
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

    # The site table across runs, which is the reading the argmax above
    # cannot give: a site that is present every run with a moving value
    # is a different animal from one that comes and goes.
    host_rows = [r for r in rows if r.get("sites_table") is not None]
    if host_rows:
        seen = {}
        for r in host_rows:
            for t, v, _z in r["sites_table"]:
                seen.setdefault(t, []).append(v)
        wraps = sorted({r["wrap_bin"] for r in host_rows})
        print(f"\nhost sites across {len(host_rows)} runs, in RAMP TABLE "
              f"indices (wrap bins seen: {wraps}):")
        for t in sorted(seen, key=lambda k: -len(seen[k])):
            vs = seen[t]
            print(f"  {t:4d}: {len(vs)}/{len(host_rows)}  "
                  f"{min(vs):+.2f} .. {max(vs):+.2f}")
        recur = [t for t in seen if len(seen[t]) >= 3]
        if recur:
            res = {}
            for t in sorted(recur):
                res.setdefault(t % 21, []).append(t)
            print("\n  mod 21, the residue classes the two benches share:")
            for r_, ts in sorted(res.items()):
                print(f"    residue {r_:2d}: {ts}")
    if args.out:
        with open(args.out, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
