"""Settling to one code, by equivalent-time sampling with the ADC.

    python3 tools/settletime.py rise      milestone 1: cross-check the
                                          reconstruction against the scope
    python3 tools/settletime.py settle    the tail, to one code
    python3 tools/settletime.py control   a held level, which must come
                                          back flat

Issue #9. The reload fold's settle mask is sized on the 10-90% rise time,
which is the wrong quantity, and the one attempt to measure the right one
produced a figure that turned out to be the scope's rail.

Neither instrument can answer it alone. The scope resolves 20 ns and
20 codes; the ADC resolves 4 codes raw - 0.25 averaged - and 2.2 us. One
is too coarse vertically, the other horizontally. `host/eqtime.py` closes
the horizontal gap by folding the capture onto the waveform's phase,
which the firmware's `M` preset was already built to make possible.

Named `settletime` rather than `eqtime` because `host/eqtime.py` owns
that name and both directories are on the path in `tools/phase0.py`.

## Milestone 1 is a cross-check and it is also the kill criterion

`rise` reconstructs the full-scale edge, which the scope has already
measured independently at 789-938 ns. Two instruments sharing no
hardware: if they agree, the method is validated by something that is
not itself. If they do not, the ADC's sample aperture is the limit and
that is the answer - say so and stop, rather than pressing on into the
tail where nothing can check the result.
"""
import argparse
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))

import calibration                                            # noqa: E402
import eqtime                                                 # noqa: E402
import measure                                                # noqa: E402
import provenance as prov                                     # noqa: E402
import repeat                                                 # noqa: E402

RECORDS = os.path.join(HERE, "records")

#: What the scope measured for the same edge, independently, and the
#: number `rise` has to reproduce. docs/status.md, tools/dso_metrics step.
SCOPE_RISE_S = (789e-9, 938e-9)

#: DAC update rate to ask for. 200,000 is RC 195 exactly, so the period
#: is 2*points*195 ticks and every candidate below is an integer RC.
DAC_HZ = 200_000

#: ADC rate to ask for. The device floors RC from the request, so 202,000
#: lands on RC 193 - prime, and therefore coprime with every period here,
#: which is what makes the fold visit all of them. Verified by the
#: coverage figure rather than assumed.
ADC_HZ = 202_000


def adc_lsb_v():
    advref, source = calibration.advref_mv()
    return advref / 1000.0 / 4096.0, advref, source


def expected_rc_dac(dac_hz):
    """The RC the device will land on for a requested DAC rate."""
    return eqtime.TC_CLOCK_HZ // dac_hz


def capture(board, *, points, seconds, dac_hz=DAC_HZ, adc_hz=ADC_HZ,
            shape="square", amp=256):
    """One run of the M preset, with everything the fold needs checked."""
    measure.set_sync(board, "off")
    # Amplitude explicitly, never inherited. `gen_amp` persists on the
    # device across commands, so a metric run that measured noise at a
    # held code first left the generator at half scale - and this then
    # folded a 1374-code square instead of a 2752-code one and reported
    # a 513 ns rise against the true 923, correctly flagging DISAGREES
    # for a reason that had nothing to do with the converter. A
    # measurement that inherits device state measures the previous
    # measurement.
    measure.set_gen(board, shape, points, amp=amp)
    res = measure.run_capture(board, preset=f"={dac_hz},{adc_hz},2M",
                              seconds=seconds)
    st = res.stream
    bad = eqtime.check_contiguous(st)
    if bad:
        raise SystemExit(
            f"refusing to reconstruct: {', '.join(bad)}. A gap shifts "
            f"every later sample's phase, which smears an edge into a "
            f"slope - and a smeared edge is what a slow converter looks "
            f"like.")
    rc_adc = eqtime.rc_from_hz(st.declared_rate_hz)
    if rc_adc is None:
        raise SystemExit(
            f"the device reported {st.declared_rate_hz} Hz, which no RC "
            f"produces. The period would be a guess.")
    vals = [float(v) for v in (st.series.get(measure.CH_A0) or [])]
    return vals, rc_adc, st


def fold(vals, rc_adc, points, *, span=4, rc_dac=195):
    """Find the period, then reconstruct on it. Reports the margin."""
    cands = [eqtime.period_ticks(rc, points)
             for rc in range(rc_dac - span, rc_dac + span + 1)]
    scan = eqtime.find_period(vals, rc_adc, cands)
    best = scan[0]
    margin = (best["sharpness"] / scan[1]["sharpness"]
              if len(scan) > 1 and scan[1]["sharpness"] else float("inf"))
    curve, cnt = eqtime.reconstruct(vals, rc_adc, best["period"])
    return curve, cnt, best, margin, scan


