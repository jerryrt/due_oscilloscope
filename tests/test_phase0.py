"""tools/phase0.py's repeat mechanics, with no board and no scope.

The things a repeatability run depends on and cannot afford to get wrong
quietly: the reflash axis waits and discards before it records, a record
never mixes two clocks, a ladder rate reaches the metric, and a scope-free
metric of the shape `fn(board, args)` can be registered.
"""
import argparse
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "host"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import measure  # noqa: E402
import repeat  # noqa: E402
import phase0  # noqa: E402


class _Board:
    def close(self):
        pass

    def stop(self):
        pass

    def drain_console(self, secs):
        return ""


def _args(tmp_path, **kw):
    import argparse
    ns = argparse.Namespace(metric="noise-fast", runs=3, axes=["in-place"], track="b",
                            out=str(tmp_path / "r.jsonl"), channel=1, trigger=200_000,
                            overrides={}, keep_first=False)
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


@pytest.fixture
def fakes(monkeypatch):
    calls = {"warm": 0, "runs": 0, "flash": 0}

    def open_board(track, flash=False, tries=2):
        calls["flash"] += bool(flash)
        return _Board(), 1

    def run_once(board, inst, metric, args):
        calls["runs"] += 1
        return {"x": 1.0}, None

    monkeypatch.setattr(phase0, "open_board", open_board)
    monkeypatch.setattr(phase0, "run_once", run_once)
    monkeypatch.setattr(phase0.repeat, "warm_up", lambda *a, **k: calls.__setitem__("warm", calls["warm"] + 1))
    monkeypatch.setattr(phase0.prov, "collect", lambda **k: {"mck_hz": measure.MCK_HZ, **k.get("extra", {})})
    monkeypatch.setattr(phase0.prov, "missing", lambda p: [])
    monkeypatch.setattr(phase0.measure, "set_sync", lambda *a, **k: None)
    return calls


def test_the_reflash_axis_waits_and_throws_one_run_away_before_each_recorded_run(tmp_path, fakes):
    path = phase0.take(_args(tmp_path, axes=["reflash"], runs=3))
    assert fakes["flash"] == 3 and fakes["warm"] == 3
    assert fakes["runs"] == 6, "three throwaway runs and three recorded ones"
    assert len(repeat.load(path)) == 3, "a throwaway run must not be recorded"


def test_the_in_place_axis_neither_waits_nor_throws_a_run_away(tmp_path, fakes):
    path = phase0.take(_args(tmp_path, axes=["in-place"], runs=3))
    assert fakes["warm"] == 0 and fakes["runs"] == 3 and len(repeat.load(path)) == 3


