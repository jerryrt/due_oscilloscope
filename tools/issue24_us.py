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
import collections
import json
import statistics

#: The two candidate lattices, in the units each is defined in.
UPDATE_LOCKED_UPDATES = 21
TIME_LOCKED_US = 105.0


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def census(rows, hold):
    """Pooled spacings, MAD and n_per_bin for one hold."""
    gaps, mads, nbin, dac, adc = [], [], None, None, None
    for r in rows:
        if r.get("hold") != hold:
            continue
        dac, adc = r.get("dac_sps"), r.get("adc_hz")
        for o in r.get("offsets", ()):
            gaps.extend(o.get("spacings", ()))
            mads.append(o.get("mad"))
            nbin = o.get("n_per_bin", nbin)
    return gaps, mads, nbin, dac, adc


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
        holds = sorted({r["hold"] for r in rows if "hold" in r})
        bench = next((r.get("bench") for r in rows if r.get("bench")), "?")
        print(f"\n=== {path}   bench={bench}   {len(rows)} rows ===")
        for hold in holds:
            gaps, mads, nbin, dac, adc = census(rows, hold)
            if not dac:
                continue
            conv = UPDATE_LOCKED_UPDATES / hold
            time = TIME_LOCKED_US * 1e-6 * dac
            degenerate = abs(conv - time) < 0.01
            print(f"\n-- hold {hold}  ADC {adc} Hz  DAC {dac} Hz  "
                  f"MAD {statistics.median(m for m in mads if m is not None):.3f}  "
                  f"n/bin {nbin}")
            print(f"   predicts: update-locked {UPDATE_LOCKED_UPDATES}"
                  f"   conversion-locked {conv:.2f}"
                  f"   time-locked {time:.2f}"
                  + ("   <- the last two are the SAME number here, this "
                     "arm cannot separate them" if degenerate else ""))
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
