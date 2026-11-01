"""The tone sweep, on synthetic captures whose amplitude and crosstalk are known.

`tone_sweep_once` runs one matched loop per tone and reads A0 and A1 at that
tone. The fake `run_loop` plants a sine of known amplitude on each channel at
whatever tone it is asked for, so a swap of the channels, a wrong divisor, a
dropped refusal or a whole-run figure each changes an answer the tests know.
"""
import math
import os
import sys
from array import array
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "host"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import measure  # noqa: E402
import metrics  # noqa: E402
import phase0  # noqa: E402

RC = 225
FS = measure.hz_for(RC)
A0_AMP = {256: 1370.0, 64: 1360.0, 16: 1300.0, 8: 1100.0}   # planted, codes
A1_AMP = {256: 5.0, 64: 8.0, 16: 20.0, 8: 40.0}
TOL = 2.0                                  # codes; int() truncation and Goertzel
WINDOWS = 12
SIZE = metrics.LOOP_WINDOW


def _fake(calls, a0=None, a1=None, refuse_at=None):
    a0 = a0 or A0_AMP
    a1 = a1 or A1_AMP

    def run_loop(board, **kw):
        calls.append(kw)
        n = round(kw["dac_sps"] / kw["tone"])
        if refuse_at == n:
            return SimpleNamespace(refused=True)
        tone = kw["dac_sps"] / n
        total = int(FS * measure.SETTLE_US / 1e6) + (WINDOWS + 2) * SIZE
        ps = measure.ParsedStream(declared_rate_hz=FS, ts_first=0)
        marks = [(k, int(k / FS * 1e6)) for k in range(0, total, 2032)]

        def sine(amp):
            return array("H", (int(2048 + amp * math.sin(
                2 * math.pi * (i % n) / n)) for i in range(total)))
        ps.series = {measure.CH_A0: sine(a0[n]), measure.CH_A1: sine(a1[n])}
        ps.marks = {measure.CH_A0: list(marks), measure.CH_A1: list(marks)}
        return SimpleNamespace(stream=ps, tone_hz=tone, refused=False)
    return run_loop


@pytest.fixture
def calls(monkeypatch):
    c = []
    monkeypatch.setattr(measure, "run_loop", _fake(c))
    return c


def test_planted_amplitude_and_crosstalk_come_back_for_every_n(calls):
    out = metrics.tone_sweep_once(None, RC)
    for n in (256, 64, 16, 8):
        assert abs(out[f"amp_n{n}"] - A0_AMP[n]) < TOL
        assert abs(out[f"xtalk_n{n}"] - A1_AMP[n]) < TOL
    floor = metrics.amplitude_limits()["window_floor_codes"]
    for n in (256, 64, 16, 8):
        assert out[f"amp_n{n}_frac"] == (1.0 if A0_AMP[n] >= floor else 0.0)


def test_key_set_is_exact(calls):
    out = metrics.tone_sweep_once(None, RC)
    want = {"rc", "fs"}
    for n in (256, 64, 16, 8):
        want |= {f"amp_n{n}", f"amp_n{n}_frac", f"xtalk_n{n}"}
    assert set(out) == want
    assert out["rc"] == RC and out["fs"] == FS


def test_loop_runs_matched_at_hz_over_n_in_order(calls):
    metrics.tone_sweep_once(None, RC)
    assert [c["tone"] for c in calls] == [FS / n for n in (256, 64, 16, 8)]
    for c in calls:
        assert c["dac_sps"] == FS and c["adc_hz"] == FS and c["channels"] == 2
        assert c["seconds"] >= metrics.loop_seconds(RC)


def test_a_refusal_raises_systemexit(monkeypatch):
    monkeypatch.setattr(measure, "run_loop", _fake([], refuse_at=16))
    with pytest.raises(SystemExit, match="N=16"):
        metrics.tone_sweep_once(None, RC)


def test_a_tone_without_whole_cycles_per_window_is_rejected_before_any_run(
        calls):
    with pytest.raises(ValueError, match="N=12"):
        metrics.tone_sweep_once(None, RC, ns=(256, 12))
    assert calls == []


def test_the_median_window_is_used_not_the_whole_run(monkeypatch):
    """One collapsed window in twelve leaves the median where it was."""
    base = _fake([])

    def run_loop(board, **kw):
        res = base(board, **kw)
        s = res.stream.series[measure.CH_A0]
        start = int(FS * measure.SETTLE_US / 1e6) + 3 * SIZE
        for i in range(start, start + SIZE):
            s[i] = 2048
        return res
    monkeypatch.setattr(measure, "run_loop", run_loop)
    out = metrics.tone_sweep_once(None, RC)
    assert abs(out["amp_n256"] - A0_AMP[256]) < TOL
    assert out["amp_n256_frac"] < 1.0


def test_registered_scope_free_and_honours_rc(calls):
    m = phase0.METRICS["tone-sweep"]
    assert m["scope"] is False
    ns = m["args"]("tone-sweep", rc=RC)
    out = m["fn"](None, None, ns)
    assert out["rc"] == RC and len(calls) == 4
