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
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "host"))

import measure                                             # noqa: E402
import provenance                                          # noqa: E402

TC_CLOCK_HZ = 39_000_000        # SystemCoreClock / 2 at MCK 78 MHz
MCK_NOMINAL_HZ = 78_000_000
#: A fit whose residual scatter is this large is not measuring a
#: clock. mac-bench's good runs sit at 0.073-0.090 ms and this
#: bench's at 0.7 ms, limited by time.time()'s ~1 ms step; the
#: rejected run was 10.494.
MAX_RESID_SD_MS = 3.0


def host_clock_discipline(seconds=60.0):
    """Is this host's reference traceable to UTC, or free-running?

    The flat claim - "accuracy is bounded by this host's crystal, which
    is not frequency-disciplined" - is false on Linux, where
    CLOCK_MONOTONIC is slewed by the kernel's NTP correction; linux-x1
    found it. They then reasoned that Windows and macOS are free-running
    because `time.monotonic()` is QueryPerformanceCounter and
    mach_absolute_time.

    That is right about those clocks and wrong about this measurement,
    because `measure.run_play()` times with **`time.time()`**, not with
    monotonic. On every platform `time.time()` is the UTC-disciplined
    system clock, so the reference is traceable wherever the host is
    actually synced - and this is the one number that says whether it
    is, instead of leaving the reader to argue about it.

    Measured on windows-desk 2026-08-30: QueryPerformanceCounter runs
    **-22 ppm** against the disciplined clock here. If this tool had
    used perf_counter, the MCK figure would have been wrong by 22 ppm -
    twice the effect being looked for - and nothing in the output would
    have said so.

    Returns ppm by which the free-running counter differs from the
    disciplined clock. Near zero means the host is not disciplining, or
    its crystal happens to be excellent; a large value means the two
    clocks genuinely differ and the disciplined one is the reference.
    """
    step = clock_resolution("time") or 1e-3
    p0, w0 = time.perf_counter(), time.time()
    time.sleep(seconds)
    dp, dw = time.perf_counter() - p0, time.time() - w0
    if not dw:
        return None, None
    # One clock step over the window is the floor on what this can
    # resolve, and saying it matters: a 20 s window on a host whose
    # time.time() steps by ~1 ms cannot see better than 50 ppm, so two
    # such readings differing by 59 ppm are one reading twice. This bench
    # produced exactly that pair - -22 over 300 s and -81 over 20 - and
    # briefly read it as the host's discipline changing.
    return 1e6 * (dp / dw - 1.0), 1e6 * step / dw


