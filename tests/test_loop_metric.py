"""The matched-loop metric, board-free.

`tools/metrics.py` `loop_once` and `tools/phase0.py`'s `loop` metric judge
the same tone and crosstalk the ladder does, from the same limits. These
tests feed `loop_figures` the synthetic captures of `test_ladder_checks`
and a fake board to `loop_once`, and each was broken on purpose on the
real code to see it fail.
"""
import copy
import json
import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for d in ("host", "tools", "tests"):
    sys.path.insert(0, os.path.join(REPO, d))
import measure  # noqa: E402
import pacing  # noqa: E402
import metrics  # noqa: E402
import phase0  # noqa: E402
import test_ladder_checks as lc  # noqa: E402

FLOOR = 1340.0


def _figs(res, channels=2):
    return metrics.loop_figures(res, FLOOR, channels)


def test_a_clean_capture_reads_a_full_tone_and_no_crosstalk():
    f = _figs(lc._result())
    assert 1360 < f["tone_median_codes"] < 1380
    assert f["windows_at_or_above_floor"] == 1.0
    assert f["windows"] >= metrics.LOOP_WINDOWS
    assert f["crosstalk_median_codes"] < 1.0


def test_a_scaled_a0_drops_the_tone_and_its_window_fraction():
    f = _figs(lc._result(a0=1000.0))
    assert f["tone_median_codes"] < FLOOR
    assert f["windows_at_or_above_floor"] == 0.0


def test_a_tone_on_a1_reads_as_crosstalk_and_only_with_two_channels():
    two = _figs(lc._result(a1=300.0))
    assert two["crosstalk_median_codes"] > 250
    one = _figs(lc._result(a1=300.0), channels=1)
    assert one["crosstalk_median_codes"] is None


def test_overruns_and_rate_ratio_come_from_the_stream():
    res = copy.deepcopy(lc._result())
    res.stream.overrun_frames = 7
    res.stream.measured_rate_hz = lambda: res.stream.declared_rate_hz * 0.99
    f = _figs(res)
    assert f["overrun_frames"] == 7
    assert abs(f["rate_ratio"] - 0.99) < 1e-9


def test_the_limits_are_the_baselines_and_not_a_literal():
    with open(os.path.join(REPO, "tests", "baseline.json"), encoding="utf-8") as fh:
        want = json.load(fh)["amplitude"]
    assert metrics.amplitude_limits() == want


def test_the_run_is_long_enough_for_ten_windows_after_the_settle():
    for rc in (1000, 225, 120, 86):
        hz = measure.hz_for(rc)
        need = measure.SETTLE_US / 1e6 + metrics.LOOP_WINDOWS * metrics.LOOP_WINDOW / hz
        assert metrics.loop_seconds(rc) >= need


class _Board:
    pass


def test_loop_once_runs_the_matched_loop_at_the_rungs_rate(monkeypatch):
    seen = {}

    def fake(board, **kw):
        seen.update(kw)
        r = lc._result()
        r.refused = False
        return r
    monkeypatch.setattr(measure, "run_loop", fake)
    out = metrics.loop_once(_Board(), 120)
    hz = measure.hz_for(120)
    assert seen["dac_sps"] == hz and seen["adc_hz"] == hz
    assert seen["tone"] == hz / 256.0 and seen["channels"] == 2
    assert seen["seconds"] >= metrics.loop_seconds(120)
    assert out["rc"] == 120 and out["hz"] == hz
    assert all(isinstance(v, (int, float)) or v is None for v in out.values())


def test_a_refused_run_is_refused_not_a_figure(monkeypatch):
    monkeypatch.setattr(measure, "run_loop",
                        lambda b, **k: SimpleNamespace(refused=True))
    try:
        metrics.loop_once(_Board(), 120)
    except SystemExit as e:
        assert "refused" in str(e)
    else:
        raise AssertionError("a refused run returned figures")


def test_m_loop_repeats_and_reports_the_limits(monkeypatch):
    monkeypatch.setattr(measure, "run_loop",
                        lambda b, **k: (lambda r: (setattr(r, "refused", False), r)[1])(lc._result()))
    got = metrics.m_loop(_Board(), SimpleNamespace(repeats=2, seconds=pacing.SHORT, rc=120))
    assert got["tone_amplitude_codes"]["n"] == 2
    assert got["rc"] == 120
    assert got["crosstalk_ceiling_codes"] == metrics.amplitude_limits()["crosstalk_ceiling_codes"]
    assert "windows_at_or_above_floor" in got


def test_phase0_registers_loop_scope_free_at_a_default_rung(monkeypatch):
    m = phase0.METRICS["loop"]
    assert m["scope"] is False
    ns = m["args"]("loop")
    assert ns.rc == metrics.LOOP_RC and measure.hz_for(ns.rc) == 200000
    assert m["args"]("loop", rc=120).rc == 120
    monkeypatch.setattr(metrics, "loop_once", lambda b, rc, s: {"rc": rc})
    assert m["fn"](None, None, ns) == {"rc": metrics.LOOP_RC}
