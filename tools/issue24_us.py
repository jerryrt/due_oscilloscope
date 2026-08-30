#!/usr/bin/env python3
"""#24's gap census, in microseconds as well as in updates.

This issue spent days on the number 21 because nobody divided it by a
rate. `fd554c2` settled that the second lattice is a *time*, and the
evidence for it was already sitting in two benches' records in a unit
neither had converted - windows-desk's ratio-4 census of "5s with 6s
making up the difference" is a mean of 5.25, which at DAC 50,000 Hz is
105.00 us exactly, and nobody saw it because the tool printed 5 and 6.

So this prints both, always, for any `issue24_hold.py` record. It is
arithmetic on a file and needs no board.

**Read the three predictions as three columns, because at a fixed ADC
rate two of them are the same number.** With the ADC held and the DAC
divided by `hold`:

    update-locked      21 DAC updates          -> 21, every hold
    conversion-locked  21 ADC conversions      -> 21 / hold
    time-locked        105 us                  -> 105e-6 * dac_hz

and `21 / hold == 105e-6 * dac_hz` whenever `adc_hz` is 200,000, which
is where this issue was born and where most of its arms were taken. A
hold sweep at one ADC rate therefore separates *update-locked* from the
other two and cannot touch the pair. Only moving `--adc-hz` does that.
The header prints all three so the degeneracy is visible rather than
rediscovered.

    python3 tools/issue24_us.py records/issue24-hold-linux.jsonl
"""
import argparse
from math import gcd
import collections
import json
import statistics

