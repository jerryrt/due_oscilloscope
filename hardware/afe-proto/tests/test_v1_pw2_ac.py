"""v1's pw2_ac driver (v1/sim/pw2_ac_v1.py): numpy only, no ngspice (the transient is v2's stored window, not re-run).
Includes the deliberate-break checks: a distance changed by 10 mm must change the figure, and v2's own geometry through the
driver must give v2's own stored results."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

AFE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("pw2_ac_v1", AFE / "v1" / "sim" / "pw2_ac_v1.py")
drv = importlib.util.module_from_spec(_spec)
sys.modules["pw2_ac_v1"] = drv
_spec.loader.exec_module(drv)


@pytest.fixture(scope="module")
def env():
    pa = drv.load_v2()
    tr = pa.load_window(drv.V2DIR / "results" / "transient_ideal_window.npz")
    return pa, tr


def test_distances_are_the_power_agents_table():
    d = drv.V1_DIST_MM
    for r, v in {"C405": 10.4, "C406": 12.5, "C409": 6.2, "C410": 8.3, "C407": 5.6, "C408": 5.8, "C403": 2.8, "C404": 5.1, "C402": 2.9}.items():
        assert d[r] == pytest.approx(v, abs=0.06), r
    assert drv.V1_C401_100N_MM == pytest.approx(7.9, abs=0.06)


def test_v2_geometry_through_the_driver_reproduces_v2_results(env):
    pa, tr = env
    ref = json.loads((drv.V2DIR / "results" / "pw2_ac_results.json").read_text())["worst_datasheet_mv"]["asbuilt"]
    got = pa.estimate(tr)["worst_datasheet_mv"]["asbuilt"]
    for n in ref:
        assert got[n] == pytest.approx(ref[n], rel=1e-9), n


def test_a_distance_change_of_10_mm_changes_the_figure_and_the_tables_are_restored(env):
    pa, tr = env
    before = (dict(pa.DIST_MM), dict(pa.WIDTH_MM), dict(pa.VIA_COUNT))
    _, base = drv.run_set(pa, tr, drv.V1_DIST_MM, drv.V1_WIDTH_MM, drv.V1_VIA)
    far = dict(drv.V1_DIST_MM)
    far["C403"] += 10.0
    _, moved = drv.run_set(pa, tr, far, drv.V1_WIDTH_MM, drv.V1_VIA)
    assert moved["worst_1.7_2.3MHz_pkpk_mv"]["vin"] > 1.3 * base["worst_1.7_2.3MHz_pkpk_mv"]["vin"]
    assert (dict(pa.DIST_MM), dict(pa.WIDTH_MM), dict(pa.VIA_COUNT)) == before


def test_a_distance_acts_on_its_own_rail_only(env):
    pa, tr = env
    _, base = drv.run_set(pa, tr, drv.V1_DIST_MM, drv.V1_WIDTH_MM, drv.V1_VIA)
    far = dict(drv.V1_DIST_MM)
    far["C405"] += 10.0                                     # CPOUT's first capacitor
    _, moved = drv.run_set(pa, tr, far, drv.V1_WIDTH_MM, drv.V1_VIA)
    b, m = base["worst_1.7_2.3MHz_pkpk_mv"], moved["worst_1.7_2.3MHz_pkpk_mv"]
    assert m["cpout"] > 1.3 * b["cpout"]
    for n in ("vin", "outp", "outn"):
        assert m[n] == pytest.approx(b[n], rel=1e-9), n


def test_the_100n_case_is_cleaned_up_and_lowers_vin(env):
    pa, tr = env
    z = pa.z_node
    _, a = drv.run_set(pa, tr, drv.V1_DIST_MM, drv.V1_WIDTH_MM, drv.V1_VIA)
    _, b = drv.run_set(pa, tr, drv.V1_DIST_MM, drv.V1_WIDTH_MM, drv.V1_VIA, c100_mm=drv.V1_C401_100N_MM)
    assert pa.z_node is z
    assert b["worst_1.7_2.3MHz_pkpk_mv"]["vin"] < a["worst_1.7_2.3MHz_pkpk_mv"]["vin"]
    assert b["worst_1.7_2.3MHz_pkpk_mv"]["outp"] == pytest.approx(a["worst_1.7_2.3MHz_pkpk_mv"]["outp"], rel=1e-9)


def test_stored_results_match_a_fresh_run(env):
    pa, tr = env
    stored = json.loads(drv.OUT.read_text())["sets"]["v1"]["vin_bank_only"]["worst_1.7_2.3MHz_pkpk_mv"]
    _, fresh = drv.run_set(pa, tr, drv.V1_DIST_MM, drv.V1_WIDTH_MM, drv.V1_VIA)
    for n, v in stored.items():
        assert fresh["worst_1.7_2.3MHz_pkpk_mv"][n] == pytest.approx(v, rel=1e-9), n
