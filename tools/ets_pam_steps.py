#!/usr/bin/env python3
"""Where an end eye's spread comes from: split the centre samples by the step into them.

A PAM-N capture's end levels can show a wider spread at the symbol centre than
the middle ones. This labels every centre sample with the previous symbol too
and reports, for the outermost eyes and one middle eye as the control:

  * the eye height when the step into the sample's level is capped at 63, 48,
    32, 16 and 8 levels, and
  * the first end level's centre mean offset and spread by the previous level.

Needs numpy (`requirements-dsp.txt`). Reads a raw capture of `ets_pam.py loop`
or `ets_cross.py capture`: 16-bit ADC codes, trimmed as `ets_pam.analyse` does.

    .venv-dsp/bin/python tools/ets_pam_steps.py RAW --pam 64 --swing-mv 2000
"""
import argparse
import array
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "host"))
import dsp  # noqa: E402
import etspam  # noqa: E402
import etspattern  # noqa: E402
import etsperiod  # noqa: E402
import etsplan  # noqa: E402

HEAD_TRIM, TAIL_TRIM = 80_000, 2_000
CAPS = (None, 0.75, 0.5, 0.25, 0.125)       # of the full swing, in levels below
GROUPS = 5


def label(raw, pam, swing_mv, rc_dac, rc_adc):
    pat = etspattern.pattern(pam, swing_mv=swing_mv)
    data = array.array("H")
    with open(raw, "rb") as f:
        data.frombytes(f.read())
    lo, hi = HEAD_TRIM, len(data) - TAIL_TRIM
    vals = [float(v) for v in data[lo:hi]]
    trk = etsperiod.track_clock_ratio(vals, rc_adc, pat.symbols, rc_dac, start=lo, levels=pam)
    unit = pat.length * rc_dac
    curve, cnt = etsperiod.fold_warped(vals, rc_adc, trk["model"], unit, 1, lo)
    b0 = etspam.boundary_offset(curve, rc_dac)
    k = etspam.LABEL_K
    idx = dsp.phase_indices(len(vals), rc_adc, lambda x: etsperiod.phase_at(trk["model"], x),
                            unit, k, lo, etsperiod.SEGMENT)
    rel = (idx - b0 * k) % (unit * k)
    span = rc_dac * k
    j = (rel // span).astype(np.int64)
    t = (rel - j * span) / span
    syms = np.array(pat.symbols)
    return np.array(vals), syms[j], syms[(j - 1) % len(syms)], t


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("raw")
    ap.add_argument("--pam", type=int, required=True)
    ap.add_argument("--swing-mv", type=float, dest="swing_mv")
    ap.add_argument("--rc-dac", type=int, dest="rc_dac")
    ap.add_argument("--rc-adc", type=int, dest="rc_adc")
    a = ap.parse_args()
    pat = etspattern.pattern(a.pam, swing_mv=a.swing_mv)
    pl = etsplan.plan(rc_dac=a.rc_dac, rc_adc=a.rc_adc, same_board=a.rc_dac is None or a.rc_dac % 2 == 0,
                      length=pat.length)
    v, lvl, prev, t = label(a.raw, a.pam, pat.swing_mv, pl["rc_dac"], pl["rc_adc"])
    n = a.pam
    centre = (t >= 0.4) & (t < 0.6)
    step = np.abs(lvl - prev)

    def height(lo_lv, cap):
        m = centre & (step <= cap)
        low, high = v[m & (lvl == lo_lv)], v[m & (lvl == lo_lv + 1)]
        if len(low) < 200 or len(high) < 200:
            return None
        return round(float(np.quantile(high, 0.001) - np.quantile(low, 0.999)), 1)

    print("swing %.0f mV, %d samples, %d at the symbol centre" % (pat.swing_mv, len(v), centre.sum()))
    for name, lo_lv in (("bottom eye", 0), ("middle eye", n // 2 - 1), ("top eye", n - 2)):
        caps = [n - 1 if c is None else int(c * (n - 1)) for c in CAPS]
        row = ["%s %d: %s" % ("every step" if cap == n - 1 else "steps up to", cap, height(lo_lv, cap))
               if cap != n - 1 else "every step: %s" % height(lo_lv, cap) for cap in caps]
        print("%-10s height (codes): %s" % (name, "; ".join(row)))
    for name, end, sign in (("bottom level", 0, 1), ("top level", n - 1, -1)):
        base = v[centre & (lvl == end)].mean()
        print("%s: centre offset and std by the previous level" % name)
        edges = [round(i * (n - 1) / GROUPS) for i in range(GROUPS + 1)]
        for g in range(GROUPS):
            lo_p, hi_p = sorted((end + sign * (edges[g] + (1 if g == 0 else 1)),
                                 end + sign * edges[g + 1]))
            m = centre & (lvl == end) & (prev >= lo_p) & (prev <= hi_p)
            if m.sum():
                print("   previous %2d-%2d  n=%6d  offset %+5.2f  std %.2f"
                      % (lo_p, hi_p, m.sum(), v[m].mean() - base, v[m].std()))


if __name__ == "__main__":
    main()