def clock_resolution(which):
    """Smallest non-zero step the clock actually reports.

    The nominal figure lies on Windows: `time.get_clock_info('time')`
    says 15.625 ms while the observed step here is ~1 ms, because the
    system timer resolution is raised. It matters because the fit's
    residual is dominated by it - 0.7 ms over a 42 s lever arm across
    ten points is about 5 ppm, which is this bench's whole repeatability.
    """
    f = time.time if which == "time" else time.perf_counter
    best = None
    for _ in range(200000):
        a = f(); b = f()
        if b > a:
            best = (b - a) if best is None else min(best, b - a)
            if which != "time":
                break
    return best


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
                   "under": raw.get("under"), "via": r.play.via}
            rows.append(row)
            print(f"  rep {rep} {secs:>5g}s: device {row['device_s']:10.6f}  "
                  f"host {row['host_s']:10.6f}  "
                  f"ratio {row['device_s'] / row['host_s']:.6f}", flush=True)

    # Drop rep 0 by index, not by a filter on what it does wrong.
    # CLAUDE.md's first-run rule, and mac-bench found this quantity is the
    # fifth to need it: their first invocation read 30 ppm off while runs
    # 2-4 agreed to 1.7. The rule is by index precisely so nobody has to
    # decide whether a particular first run "looks" bad.
    fitted = [r for r in rows if r["rep"] > 0]
    if len(fitted) < 4:
        sys.exit("not enough runs to fit after dropping rep 0")

    xs = [r["host_s"] for r in fitted]
    ys = [r["device_s"] for r in fitted]
    slope, icept = fit(xs, ys)
    resid = [y - (slope * x + icept) for x, y in zip(xs, ys)]
    mck = MCK_NOMINAL_HZ * slope
    overhead_ms = -icept / slope * 1000.0
    resid_sd_ms = st.pstdev(resid) * 1e3

    # Refuse a fit that refutes its own model, rather than printing a
    # number. mac-bench had one run read -192 ppm from a single perturbed
    # 3 s row - maximum leverage - and the fit said so twice: a NEGATIVE
    # fixed overhead, which cannot exist, and a residual sd 144x the
    # other runs'. Both were already in the JSON and nothing looked at
    # them. Five benches should not each rediscover that.
    verdict, why = "ok", []
    if overhead_ms < 0:
        why.append(f"fitted host overhead is negative ({overhead_ms:.1f} ms); "
                   f"a fixed per-run cost cannot be, so the model is refuted "
                   f"by its own parameter")
    if resid_sd_ms > MAX_RESID_SD_MS:
        why.append(f"residual sd {resid_sd_ms:.3f} ms exceeds "
                   f"{MAX_RESID_SD_MS:.1f} ms; one perturbed row on a short "
                   f"arm carries maximum leverage")
    if why:
        verdict = "REJECTED"
    ppm = (slope - 1.0) * 1e6

    print()
    print(f"  n = {len(fitted)} of {len(rows)} (rep 0 dropped by index)"
          f"   device clock / host clock = {slope:.7f}")
    print(f"  fixed host overhead        {overhead_ms:8.1f} ms per run")
    print(f"  residual sd                {resid_sd_ms:8.3f} ms"
          f"   max |resid| {max(abs(r) for r in resid) * 1e3:.3f} ms")
    print(f"  implied MCK                {mck:,.0f} Hz  ({ppm:+.1f} ppm)")
    if verdict != "ok":
        print()
        print("  *** RUN REJECTED - do not quote the figure above ***")
        for w in why:
            print(f"    - {w}")
    print()
    qpc_ppm, qpc_err = host_clock_discipline()
    res_t = clock_resolution("time")
    print(f"  host reference   time.time() = {time.get_clock_info('time').implementation}")
    print(f"  observed step    {res_t * 1e6:8.1f} us   (nominal "
          f"{time.get_clock_info('time').resolution * 1e6:.0f} us)")
    print(f"  free-running counter vs it: {qpc_ppm:+.1f} ppm "
          f"(+/- {qpc_err:.0f} ppm from one clock step over the window)")
    print()
    print("  measure.run_play() times with time.time(), the UTC-disciplined")
    print("  system clock - NOT monotonic/perf_counter. So this figure is an")
    print("  accuracy statement wherever the host is actually NTP-synced.")
    print("  Check that it is; an unsynced host makes it an agreement")
    print("  statement again, and the line above cannot tell the difference.")

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
        # run_fields() is the shape the other eight tools settled on after
        # #53 (1e3d270), so this one follows it rather than inventing a
        # second arrangement - a convention with an exception in it is
        # how the track field went wrong in the first place. collect()
        # is kept alongside because this tool's whole subject is the host
        # clock, and the host fields are not in run_fields().
        prov = provenance.collect(board=board)
        fields = provenance.run_fields(board=board)
        missing = provenance.missing(prov) if hasattr(provenance, "missing") else []
        json.dump({"bench": a.bench or prov.get("bench"),
                   **fields,
                   "team": "windows-platform-team",
                   "instrument": "tools/clock_calib.py",
                   "provenance": prov,
                   "provenance_missing": list(missing),
                   "rc": a.rc, "sps": sps,
                   "lengths_s": [a.short, a.long], "reps": a.reps,
                   "n": len(fitted), "rows": rows,
                   "reps_dropped_by_index": [0],
                   "verdict": verdict, "rejected_because": why,
                   "slope_device_over_host": slope,
                   "intercept_s": icept,
                   "host_overhead_ms": overhead_ms,
                   "residual_sd_ms": resid_sd_ms,
                   "implied_mck_hz": mck, "ppm_from_nominal": ppm,
                   "host_clock": {
                       "reference_used_by_measure_py": "time.time()",
                       "implementation":
                           time.get_clock_info("time").implementation,
                       "nominal_resolution_s":
                           time.get_clock_info("time").resolution,
                       "observed_step_s": res_t,
                       "free_running_vs_disciplined_ppm": qpc_ppm,
                       "free_running_vs_disciplined_ppm_floor": qpc_err}},
                  open(a.out, "w"), indent=1)
        print(f"  wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
