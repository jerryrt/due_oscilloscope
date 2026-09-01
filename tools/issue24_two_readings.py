"""#24 vs #5: both site readings over the SAME captures, so the
comparison is instrument-controlled.

mac-bench put windows-desk's #24 Jaccard of 0.010 in one table against
their own #5 arms at 0.78-1.00 and read the gap as evidence that the
two phenomena differ. The two rows were produced by different inputs to
measure.fold_sites:

  #5,  tools/issue5_sites.py:46    pair_fold's profile, passed AS IS
  #24, tools/issue24_period.py:77  a neighbour residual, keep-masked

fold_sites' own docstring says that choice "is not cosmetic". So the
gap may be the instrument and not the phenomenon, and neither bench can
tell from data taken only one way.

This captures once per run and reads it BOTH ways. One capture, two
readings, so the instrument is the only thing that differs.

PRE-REGISTERED, before the first run, so the reading cannot be chosen
to suit the answer:

  A. pair_fold reports hold_ok FALSE on the host-fed ramp
     -> pair_fold is inapplicable here by its own gate. The neighbour
        residual is the only valid reading of #24, windows-desk's 0.010
        stands as correct, and mac-bench's table is comparing two
        instruments rather than two benches. Their withdrawal of the
        "not the same phenomenon" claim is the right call and the #5
        overlap stays open.

  B. hold_ok TRUE, and pair-reading Jaccard high (>= 0.5) while
     residual-reading Jaccard stays low (<= 0.1)
     -> the instrument makes the difference. #24's "sites are a per-run
        draw" is an artifact of the residual reading, and that is a
        defect in how this issue has been measured all along.

  C. both readings low (<= 0.1)
     -> the site instability is real and survives the instrument. The
        difference from mac-bench is then the bench or the phenomenon,
        which is the interesting answer, and #5-vs-#24 can be argued on
        it.

  D. both readings high
     -> windows-desk's 0.010 does not reproduce at all and the earlier
        record needs retracting, not defending.

No other outcome is a result. A run that gaps or CRC-fails is dropped
before any reading, not after.
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


def residual_reading(tail, period):
    """#24's reading: neighbour residual, wrap masked. issue24_period:77."""
    sums = [0.0] * period
    counts = [0] * period
    for i, v in enumerate(tail):
        sums[i % period] += v
        counts[i % period] += 1
    if min(counts) == 0:
        return None
    means = [sums[b] / counts[b] for b in range(period)]
    resid = [means[b] - (means[(b - 1) % period]
                         + means[(b + 1) % period]) / 2.0
             for b in range(period)]
    drops = [means[b] - means[(b - 1) % period] for b in range(period)]
    w = min(range(period), key=lambda b: drops[b])
    masked = {(w + k) % period for k in (-2, -1, 0, 1, 2)}
    keep = [b for b in range(period) if b not in masked]
    if len(keep) < 8:
        return None
    sites, mad = measure.fold_sites(resid, keep=keep, absorb=True)
    return {"sites": sites, "mad": mad, "wrap": w}


def pair_reading(tail, period):
    """#5's reading: pair_fold's profile, passed as is. issue5_sites:46."""
    pf = measure.pair_fold(tail, period=period)
    if pf is None:
        return None
    prof = pf.get("profile")
    if prof is None:
        return None
    sites, mad = measure.fold_sites(prof)
    return {"sites": sites, "mad": mad,
            "hold_ok": pf.get("hold_ok"),
            "pair_spread": pf.get("pair_spread")}


def jaccard(a, b):
    a, b = set(a), set(b)
    if not a and not b:
        return None
    return len(a & b) / float(len(a | b))


