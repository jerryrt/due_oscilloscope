"""tools/phase0.py's repeat mechanics, with no board and no scope.

The things a repeatability run depends on and cannot afford to get wrong
quietly: the reflash axis waits and discards before it records, a record
never mixes two clocks, a ladder rate reaches the metric, and a scope-free
metric of the shape `fn(board, args)` can be registered.
"""
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


def test_the_cli_takes_track_c_a_ladder_rc_and_keeps_run_zero_only_when_asked(monkeypatch):
    seen = {}
    monkeypatch.setattr(phase0, "take", lambda a: seen.setdefault("args", a) and "/dev/null")
    monkeypatch.setattr(phase0, "report", lambda path, metric, first=False: seen.update(first=first))
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
