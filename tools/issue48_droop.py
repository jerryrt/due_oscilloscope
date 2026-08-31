#!/usr/bin/env python3
"""What does `DACC_MR_REFRESH(2)` cost, measured with the ADC.

#48 established that `DACC_MR_REFRESH` is behind the playback rate
deficit, and that changing it 1 -> 2 clears every slow row on the
ladder. The reason not to just change it is that refresh exists to hold
the DAC's output against droop, and nobody had measured what doubling
its period costs. That was called a scope job. It is not.

Two facts make it an ADC job on this bench:

  A0 is jumpered to DAC0, so the converter under test is wired to the
  instrument.

  The refresh rate is known EXACTLY - MCK/1024 = 76,171.9 Hz at
  REFRESH(1), MCK/2048 = 38,085.9 Hz at REFRESH(2) - and both sit well
  inside the 226 kHz Nyquist of a 453,488 Hz/channel capture. A known
  frequency in a noisy record is a Goertzel, which host/measure.py
  already has.

**Refresh only does anything when the DAC is left holding.** During
playback at every rate on the ladder the DAC is rewritten 9 to 18 times
more often than refresh would rewrite it, so while streaming refresh is
redundant by construction and its whole effect is the conversion slots
it costs. To make it matter, this drives the DAC **slowly** - 5,000 sps,
one update every 200 us - while capturing at the top ADC rate. Refresh
then fires ~15 times between updates and its ripple is the only thing in
the record that can sit at exactly MCK/1024.

A loop run rather than a capture preset, and that is not a detail:
`stream_start()` passes `with_gen = true`, so presets 1-5 run the
internal generator into DAC0. My first attempt used preset 5 and
measured a held DC of standard deviation **1372 codes** - which is the
figure CLAUDE.md already records for a full-scale square, and the reason
the number was obviously wrong rather than quietly wrong. `run_loop`
feeds the DAC from the host with the generator off.

The frequency-domain form of this was tried first and found nothing:
sweeping A0 from 1 kHz to Nyquist on a held DC at REFRESH(1), the
largest bin anywhere is 0.055 codes against a standard deviation of
1.41, and **neither 76,172 Hz nor 38,086 Hz stands out at all**. So the
refresh ripple is below this bench's floor and cannot be detected
directly.

That makes the useful question an equivalence rather than a detection:
**does the held level get noisier when the refresh period doubles?** If
sd and peak-to-peak on a DC-held A0 are indistinguishable between
REFRESH(1) and REFRESH(2), then doubling the period costs nothing this
bench can measure, and #48's remaining objection is answered without a
scope. If REFRESH(2) is measurably worse, that is the cost, quantified.

    python3 tools/issue48_droop.py --reps 6
"""
import argparse, json, os, platform, statistics, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "host"))
import measure
import provenance

MCK = 78e6
F_R1 = MCK / 1024.0
F_R2 = MCK / 2048.0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=6)
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--dc", type=int, default=2048)
    ap.add_argument("--dac-sps", type=int, default=5000,
                    help="slow on purpose - refresh must fire "
                         "between updates to have any effect")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH"),
                    help="which bench this is; defaults to $DUE_BENCH")
    ap.add_argument("--label", required=True,
                    help="which refresh setting this image has, e.g. R1 or R2")
    ap.add_argument("--out", default=None,
                    help="defaults to records/issue48-droop-<bench>.jsonl")
    a = ap.parse_args()

    bench = a.bench or platform.node() or "unknown-bench"
    host = f"{platform.system()} {platform.release()}"
    out_path = a.out or f"records/issue48-droop-{bench}.jsonl"

    board = measure.Board(settle=3.0)

    # What the board actually is, and what produced it (issue #53).

    prov = provenance.run_fields(board)
    rows = []
    print(f"idle-hold droop, image={a.label}, dc={a.dc}\n")
    for i in range(1, a.reps + 1):
        # Park the DAC at a known code, then let playback go away so the
        # output is held rather than rewritten.
        r = measure.run_loop(board, dac_sps=a.dac_sps, adc_hz=453488,
                             dc=a.dc, seconds=a.seconds)
        st = r.stream
        fs = st.declared_rate_hz or 453488
        # ADC channel 7 is A0, which is the pin DAC0 drives. Channel 6
        # is A1, jumpered to DAC1, and on this bench DAC1 carries the
        # sync square - sd 555 codes against A0's 1.4. Taking "the first
        # channel with enough samples" picks A1 and measures the sync.
        vals = st.series.get(7)
        vals = list(vals) if vals else None
        if vals is None:
            print(f"  run {i}: no series"); continue
        n = min(len(vals), 200000)
        v = vals[:n]
        m1 = measure.goertzel(v, fs, F_R1)
        m2 = measure.goertzel(v, fs, F_R2)
        # Two off-refresh controls: whatever these read is the noise
        # floor this bench puts in any single bin, so the refresh bins
        # are only interesting relative to them.
        c1 = measure.goertzel(v, fs, 61000.0)
        c2 = measure.goertzel(v, fs, 91000.0)
        floor = (c1 + c2) / 2.0
        rows.append(dict(bench=bench, host=host, **prov,
                         issue=48, test="idle-hold-droop", image=a.label,
                         run=i, dc=a.dc, seconds=a.seconds, fs=fs,
                         dac_sps=a.dac_sps, n=n, sd=round(statistics.pstdev(v), 3),
                         p2p=max(v) - min(v),
                         mag_76172=round(m1, 4), mag_38086=round(m2, 4),
                         floor=round(floor, 4),
                         snr_76172=round(m1 / floor, 3) if floor else None,
                         snr_38086=round(m2 / floor, 3) if floor else None))
        print(f"  run {i}: sd {rows[-1]['sd']:6.2f} codes  p2p {rows[-1]['p2p']:4d}"
              f"   76.2kHz {m1:8.3f}  38.1kHz {m2:8.3f}  floor {floor:8.3f}"
              f"   SNR {m1/floor:5.2f} / {m2/floor:5.2f}")

    if rows:
        print(f"\n  medians: 76.2kHz SNR "
              f"{statistics.median(r['snr_76172'] for r in rows):.2f}   "
              f"38.1kHz SNR {statistics.median(r['snr_38086'] for r in rows):.2f}")
        print("  An SNR near 1 means that bin is indistinguishable from "
              "the bench floor.")
    with open(out_path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"\nwrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    main()