def _report_fold(vals, rc_adc, best, margin, cnt, lsb_v):
    per_bin = len(vals) / max(1, sum(1 for c in cnt if c))
    print(f"  {len(vals):,} samples, RC_adc {rc_adc} "
          f"({eqtime.TC_CLOCK_HZ/rc_adc:,.1f} sps)")
    print(f"  period {best['period']} ticks = "
          f"{best['period']/eqtime.TC_CLOCK_HZ*1e6:.2f} us")
    print(f"  chosen by a {margin:.1f}x margin over the next candidate, "
          f"amplitude {best['sharpness']:.0f} codes")
    print(f"  phase coverage {best['coverage']*100:.1f}%, "
          f"{per_bin:.0f} samples per position, so noise falls by "
          f"{math.sqrt(per_bin):.0f}x")
    print(f"  resolution {1e9/eqtime.TC_CLOCK_HZ:.1f} ns per position "
          f"against a {1e6*rc_adc/eqtime.TC_CLOCK_HZ:.2f} us sample period")


def edge_times(seg, lo, hi):
    """10% and 90% crossing indices of the reconstructed edge."""
    t10 = t90 = None
    for i, v in enumerate(seg):
        if v is None:
            continue
        if t10 is None and v > lo + 0.1 * (hi - lo):
            t10 = i
        if v > lo + 0.9 * (hi - lo):
            t90 = i
            break
    return t10, t90


def cmd_rise(board, args):
    """Milestone 1: does the fold reproduce the scope's rise time?"""
    lsb_v, advref, source = adc_lsb_v()
    print(f"ADC LSB {lsb_v*1e6:.1f} uV (ADVREF {advref} mV, {source})\n")
    vals, rc_adc, st = capture(board, points=args.points,
                               seconds=args.seconds, dac_hz=args.dac_hz)
    curve, cnt, best, margin, scan = fold(vals, rc_adc, args.points,
                                          rc_dac=expected_rc_dac(args.dac_hz))
    _report_fold(vals, rc_adc, best, margin, cnt, lsb_v)

    seg = eqtime.segment_after_edge(curve, pre=args.pre)
    ok = sorted(v for v in seg if v is not None)
    lo, hi = ok[int(0.01 * len(ok))], ok[int(0.99 * len(ok))]
    t10, t90 = edge_times(seg, lo, hi)
    if t10 is None or t90 is None:
        raise SystemExit("no edge in the reconstruction")
    rise = (t90 - t10) / eqtime.TC_CLOCK_HZ
    print(f"\n  step {(hi-lo)*lsb_v*1000:.0f} mV = {hi-lo:.0f} ADC codes")
    print(f"  rise 10-90%  {rise*1e9:.0f} ns  ({t90-t10} ticks)")
    print(f"  the scope, independently: {SCOPE_RISE_S[0]*1e9:.0f}-"
          f"{SCOPE_RISE_S[1]*1e9:.0f} ns")
    inside = SCOPE_RISE_S[0] * 0.7 <= rise <= SCOPE_RISE_S[1] * 1.4
    print(f"\n  {'AGREES' if inside else 'DISAGREES'} with the scope.")
    if not inside:
        print("  The reconstruction is not validated. Either the ADC's\n"
              "  sample aperture is the limit or the model is wrong;\n"
              "  either way the tail must not be read off this.")
    return {"rise_s": rise, "step_codes": hi - lo, "agrees": inside,
            "margin": margin, "coverage": best["coverage"],
            "period_ticks": best["period"], "rc_adc": rc_adc}


