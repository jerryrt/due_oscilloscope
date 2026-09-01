"""#24 per-wrap or per-second, with the step height and the pair count
both held fixed. Replaces the VOID arm in issue24_wrap_rate.py.

That arm scanned the ramp step, which changes the wrap rate AND the DAC
step height - and the step height is what a straddled pair reads, so the
scan set its own noise floor. `records/issue24-wrap-rate-VOID-windows.jsonl`.

This holds the table fixed (512 entries, ramp step 8, so the step height
never moves) and holds the ADC rate fixed (so the number of pairs the
detector examines never moves), and varies only the DAC rate - which is
the wrap rate:

    arm    adc_hz   dac_sps   hold   wraps/s   pairs/s   step height
    FAST   300000   150000     2      293.0    150000    8 DAC codes
    SLOW   300000    75000     4      146.5    150000    8 DAC codes

300000 Hz is RC 130 exactly (39 MHz / 130), and divides by both 2 and 4,
so the hold is an exact integer in both arms and pair_fold's premise
holds. A fractional hold would break the pairing and reintroduce
straddling, which is the whole failure being avoided.

PRE-REGISTERED before the first run:

  A. count scales with the wrap rate (FAST/SLOW ratio near 2.0)
     -> the events are per-wrap or per-DAC-sample. This issue's title
        is right about the periodicity.

  B. count is flat (ratio near 1.0)
     -> the events are per-second or per-ADC-pair. The "one sample per
        DAC table wrap" framing is wrong and needs retracting.

  C. anything else -> report the ratio, claim no mechanism.

  D. counts near zero in both arms -> the detector is not seeing the
     phenomenon; no conclusion. Listed as an outcome rather than
     discovered afterwards.

WHAT THIS CANNOT SEPARATE, said before it is run rather than after.
dac_sps varies between the arms, so "once per table wrap" and "once per
N DAC samples" scale together and this design cannot tell them apart.
Likewise "per second" and "per ADC pair" are degenerate here because the
ADC rate is deliberately fixed. So the result splits
{per-wrap, per-DAC-sample} from {per-second, per-ADC-pair} and no
further. That is still the split the issue title turns on.

Interleaved arm by arm, never blocked, so a drift lands on both.
"""
import argparse
import importlib.util
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure  # noqa: E402
import provenance  # noqa: E402

# Reuse the detector rather than copy it: a second copy of a threshold
# rule is how two benches came to read one statistic two ways (#24).
_spec = importlib.util.spec_from_file_location(
    "issue24_wrap_rate", os.path.join(ROOT, "tools", "issue24_wrap_rate.py"))
_wr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_wr)
count_events = _wr.count_events
THRESHOLDS = _wr.THRESHOLDS

ADC_HZ = 300_000                      # RC 130 exactly
ARMS = (("FAST", 150_000, 2), ("SLOW", 75_000, 4))
ENTRIES = 512                         # ramp step 8, so step height is fixed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--reps", type=int, default=6)
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        prov = provenance.run_fields(board)
        print("provenance: " + ", ".join("%s=%s" % (k, v)
                                         for k, v in prov.items()), flush=True)
        for name, dac, hold in ARMS:
            print("  %-5s adc %d / dac %d = hold %d, wraps/s %.1f, pairs/s %d"
                  % (name, ADC_HZ, dac, hold, dac / float(ENTRIES), ADC_HZ // 2),
                  flush=True)
        for rep in range(1, args.reps + 1):
            for name, dac, hold in ARMS:            # interleaved
                res = measure.run_loop(board, dac_sps=dac, adc_hz=ADC_HZ,
                                       channels=2, ramp=8,
                                       seconds=args.seconds)
                ps = res.stream
                vals = ps.series.get(measure.CH_A0) or []
                start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
                tail = list(vals[start:])
                ev = count_events(tail)
                row = {"rep": rep, "arm": name, "issue": 24,
                       "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "team": "windows-platform-team", "bench": "windows-desk",
                       "test": "per-wrap-or-per-second-pairs-held-fixed",
                       "adc_hz": ADC_HZ, "dac_sps": dac, "hold": hold,
                       "entries": ENTRIES, "ramp_step": 8,
                       "wraps_per_sec": round(dac / float(ENTRIES), 2),
                       "seconds": args.seconds, "n_samples": len(tail),
                       "seq_gaps": ps.seq_gaps, "crc_bad": ps.crc_bad,
                       "underruns": res.play.underruns if res.play else None,
                       "events": ev}
                row.update(prov)
                rows.append(row)
                print("rep %2d %-5s hold %d  n=%-7d gaps=%s  %s"
                      % (rep, name, hold, len(tail), ps.seq_gaps,
                         " ".join("%s=%s" % (k, ev[k]) for k in sorted(ev)
                                  if k.startswith("n_ge") or k == "wrap_like")
                         if ev else "NO EVENTS DICT"), flush=True)
    finally:
        try:
            board.close()
        except Exception:
            pass

    summary = {"issue": 24, "test": "per-wrap-or-per-second-pairs-held-fixed",
               "team": "windows-platform-team", "bench": "windows-desk",
               "adc_hz": ADC_HZ, "entries": ENTRIES, "reps": args.reps,
               "seconds": args.seconds}
    per = {}
    for name, dac, hold in ARMS:
        got = [r for r in rows if r["arm"] == name and r["events"]
               and not r["seq_gaps"] and not r["crc_bad"]]
        d = {"n": len(got), "dac_sps": dac, "hold": hold,
             "wraps_per_sec": round(dac / float(ENTRIES), 2),
             "n_pairs_mean": (round(statistics.mean(
                 [r["events"]["n_pairs"] for r in got]), 0) if got else None),
             "wrap_like_mean": (round(statistics.mean(
                 [r["events"]["wrap_like"] for r in got]), 2) if got else None)}
        for t in THRESHOLDS:
            k = "n_ge_%d" % int(t)
            v = [r["events"][k] for r in got]
            d[k] = {"mean": round(statistics.mean(v), 3),
                    "values": v} if v else None
        per[name] = d
    summary["per_arm"] = per
    ratios = {}
    for t in THRESHOLDS:
        k = "n_ge_%d" % int(t)
        f, s = per["FAST"].get(k), per["SLOW"].get(k)
        ratios[k] = (round(f["mean"] / s["mean"], 3)
                     if f and s and s["mean"] else None)
    summary["FAST_over_SLOW"] = ratios
    summary["expected_if_per_wrap"] = 2.0
    summary["expected_if_per_second"] = 1.0
    summary["cannot_separate"] = ("per-wrap from per-DAC-sample (dac_sps "
                                  "varies), and per-second from per-ADC-pair "
                                  "(adc_hz is fixed by design)")
    print()
    print(json.dumps(summary, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
            fh.write(json.dumps(summary) + "\n")
        print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
