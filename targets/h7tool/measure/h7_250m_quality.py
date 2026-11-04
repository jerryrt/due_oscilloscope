"""Measure the 250M module the way docs/23 did: the transfer function of each range, and where the hardware trigger puts the edge.

    python3 targets/h7tool/measure/h7_250m_quality.py ranges      # three DC levels per range code: codes per volt, zero code, noise
    python3 targets/h7tool/measure/h7_250m_quality.py trigger     # a 1 kHz triangle, single trigger, levels x edges x positions: where the edge lands

Needs the stock app running with the module attached, TVCC 3.3 V (the tool sets it), and the H7-TOOL's VOUT wired to the module's CH1 on a 1x probe.
Every capture goes out with a settle time after a change and the first capture of each point thrown away (the first one after a change is wrong). The
analysis functions below are pure and tested on synthetic signals (tests/test_h7_250m_quality.py)."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))

NOMINAL_HALF_MV = [40000, 20000, 8000, 4000, 2000, 800, 400, 200, 80, 40]      # the vendor's range list, code 0..9


def stats(x):
    n = len(x); mean = sum(x) / n
    return {"mean": mean, "std": (sum((v - mean) ** 2 for v in x) / n) ** 0.5, "min": min(x), "max": max(x), "distinct": len(set(x))}


def fit_gain(points):
    """Least squares over (volts, mean code) pairs: codes per volt, the code at 0 V, and the rms residual in codes."""
    n = len(points); sx = sum(v for v, _ in points); sy = sum(c for _, c in points)
    sxx = sum(v * v for v, _ in points); sxy = sum(v * c for v, c in points)
    slope = (n * sxy - sx * sy) / (n * sxx - sx * sx); zero = (sy - slope * sx) / n
    return slope, zero, (sum((c - (zero + slope * v)) ** 2 for v, c in points) / n) ** 0.5


def smooth(x, k=15):
    """Moving average with the window centred (shorter at the ends)."""
    h = k // 2; out = []
    for i in range(len(x)):
        a, b = max(0, i - h), min(len(x), i + h + 1); out.append(sum(x[a:b]) / (b - a))
    return out


def crossings(x, level, rising, k=15, lo=130, hi_margin=60):
    """Sample indices where the smoothed signal crosses `level` in the wanted direction, away from the start-up junk and the end."""
    s = smooth(x, k)
    c = [i for i in range(len(s) - 1) if (s[i] < level <= s[i + 1] if rising else s[i] > level >= s[i + 1])]
    return [i for i in c if lo < i < len(x) - hi_margin]


def edge_position(x, level, rising, near, half=40):
    """Sub-sample position of the crossing nearest `near`, from a straight line fitted through 2*half+1 samples around it; None when there is none."""
    c = crossings(x, level, rising)
    if not c: return None
    i = min(c, key=lambda j: abs(j - near)); lo, hi = max(0, i - half), min(len(x), i + half + 1)
    xs = list(range(lo, hi)); ys = x[lo:hi]; n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    slope = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / sum((a - mx) ** 2 for a in xs)
    return mx + (level - my) / slope


def classify_trigger(x, level, requested_rising, expected, tol=60):
    """'requested' if an edge of the requested direction is within tol of the expected position, 'opposite' if only the other direction is, else 'neither'."""
    near = lambda r: any(abs(i - expected) < tol for i in crossings(x, level, r))
    if near(requested_rising): return "requested"
    return "opposite" if near(not requested_rising) else "neither"


def summary(values):
    n = len(values)
    if not n: return {"n": 0, "mean": None, "std": None}
    m = sum(values) / n
    return {"n": n, "mean": m, "std": (sum((v - m) ** 2 for v in values) / n) ** 0.5}


# ---- the procedures (hardware) ----
def measure_ranges(m, codes=range(10), settle=0.6):
    from h7_250m import generator_block
    out = []
    try:
        for code in codes:
            x = min(8000, int(0.4 * NOMINAL_HALF_MV[code]))
            m.set_generator(generator_block(1, 0, 0)); time.sleep(0.5); m.capture(14, 0, range_code=code); time.sleep(0.3)    # settle the new range, discard
            pts = []
            for mv in (-x, 0, x):
                m.set_generator(generator_block(1, mv, mv)); time.sleep(settle); m.capture(14, 0, range_code=code)               # discard the first at each level
                both = m.capture(14, 0, range_code=code) + m.capture(14, 0, range_code=code)
                pts.append((mv / 1000.0, stats(both)))
            slope, zero, _ = fit_gain([(v, s["mean"]) for v, s in pts])
            out.append((code, slope, zero, [s["std"] for _, s in pts]))
            print("range %d: %8.2f codes/V = %8.3f mV/code, zero %.1f, std at -x/0/+x %s" % (code, slope, 1000 / slope, zero, ["%.2f" % s["std"] for _, s in pts]), flush=True)
    finally:
        m.generator_off()
    return out


def measure_trigger(m, levels=(-0.1, 0.0, 0.1), positions=(10, 50, 90), reps=20, zero=116.54, gain=264.6, n=2048):
    from h7_250m import generator_block
    rows = []
    try:
        m.set_generator(generator_block(3, -200, 200, 1000)); time.sleep(0.6); m.capture(12, 1, range_code=6)
        for rising in (1, 0):
            for lv in levels:
                for pos in positions:
                    exp = n * pos / 100.0; offs = []; cls = {"requested": 0, "opposite": 0, "neither": 0}
                    for _ in range(reps):
                        x = m.capture(12, 1, range_code=6, trig_level_v=lv, trig_pos=pos, trig_mode=2, trig_ch=0, edge=rising)
                        level = zero + gain * lv
                        cls[classify_trigger(x, level, bool(rising), exp)] += 1
                        e = edge_position(x, level, bool(rising), exp)
                        if e is not None and abs(e - exp) < 60: offs.append(e - exp)
                    s = summary(offs); rows.append((rising, lv, pos, cls, s))
                    print("%-7s level %+.1f V pos %2d%%: %s, offset mean %s std %s samples" % ("rising" if rising else "falling", lv, pos, cls,
                          "%+.1f" % s["mean"] if s["n"] else "-", "%.1f" % s["std"] if s["n"] else "-"), flush=True)
    finally:
        m.generator_off()
    return rows


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("ranges", "trigger"): raise SystemExit(__doc__)
    from h7_250m import Module, HidrawTransport
    mod = Module(HidrawTransport()); mod.set_tvcc_mv(3300); mod.enable()
    measure_ranges(mod) if sys.argv[1] == "ranges" else measure_trigger(mod)
