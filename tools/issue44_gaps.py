#!/usr/bin/env python3
"""#44: did the device keep cadence while the lost frames vanished?

The issue is that starting a loop run intermittently loses tens to
hundreds of inbound frames. Three findings are established across two
benches - the loss needs the USB OUT path present (0/32 preset M against
11/32 loop, p = 0.00017), it does not scale with the device's OUT
transfer count (r = +0.003, n = 175, CI excludes the predicted -0.153),
and it is single-frame (121/121 increments of +1). Presence matters,
count does not.

What is not settled is whether the frames die in the transport or are
never put on the wire in the right order. I volunteered to build a
capture-side timestamp trace in firmware for this. **It is not needed.**

`seq` in the frame header advances only when a frame has been handed to
the USB DMA, and `timestamp_us` is stamped by the device as the header
is built. So a sequence gap already means the device sent frames the
host never saw, and the device's own clock either side of the gap says
which of two things happened:

    ts jump == n_lost + 1 periods    the device kept perfect cadence
                                     while N frames vanished between it
                                     and the host - a TRANSPORT loss

    ts jump  > n_lost + 1 periods    the device's loop was somewhere
                                     else - an ORDERING fault, and the
                                     frames were built late rather than
                                     lost

Both are read from data the host is already receiving. No firmware, no
new opcode, and nothing that perturbs the path being measured - which
the playback rate trace explicitly does, and is why it defaults off.

**`--bench` is not cosmetic.** windows-desk ran a sibling of this tool
with `bench="macos"` baked in and appended twelve Windows rows to the
macOS record file under the macOS label. On a cross-bench question that
is the one error that makes data actively misleading rather than merely
absent - so bench comes from `--bench`, then `$DUE_BENCH`, then the
hostname, and the output file is named after it.

    python3 tools/issue44_gaps.py --reps 40
"""
import argparse, json, os, platform, statistics, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "host"))
import measure


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=40)
    ap.add_argument("--adc-hz", type=int, default=402061)
    ap.add_argument("--dac-sps", type=int, default=200000)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH"),
                    help="which bench this is; defaults to $DUE_BENCH")
    ap.add_argument("--out", default=None,
                    help="defaults to records/issue44-gaps-<bench>.jsonl")
    a = ap.parse_args()

    bench = a.bench or platform.node() or "unknown-bench"
    host = f"{platform.system()} {platform.release()}"
    out_path = a.out or f"records/issue44-gaps-{bench}.jsonl"

    board = measure.Board(settle=3.0)
    rows, all_gaps = [], []
    print(f"loop: ADC {a.adc_hz:,} Hz, DAC {a.dac_sps:,} sps, "
          f"{a.seconds}s x {a.reps}\n")
    for i in range(1, a.reps + 1):
        r = measure.run_loop(board, adc_hz=a.adc_hz, dac_sps=a.dac_sps,
                             seconds=a.seconds)
        st = r.stream
        steps = st.seq_steps or []
        # Frame period from the run itself rather than from the rate
        # asked for: #48 says the device does not always deliver the
        # rate it accepts, and a predicted period taken from nominal
        # would mis-score every gap on an affected run.
        per = None
        if st.frames > 1 and st.ts_first is not None and st.ts_last is not None:
            per = (st.ts_last - st.ts_first) / (st.frames - 1)
        for (idx, t0, t1, n) in steps:
            if t0 is None or per is None or per <= 0:
                continue
            expect = (n + 1) * per
            got = (t1 - t0) & 0xFFFFFFFF
            g = dict(run=i, frame_index=idx, n_lost=n,
                     ts_gap_us=got, expect_us=round(expect, 1),
                     ratio=round(got / expect, 4) if expect else None,
                     frac_into_run=round(idx / max(st.frames, 1), 4))
            all_gaps.append(g)
        rows.append(dict(bench=bench, host=host, track="b",
                         issue=44, test="seq-gap-cadence", run=i,
                         adc_hz=a.adc_hz, dac_sps=a.dac_sps,
                         seconds=a.seconds, frames=st.frames,
                         seq_gaps=st.seq_gaps, dropped=st.dropped_frames,
                         frame_period_us=round(per, 2) if per else None,
                         gaps=[g for g in all_gaps if g["run"] == i]))
        mark = f"  {st.seq_gaps} gap(s), {st.dropped_frames} lost" \
               if st.seq_gaps else ""
        print(f"  run {i:2d}: {st.frames:5d} frames{mark}")

    print(f"\n  {sum(1 for r in rows if r['seq_gaps'])} of {len(rows)} runs "
          f"lost frames; {len(all_gaps)} gaps total")
    if all_gaps:
        rat = [g["ratio"] for g in all_gaps if g["ratio"]]
        onep = sum(1 for g in all_gaps if g["n_lost"] == 1)
        print(f"  gap sizes: {sorted({g['n_lost'] for g in all_gaps})}"
              f"   ({onep}/{len(all_gaps)} are single-frame)")
        if rat:
            print(f"  ts jump / expected: median {statistics.median(rat):.4f}"
                  f"   range {min(rat):.4f}-{max(rat):.4f}")
            print(f"\n  VERDICT: ~1.00 means the device kept cadence and the "
                  f"frames died in TRANSPORT.")
            print(f"           >1 means the device built them late - an "
                  f"ORDERING fault in the loop.")
        pos = [g["frac_into_run"] for g in all_gaps]
        print(f"  position in run: median {statistics.median(pos):.3f} "
              f"(0 = start, 1 = end)")

    with open(out_path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"\nwrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    main()
