"""The square's shape against frequency and amplitude, scope-free.

    python3 tools/square_shape.py --points 8 --dac-hz 200000 --amp 256
    python3 tools/square_shape.py grid --amps 256,128,58,29 \
        --freqs-hz 50000,100000,200000,400000,600000

The rise of a full-amplitude step scales with the step (slew limited),
so whether the output is still a square depends on frequency *and*
amplitude. This folds a repeating square the way `settletime.py` does -
equivalent-time sampling with the ADC at an RC coprime with the period,
22.2 ns per position at the 45 MHz timer clock - and reads the shape off
the folded period: both edges, how flat each level is, and how much of
the step survived. docs/awg.md has the ceilings this stays inside.

Frequency relation (eqtime.period_ticks): the cycle is `2 * points`
trigger periods, or `points` in solo, so f = TC / period_ticks.
"""
import argparse
import math
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))
sys.path.insert(0, os.path.join(HERE, "tools"))

import eqtime                                                 # noqa: E402
import measure                                                # noqa: E402
import settletime as st                                       # noqa: E402

TC_HZ = eqtime.TC_CLOCK_HZ

#: DACC conversion ceiling as an RC: docs/awg.md's 1,392,857 updates/s
#: is RC 28 at the 39 MHz timer clock, and every ceiling here is a count
#: of clocks, so it is RC 28 at 45 MHz too (1.6 M updates/s, which the
#: doc's Hz figure does not predict *(check on the board)*).
MIN_DAC_RC = 28
DACC_MAX_UPDATES_HZ = TC_HZ // MIN_DAC_RC

#: Points the grid chooses from, largest preferred on a tie (finer RC).
GRID_POINTS = (16, 8, 4, 2)

#: A level is "flat" where the fold is within this fraction of the step
#: of that level's own median.
FLAT_TOL = 0.02

#: Labels for reading a table, not gates: no test or run fails on them.
SQUARE_FLAT_MIN = 0.5
SQUARE_VPP_MIN = 0.95
TRIANGLE_FLAT_MAX = 0.1


def label(flat_frac, vpp_frac):
    """square / trapezoid / triangle from the flat fraction and vpp_frac."""
    if flat_frac < TRIANGLE_FLAT_MAX:
        return "triangle"
    if flat_frac >= SQUARE_FLAT_MIN and (vpp_frac is None
                                         or vpp_frac >= SQUARE_VPP_MIN):
        return "square"
    return "trapezoid"


def _pct(sorted_vals, q):
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))]


def _cross(seg, level, at):
    """Fractional index where seg first passes `level`, interpolated."""
    if at <= 0:
        return float(at)
    a, b = seg[at - 1], seg[at]
    return (at - 1) + ((level - a) / (b - a) if b != a else 1.0)


def _edge_ticks(seg, lo, hi):
    t10, t90 = st.edge_times(seg, lo, hi)
    if t10 is None or t90 is None:
        raise SystemExit("no edge in the folded period")
    return (_cross(seg, lo + 0.9 * (hi - lo), t90)
            - _cross(seg, lo + 0.1 * (hi - lo), t10))


