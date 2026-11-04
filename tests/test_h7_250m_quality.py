"""targets/h7tool/measure/h7_250m_quality.py: the analysis functions on synthetic signals (a triangle with noise, the shape the trigger test uses) with known answers."""
import importlib.util, os, random, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "targets", "h7tool", "measure", "h7_250m_quality.py")


def load(path, name="h7_250m_quality_under_test"):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m)
    return m


def triangle(n=2048, period=998, amp=53.0, zero=116.5, phase=0, noise=1.5, seed=1):
    """A triangle of +-amp codes about `zero`, rising first from the zero crossing at sample `phase`, as integer codes with gaussian noise."""
    rnd = random.Random(seed); out = []
    for i in range(n):
        p = ((i - phase) % period) / period                      # 0 at a rising zero crossing
        v = 4 * amp * p if p < 0.25 else (2 * amp - 4 * amp * p if p < 0.75 else 4 * amp * p - 4 * amp)
        out.append(int(round(zero + v + rnd.gauss(0, noise))))
    return out


def run_checks(q):
    bad = []
    def check(ok, what):
        if not ok: bad.append(what)
    slope, zero, res = q.fit_gain([(-0.2, 63.0), (0.0, 116.5), (0.2, 170.0)])
    check(abs(slope - 267.5) < 1e-6 and abs(zero - 116.5) < 1e-6 and res < 1e-6, "an exact line is fitted exactly")
    slope, zero, res = q.fit_gain([(-0.2, 64.0), (0.0, 116.0), (0.2, 170.0)])
    check(abs(slope - 265.0) < 1e-6 and abs(zero - (64 + 116 + 170) / 3) < 1e-6 and 0.3 < res < 0.6, "a line with scatter reports its residual")
    s = q.stats([1, 2, 3, 3])
    check(abs(s["mean"] - 2.25) < 1e-9 and s["min"] == 1 and s["max"] == 3 and s["distinct"] == 3 and abs(s["std"] - 0.8292) < 1e-3, "stats")
    check(abs(q.smooth([0, 0, 9, 0, 0], 3)[2] - 3.0) < 1e-9 and abs(q.smooth([2, 4], 3)[0] - 3.0) < 1e-9, "the moving average is centred and shorter at the ends")
    x = triangle(phase=300, noise=0.0)
    rise = q.edge_position(x, 116.5, True, 300); fall = q.edge_position(x, 116.5, False, 300 + 499)
    check(rise is not None and abs(rise - 300) < 0.6, "a rising crossing is placed to under a sample on a clean triangle")
    check(fall is not None and abs(fall - (300 + 499)) < 1.5, "a falling crossing is placed to a sample or so")
    later = q.edge_position(x, 116.5, True, 900)
    check(later is not None and abs(later - (300 + 998)) < 0.6, "the nearest crossing of the right direction is taken")
    check(q.edge_position([116] * 600, 116.5, True, 300) is None, "a flat signal has no edge")
    xn = triangle(phase=1024, noise=1.5)
    en = q.edge_position(xn, 116.5, True, 1024)
    check(en is not None and abs(en - 1024) < 3.0, "noise of 1.5 codes on a 0.2 code per sample slope moves the edge by only a few samples")
    check(q.classify_trigger(x, 116.5, True, 300) == "requested", "an edge of the requested direction at the point")
    check(q.classify_trigger(x, 116.5, False, 300) == "opposite", "only the other direction at the point")
    check(q.classify_trigger(x, 116.5, True, 650) == "neither", "no edge near the point")
    c = q.crossings(triangle(phase=100, noise=0.0), 116.5, True)
    check(c and min(c) > 1000, "a crossing inside the start-up junk head (sample 100) is ignored and the next one is found")
    check(len(q.crossings([150] * 300 + [120] * 300, 140.0, False)) == 1, "a smoothed value exactly at the level counts as a falling crossing")
    check(len(q.crossings([120] * 300 + [150] * 300, 130.0, True)) == 1, "and as a rising one")
    sm = q.summary([1.0, 2.0, 3.0])
    check(sm["n"] == 3 and abs(sm["mean"] - 2.0) < 1e-9 and abs(sm["std"] - 0.8165) < 1e-3 and q.summary([])["n"] == 0, "summary")
    return bad


def test_the_analysis_gets_known_answers_from_synthetic_signals():
    assert run_checks(load(TOOL)) == []


@pytest.mark.parametrize("old, new, what", [
    ("slope = (n * sxy - sx * sy) / (n * sxx - sx * sx); zero = (sy - slope * sx) / n", "slope = (n * sxy - sx * sy) / (n * sxx - sx * sx); zero = sy / n + 1", "zero code"),
    ("return mx + (level - my) / slope", "return mx - (level - my) / slope", "edge interpolation sign"),
    ("(s[i] < level <= s[i + 1] if rising else s[i] > level >= s[i + 1])", "(s[i] > level >= s[i + 1] if rising else s[i] < level <= s[i + 1])", "rising and falling swapped"),
    ("if lo < i < len(x) - hi_margin]", "if i < len(x) - hi_margin]", "start-up junk exclusion"),
    ("if rising else s[i] > level >= s[i + 1])]", "if rising else s[i] > level > s[i + 1])]", "falling crossing at equality"),
    ("return \"opposite\" if near(not requested_rising) else \"neither\"", "return \"neither\"", "opposite-edge class"),
    ("a, b = max(0, i - h), min(len(x), i + h + 1); out.append(sum(x[a:b]) / (b - a))", "a, b = max(0, i - h), min(len(x), i + h + 1); out.append(sum(x[a:b]) / (b - a + 1))", "moving average divisor"),
    ("(sum((v - mean) ** 2 for v in x) / n) ** 0.5", "(sum((v - mean) ** 2 for v in x) / (n - 1)) ** 0.5", "standard deviation divisor"),
])
def test_a_fault_in_the_analysis_is_caught(tmp_path, old, new, what):
    src = open(TOOL, encoding="utf-8").read()
    assert src.count(old) == 1, what
    bad = tmp_path / "h7_250m_quality_mut.py"
    bad.write_text(src.replace(old, new), encoding="utf-8")
    q = load(str(bad), "h7_250m_quality_mutant")
    try: failures = run_checks(q)
    except Exception: failures = ["raised"]
    assert failures, what
