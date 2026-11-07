"""The probes-on extra room, applied only where the bench declares it.

Board-free. `tests/baseline.json` holds the probes-off bounds, which are
a decision and are never edited to suit a probed bench; each
`<key>_probes_extra` is the room the probes were measured to need on top.
"""

import json
import os

import pytest

from helpers import GATE_ON, GATE_STRICT, apply_probe_state, gate_label, gate_note

HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture(scope="module")
def raw():
    with open(os.path.join(HERE, "baseline.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("declared", [None, {}, {"probes": "off"}])
def test_without_the_declaration_the_bounds_are_the_recorded_ones(raw, declared):
    got = apply_probe_state(raw, declared)
    for name in ("noise", "sinad"):
        for key, val in raw[name].items():
            if key.endswith("_probes_extra") or key == "_probes_extra_comment":
                assert key not in got[name]
            else:
                assert got[name][key] == val, (name, key)


def test_declared_on_adds_the_extra_to_ceilings_and_takes_it_from_floors(raw):
    got = apply_probe_state(raw, {"probes": "on"})
    n, s = raw["noise"], raw["sinad"]
    assert got["noise"]["rms_ceiling_lsb"] == pytest.approx(
        n["rms_ceiling_lsb"] + n["rms_ceiling_lsb_probes_extra"])
    assert got["sinad"]["sinad_db_min"] == pytest.approx(
        s["sinad_db_min"] - s["sinad_db_min_probes_extra"])
    assert got["sinad"]["enob_min"] < s["enob_min"]
    assert got["sinad"]["noise_floor_rms_lsb_max"] > s["noise_floor_rms_lsb_max"]
    assert got["sinad"]["thd_db_max"] > s["thd_db_max"]
    # What the probes did not move is not widened.
    assert got["noise"]["line_fraction_ceiling"] == n["line_fraction_ceiling"]
    assert (got["sinad"]["signal_rms_lsb_min"], got["sinad"]["signal_rms_lsb_max"]) == (
        s["signal_rms_lsb_min"], s["signal_rms_lsb_max"])


def test_the_input_is_not_modified(raw):
    before = json.dumps(raw, sort_keys=True)
    apply_probe_state(raw, {"probes": "on"})
    assert json.dumps(raw, sort_keys=True) == before


def test_each_section_says_which_gate_it_carries(raw):
    assert apply_probe_state(raw, {"probes": "on"})["noise"]["gate"] == GATE_ON
    assert apply_probe_state(raw, {})["noise"]["gate"] == GATE_STRICT
    assert apply_probe_state(raw, {"probes": "off"})["sinad"]["gate"] == GATE_STRICT
    assert "gate" not in apply_probe_state(raw, {})["dc_transfer"]


def test_the_header_label_agrees_with_what_is_applied(raw):
    for declared in ({}, {"probes": "off"}, {"probes": "on"}):
        assert (gate_label(declared)
                == apply_probe_state(raw, declared)["noise"]["gate"])


def test_a_failure_message_names_the_gate():
    assert "probes-off (strict) gate" in gate_note({"gate": GATE_STRICT})
    assert gate_note({}) == ""


def test_the_declaration_reaches_the_records(monkeypatch):
    import provenance
    for declared, want in (({"probes": "on"}, "on"), ({}, None)):
        monkeypatch.setattr(provenance, "bench", lambda d=declared: d)
        assert provenance._collect()["probes"] == want
