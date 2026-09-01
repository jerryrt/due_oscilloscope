"""#24's last open question: are the host-fed events PER WRAP or PER SECOND?

issue24_drive_path.py established that the instability belongs to the
host-fed drive path, and that it is locked to neither the DAC table wrap
nor the play buffer. What is left is what the events actually are, and
this issue's title asserts one of the two answers:

    "One sample per DAC table wrap arrives ~17-30 codes low"

CORRECTING MY OWN PROPOSED DISCRIMINATOR. I said on the issue that
varying --seconds would separate these. It does not: at a fixed sample
rate, doubling the duration doubles the elapsed time AND the number of
wraps, so both hypotheses predict the same doubling. Duration is not a
lever at all.

The lever is the WRAP RATE at fixed duration. The table holds
4096/ramp_step entries, so at fixed dac_sps the wraps per second scale
LINEARLY with the ramp step:

    ramp  8 -> 512 entries -> 1x wraps/sec
    ramp 16 -> 256 entries -> 2x
    ramp 32 -> 128 entries -> 4x

Same seconds, same dac_sps, same adc_hz, same everything else. So:

  PER WRAP    event count scales 1 : 2 : 4
  PER SECOND  event count is flat across all three

PRE-REGISTERED, before the first run:

  A. counts scale with the wrap rate (ratio within 1.5x of 1:2:4)
     -> the issue's title is right, the events are per-wrap, and the
        drive-path finding means the host-fed path has a per-wrap defect
        the internal path does not.

  B. counts are flat (max/min <= 1.5)
     -> the events are per-SECOND, and this issue has been named after a
        periodicity it does not have since it was opened. The "one
        sample per DAC table wrap" framing would need retracting.

  C. neither - scaling present but not proportional
     -> report the ratios and claim nothing about mechanism.

  D. counts are zero or near-zero at every step
     -> the detector is not seeing the phenomenon at all and no
        conclusion may be drawn from its ratios. This is the outcome
        that has gone void twice on this project today, so it is listed
        as an outcome rather than discovered as a surprise.

THE DETECTOR is fold-free on purpose, since folding is what made the
period ambiguous in the first place. At hold 2 the DAC holds each level
for two ADC samples, so the two samples of a pair should read the same
and a one-sample artifact lands on exactly one of them - pair_fold's
own premise, and hold_ok was True 12/12 on this path. So:

    d[k] = v[2k] - v[2k+1]        an event is |d[k] - median(d)| > T

Counts are reported at several thresholds because a count that only
exists at one threshold is a threshold artifact. THE ANSWER IS THE
RATIO ACROSS RAMP STEPS, not the absolute count, and the ratio must
hold at every threshold to count as scaling.

The wrap itself is a real full-scale discontinuity and would be counted
as an event at every threshold, once per wrap by construction - which
would manufacture outcome A out of nothing. Pairs whose difference is a
large fraction of full scale are excluded and counted separately.

Ramp steps are interleaved, never blocked, so a drift over the run
lands on all three rather than on whichever ran last.
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
import provenance  # noqa: E402

#: A pair difference this large is the sawtooth's own full-scale step,
#: not an event. Full scale is 4095 DAC codes; through the loop gain the
#: wrap reads a few thousand ADC codes. Anything past this is the wrap.
WRAP_CODES = 200.0

#: The counts are reported at each of these, and scaling must survive
#: all of them.
THRESHOLDS = (10.0, 20.0, 30.0)


def count_events(tail):
    """Within-pair discontinuities, fold-free. Returns counts per threshold."""
    if len(tail) < 4:
        return None
    d = [tail[i] - tail[i + 1] for i in range(0, len(tail) - 1, 2)]
    if not d:
        return None
    med = statistics.median(d)
    dev = [abs(x - med) for x in d]
    wraps = sum(1 for x in dev if x >= WRAP_CODES)
    body = [x for x in dev if x < WRAP_CODES]
    if not body:
        return None
    body_med = statistics.median(body)
    out = {"n_pairs": len(d), "median": round(med, 3),
           "wrap_like": wraps,
           "mad": round(statistics.median([abs(x - body_med) for x in body]), 4)}
    for t in THRESHOLDS:
        out["n_ge_%d" % int(t)] = sum(1 for x in body if x >= t)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--reps", type=int, default=6,
                    help="reps per ramp step; steps are interleaved")
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--steps", default="8,16,32")
    ap.add_argument("--dac-sps", type=int, default=100000)
    ap.add_argument("--adc-hz", type=int, default=200000)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    steps = [int(s) for s in args.steps.split(",") if s.strip()]
    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        prov = provenance.run_fields(board)
        print("provenance: " + ", ".join("%s=%s" % (k, v)
                                         for k, v in prov.items()), flush=True)
        for step in steps:
            entries = 4096 // step
            wps = args.dac_sps / float(entries)
            print("  ramp %-3d -> %4d entries -> %.1f wraps/sec"
                  % (step, entries, wps), flush=True)
        for rep in range(1, args.reps + 1):
            for step in steps:               # interleaved, not blocked
                res = measure.run_loop(board, dac_sps=args.dac_sps,
                                       adc_hz=args.adc_hz, channels=2,
                                       ramp=step, seconds=args.seconds)
                ps = res.stream
                vals = ps.series.get(measure.CH_A0) or []
                start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
                tail = list(vals[start:])
                ev = count_events(tail)
                entries = 4096 // step
                row = {"rep": rep, "ramp_step": step, "entries": entries,
                       "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "issue": 24, "team": "windows-platform-team",
                       "bench": "windows-desk",
                       "seconds": args.seconds, "dac_sps": args.dac_sps,
                       "adc_hz": args.adc_hz,
                       "wraps_per_sec": round(args.dac_sps / float(entries), 2),
                       "n_samples": len(tail),
                       "seq_gaps": ps.seq_gaps, "crc_bad": ps.crc_bad,
                       "underruns": res.play.underruns if res.play else None,
                       "events": ev}
                row.update(prov)
                rows.append(row)
                print("rep %2d ramp %-3d n=%-7d gaps=%s under=%s  %s"
                      % (rep, step, len(tail), ps.seq_gaps,
                         row["underruns"],
                         " ".join("%s=%s" % (k, ev[k]) for k in sorted(ev)
                                  if k.startswith("n_ge") or k == "wrap_like")
                         if ev else "no events dict"), flush=True)
    finally:
        try:
            board.close()
        except Exception:
            pass

    print()
    summary = {"issue": 24, "test": "per-wrap-or-per-second",
               "team": "windows-platform-team", "bench": "windows-desk",
               "seconds": args.seconds, "dac_sps": args.dac_sps,
               "adc_hz": args.adc_hz, "steps": steps, "reps": args.reps}
    per = {}
    for step in steps:
        got = [r for r in rows if r["ramp_step"] == step
               and not r["seq_gaps"] and not r["crc_bad"] and r["events"]]
        d = {"n_runs": len(got),
             "wraps_per_sec": got[0]["wraps_per_sec"] if got else None,
             "wrap_like_mean": (round(statistics.mean(
                 [r["events"]["wrap_like"] for r in got]), 2) if got else None)}
        for t in THRESHOLDS:
            k = "n_ge_%d" % int(t)
            vals = [r["events"][k] for r in got]
            d[k] = {"mean": round(statistics.mean(vals), 3),
                    "total": sum(vals)} if vals else None
        per[str(step)] = d
    summary["per_step"] = per
    # The ratio, which is the answer. Normalised to the smallest step.
    base = str(min(steps))
    ratios = {}
    for t in THRESHOLDS:
        k = "n_ge_%d" % int(t)
        b = per[base][k]["mean"] if per[base][k] else None
        if not b:
            ratios[k] = None
            continue
        ratios[k] = {str(s): round(per[str(s)][k]["mean"] / b, 3)
                     for s in steps if per[str(s)][k]}
    summary["ratio_to_ramp_%s" % base] = ratios
    summary["expected_if_per_wrap"] = {str(s): round(s / float(min(steps)), 3)
                                       for s in steps}
    summary["expected_if_per_second"] = {str(s): 1.0 for s in steps}
    print(json.dumps(summary, indent=2))

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
            fh.write(json.dumps(summary) + "\n")
        print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
