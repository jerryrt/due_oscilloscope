"""`tools/square_shape.py`, board-free, on synthetic folded periods."""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "host"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import eqtime                                                    # noqa: E402
import measure                                                   # noqa: E402
import square_shape as sq                                        # noqa: E402

N = 1800            # period in ticks (8 points x RC 225)
TC = eqtime.TC_CLOCK_HZ


def wave(rise, fall=None, amp=2000.0, base=300.0, n=N, shift=200):
    """One period: 10-90% edges of `rise`/`fall` ticks (linear ramps)."""
    fall = rise if fall is None else fall
    half = n // 2
    rl, fl = rise / 0.8, fall / 0.8
    out = []
    for i in range(n):
        t = (i - shift) % n
        if t < rl:
            v = t / rl
        elif t < half:
            v = 1.0
        elif t < half + fl:
            v = 1.0 - (t - half) / fl
        else:
            v = 0.0
        out.append(base + amp * v)
    return out


def an(curve, **kw):
    d = dict(coverage=1.0, rc_adc=221, period=N, rc_dac=225)
    d.update(kw)
    return sq.analyse_square(curve, **d)


def test_clean_square_reads_its_edge_and_is_a_square():
    r = an(wave(10, 10))
    assert r["rise_ticks"] == pytest.approx(10, abs=1)
    assert r["fall_ticks"] == pytest.approx(10, abs=1)
    assert r["rise_ns"] == pytest.approx(r["rise_ticks"] * 1e9 / TC, abs=0.01)
    assert r["half_period_ns"] == pytest.approx(N // 2 * 1e9 / TC, abs=0.01)
    assert r["shape"] == "square"
    assert r["f_hz"] == pytest.approx(TC / N)


def test_rise_and_fall_are_not_swapped():
    r = an(wave(10, 40))
    assert r["rise_ticks"] == pytest.approx(10, abs=1.5)
    assert r["fall_ticks"] == pytest.approx(40, abs=1.5)


def test_trapezoid_and_triangle_labels():
    half = N // 2
    assert an(wave(0.5 * half, 0.5 * half))["shape"] == "trapezoid"
    assert an(wave(half * 0.8, half * 0.8))["shape"] == "triangle"


def test_amplitude_against_a_reference():
    ref = an(wave(10, amp=2000.0))["vpp_codes"]
    r = an(wave(10, amp=1200.0), ref_vpp=ref)
    assert r["vpp_frac"] == pytest.approx(0.6, abs=0.01)
    assert r["shape"] == "trapezoid"       # square-flat but only 60% of step


def test_partial_coverage_refuses():
    with pytest.raises(SystemExit, match="coverage"):
        an(wave(10), coverage=0.9)


def test_non_coprime_adc_rc_refuses():
    with pytest.raises(SystemExit, match="gcd"):
        an(wave(10), rc_adc=222, period=1800)


def test_plan_reports_the_achievable_frequency_not_the_request():
    for f in (50_000, 100_000, 200_000, 300_000):
        pts, hz, got = sq.plan(f)
        rc = measure.rc_for(hz)
        assert rc >= sq.MIN_DAC_RC
        assert got == pytest.approx(TC / (2 * pts * rc))
        assert abs(got - f) / f < 0.05
    pts, hz, got = sq.plan(300_000, solo=True)
    assert got == pytest.approx(TC / (pts * measure.rc_for(hz)))
    assert sq.plan(5_000_000) is None
    assert sq.plan(450_000) is None         # past TC/(4*RC 28) non-solo


def _fake(calls):
    def run(board, *, points, dac_hz, amp, seconds, solo, ref_vpp):
        calls.append((points, dac_hz, amp, ref_vpp))
        rc = measure.rc_for(dac_hz)
        v = 1000.0 * amp / 256
        return {"f_hz": TC / (2 * points * rc), "vpp_codes": v,
                "vpp_frac": v / ref_vpp if ref_vpp else None, "rise_ns": 1.0, "fall_ns": 1.0,
                "flat_frac_high": 0.9, "flat_frac_low": 0.9,
                "shape": "square"}
    return run


def test_grid_runs_each_amp_and_restores_256(monkeypatch):
    sets, calls, lines = [], [], []
    monkeypatch.setattr(measure, "set_gen",
                        lambda b, s, p, amp=None: sets.append((s, p, amp)))
    rows = sq.grid(None, [256, 128], [50_000, 5_000_000, 200_000],
                   run=_fake(calls), out=lines.append)
    assert len(rows) == 4 and sets == [("square", sets[0][1], 256)]
    assert any("skip 5,000,000" in ln for ln in lines)
    assert calls[1][3] == 1000.0            # reference = lowest f's vpp
    assert rows[0]["vpp_frac"] == 1.0


def test_amp_is_restored_when_a_run_raises(monkeypatch):
    sets = []
    monkeypatch.setattr(measure, "set_gen",
                        lambda b, s, p, amp=None: sets.append(amp))

    def boom(*a, **k):
        raise RuntimeError("x")
    with pytest.raises(RuntimeError):
        sq.grid(None, [128], [50_000], run=boom, out=lambda s: None)
    assert sets == [256]
