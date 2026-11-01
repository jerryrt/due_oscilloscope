"""`square_gate_once` and `square_bias_control`, board-free."""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "host"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import measure                                                   # noqa: E402
import square_shape as sq                                        # noqa: E402

KEYS = {"f_hz", "rise_ns", "fall_ns", "vpp_codes", "flat_hi", "flat_lo"}


class Board:
    def __init__(self, events):
        self.events = events

    def poll_console(self):
        pass

    def cmd(self, text):
        self.events.append(("cmd", text))

    def drain_console(self, t):
        return ""


def install(monkeypatch, events, vpps=(1000.0, 990.0), raise_on=None):
    runs = []

    def fake(board, *, points, dac_hz, amp, seconds=4.0, solo=False,
             ref_vpp=None):
        runs.append((points, dac_hz, amp, seconds))
        events.append(("run", len(runs), seconds))
        if raise_on == len(runs):
            raise RuntimeError("boom")
        vpp = vpps[min(len(runs), len(vpps)) - 1]
        f = sq.TC_HZ / (2 * points * round(
            sq.TC_HZ / (2 * points * 100_000 * len(runs) ** 2)))
        return {"f_hz": f, "rise_ns": 300.0 + len(runs), "fall_ns": 301.0,
                "vpp_codes": vpp, "flat_frac_high": 0.5,
                "flat_frac_low": 0.6, "edge_over_half": 0.1 * len(runs)}
    monkeypatch.setattr(sq, "square_shape", fake)
    monkeypatch.setattr(
        measure, "set_gen",
        lambda b, s, p, amp=None: events.append(("amp", amp)))
    return runs


def test_gate_keys_exact_and_reference_division(monkeypatch):
    ev = []
    install(monkeypatch, ev, vpps=(1000.0, 800.0))
    r = sq.square_gate_once(Board(ev))
    want = {k + "_" + s for k in KEYS for s in ("100k", "400k")}
    want |= {"vpp_frac_400k", "edge_over_half_400k"}
    assert set(r) == want
    assert r["vpp_frac_400k"] == pytest.approx(0.8)
    assert r["vpp_codes_100k"] == 1000.0 and r["vpp_codes_400k"] == 800.0


def test_gate_reports_the_actual_frequency_not_the_request(monkeypatch):
    ev = []
    runs = install(monkeypatch, ev)
    r = sq.square_gate_once(Board(ev))
    assert r["f_hz_100k"] != 100_000 and r["f_hz_400k"] != 400_000
    assert r["f_hz_100k"] == pytest.approx(
        sq.TC_HZ / (2 * runs[0][0] * round(
            sq.TC_HZ / (2 * runs[0][0] * 100_000))))
    assert [x[2] for x in runs] == [256, 256]


def test_gate_refuses_an_unreachable_plan(monkeypatch):
    ev = []
    install(monkeypatch, ev)
    monkeypatch.setattr(sq, "plan", lambda f, solo=False: None)
    with pytest.raises(SystemExit):
        sq.square_gate_once(Board(ev))


@pytest.mark.parametrize("which", [1, 2])
def test_gate_restores_amp_when_a_run_raises(monkeypatch, which):
    ev = []
    install(monkeypatch, ev, raise_on=which)
    with pytest.raises(RuntimeError):
        sq.square_gate_once(Board(ev))
    assert ev[-1] == ("amp", 256)


def test_control_order_and_result(monkeypatch):
    ev = []
    install(monkeypatch, ev, vpps=(1000.0, 957.0, 1000.0))
    r = sq.square_bias_control(Board(ev))
    cmds = [e[1] for e in ev if e[0] == "cmd"]
    assert cmds == ["=0,0I", "=2,1I"]
    i_restore = ev.index(("cmd", "=2,1I"))
    assert ev[:i_restore].count(("cmd", "=0,0I")) == 1
    runs_before = [e for e in ev[:i_restore] if e[0] == "run"]
    runs_after = [e for e in ev[i_restore:] if e[0] == "run"]
    assert len(runs_before) == 2 and len(runs_after) == 1
    assert ev.index(("cmd", "=0,0I")) < ev.index(runs_before[0])
    assert set(r) == {"rise_ns_biased", "flat_hi_biased", "vpp_frac_biased"}
    assert r["vpp_frac_biased"] == pytest.approx(0.957)


@pytest.mark.parametrize("which", [1, 2])
def test_control_restores_even_when_the_run_raises(monkeypatch, which):
    ev = []
    install(monkeypatch, ev, raise_on=which)
    with pytest.raises(RuntimeError):
        sq.square_bias_control(Board(ev))
    i = ev.index(("cmd", "=2,1I"))
    assert ev.index(("cmd", "=0,0I")) < i
    assert any(e[0] == "run" for e in ev[i:])
