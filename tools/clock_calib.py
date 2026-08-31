#!/usr/bin/env python3
"""Measure the device's clock against the host's, free of host overhead.

Every rate in this project is derived from MCK: the ADC trigger, the DAC
timer, and `runus`. `CLAUDE.md` states MCK is 78 MHz and corrects two
other documents from it - but that is a **register-derived** figure, read
back from the PLL settings. Until 2026-08-30 nobody had measured it.

**Why one run length cannot do it.** A run costs a fixed amount of host
time to start and stop, so

    host_elapsed = device_time / ratio + overhead

is one equation in two unknowns. Measured here, that overhead is ~16 ms;
at a 3 s run it makes the device look 5300 ppm slow, which is a thousand
times the effect being looked for. Two lengths separate them:

    device_time = ratio * host_elapsed - ratio * overhead
                  ^slope                 ^intercept

The lengths are interleaved so that a drift over the sweep cannot pose
as a slope. Validated on synthetic data before use: with a known ratio
and a known overhead plus 1 ms of jitter, the fit recovers the ratio to
0.4 ppm, where the mean of the short arm alone is out by 5352 ppm.

**What this does and does not establish.** It measures the device
oscillator against *this host's* oscillator. The precision is a few ppm;
the ACCURACY is bounded by the host crystal, which is typically tens of
ppm and is not disciplined for frequency by NTP. So a single bench
cannot say the device is right in absolute terms - it can only say the
two agree. Three benches with independent crystals can: a common-mode
error needs three unrelated oscillators to be wrong together and by the
same amount. **Run it on every bench and compare.**

The default rate is deliberately one that reads n=0 on the #48 lattice,
so that issue's deficit is not sitting inside the arm; the deficit is a
device-time effect and cancels here anyway, but it costs nothing to
avoid it.

[windows-platform-team / windows-desk]
"""
import argparse
import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "host"))

import measure                                             # noqa: E402
import provenance                                          # noqa: E402

TC_CLOCK_HZ = 39_000_000        # SystemCoreClock / 2 at MCK 78 MHz
MCK_NOMINAL_HZ = 78_000_000


def fit(xs, ys):
    """Least squares slope and intercept, written out rather than pulled
    in, because this file must run on a bench with no numpy."""
    n = len(xs)
    mx, my = st.mean(xs), st.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    return slope, my - slope * mx


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rc", type=int, default=56,
                    help="TC divisor; 56 reads n=0 on the #48 lattice")
    ap.add_argument("--short", type=float, default=3.0)
    ap.add_argument("--long", type=float, default=45.0)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--port", default=None)
    ap.add_argument("--bench", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    if a.long <= a.short * 2:
        sys.exit("--long must be well clear of --short, or the fit has no "
                 "lever arm and the intercept eats the slope")

    sps = TC_CLOCK_HZ // a.rc
    board = measure.Board(a.port) if a.port else measure.Board()
    rows = []
    for rep in range(a.reps):
        # Interleaved: a drift over the sweep must not look like a slope.
        order = (a.short, a.long) if rep % 2 == 0 else (a.long, a.short)
        for secs in order:
            r = measure.run_play(board, dac_sps=sps, seconds=secs,
                                 ramp=measure.RAMP_STEP)
            raw = r.play.raw
            if not raw.get("runus"):
                print(f"  rep {rep} {secs:g}s: no runus", flush=True)
                continue
            row = {"rep": rep, "requested_s": secs,
                   "device_s": raw["runus"] / 1e6, "host_s": r.elapsed_s,
                   "under": raw.get("under")}
            rows.append(row)
            print(f"  rep {rep} {secs:>5g}s: device {row['device_s']:10.6f}  "
                  f"host {row['host_s']:10.6f}  "
                  f"ratio {row['device_s'] / row['host_s']:.6f}", flush=True)

    if len(rows) < 4:
        sys.exit("not enough runs to fit")

    xs = [r["host_s"] for r in rows]
    ys = [r["device_s"] for r in rows]
    slope, icept = fit(xs, ys)
    resid = [y - (slope * x + icept) for x, y in zip(xs, ys)]
    mck = MCK_NOMINAL_HZ * slope
    ppm = (slope - 1.0) * 1e6

    print()
    print(f"  n = {len(rows)}   device clock / host clock = {slope:.7f}")
    print(f"  fixed host overhead        {-icept / slope * 1000:8.1f} ms per run")
    print(f"  residual sd                {st.pstdev(resid) * 1e3:8.3f} ms"
          f"   max |resid| {max(abs(r) for r in resid) * 1e3:.3f} ms")
    print(f"  implied MCK                {mck:,.0f} Hz  ({ppm:+.1f} ppm)")
    print()
    print("  Precision is a few ppm; ACCURACY is bounded by this host's")
    print("  crystal, which is not frequency-disciplined. One bench shows")
    print("  agreement, not correctness. Compare across benches.")

    if a.out:
        # Provenance, and not by hand. #53 found nine tools hardcoding
        # track="b", so Track A datasets say Track B - including the one
        # CLAUDE.md quotes for "it is the silicon and not one track's
        # register programming". Asking provenance.collect() means this
        # tool cannot drift from what the fixture requires, and the
        # firmware commit comes from the board rather than from whoever
        # is typing.
        #
        # This file needed the lesson: its first record carried a bench
        # and nothing else - no track, no firmware commit - written an
        # hour after I committed the doc rule saying a figure carries
        # its bench, its commit and its instrument (f953876).
        prov = provenance.collect(board=board)
        missing = provenance.missing(prov) if hasattr(provenance, "missing") else []
        json.dump({"bench": a.bench or prov.get("bench"),
                   "team": "windows-platform-team",
                   "instrument": "tools/clock_calib.py",
                   "provenance": prov,
                   "provenance_missing": list(missing),
                   "rc": a.rc, "sps": sps,
                   "lengths_s": [a.short, a.long], "reps": a.reps,
                   "n": len(rows), "rows": rows,
                   "slope_device_over_host": slope,
                   "intercept_s": icept,
                   "host_overhead_ms": -icept / slope * 1000,
                   "residual_sd_ms": st.pstdev(resid) * 1e3,
                   "implied_mck_hz": mck, "ppm_from_nominal": ppm},
                  open(a.out, "w"), indent=1)
        print(f"  wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