def pairwise(site_sets):
    vals = []
    for i in range(len(site_sets)):
        for j in range(i + 1, len(site_sets)):
            j2 = jaccard(site_sets[i], site_sets[j])
            if j2 is not None:
                vals.append(j2)
    if not vals:
        return None
    return {"n_pairs": len(vals), "mean": round(statistics.mean(vals), 4),
            "min": round(min(vals), 4), "max": round(max(vals), 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=12)
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--ramp", type=int, default=8)
    ap.add_argument("--dac-sps", type=int, default=200000)
    ap.add_argument("--adc-hz", type=int, default=200000)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    # The ADC-side period is the DAC table length times the hold: at
    # hold 2 each DAC level occupies two ADC samples, so a wrap is 1024
    # samples and not 512.
    #
    # Measured, not assumed - a one-sample artifact injected once per
    # 1024-sample wrap, read at both periods:
    #
    #   fold 1024 (right)  site 150 at -25.2 codes, z 168.8, n_per_bin 20
    #   fold  512 (wrong)  site 150 at -12.6 codes, z 114.4, n_per_bin 40
    #
    # So the wrong period does NOT move the site - it HALVES the
    # amplitude, by averaging the wrap's two halves and diluting an
    # artifact that lives in one of them. That is the dangerous failure
    # here, because #24 is a claim about magnitude ("~17-30 codes low"):
    # a site table read at the wrong period looks entirely healthy and
    # reports half the number. Derived, never passed in.
    dac_entries = 4096 // args.ramp
    hold = round(float(args.adc_hz) / float(args.dac_sps), 3)
    if abs(hold - round(hold)) > 1e-6 or round(hold) < 1:
        raise SystemExit("hold must be a positive integer; adc_hz/dac_sps "
                         "= %s. A fractional hold has no fold period."
                         % (hold,))
    period = dac_entries * int(round(hold))
    board = measure.Board(settle=3.0)
    rows, dropped = [], 0
    try:
        board.stop()
        board.drain_console(0.5)
        prov = provenance.run_fields(board)
        print("provenance: " + ", ".join("%s=%s" % (k, v)
                                         for k, v in prov.items()), flush=True)
        print("period %d, ramp step %d, hold %.3f (adc %d / dac %d)"
              % (period, args.ramp, hold, args.adc_hz, args.dac_sps), flush=True)
        for i in range(1, args.runs + 1):
            res = measure.run_loop(board, dac_sps=args.dac_sps,
                                   adc_hz=args.adc_hz, channels=2,
                                   ramp=args.ramp, seconds=args.seconds)
            ps = res.stream
            if ps.seq_gaps or ps.crc_bad:
                dropped += 1
                print("run %2d DROPPED: seq_gaps=%s crc_bad=%s"
                      % (i, ps.seq_gaps, ps.crc_bad), flush=True)
                continue
            vals = ps.series.get(measure.CH_A0) or []
            start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
            tail = list(vals[start:])
            rr = residual_reading(tail, period)
            pr = pair_reading(tail, period)
            row = {"run": i, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "issue": 24, "also": [5],
                   "team": "windows-platform-team", "bench": "windows-desk",
                   "period": period, "ramp_step": args.ramp,
                   "adc_hz": args.adc_hz, "dac_sps": args.dac_sps,
                   "hold": hold, "n_samples": len(tail),
                   "seq_gaps": ps.seq_gaps, "crc_bad": ps.crc_bad}
            row.update(prov)
            for label, got in (("residual", rr), ("pair", pr)):
                if got is None:
                    row[label] = None
                    continue
                d = {"n_sites": len(got["sites"]),
                     "mad": round(got["mad"], 4),
                     "bins": [b for b, _v, _z in got["sites"]],
                     "sites": [[b, round(v, 3), round(z, 1)]
                               for b, v, z in got["sites"][:12]]}
                if "hold_ok" in got:
                    d["hold_ok"] = got["hold_ok"]
                    d["pair_spread"] = (round(got["pair_spread"], 3)
                                        if got["pair_spread"] is not None
                                        else None)
                if "wrap" in got:
                    d["wrap"] = got["wrap"]
                row[label] = d
            rows.append(row)
            r_, p_ = row.get("residual"), row.get("pair")
            print("run %2d  residual n=%-3s bins=%-28s | pair n=%-3s "
                  "hold_ok=%-5s spread=%s"
                  % (i,
                     r_["n_sites"] if r_ else "-",
                     str(r_["bins"][:6]) if r_ else "-",
                     p_["n_sites"] if p_ else "-",
                     p_.get("hold_ok") if p_ else "-",
                     p_.get("pair_spread") if p_ else "-"), flush=True)
    finally:
        try:
            board.close()
        except Exception:
            pass

    print()
    print("kept %d runs, dropped %d" % (len(rows), dropped))
    summary = {"issue": 24, "also": [5], "test": "two-readings-one-capture",
               "team": "windows-platform-team", "bench": "windows-desk",
               "period": period, "ramp_step": args.ramp, "hold": hold,
               "adc_hz": args.adc_hz, "dac_sps": args.dac_sps,
               "runs_kept": len(rows), "runs_dropped": dropped}
    for label in ("residual", "pair"):
        sets = [r[label]["bins"] for r in rows if r.get(label)]
        summary[label + "_jaccard"] = pairwise(sets)
        summary[label + "_n_sites"] = [len(s) for s in sets]
    holds = [r["pair"].get("hold_ok") for r in rows
             if r.get("pair") and "hold_ok" in r["pair"]]
    summary["hold_ok_true"] = sum(1 for h in holds if h)
    summary["hold_ok_total"] = len(holds)
    print(json.dumps(summary, indent=2))

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
            fh.write(json.dumps(summary) + "\n")
        print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
