#!/usr/bin/env python3
"""Does the rate deficit need the USB feed, or is it the DACC alone?

Everything on #48 so far was measured on the host-fed playback path:
bytes arrive over bulk OUT, endpoint DMA fills the ring, the PDC hands
them to the DACC. So "the converter runs slow" is really "the converter
runs slow while being fed over USB", and no arm has separated those.

Preset M separates them. `=<dac>[,<adc>]M` runs the **internal**
generator - the device's own 256-point table, `drivers/gen.c` - with the
DAC clocked from TIOA1, independent of the ADC's TIOA0, and **no USB in
the DAC path at all**. If the deficit is the DACC's, it must appear
here too.

The readout is the generator's own output frequency, which is a direct
function of its update rate:

    f_out = dac_update_rate / (2 * points)

so a converter running at 0.9765 of its programmed rate emits a tone
0.9765 of the expected frequency. A0 is jumpered to DAC0, the ADC
samples it, and a Goertzel finds the tone. A 2.35% shift on a ~1.9 kHz
tone is ~46 Hz, far above the ~0.5 Hz resolution of a 2 s capture.

**Clean rates are the reference, not the arithmetic.** The factor of 2
above, the table length and any fixed offset all cancel if the measured
ratio at a rate OUTSIDE the band is used as the baseline. So this runs
band rates and clean rates in the same session and compares them, rather
than trusting a formula.

**`--bench` is not cosmetic.** windows-desk ran a sibling of this tool
with `bench="macos"` baked in and appended twelve Windows rows to the
macOS record file under the macOS label. On a cross-bench question that
is the one error that makes data actively misleading rather than merely
absent - so bench comes from `--bench`, then `$DUE_BENCH`, then the
hostname, and the output file is named after it.

    python3 tools/issue48_nousb.py
"""
import argparse, json, os, platform, statistics, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "host"))
import measure

A0_CH = 7          # ADC channel 7 is A0; channel 6 is A1 - see docs/awg.md


def tone_of(vals, fs, f_nom, span=0.12, steps=600):
    """Peak of the Goertzel over +-span around the nominal tone."""
    lo, hi = f_nom * (1 - span), f_nom * (1 + span)
    best = (None, -1.0)
    for i in range(steps + 1):
        f = lo + (hi - lo) * i / steps
        m = measure.goertzel(vals, fs, f)
        if m > best[1]:
            best = (f, m)
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=4)
    ap.add_argument("--adc-hz", type=int, default=200000)
    ap.add_argument("--points", type=int, default=256)
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--band", type=int, nargs="+",
                    default=[1000000, 886363],
                    help="DAC update rates inside the affected band")
    ap.add_argument("--clean", type=int, nargs="+",
                    default=[696428, 650000],
                    help="DAC update rates outside it, as the reference")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH"),
                    help="which bench this is; defaults to $DUE_BENCH")
    ap.add_argument("--out", default=None,
                    help="defaults to records/issue48-nousb-<bench>.jsonl")
    a = ap.parse_args()

    bench = a.bench or platform.node() or "unknown-bench"
    host = f"{platform.system()} {platform.release()}"
    out_path = a.out or f"records/issue48-nousb-{bench}.jsonl"

    board = measure.Board(settle=3.0)
    rows = []
    for label, rates in (("clean", a.clean), ("band", a.band)):
        for dac in rates:
            f_nom = dac / (2.0 * a.points)
            for i in range(1, a.reps + 1):
                r = measure.run_capture(board, preset=f"={dac},{a.adc_hz}M",
                                        seconds=a.seconds)
                st = r.stream
                v = st.series.get(A0_CH)
                if not v or len(v) < 8192:
                    print(f"  {dac}: no A0 series"); continue
                vals = list(v)[:200000]
                fs = st.declared_rate_hz or a.adc_hz
                f, mag = tone_of(vals, fs, f_nom)
                rows.append(dict(bench=bench, host=host,
                                 track="b", issue=48, test="internal-gen-rate",
                                 arm=label, dac_update_hz=dac, run=i,
                                 points=a.points, adc_hz=a.adc_hz, fs=fs,
                                 f_nominal=round(f_nom, 3),
                                 f_measured=round(f, 3),
                                 ratio=round(f / f_nom, 5), mag=round(mag, 2)))
                print(f"  {label:5s} dac {dac:>9,}: nominal {f_nom:9.2f} Hz  "
                      f"measured {f:9.2f} Hz  ratio {f/f_nom:.5f}  mag {mag:.1f}")

    print()
    for label in ("clean", "band"):
        v = [x["ratio"] for x in rows if x["arm"] == label]
        if v:
            print(f"  {label:5s}: n={len(v)}  median ratio {statistics.median(v):.5f}"
                  f"  range {min(v):.5f}-{max(v):.5f}")
    c = [x["ratio"] for x in rows if x["arm"] == "clean"]
    b = [x["ratio"] for x in rows if x["arm"] == "band"]
    if c and b:
        d = statistics.median(b) / statistics.median(c)
        print(f"\n  band / clean = {d:.5f}")
        print(f"  the host-fed path shows 0.977 (RC 39) and 0.984 (RC 44).")
        print(f"  ~1.00 here means the deficit NEEDS the USB feed;")
        print(f"  ~0.98 means it is the DACC alone.")

    with open(out_path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"\nwrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    main()
