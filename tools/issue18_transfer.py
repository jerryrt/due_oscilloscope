#!/usr/bin/env python3
"""Does the calibration follow the sensor excursion? The half we can see.

#18's soak found the environment moves the on-die sensor by 2.72 codes
peak to peak at fixed build and fixed activity, against a 0.20-code
noise floor. windows-desk's closing question is the right one: that is a
SENSOR excursion, and what a stored calibration needs to know is whether
a CALIBRATION follows it.

`calibration.json` holds two quantities and they have opposite
sensitivities, which the issue has not separated:

  * `adc_transfer.loop_slope_adc_per_dac_code` - the DAC0 -> A0 loop.
    ADVREF is the reference for the ADC *and* the DAC, so this is
    RATIOMETRIC and divides its own reference out exactly. A reference
    excursion moves it by zero codes at every code, by construction -
    see Control.temperature()'s docstring and issue #11.
  * `dac_mv` - an absolute span in millivolts, measured with a scope on
    the pin. This one goes as ADVREF directly.

And the sensor cannot tell the two causes apart: it is bandgap-derived,
so it goes as 1/ADVREF and sees reference noise at full weight, and one
channel cannot separate its own noise from the reference's.

So the excursion has two candidate causes with opposite consequences.
Reference-borne moves `dac_mv` and provably not the loop; die-temperature
-borne could move both. This measures the loop half, which is the half a
bench with no scope can reach. A null here is not a null for #18 - it
narrows the issue to `dac_mv`, which needs the DSO bench.

Arms are interleaved cool/hot rather than blocked, because this
configuration drifts and blocked arms cannot separate an arm from the
weather. Heat is induced by sustained max-rate capture, which #18
measured at +1.57 +- 0.26 codes for 20 s.

    .venv/bin/python tools/issue18_transfer.py -n 4
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

LEVELS = (600, 1200, 1800, 2400, 3000, 3600)


def slope(board, seconds):
    """Loop slope in ADC codes per DAC code, by least squares.

    Every level is played as DC through the ordinary host-fed path, so
    this measures the same loop calibration.json records rather than a
    different one.
    """
    xs, ys = [], []
    for code in LEVELS:
        res = measure.run_loop(board, dac_sps=200000, adc_hz=200000,
                               channels=2, dc=code, seconds=seconds)
        vals = res.stream.series.get(measure.CH_A0) or []
        start = res.stream._index_at(measure.CH_A0, measure.SETTLE_US)
        tail = list(vals[start:])
        if len(tail) < 1000:
            continue
        xs.append(code)
        # MEAN, not median. The median of integer ADC codes is an
        # integer, so the fitted slope is quantised to one code over the
        # level span - 1/3000 = 0.00033 - which is larger than any
        # difference this experiment is looking for. The first run of
        # this tool reported slopes of exactly 0.670000, 0.670238 and
        # 0.670381 and nothing between, which is the quantisation and
        # not the board. The mean over ~200k samples resolves far below
        # a code.
        ys.append(statistics.fmean(tail))
        board.stop()
        board.drain_console(0.2)
    if len(xs) < 3:
        return None, None, 0
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    m = sxy / sxx
    resid = max(abs(y - (my + m * (x - mx))) for x, y in zip(xs, ys))
    # The residual now means something too: with sub-code y values it
    # is real nonlinearity plus noise rather than rounding.
    return m, resid, len(xs)


def temp(board):
    ctl = board.ctl()
    if ctl is None:
        return None
    try:
        return ctl.temperature(samples=256)
    except Exception:                                        # noqa: BLE001
        return None


def heat(board, seconds):
    """Sustained max-rate capture: the workload term #18 measured."""
    end = time.time() + seconds
    while time.time() < end:
        measure.run_capture(board, preset="M", seconds=3.0)
        board.stop()
        board.drain_console(0.1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--pairs", type=int, default=4)
    ap.add_argument("-s", "--seconds", type=float, default=1.5,
                    help="per DC level")
    ap.add_argument("--soak", type=float, default=90.0,
                    help="seconds of max-rate capture before a hot arm")
    ap.add_argument("--rest", type=float, default=90.0,
                    help="seconds idle before a cool arm")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        for i in range(1, args.pairs + 1):
            for label in ("cool", "hot"):
                if label == "cool":
                    board.stop()
                    time.sleep(args.rest)
                else:
                    heat(board, args.soak)
                t = temp(board)
                m, resid, n = slope(board, args.seconds)
                if m is None:
                    print(f"pair {i} {label}: slope unmeasurable",
                          flush=True)
                    continue
                row = {"pair": i, "arm": label, "bench": args.bench,
                       "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "slope": round(m, 6), "max_resid_codes": round(resid, 2),
                       "levels": n,
                       # The key is "code", already in whole codes -
                       # control.py divides the wire's sixteenths. Reading
                       # a key that does not exist gave a flat 0.0 and
                       # looked like a sensor that never moves.
                       "temp_code": (round(t["code"], 3) if t else None),
                       "temp_min": (t or {}).get("code_min"),
                       "temp_max": (t or {}).get("code_max"),
                       "tson": (t or {}).get("tson")}
                rows.append(row)
                print(f"pair {i} {label:4s}: slope {m:.6f}  "
                      f"resid {resid:.2f}  temp "
                      f"{row['temp_code']}", flush=True)
    finally:
        try:
            board.stop()
        finally:
            board.close()

    for a in ("cool", "hot"):
        s = [r["slope"] for r in rows if r["arm"] == a]
        t = [r["temp_code"] for r in rows if r["arm"] == a
             and r["temp_code"] is not None]
        if s:
            print(f"\n{a:4s}: n={len(s)}  slope median "
                  f"{statistics.median(s):.6f}"
                  + (f"  temp median {statistics.median(t):.2f}" if t else ""))
    sc = [r["slope"] for r in rows if r["arm"] == "cool"]
    sh = [r["slope"] for r in rows if r["arm"] == "hot"]
    tc = [r["temp_code"] for r in rows if r["arm"] == "cool" and r["temp_code"]]
    th = [r["temp_code"] for r in rows if r["arm"] == "hot" and r["temp_code"]]
    if sc and sh:
        d = statistics.median(sh) - statistics.median(sc)
        print(f"\nslope hot - cool = {d:+.6f} codes per DAC code")
        if tc and th:
            dt = statistics.median(th) - statistics.median(tc)
            print(f"sensor  hot - cool = {dt:+.2f} codes")
            if abs(dt) < 0.5:
                print("  the sensor barely moved, so this says nothing "
                      "about whether the calibration follows it - "
                      "lengthen --soak")
    if args.out:
        with open(args.out, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
