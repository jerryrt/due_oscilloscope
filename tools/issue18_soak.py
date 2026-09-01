#!/usr/bin/env python3
"""#18 step 1: is there a room signal left once build and activity are fixed?

The issue's own framing is that the die sensor resolves *what the
firmware is doing* far better than *what the room is doing*: a 20 s
capture moves the reading +1.57 codes against idle, two builds differ by
0.6-0.8, and two boards sit 39 codes apart. Against a short-term noise
floor of ~0.20 codes, both dominate any drift small enough to be
interesting.

So step 1 asks the only question that decides whether step 2 is worth
building:

    hold the build fixed, hold the activity fixed, and read for hours.
    If nothing above the noise floor survives, #18 closes with a
    documented negative and dc_transfer keeps its fixed tolerances.

**Activity is held by doing nothing.** The workload term is 8x the noise
floor, so a soak that runs captures is measuring its own captures. This
takes one CTL_OP_TEMP reading per interval over the control channel -
146 us, no console, no sample path - and nothing else touches the board.
That is the quietest activity level available, and it is constant by
construction rather than by intention.

**Never opens the programming port.** measure.Board's own docstring says
opening it asserts NRSTB, measured 3 of 3 in tools/uptime_reset_probe.py
- and a reset mid-soak both restarts the thermal transient and voids the
"same build, same activity" premise. The command port is the native
port's second CDC function and does not touch NRSTB.

Each row carries the reading, its spread, and uptime, so a reset that
happens anyway is visible in the record rather than silently averaged
into it.

    python3 tools/issue18_soak.py --hours 8
    python3 tools/issue18_soak.py --hours 1 --interval 30
"""
import argparse
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import control  # noqa: E402
import ports  # noqa: E402
import provenance  # noqa: E402

#: Issue #11's short-term noise on a held reading, for reference only.
#:
#: NOT what the soak is judged against. It was measured elsewhere, with
#: its own averaging and its own conditions, and docs/measurement-suite
#: .md's Phase 0 rule is that no tolerance gets written until its own
#: repeatability has been measured. A first version of this tool
#: compared an hours-long span against this constant and reported "7.2x
#: the floor" off a 72-second smoke test - which is a statement about
#: someone else's ruler.
QUOTED_FLOOR_CODES = 0.20


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=float, default=8.0)
    ap.add_argument("--interval", type=float, default=60.0,
                    help="seconds between readings")
    ap.add_argument("--samples", type=int, default=1024,
                    help="conversions the device averages per reading")
    ap.add_argument("--floor-n", type=int, default=20,
                    help="back-to-back readings taken first, to measure "
                         "THIS bench's own short-term floor before the "
                         "soak is judged against anything")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    nodes = ports.native_nodes()
    if len(nodes) < 2:
        print("no command node: this board has one CDC function, so a "
              "temperature read would have to go over the console and "
              "block the main loop it is trying not to perturb",
              file=sys.stderr)
        return 2
    cmd = nodes[1]

    link = control.Control(cmd, timeout=3.0)
    try:
        ident = link.identity()
        fields = provenance.run_fields(ident=ident)
        if args.bench:
            fields["bench"] = args.bench
        print(f"command port: {cmd}")
        print(f"build: {ident.get('build')}  track={ident.get('track')}")
        print(f"reading every {args.interval:g}s for {args.hours:g}h, "
              f"{args.samples} conversions averaged, nothing else touching "
              f"the board\n")

        out = args.out or os.path.join(
            ROOT, "records",
            f"issue18-soak-{args.bench or 'unknown'}.jsonl")
        # Phase 0: measure the ruler before the thing.
        #
        # Back-to-back readings, no interval, so nothing the room does
        # can move them. Their span is this bench's short-term floor for
        # THIS averaging and THESE conditions, and it is what the soak is
        # judged against - not a constant from another issue.
        print(f"floor: {args.floor_n} back-to-back readings...", flush=True)
        floor = [link.temperature(samples=args.samples)["code"]
                 for _ in range(args.floor_n)]
        floor_span = max(floor) - min(floor)
        floor_sd = statistics.stdev(floor) if len(floor) > 1 else 0.0
        # Report both, and compare like with like. #11's 0.20 is a noise
        # figure on a held reading; a SPAN over n readings runs about
        # 3.5 sd at n=20, so quoting a span against it manufactures a
        # discrepancy that is only the two statistics differing.
        print(f"  short-term  span {floor_span:.3f}  sd {floor_sd:.3f}  "
              f"codes ({min(floor):.3f}..{max(floor):.3f})")
        print(f"  #11's quoted {QUOTED_FLOOR_CODES} is a noise figure, so "
              f"compare it with the sd, not the span\n", flush=True)

        end = time.time() + args.hours * 3600.0
        rows = []
        first = None
        while time.time() < end:
            t = link.temperature(samples=args.samples)
            hb = link.heartbeat()
            row = dict(fields)
            row.update(t=time.strftime("%Y-%m-%dT%H:%M:%S"),
                       code=t["code"], code_min=t["code_min"],
                       code_max=t["code_max"], samples=t["samples"],
                       # The conditions the hardware held DURING the
                       # conversions. control.temperature()'s docstring:
                       # a reading taken at one track/settling time is
                       # not comparable with one taken at another. A
                       # soak that does not record them cannot prove it
                       # held them fixed, which is the whole premise.
                       adc_mr=t["adc_mr"], adc_acr=t["adc_acr"],
                       tson=t["tson"], channel=t["channel"],
                       uptime_ms=hb["uptime_ms"], issue=18,
                       test="room-signal-with-build-and-activity-fixed")
            rows.append(row)
            if first is None:
                first = t["code"]
            # Append as we go. A soak that only writes at the end loses
            # everything to any interruption, and this one runs for
            # hours.
            with open(out, "a") as fh:
                fh.write(json.dumps(row) + "\n")
            print(f"{row['t']}  code {t['code']:8.3f}  "
                  f"drift {t['code'] - first:+6.3f}  "
                  f"spread {t['code_max'] - t['code_min']:3d}  "
                  f"up {hb['uptime_ms'] / 1000.0:8.1f}s", flush=True)
            time.sleep(args.interval)

        codes = [r["code"] for r in rows]
        span = max(codes) - min(codes)
        print(f"\n{len(rows)} readings over {args.hours:g}h")
        print(f"soak span  {span:.3f} codes")
        print(f"floor span {floor_span:.3f} codes  (this bench, this "
              f"averaging, back to back)")
        if floor_span <= 0:
            print("  floor is zero, which is not credible - too few "
                  "readings or the device is repeating an answer")
        elif span <= floor_span:
            print("  the soak did not exceed its own short-term floor: on "
                  "this evidence there is no slow signal to condition a "
                  "calibration on, and #18 step 2 has nothing to store")
        else:
            print(f"  {span / floor_span:.1f}x this bench's own floor - "
                  f"something slow survives. It is NOT established to be "
                  f"the room: a reset, a build change or any activity "
                  f"would do this too, which is what the uptime and "
                  f"adc_mr columns are for")
        print(f"wrote {len(rows)} rows to {out}")
    finally:
        link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