#: The two candidate lattices, in the units each is defined in.
UPDATE_LOCKED_UPDATES = 21
TIME_LOCKED_US = 105.0


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def census(rows, key):
    """Pooled spacings, MAD and n_per_bin for one (hold, dac, adc) arm.

    Grouping by HOLD ALONE pools arms taken at different rates and then
    labels the result with whichever row happened to come last. On a
    file holding both RC 195 hold 2 (DAC 100,000) and RC 292 hold 2
    (DAC 66,780) that mixes two different lattice spacings into one
    histogram and prints one rate over it - which is the same class of
    error as reading a count at a single ADC rate and calling it
    invariant.
    """
    hold, dac, adc = key
    gaps, mads, nbin = [], [], None
    decimating = None
    for r in rows:
        if (r.get("hold"), r.get("dac_sps"), r.get("adc_hz")) != key:
            continue
        if r.get("offsets"):
            decimating = True
            for o in r["offsets"]:
                gaps.extend(o.get("spacings", ()))
                mads.append(o.get("mad"))
                nbin = o.get("n_per_bin", nbin)
        elif isinstance(r.get("gaps"), dict):
            decimating = False
            # tools/issue24_holdavg.py and issue24_taginterleave.py
            # write a pooled {gap: count} per capture instead of one
            # entry per decimation offset. Reading only `offsets` made
            # this tool report "no gaps within range" on those files -
            # silently, which on this issue is how a null gets made.
            for k, v in r["gaps"].items():
                gaps.extend([int(k)] * int(v))
            mads.append(r.get("mad"))
    return gaps, mads, nbin, dac, adc, decimating


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("records", nargs="+")
    ap.add_argument("--max-gap", type=int, default=60,
                    help="gaps above this are wrap and merge artefacts, "
                         "not lattice spacings")
    ap.add_argument("--cluster", type=int, default=2,
                    help="cluster half-width around the modal gap")
    args = ap.parse_args()

    for path in args.records:
        rows = load(path)
        holds = sorted({(r["hold"], r.get("dac_sps"), r.get("adc_hz"))
                        for r in rows if "hold" in r},
                       key=lambda k: (k[0], k[1] or 0))
        bench = next((r.get("bench") for r in rows if r.get("bench")), "?")
        # Both, and loudly if they disagree. The tracks are two
        # independent programmings of the same silicon, so a lattice may
        # differ between them, and a file pooling both is not one
        # measurement - the same reason this tool already refuses to
        # pool two ADC rates under one hold.
        tracks = sorted({str(r.get("track")) for r in rows
                         if r.get("track") is not None})
        label = "/".join(tracks) if tracks else "unrecorded"
        print(f"\n=== {path}   bench={bench}   track={label}   "
              f"{len(rows)} rows ===")
        if len(tracks) > 1:
            print(f"    !! this file pools tracks {tracks} - the arms are "
                  f"not comparable, split it before reading anything below")
        if not tracks:
            print("    !! no track recorded; written before "
                  "tools/issue24_hold.py logged one. Which board built "
                  "this is not recoverable from the file")
        for key in holds:
            hold, dac, adc = key
            gaps, mads, nbin, dac, adc, decimating = census(rows, key)
            if not dac:
                continue
            # period / gcd(period, hold), NOT period / hold.
            #
            # issue24_hold.py reads a decimated series - vals[offset::hold],
            # one sample per DAC update - so a lattice every `period` ADC
            # conversions only lands on the kept samples at the multiples
            # of lcm(period, hold), and the gap in update space is
            # period/gcd. period/hold is what an undecimated reader would
            # see, and printing it here has been telling three benches
            # that hold 2 predicts 10.5 and hold 6 predicts 3.5 when the
            # instrument can only produce 21 and 7. I put a pre-registered
            # "alternating 10/11 at hold 2" on issue #24 from this line
            # and it was untestable. tools/issue24_visible.py checks the
            # closed form against a simulation.
            # WHICH READER wrote these rows decides the formula, and
            # the two differ at exactly the holds this issue argues
            # about. A decimating reader keeps one sample per update, so
            # a lattice every `period` conversions only lands on a kept
            # sample at multiples of lcm(period, hold) and the gap is
            # period/gcd. A reader that AVERAGES the hold discards no
            # phase, so the event lands in the bin containing it and the
            # gap is period/hold - fractional, showing as alternating
            # floor and ceil.
            #
            # 421e6d4 corrected the formula to the decimating one and
            # applied it to every record. issue24_holdavg.py and
            # issue24_taginterleave.py average, so their hold-2 rows
            # were then told to expect 21 when the instrument that wrote
            # them produces 10.5. Same class of error as the one that
            # commit fixed, one layer along.
            if decimating is False:
                conv = UPDATE_LOCKED_UPDATES / hold
            else:
                conv = UPDATE_LOCKED_UPDATES / gcd(UPDATE_LOCKED_UPDATES,
                                                   hold)
            time = TIME_LOCKED_US * 1e-6 * dac
            degenerate = abs(conv - time) < 0.01
            upd_degenerate = abs(conv - UPDATE_LOCKED_UPDATES) < 0.01
            # Not every writer records a MAD - issue24_holdavg.py does
            # not - and taking a median of nothing raised
            # StatisticsError and killed the whole report rather than
            # one column of it. A tool that reads other tools' records
            # has to survive a missing field.
            have = [m for m in mads if m is not None]
            mad_s = f"{statistics.median(have):.3f}" if have else "n/a"
            reader = ("decimating" if decimating
                      else "averaging" if decimating is False else "?")
            print(f"\n-- hold {hold}  ADC {adc} Hz  DAC {dac} Hz  "
                  f"MAD {mad_s}  n/bin {nbin}  reader={reader}")
            print(f"   predicts: update-locked {UPDATE_LOCKED_UPDATES}"
                  f"   conversion-locked {conv:.2f}"
                  f"   time-locked {time:.2f}"
                  + ("   <- the last two are the SAME number here, this "
                     "arm cannot separate them" if degenerate else "")
                  + ("   <- conversion and update are the SAME number "
                     "here, this arm cannot separate THOSE"
                     if upd_degenerate else ""))
            small = collections.Counter(g for g in gaps
                                        if 0 < g <= args.max_gap)
            if not small:
                print("   no gaps within range")
                continue
            mode = max(small.items(), key=lambda kv: kv[1])[0]
            clus = {g: n for g, n in small.items()
                    if abs(g - mode) <= args.cluster}
            n = sum(clus.values())
            mean = sum(g * c for g, c in clus.items()) / n
            print(f"   histogram <= {args.max_gap}: "
                  f"{dict(sorted(small.items()))}")
            print(f"   modal cluster {sorted(clus)} n={n}  "
                  f"mean {mean:.3f} updates = {mean / dac * 1e6:.2f} us")
            # The update-locked signature, counted whether or not it is
            # the mode: its absence at a separating hold is the finding.
            n21 = sum(c for g, c in small.items()
                      if abs(g - UPDATE_LOCKED_UPDATES) <= 1)
            print(f"   gaps of 20/21/22 (update-locked): {n21}"
                  + ("   [degenerate with the mode here]"
                     if abs(mode - UPDATE_LOCKED_UPDATES) <= 1 else ""))


if __name__ == "__main__":
    main()