def test_a_record_taken_at_another_clock_is_not_appended_to(tmp_path, fakes):
    other = 78_000_000 if measure.MCK_HZ != 78_000_000 else 90_000_000
    out = tmp_path / "r.jsonl"
    out.write_text(json.dumps({"run": 1, "axis": "in-place", "values": {"x": 1.0},
                               "provenance": {"mck_hz": other}}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        phase0.take(_args(tmp_path))
    assert "--out" in str(e.value) and fakes["runs"] == 0


def test_a_report_on_a_mixed_record_is_refused(tmp_path):
    rec = repeat.Recorder(str(tmp_path / "m.jsonl"))
    for i, c in enumerate((78_000_000, 90_000_000, 90_000_000)):
        rec.add({"run": i, "axis": "in-place", "metric": "noise-fast",
                 "values": {"x": 1.0}, "provenance": {"mck_hz": c}})
    with pytest.raises(SystemExit) as e:
        phase0.report(str(tmp_path / "m.jsonl"), "noise-fast")
    assert "refusing to report" in str(e.value)


def _record(tmp_path, n_runs, clock=90_000_000, vals=None):
    path = str(tmp_path / "g.jsonl")
    rec = repeat.Recorder(path)
    for i in range(n_runs):
        v = 1.0 + 0.1 * (i % 3) if vals is None else vals[i]
        rec.add({"run": i, "axis": "in-place", "metric": "noise-fast",
                 "values": {"x": v}, "provenance": {"mck_hz": clock}})
    return path


def test_six_kept_runs_are_refused_and_print_no_tolerance(tmp_path, capsys):
    path = _record(tmp_path, 7)  # run 0 dropped by index leaves six
    with pytest.raises(SystemExit) as e:
        phase0.report(path, "noise-fast")
    msg = str(e.value)
    assert "x" in msg and "6 kept" in msg and str(repeat.MIN_KEPT) in msg
    assert "proposed gate" not in capsys.readouterr().out


def test_seven_kept_runs_print_a_proposed_gate(tmp_path, capsys):
    phase0.report(_record(tmp_path, 8), "noise-fast")
    assert "proposed gate" in capsys.readouterr().out


def test_a_mixed_clock_record_with_enough_runs_is_still_refused(tmp_path):
    path = _record(tmp_path, 9)
    repeat.Recorder(path).add({"run": 9, "axis": "in-place", "values": {"x": 1.0},
                               "provenance": {"mck_hz": 78_000_000}})
    with pytest.raises(SystemExit) as e:
        phase0.report(path, "noise-fast")
    assert "more than one master clock" in str(e.value)


def test_a_spread_above_a_supplied_gate_is_reported_and_one_below_is_not(tmp_path, capsys):
    path = _record(tmp_path, 8)  # kept spread is 0.2
    assert phase0.report(path, "noise-fast", gates={"x": 0.1}) is None
    out = capsys.readouterr().out
    assert "!! spread exceeds gate" in out and "0.2" in out and "0.1" in out
    phase0.report(path, "noise-fast", gates={"x": 0.5})
    assert "!! spread exceeds gate" not in capsys.readouterr().out
    phase0.report(path, "noise-fast")
    assert "!! spread exceeds gate" not in capsys.readouterr().out


def test_the_cli_reads_a_gates_file_and_hands_it_to_report(monkeypatch, tmp_path):
    g = tmp_path / "g.json"
    g.write_text('{"x": 0.1}', encoding="utf-8")
    seen = {}
    monkeypatch.setattr(phase0, "report",
                        lambda path, metric, first=False, gates=None: seen.update(gates=gates))
    monkeypatch.setattr(sys, "argv", ["phase0", "noise-fast", "--report",
                                      "--gates", str(g)])
    phase0.main()
    assert seen["gates"] == {"x": 0.1}


def test_the_cli_takes_track_c_a_ladder_rc_and_keeps_run_zero_only_when_asked(monkeypatch):
    seen = {}
    monkeypatch.setattr(phase0, "take", lambda a: seen.setdefault("args", a) and "/dev/null")
    monkeypatch.setattr(phase0, "report", lambda path, metric, first=False, gates=None: seen.update(first=first))
    monkeypatch.setattr(sys, "argv", ["phase0", "noise-fast", "--track", "c", "--rc", "86"])
    phase0.main()
    a = seen["args"]
    assert a.track == "c" and a.runs == 8 and a.overrides["rc"] == 86 and seen["first"] is False
    monkeypatch.setattr(sys, "argv", ["phase0", "noise-fast", "--keep-first"])
    seen.clear()
    phase0.main()
    assert seen["first"] is True


def test_a_scope_free_metric_of_the_two_argument_shape_is_called_in_the_three_argument_one():
    got = []
    metric = phase0.adapt(lambda board, args: got.append((board, args)) or {"k": 1.0})
    assert metric("B", None, "A") == {"k": 1.0} and got == [("B", "A")]


def test_a_ladder_rc_reaches_the_noise_metric_as_that_rates_trigger(monkeypatch):
    import noise_metrics as nm
    import noisetool

    class Res:
        class stream:
            declared_rate_hz = None
    seen = {}
    monkeypatch.setattr(noisetool, "adc_lsb_v", lambda: (1.0, 3300, "x"))
    monkeypatch.setattr(noisetool, "_series", lambda res, tag: [1] * 10)
    monkeypatch.setattr(noisetool, "analyse", lambda vals, fs, lsb, window=0: seen.update(fs=fs) or {"rms": 1.0})
    monkeypatch.setattr(noisetool, "hold_gen_dc", lambda b, c, preset, s: seen.update(preset=preset) or Res)
    monkeypatch.setattr(noisetool, "hold_host_dc", lambda b, c, hz, s: seen.update(host=hz) or Res)
    hz = measure.hz_for(120)
    nm._run(None, 2048, 1.0, 4096, preset="5", rc=120)
    assert seen["preset"] == f"={hz},{hz}M" and seen["fs"] == hz
    nm._run(None, 2048, 1.0, 4096, host_rate=200000, rc=120)
    assert seen["host"] == hz
    seen.clear()
    nm._run(None, 2048, 1.0, 4096, preset="5")
    assert seen["preset"] == "5", "no --rc must leave the preset alone"


# --- several metrics from one reflash cycle -------------------------------

_REAL_RUN_ONCE = phase0.run_once


def _two(tmp_path, **kw):
    return _args(tmp_path, metric="a", metrics=["a", "b"],
                 out=str(tmp_path / "r"), **kw)


@pytest.fixture
def two_metrics(monkeypatch, fakes):
    """Metrics `a` and `b`, each recording the calls it gets."""
    seen = []

    def make(name):
        def fn(board, inst, args):
            seen.append(name)
            return {"x": 1.0}
        return {"fn": fn, "scope": False, "args": lambda what, **o: argparse.Namespace()}
    monkeypatch.setitem(phase0.METRICS, "a", make("a"))
    monkeypatch.setitem(phase0.METRICS, "b", make("b"))
    monkeypatch.setattr(phase0, "run_once", _REAL_RUN_ONCE)
    fakes["seen"] = seen
    return fakes


def test_two_metrics_share_one_flash_and_one_warm_up_per_run_index(tmp_path, two_metrics):
    f = two_metrics
    paths = phase0.take(_two(tmp_path, axes=["reflash"], runs=3))
    assert f["flash"] == 3 and f["warm"] == 3, "one cycle per run index, not per metric"
    assert f["seen"].count("a") == 6 and f["seen"].count("b") == 6, \
        "the throwaway cycle runs and discards one of each"
    for m in "ab":
        rows = repeat.load(paths[m])
        assert [r["run"] for r in rows] == [0, 1, 2] and {r["metric"] for r in rows} == {m}


def test_the_in_place_axis_runs_the_metrics_back_to_back_per_run_index(tmp_path, two_metrics):
    f = two_metrics
    phase0.take(_two(tmp_path, runs=2))
    assert f["seen"] == ["a", "b", "a", "b"] and f["warm"] == 0


def test_a_failing_metric_records_its_error_and_the_others_still_run(tmp_path, two_metrics):
    def boom(board, inst, args):
        raise SystemExit("refusing to report: phase coverage 90.0%")
    phase0.METRICS["a"]["fn"] = boom
    paths = phase0.take(_two(tmp_path, axes=["reflash"], runs=2))
    a, b = repeat.load(paths["a"]), repeat.load(paths["b"])
    assert len(a) == 2 and all("coverage" in r["error"] and r["values"] == {} for r in a)
    assert len(b) == 2 and all(r["error"] is None and r["values"] == {"x": 1.0} for r in b)


def test_each_metric_keeps_its_own_clock_refusal(tmp_path, two_metrics):
    other = 78_000_000 if measure.MCK_HZ != 78_000_000 else 90_000_000
    (tmp_path / "r-b.jsonl").write_text(json.dumps(
        {"run": 1, "axis": "in-place", "values": {"x": 1.0},
         "provenance": {"mck_hz": other}}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        phase0.take(_two(tmp_path))
    assert "r-b.jsonl" in str(e.value) and not two_metrics["seen"]


def test_one_name_still_writes_the_out_path_as_given(tmp_path, fakes):
    path = phase0.take(_args(tmp_path, runs=2))
    assert path == str(tmp_path / "r.jsonl") and len(repeat.load(path)) == 2


def test_the_cli_takes_a_comma_list_and_refuses_an_unknown_name(monkeypatch):
    seen = {}
    monkeypatch.setattr(phase0, "take", lambda a: seen.update(a=a))
    monkeypatch.setattr(phase0, "report", lambda path, metric, first=False, gates=None:
                        seen.setdefault("rep", []).append((path, metric)))
    monkeypatch.setattr(sys, "argv", ["phase0", "loop,dc-fit,rise", "--out", "/x/p"])
    phase0.main()
    assert seen["a"].metrics == ["loop", "dc-fit", "rise"]
    assert seen["rep"] == [("/x/p-loop.jsonl", "loop"), ("/x/p-dc-fit.jsonl", "dc-fit"),
                           ("/x/p-rise.jsonl", "rise")]
    monkeypatch.setattr(sys, "argv", ["phase0", "loop,nope"])
    with pytest.raises(SystemExit):
        phase0.main()


# --- dc-fit and rise -----------------------------------------------------

def test_the_tools_dc_fit_equals_the_test_helpers_fit():
    import helpers
    import metrics
    pts = [(512, 1017.3), (1024, 1360.9), (2048, 2046.2), (3072, 2733.8), (3583, 3075.1)]
    assert metrics.dc_fit(pts) == pytest.approx(helpers.dc_fit(pts), rel=1e-12, abs=1e-12)
    assert metrics.dc_fit(pts)[0] == pytest.approx(0.67, abs=0.01)


def test_dc_fit_runs_five_codes_and_returns_flat_numbers(monkeypatch):
    import metrics
    from types import SimpleNamespace
    calls = []

    def run_loop(board, **kw):
        calls.append(kw)
        v = [int(100 + 0.67 * kw["dc"])] * 8
        return SimpleNamespace(refused=False, stream=SimpleNamespace(settled={measure.CH_A0: v}))
    monkeypatch.setattr(measure, "run_loop", run_loop)
    out = phase0.METRICS["dc-fit"]["fn"](
        None, None, phase0.dc_fit_default_args("dc-fit", rc=86))
    assert [c["dc"] for c in calls] == [512, 1024, 2048, 3072, 3583]
    assert all(c["dac_sps"] == 200000 and c["channels"] == 2 and c["adc_hz"] == measure.hz_for(86)
               for c in calls)
    assert set(out) >= {"slope", "offset", "rms", "worst", "mean_c512", "mean_c3583"}
    assert out["slope"] == pytest.approx(0.67, abs=0.001) and out["rc"] == 86
    assert all(isinstance(v, (int, float)) for v in out.values())
    calls.clear()
    phase0.METRICS["dc-fit"]["fn"](None, None, phase0.dc_fit_default_args("dc-fit"))
    assert calls[0]["adc_hz"] == measure.hz_for(measure.rc_for(200000))


def _rise_capture(monkeypatch, rc_adc):
    import eqtime
    import settletime
    import test_settletime_guard as g
    vals = g._square(rc_adc, 30000, g._period())
    monkeypatch.setattr(settletime, "capture", lambda board, **kw: (vals, rc_adc, None))
    monkeypatch.setattr(settletime, "adc_lsb_v", lambda: (0.0008, 3300, "test"))
    return settletime


def test_rise_returns_flat_numbers_on_a_full_fold(monkeypatch):
    st = _rise_capture(monkeypatch, 221)
    out, err = _REAL_RUN_ONCE(_Board(), None, "rise", phase0.rise_default_args("rise"))
    assert err is None and out["coverage"] == 1.0 and out["rc"] == 221
    assert out["rise_ticks"] > 0 and out["rise_s"] == pytest.approx(out["rise_ticks"] / st.eqtime.TC_CLOCK_HZ, abs=1e-8)


def test_rise_on_a_coverage_of_0_9_is_an_error_row_and_not_a_zero(monkeypatch, tmp_path):
    _rise_capture(monkeypatch, 221)
    import settletime
    real_fold = settletime.fold

    def fold(*a, **k):
        curve, cnt, best, margin, scan = real_fold(*a, **k)
        return curve, cnt, dict(best, coverage=0.9), margin, scan
    monkeypatch.setattr(settletime, "fold", fold)
    out, err = _REAL_RUN_ONCE(_Board(), None, "rise", phase0.rise_default_args("rise"))
    assert out is None and "coverage" in err