def cmd_settle(board, args):
    """The tail, to one code."""
    lsb_v, advref, source = adc_lsb_v()
    print(f"ADC LSB {lsb_v*1e6:.1f} uV (ADVREF {advref} mV, {source})\n")
    vals, rc_adc, st = capture(board, points=args.points,
                               seconds=args.seconds, dac_hz=args.dac_hz)
    curve, cnt, best, margin, scan = fold(vals, rc_adc, args.points,
                                          rc_dac=expected_rc_dac(args.dac_hz))
    _report_fold(vals, rc_adc, best, margin, cnt, lsb_v)

    seg = eqtime.segment_after_edge(curve, pre=0)
    rows = eqtime.settle_profile(seg, lsb=1.0)
    resid = _residual(seg)
    print(f"\n  residual on the settled part: {resid:.3f} codes rms")
    print(f"\n{'band':>8s} {'settled by':>14s} {'ticks out':>11s}")
    print("-" * 36)
    for r in rows:
        t = ("-" if r["settled_by_s"] is None
             else f"{r['settled_by_s']*1e9:11.0f} ns")
        print(f"{r['codes']:6.1f}c {t:>14s} {r['n_outside']:11d}")
    below = [r["codes"] for r in rows if r["codes"] < resid]
    if below:
        print(f"\n  Bands {min(below):g}-{max(below):g} are BELOW the "
              f"{resid:.2f}-code residual.\n  A time to enter a band "
              f"smaller than the noise is the time the noise\n  happened "
              f"to fall inside it. docs/noise.md.")
    same = {r["settled_by_s"] for r in rows if r["settled_by_s"]}
    if len(same) == 1 and len(rows) > 1:
        print("\n  Every band answering the same number is the signature "
              "of a rail,\n  not a tail. Do not read this as settling.")
    return {"bands": rows, "residual_codes": resid, "margin": margin,
            "coverage": best["coverage"], "rc_adc": rc_adc}


def _residual(seg):
    """Rms of the settled part, which bounds what the bands can mean."""
    vals = [v for v in seg[int(len(seg) * 0.6):] if v is not None]
    if len(vals) < 8:
        return 0.0
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))


def cmd_control(board, args):
    """A held level, folded identically. It must come back flat.

    The arm without which none of the above means anything: the same
    reconstruction on a DAC that is not stepping. If it manufactures an
    edge or a tail out of a constant, nothing it says about a real edge
    can be believed - and this project has twice published a curve that
    was an artifact of its own analysis.
    """
    lsb_v, _, _ = adc_lsb_v()
    vals, rc_adc, st = capture(board, points=args.points,
                               seconds=args.seconds, shape="dc",
                               dac_hz=args.dac_hz)
    curve, cnt, best, margin, scan = fold(vals, rc_adc, args.points,
                                          rc_dac=expected_rc_dac(args.dac_hz))
    ok = [v for v in curve if v is not None]
    m = sum(ok) / len(ok)
    rms = math.sqrt(sum((v - m) ** 2 for v in ok) / len(ok))
    span = eqtime.sharpness(curve)
    print(f"  held level {m:.2f} codes, {rms:.3f} codes rms across "
          f"phase, span {span:.2f} codes")
    print(f"  the same fold on a stepping output found "
          f"{'an amplitude' if span > 50 else 'nothing'}")
    flat = span < 20.0
    print(f"\n  {'FLAT, as it must be' if flat else 'NOT FLAT - the fold '
          'is manufacturing structure'}")
    return {"held_rms_codes": rms, "span_codes": span, "flat": flat,
            "rc_adc": rc_adc}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=("rise", "settle", "control"))
    ap.add_argument("--points", type=int, default=8,
                    help="generator resolution; the cycle is 2*points "
                         "DAC updates, so this sets how much hold "
                         "follows each edge")
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--dac-hz", type=int, default=DAC_HZ, dest="dac_hz",
                    help="DAC update rate. Halving it doubles the "
                         "interval between updates, which is the test "
                         "for whether a feature is tied to the update "
                         "clock or is a time constant")
    ap.add_argument("--pre", type=int, default=80,
                    help="ticks of pre-edge baseline to keep")
    ap.add_argument("--record", action="store_true",
                    help="append the result to records/")
    args = ap.parse_args()

    board = measure.Board(settle=3.0)
    try:
        board.stop()
        board.drain_console(0.5)
        p = prov.collect(board=board, extra={"metric": f"settletime-{args.what}",
                                            "points": args.points,
                                            "seconds": args.seconds})
        gaps = prov.missing(p)
        if gaps:
            raise SystemExit(f"refusing to record: provenance missing {gaps}")
        out = {"rise": cmd_rise, "settle": cmd_settle,
               "control": cmd_control}[args.what](board, args)
        if args.record:
            rec = repeat.Recorder(os.path.join(RECORDS, "settletime.jsonl"))
            rec.add({"metric": f"settletime-{args.what}",
                     "axis": "in-place",
                     "values": {k: v for k, v in out.items()
                                if isinstance(v, (int, float))
                                and not isinstance(v, bool)},
                     "bands": out.get("bands"),
                     "agrees": out.get("agrees"), "flat": out.get("flat"),
                     "provenance": p})
    finally:
        try:
            board.stop()
            measure.set_sync(board, "cycle")
        finally:
            board.close()


if __name__ == "__main__":
    main()
