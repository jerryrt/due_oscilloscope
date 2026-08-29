#!/usr/bin/env python3
"""Judge a temperature soak against issue #18's adopted bands.

The bands were fixed on #18 *before* the soak's answer was known, which
is the only reason its verdict means anything - so this tool implements
them and does not invent any. Two components, reported separately, the
**worse one governing**:

  1. **mean drift** - |last minus first post-warm-up 30-minute mean|.
     A walk is what makes a stored calibration wrong later, and it is
     the number conditioning could actually fix.
  2. **worst-case calibration error** - the oscillation amplitude (half
     the peak-to-peak of the 10-minute means) plus half the mean drift.
     A calibration sits at the *mean* of an oscillation, so the worst
     error a user of it ever sees is the amplitude, not the full swing.
     Charging peak-to-peak double-counts the wiggle and would buy
     conditioning work for a reading that does not need it.

Bands, from the owner's proposal as adopted:

  <= 0.25 codes   close with the documented negative
  <= 1.00 codes   close with a documented note
   > 1.00 codes   the conditioning implementation is bought

The first 30 minutes are excluded as die warm-up, which is kept in the
record rather than trimmed at capture time because where the warm-up
ends is itself a reading.

    .venv/Scripts/python.exe tools/temp_bands.py \\
        records/temp-soak-overnight.jsonl

**It reports the soak's own duration and refuses to hide a short one.**
The bands were set for an 8-hour soak; a shorter record cannot deliver
the drift figure they were sized against, and the verdict line says so
rather than quoting a band pass taken over the wrong window.
"""
import argparse
import json
import statistics
import sys

WARMUP_S = 30 * 60
BAND_NEGATIVE = 0.25
BAND_NOTE = 1.00
FULL_SOAK_S = 8 * 3600


def block_means(rows, block_s):
    """Mean code per block of wall time, in order, with each block's span."""
    if not rows:
        return []
    out, cur, start = [], [], rows[0]["t_s"]
    for r in rows:
        if r["t_s"] - start >= block_s:
            if cur:
                out.append((start, rows[len(out)]["t_s"], statistics.fmean(cur)))
            cur, start = [], r["t_s"]
        cur.append(r["code"])
    if cur:
        out.append((start, rows[-1]["t_s"], statistics.fmean(cur)))
    return out


def verdict(value):
    if value <= BAND_NEGATIVE:
        return "close, documented negative"
    if value <= BAND_NOTE:
        return "close, documented note"
    return "conditioning work is bought"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("record")
    ap.add_argument("--warmup", type=float, default=WARMUP_S,
                    help="seconds excluded as die warm-up (default 1800)")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    rows = []
    with open(args.record) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows.sort(key=lambda r: r["t_s"])
    if not rows:
        sys.exit("empty record")

    span = rows[-1]["t_s"] - rows[0]["t_s"]
    post = [r for r in rows if r["t_s"] - rows[0]["t_s"] >= args.warmup]
    if len(post) < 4:
        sys.exit("not enough post-warm-up rows to judge")

    seams = sum(1 for r in rows if r.get("seam"))

    m30 = block_means(post, 30 * 60)
    m10 = block_means(post, 10 * 60)
    if len(m30) < 2 or len(m10) < 2:
        sys.exit("record too short for a 30-minute endpoint comparison")

    mean_drift = abs(m30[-1][2] - m30[0][2])
    vals10 = [m for _, _, m in m10]
    pp10 = max(vals10) - min(vals10)
    amplitude = pp10 / 2.0
    worst_case = amplitude + mean_drift / 2.0
    governing = max(mean_drift, worst_case)

    codes = [r["code"] for r in post]
    print(f"record        {args.record}")
    print(f"rows          {len(rows)} total, {len(post)} post-warm-up "
          f"({args.warmup / 60:.0f} min excluded), {seams} seam rows")
    print(f"span          {span:.0f} s = {span / 3600:.2f} h")
    print(f"post-warm-up  median {statistics.median(codes):.2f} codes, "
          f"sd {statistics.pstdev(codes):.2f}")
    print()
    print(f"30-min means  {len(m30)} blocks, "
          f"first {m30[0][2]:.2f} -> last {m30[-1][2]:.2f}")
    print(f"10-min means  {len(m10)} blocks, "
          f"{min(vals10):.2f} .. {max(vals10):.2f}  (p-p {pp10:.2f})")
    print()
    print(f"mean drift            {mean_drift:.2f} codes   "
          f"-> {verdict(mean_drift)}")
    print(f"worst-case cal error  {worst_case:.2f} codes   "
          f"-> {verdict(worst_case)}   "
          f"(amplitude {amplitude:.2f} + half drift {mean_drift / 2:.2f})")
    print()
    print(f"GOVERNING (worse)     {governing:.2f} codes   -> {verdict(governing)}")

    short = span < FULL_SOAK_S
    if short:
        print()
        print(f"** SHORT SOAK: {span / 3600:.2f} h against the 8 h the bands "
              f"were fixed for.")
        print("   The drift component is the one that needs the full window - "
              "a walk")
        print("   has less time to show. Quote this verdict with its duration, "
              "and do")
        print("   not read a band pass here as the 8-hour result.")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"record": args.record, "span_s": span,
                       "rows": len(rows), "post_rows": len(post),
                       "warmup_s": args.warmup, "seam_rows": seams,
                       "mean_drift": round(mean_drift, 3),
                       "amplitude": round(amplitude, 3),
                       "worst_case": round(worst_case, 3),
                       "governing": round(governing, 3),
                       "verdict": verdict(governing),
                       "full_soak": not short}, fh, indent=2)
            fh.write("\n")
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