def analyse_square(curve, *, coverage, rc_adc, period, rc_dac,
                   ref_vpp=None):
    """Flat numbers from one folded period; refuses a partial fold."""
    st.require_full_coverage(coverage)
    st.refuse_unless_coprime(rc_adc, period)
    c = [float(v) for v in curve]
    n = len(c)
    srt = sorted(c)
    lo, hi = _pct(srt, 0.1), _pct(srt, 0.9)
    vpp = hi - lo
    if vpp <= 0:
        raise SystemExit("no step in the folded period")
    mid = (lo + hi) / 2
    half = n // 2
    # The rising crossing with the most high ahead and most low behind.
    best, r = None, None
    for i in range(n):
        if c[i - 1] < mid <= c[i]:
            ahead = sum(c[(i + k) % n] for k in range(half)) / half
            behind = sum(c[(i - k - 1) % n] for k in range(half)) / half
            if best is None or ahead - behind > best:
                best, r = ahead - behind, i
    if r is None:
        raise SystemExit("no rising edge in the folded period")
    # Start a quarter period before the rising edge: low, then the edge.
    q = n // 4
    seg = [c[(r - q + k) % n] for k in range(n)]
    rise = _edge_ticks(seg, lo, hi)
    # The falling edge, as a rising one on the negated curve.
    fall_from = [-seg[(k + half) % n] for k in range(n)]
    fall = _edge_ticks(fall_from, -hi, -lo)
    # Flat fractions over the half period each side of the rising edge.
    hi_part = [seg[(q + k) % n] for k in range(half)]
    lo_part = [seg[(q + half + k) % n] for k in range(n - half)]
    tol = FLAT_TOL * vpp

    def flat(part, above):
        # The level is the median of the quarter of the step nearest it,
        # so a slow edge's ramp does not drag the median off the level.
        cut = lo + (0.75 if above else 0.25) * vpp
        pick = sorted(v for v in part if (v >= cut) == above)
        if not pick:
            return 0.0
        med = pick[len(pick) // 2]
        return sum(1 for v in part if abs(v - med) <= tol) / len(part)
    ffh, ffl = flat(hi_part, True), flat(lo_part, False)
    vpp_frac = vpp / ref_vpp if ref_vpp else None
    half_ns = half / TC_HZ * 1e9
    return {"f_hz": TC_HZ / period, "period_ticks": period,
            "rc_dac": rc_dac, "rc_adc": rc_adc, "coverage": coverage,
            "vpp_codes": vpp, "vpp_frac": vpp_frac,
            "rise_ticks": rise, "fall_ticks": fall,
            "rise_ns": rise / TC_HZ * 1e9, "fall_ns": fall / TC_HZ * 1e9,
            "flat_frac_high": ffh, "flat_frac_low": ffl,
            "half_period_ns": half_ns,
            "edge_over_half": rise / TC_HZ * 1e9 / half_ns,
            "shape": label(min(ffh, ffl), vpp_frac)}


def square_shape(board, *, points, dac_hz, amp, seconds=4.0, solo=False,
                 ref_vpp=None):
    """Capture, fold and analyse one repeating square. Flat dict."""
    vals, rc_adc, _ = st.capture(board, points=points, seconds=seconds,
                                 dac_hz=dac_hz, amp=amp, solo=solo)
    curve, cnt, best, _, _ = st.fold(vals, rc_adc, points,
                                     rc_dac=st.expected_rc_dac(dac_hz),
                                     solo=solo)
    upc = points if solo else 2 * points
    out = analyse_square(curve, coverage=best["coverage"], rc_adc=rc_adc,
                         period=best["period"],
                         rc_dac=best["period"] // upc, ref_vpp=ref_vpp)
    out["amp"] = amp
    return out


def plan(freq_hz, *, solo=False):
    """(points, dac_hz, actual_f) nearest `freq_hz`, or None past the DACC.

    f = TC / (upc * rc) with upc = points (solo) or 2 * points, and rc
    an integer >= MIN_DAC_RC. dac_hz is hz_for(rc) so the RC lands.
    """
    best = None
    for pts in GRID_POINTS:
        upc = pts if solo else 2 * pts
        rc = max(MIN_DAC_RC, round(TC_HZ / (upc * freq_hz)))
        f = TC_HZ / (upc * rc)
        err = abs(f - freq_hz)
        if best is None or err < best[0] - 1e-9:
            best = (err, pts, rc, f)
    err, pts, rc, f = best
    if err > 0.05 * freq_hz:
        return None
    return pts, measure.hz_for(rc), f


def grid(board, amps, freqs, *, seconds=4.0, solo=False, run=None,
         out=print):
    run = run or square_shape
    rows = []
    plans = []
    for f in sorted(freqs):
        p = plan(f, solo=solo)
        if p is None:
            out(f"skip {f:,.0f} Hz: not reachable under the DACC's "
                f"{DACC_MAX_UPDATES_HZ:,} updates/s (docs/awg.md)")
        else:
            plans.append(p)
    last_pts = plans[0][0] if plans else 2
    try:
        out(f"{'f_hz':>9s} {'amp':>4s} {'vpp':>6s} {'vpp_frac':>8s} "
            f"{'rise_ns':>8s} {'fall_ns':>8s} {'flat_hi':>7s} shape")
        for amp in amps:
            ref = None
            for pts, dac_hz, _ in plans:
                last_pts = pts
                r = run(board, points=pts, dac_hz=dac_hz, amp=amp,
                        seconds=seconds, solo=solo, ref_vpp=ref)
                if ref is None:
                    ref = r["vpp_codes"]
                    r["vpp_frac"] = 1.0
                    r["shape"] = label(min(r["flat_frac_high"],
                                           r["flat_frac_low"]), 1.0)
                rows.append(r)
                out(f"{r['f_hz']:9,.0f} {amp:4d} {r['vpp_codes']:6.0f} "
                    f"{r['vpp_frac']:8.3f} {r['rise_ns']:8.0f} "
                    f"{r['fall_ns']:8.0f} {r['flat_frac_high']:7.2f} "
                    f"{r['shape']}")
    finally:
        measure.set_gen(board, "square", last_pts, amp=256)
    return rows


def _one_line(r):
    return (f"f={r['f_hz']:,.0f} Hz amp={r['amp']} vpp={r['vpp_codes']:.0f} "
            f"rise={r['rise_ns']:.0f} ns fall={r['fall_ns']:.0f} ns "
            f"flat_hi={r['flat_frac_high']:.2f} {r['shape']}")


def square_shape_once(board, rc=225, seconds=4.0, points=8, amp=256):
    """Flat numbers at DAC RC `rc` (phase0's `square-shape`)."""
    try:
        r = square_shape(board, points=points, dac_hz=measure.hz_for(rc),
                         amp=amp, seconds=seconds)
    finally:
        measure.set_gen(board, "square", points, amp=256)
    return {k: v for k, v in r.items() if isinstance(v, (int, float, str))}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", nargs="?", choices=("grid",))
    ap.add_argument("--points", type=int, default=8)
    ap.add_argument("--dac-hz", type=int, default=st.DAC_HZ, dest="dac_hz")
    ap.add_argument("--amp", type=int, default=256)
    ap.add_argument("--solo", action="store_true")
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--amps", default="256,128,58,29")
    ap.add_argument("--freqs-hz", default="50000,100000,200000,400000,600000",
                    dest="freqs")
    a = ap.parse_args()
    board = measure.Board(settle=3.0)
    try:
        board.stop()
        board.drain_console(0.5)
        if a.what == "grid":
            grid(board, [int(x) for x in a.amps.split(",")],
                 [float(x) for x in a.freqs.split(",")],
                 seconds=a.seconds, solo=a.solo)
        else:
            try:
                print(_one_line(square_shape(
                    board, points=a.points, dac_hz=a.dac_hz, amp=a.amp,
                    seconds=a.seconds, solo=a.solo)))
            finally:
                measure.set_gen(board, "square", a.points, amp=256)
    finally:
        try:
            board.stop()
            measure.set_sync(board, "cycle")
        finally:
            board.close()


if __name__ == "__main__":
    main()
