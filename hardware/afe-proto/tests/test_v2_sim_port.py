"""The ported v2 AWG and scope studies reproduce what the old code produced, number for number.

The goldens are tests/golden/v2-awg-scope-924e035 (STAMP.json says how they were taken: the OLD scripts, frozen in
tests/fixtures/v2-awg-scope-924e035, run twice in the PCB image and compared byte for byte). A ported study is kept only
while it reproduces them; every difference is explained in the test that allows it:

  * results.json header (awg) and meta.json (scope): the path of the op-amp macro and the name of the behavioural model,
    which the old code wrote as machine paths and the port writes as names. The ngspice version and every hash are compared.
  * awg.cir, scope_v2.cir: the `.include` line, a relative path in the old code and the macro's bare name in the port.
  * report.md: the two places that quote those paths.
  Nothing else differs, at rtol 0 (the tolerance asserted is 1e-9, the one the v1 port states).

Each arm of TestMutationArms breaks one computation in a copy of the ported code and shows the comparison fails, so a green
equivalence cannot be a comparison that sees nothing. A test that did not run is not a pass: these need ngspice and the
fetched vendor models and FAIL under --require-tool=vendor without them.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from simtools.compare import compare_trees, compare_values

pytestmark = [pytest.mark.vendor, pytest.mark.ngspice, pytest.mark.slow]

AFE = Path(__file__).resolve().parents[1]
GOLD = Path(__file__).resolve().parent / "golden" / "v2-awg-scope-924e035"
RTOL = 1e-9
SECTIONS = "netlist cscan dc ac bw noise d17 tran stab beh prot xtalk static mc guards".split()
OLD_INCLUDE = "../../../../whatif/tph2502/models/TPH2501_ngspice.mdl"
OLD_SCOPE_INCLUDE = "../../../whatif/tph2502/models/TPH2501_ngspice.mdl"


def _run(argv, cwd, timeout=900, check=True):
    r = subprocess.run([sys.executable, "-I", "-B", *map(str, argv)], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    if check:
        assert r.returncode == 0, f"{argv}: {r.stdout[-600:]}{r.stderr[-600:]}"
        return r.stdout
    return r


def mutant_tree(tmp, edits=()):
    """A copy of the ported code that finds simtools and the models like the real one: tmp/afe-proto with v2/sim/{awg,scope},
    simtools and the jlc table copied and the model folders linked. edits: (relative file, old, new); old must occur."""
    root = tmp / "afe-proto"
    for part in ("v2/sim/awg", "v2/sim/scope", "simtools"):
        shutil.copytree(AFE / part, root / part, ignore=shutil.ignore_patterns("__pycache__", "netlists*", "work*", "raw*", "results*", "*.log"))
    shutil.copy(AFE / "v2" / "jlc-basic.csv", root / "v2" / "jlc-basic.csv")
    for m in ("models", "models-open"):
        (root / m).symlink_to(AFE / m)
    for rel, old, new in edits:
        p = root / rel
        t = p.read_text()
        assert t.count(old) == 1, f"{rel}: {old!r} occurs {t.count(old)} times"
        p.write_text(t.replace(old, new))
    return root


# ------------------------------------------------------------------------------------------------ the AWG study
# The golden is the OLD study at its old guaranteed range, -1.5 V to +1.63 V. The owner's ruling of 2026-11-13 made the range +-1.6 V (design.OUT_LO,
# OUT_HI, and four texts in run.py that name the range or the broken-on-purpose level), which changes the numbers on purpose and is not a porting
# difference. The equivalence is therefore taken with the range put back to the old one in a copy of the code: these edits are the whole of the
# difference between the golden and the tree (the filter resistor Rvr, the divider arm R6 and two guard bodies, below), and a port that drifts anywhere else still fails.
OLD_RANGE_EDITS = [
    ("v2/sim/awg/design.py", "OUT_LO, OUT_HI = -1.5, 1.5 ", "OUT_LO, OUT_HI = -1.5, 1.63 "),
    # the filter resistor Rvr is 150 ohm and the divider's upper arm R6 (Rbin) 3.0 kohm now (SC-9 through the reference at the scope's +-5 V,
    # and the AC top end that the larger Rvr raises); the golden has 100 ohm and 2.7 kohm
    ("v2/sim/awg/design.py", "Rg2=3000.0, Rvr=150.0, Rbin=3000.0,", "Rg2=3000.0, Rvr=100.0, Rbin=2700.0,"),
    ("v2/sim/awg/params.py", "Rvr=150.0, Cvr=14e-6", "Rvr=100.0, Cvr=14e-6"),
    ("v2/sim/awg/params.py", "Rbin=3000.0,", "Rbin=2700.0,"),
    ("v2/sim/awg/run.py", "'commanding +1.6 V (the next level above the guarantee, over what the window allows) must fail the position-aware 92 % at the hard corners; the guaranteed +1.5 V passes', g_range, dict(th=1.6), dict(th=design.OUT_HI))",
     "'commanding +1.71 V (the earlier guarantee, before the offset filter) must fail the position-aware 92 %; the guaranteed +1.63 V passes', g_range, dict(th=1.71), dict(th=1.63))"),
    ("v2/sim/awg/run.py", """    def g_sc9b(rs):
        Rf_, Rg2_ = rs
        m = ref_move((design.OUT_HI - design.OUT_LO) / (1 + Rf_ / Rg2_), Rg2_, V['Rvr'], D['Cvr'])[0]
        return m * SCOPE_REF_TO_INPUT / LSB_IN <= 2.0
    guard('reference coupling, resistors', 'the filter-alone resistor set (Rf 470, Rg2 390 ohm, the small values of option A) must fail SC-9; Rf = Rg2 = 3 kohm passes', g_sc9b, dict(rs=(470.0, 390.0)), dict(rs=(V['Rf'], V['Rg2'])))
""", """    def g_sc9b(Rg2):
        m = ref_move((design.OUT_HI - design.OUT_LO) / (1 + V['Rf'] / Rg2), Rg2, V['Rvr'], D['Cvr'])[0]
        return m * SCOPE_REF_TO_INPUT / LSB_IN <= 2.0
    guard('reference coupling, resistors', 'the filter-alone 390 ohm Rg2 must fail SC-9; 3 kohm passes', g_sc9b, dict(Rg2=390.0), dict(Rg2=V['Rg2']))
"""),
    ("v2/sim/awg/run.py", "'a negative rail that does not reach the commanded bottom into 50 ohm (-1.5 V: clips at -1.4 V) must fail",
     "'a negative rail that does not reach -1.5 V into 50 ohm (-1.5 V: clips at -1.4 V) must fail"),
    ("v2/sim/awg/run.py", "the lowest commanded bottom / window", "the lowest commanded -1.5 V / window"),
]


def run_awg(root, out, work, check=True):
    return _run([root / "v2/sim/awg/run.py", "--out", out, "--work", work], cwd=root / "v2/sim/awg", check=check)


def awg_diffs(out, golden=GOLD / "awg"):
    new = json.loads((out / "raw" / "results.json").read_text())
    old = json.loads((golden / "results.json").read_text())
    diffs = []
    assert new["header"]["vendor"].startswith("TPH2501_ngspice.mdl")          # a name, not a machine path
    assert new["header"]["ngspice"] == old["header"]["ngspice"] and new["header"]["vendor_sha"] == old["header"]["vendor_sha"]
    new["header"].pop("vendor"), old["header"].pop("vendor")
    diffs += compare_values(old, new, rtol=RTOL)
    cir_old = (golden / "awg.cir").read_text().replace(OLD_INCLUDE, "TPH2501_ngspice.mdl")
    if (out / "awg.cir").read_text() != cir_old:
        diffs.append(("awg.cir", "differs", None))
    for f in ("parts.csv", "report_table.md"):
        if (out / f).read_bytes() != (golden / f).read_bytes():
            diffs.append((f, "differs", None))
    return diffs


@pytest.fixture(scope="module")
def awg_run(tmp_path_factory):
    d = tmp_path_factory.mktemp("awg")
    root = mutant_tree(d / "tree", OLD_RANGE_EDITS)
    stdout = run_awg(root, d / "out", d / "work")
    return d / "out", stdout


def test_awg_results_reproduce_the_golden(awg_run):
    out, _ = awg_run
    assert awg_diffs(out) == []


def test_awg_prints_what_the_old_code_printed(awg_run):
    _, stdout = awg_run
    old = (GOLD / "awg" / "stdout.txt").read_text()
    assert old.rstrip().endswith("exit=0")
    assert stdout.rstrip() == old.rstrip().rsplit("\n", 1)[0].rstrip()
    assert stdout.count("\nPASS") + stdout.count("\nINFO") + stdout.count("\nFAIL") > 80


# ----------------------------------------------------------------------------------------------- the scope study
def run_scope(root, out, work, sections=SECTIONS):
    """one process per section, as the old golden was taken; returns the concatenated stdout"""
    text = ""
    for s in sections:
        text += _run([root / "v2/sim/scope/run.py", "--out", out, "--work", Path(work) / s, s], cwd=root / "v2/sim/scope")
    return text


def scope_diffs(out, golden=GOLD / "scope", sections=None):
    """differences between the ported results and the golden's, for the result files the run wrote"""
    new = Path(out) / "results"
    names = sorted(p.name for p in new.glob("*.json"))
    diffs = []
    gold_dir = Path(out) / "_gold"
    shutil.rmtree(gold_dir, ignore_errors=True)
    gold_dir.mkdir()
    for n in names:
        if n != "meta.json":
            shutil.copy(golden / "results" / n, gold_dir / n)
    # the golden side holds exactly the files this run wrote (meta.json apart), so none is "missing"; a run that wrote none is an error
    assert [n for n in names if n != "meta.json"], "the run wrote no result file: nothing was compared"
    return compare_trees(gold_dir, new, rtol=RTOL)


def scope_golden_ac():
    return json.loads((GOLD / "scope" / "results" / "ac.json").read_text())


def meta_check(out):
    new = json.loads((Path(out) / "results" / "meta.json").read_text())
    old = json.loads((GOLD / "scope" / "results" / "meta.json").read_text())
    assert new["ngspice"] == old["ngspice"] and new["model_sha256"] == old["model_sha256"] and new["beh_lib_sha256"] == old["beh_lib_sha256"]
    assert new["model"] == "TPH2501_ngspice.mdl (simtools.vendor)" and new["beh_lib"] == "models-open/tph2502-beh/tph2502_beh.lib"


@pytest.fixture(scope="module")
def scope_run(tmp_path_factory):
    d = tmp_path_factory.mktemp("scope")
    stdout = run_scope(AFE, d / "out", d / "work")
    _run([AFE / "v2/sim/scope/report.py", d / "out"], cwd=AFE / "v2/sim/scope")
    return d / "out", stdout


def test_scope_results_reproduce_the_golden(scope_run):
    out, _ = scope_run
    assert sorted(p.name for p in (out / "results").glob("*.json")) == sorted(p.name for p in (GOLD / "scope" / "results").glob("*.json"))
    assert scope_diffs(out) == []
    meta_check(out)


def test_scope_report_and_netlist_reproduce_the_golden(scope_run):
    out, stdout = scope_run
    old = (GOLD / "scope" / "report.md").read_text()
    old = old.replace(f"`{OLD_SCOPE_INCLUDE}`", "`TPH2501_ngspice.mdl (simtools.vendor)`")
    old = old.replace("`beh/tph2502_beh.lib (whatif/tph2502, read-only)`", "`models-open/tph2502-beh/tph2502_beh.lib`")
    old = old.replace(".include " + OLD_SCOPE_INCLUDE, ".include TPH2501_ngspice.mdl")
    assert (out / "report.md").read_text() == old
    cir = (GOLD / "scope" / "scope_v2.cir").read_text().replace(OLD_SCOPE_INCLUDE, "TPH2501_ngspice.mdl")
    assert (out / "scope_v2.cir").read_text() == cir
    assert [l for l in stdout.splitlines() if l.startswith("==")] == [f"== {s}" for s in SECTIONS]


def test_the_new_report_builder_on_the_golden_results_is_the_golden_report(tmp_path):
    """report.py alone: same code path with the golden results as input, so no simulation and no text substitution"""
    shutil.copytree(GOLD / "scope" / "results", tmp_path / "results")
    _run([AFE / "v2/sim/scope/report.py", tmp_path], cwd=AFE / "v2/sim/scope")
    assert (tmp_path / "report.md").read_text() == (GOLD / "scope" / "report.md").read_text()


# --------------------------------------------------------------------------------- the old code still makes the goldens
@pytest.mark.parametrize("tool,files", [("awg", ["results.json", "awg.cir", "parts.csv", "report_table.md", "stdout.txt"]),
                                         ("scope", ["scope_v2.cir", "report.md", "stdout.txt"])])
def test_the_frozen_old_study_still_makes_its_golden(tmp_path, tool, files):
    """tests/golden/.../run_old.sh runs the frozen fixture (the old scripts, deleted from the tree) in a throw-away copy: what it
    writes is the golden, byte for byte. This is what lets the equivalence be re-run after the old code is gone."""
    r = subprocess.run(["bash", str(GOLD / "run_old.sh"), tool, str(tmp_path)], capture_output=True, text=True, timeout=900,
                       env=dict(os.environ, AFE_ROOT=str(AFE)))
    assert r.returncode == 0, r.stdout[-500:] + r.stderr[-500:]
    for f in files:
        assert (tmp_path / f).read_bytes() == (GOLD / tool / f).read_bytes(), f
    if tool == "scope":
        names = sorted(p.name for p in (GOLD / tool / "results").glob("*.json"))
        assert names and [p.name for p in sorted((tmp_path / "results").glob("*.json"))] == names
        for n in names:
            assert (tmp_path / "results" / n).read_bytes() == (GOLD / tool / "results" / n).read_bytes(), n


# --------------------------------------------------------------------------------------------- no machine in the code
BAD = re.compile(r"/home/|due_oscilloscope|ThreadPool|ProcessPool|multiprocessing|concurrent\.futures|subprocess\.run\(\s*\[\s*['\"]ngspice['\"]\s*,\s*['\"]-b")


def machine_in(text):
    return BAD.findall(text)


def test_the_ported_code_names_no_machine_pool_or_raw_ngspice():
    files = [*sorted((AFE / "v2/sim/awg").glob("*.py")), *sorted((AFE / "v2/sim/scope").glob("*.py")), AFE / "simtools" / "vendor.py"]
    assert len(files) >= 9
    for f in files:
        assert machine_in(f.read_text()) == [], f


def test_the_machine_guard_can_fail():
    for bad in ("p = '/home/jerry/x'", "from concurrent.futures import ThreadPoolExecutor", "subprocess.run(['ngspice', '-b', p])",
                "ngspice -v is fine but WHATIF = '../due_oscilloscope/whatif'"):
        assert machine_in(bad), bad
    assert machine_in("subprocess.run(['ngspice', '-v'], capture_output=True)") == []


# ------------------------------------------------------------------------------------------------------ mutation arms
AWG_ARMS = {
    "rail corner (params.RAILS weak negative rail)": ("v2/sim/awg/params.py", "'weak': (3.2205, -1.9549)", "'weak': (3.2205, -1.9)"),
    "design values (params.D Rf)": ("v2/sim/awg/params.py", "D = dict(Rf=3000.0,", "D = dict(Rf=3300.0,"),
    "hard-corner stack (design.corner_stats guaranteed top)": ("v2/sim/awg/design.py", "oh - 0.04 * sp)       # highest", "oh - 0.05 * sp)       # highest"),
    "Monte Carlo draw (design.dc_mc divider ratio)": ("v2/sim/awg/design.py", "kin = Rbpl / (Rbin + Rbpl)\n    Gs = Gs0 * kin", "kin = Rbpl / (Rbin + Rbpl) * 1.01\n    Gs = Gs0 * kin"),
    "netlist builder (Rbpl in the divider)": ("v2/sim/awg/netlist.py", "Rbpl bin 0 {q['Rbpl']}", "Rbpl bin 0 {q['Rbpl'] * 1.1}"),
    "closed-form map (run.analytic_out offset sign)": ("v2/sim/awg/run.py", "- p['Rf'] / Rg2 * vrail", "+ p['Rf'] / Rg2 * vrail"),
    "noise integral (netlist.integ trapezoid)": ("v2/sim/awg/netlist.py", "np.sum(0.5 * (yy[1:] + yy[:-1])", "np.sum(0.6 * (yy[1:] + yy[:-1])"),
}


class TestMutationArms:
    def test_the_control_arm_a_copy_with_no_edit_reproduces(self, tmp_path):
        """without this a failing mutant could be a broken copy, not a broken computation"""
        root = mutant_tree(tmp_path, OLD_RANGE_EDITS)
        run_awg(root, tmp_path / "out", tmp_path / "work")
        assert awg_diffs(tmp_path / "out") == []

    @pytest.mark.parametrize("arm", list(AWG_ARMS))
    def test_awg_arm(self, tmp_path, arm):
        root = mutant_tree(tmp_path, [*OLD_RANGE_EDITS, AWG_ARMS[arm]])
        r = run_awg(root, tmp_path / "out", tmp_path / "work", check=False)
        # noticed = the study's own guards refuse to run on the broken code (exit 1, 'does not discriminate'), or its numbers differ
        noticed = r.returncode != 0 and "Traceback" in r.stderr or (r.returncode == 0 and awg_diffs(tmp_path / "out") != [])
        assert noticed, f"the equivalence did not notice: {arm}"

    SCOPE_ARMS = {
        "closed-form network (run.net offset)": ([("v2/sim/scope/run.py", "voff = vr * rp / r3", "voff = vr * rp / r2")], "dc mc".split()),
        "design values (netlib.P0 R1)": ([("v2/sim/scope/netlib.py", "R1=(510e3, 30e3)", "R1=(510e3, 33e3)")], "dc ac".split()),
        "netlist builder (netlib.chan Riso)": ([("v2/sim/scope/netlib.py", "{k}pin {p['Riso']:.6g}", "{k}pin {p['Riso'] * 2:.6g}")], "ac bw".split()),
        "ADC acquisition window (run.T_TRACK)": ([("v2/sim/scope/run.py", "T_TRACK = 15 / 22.5e6", "T_TRACK = 16 / 22.5e6")], ["tran"]),
    }

    @pytest.mark.parametrize("arm", list(SCOPE_ARMS))
    def test_scope_arm(self, tmp_path, arm):
        edits, sections = self.SCOPE_ARMS[arm]
        root = mutant_tree(tmp_path, edits)
        run_scope(root, tmp_path / "out", tmp_path / "work", sections)
        assert scope_diffs(tmp_path / "out") != [], f"the equivalence did not notice: {arm}"

    def test_scope_control_arm_a_copy_with_no_edit_reproduces(self, tmp_path):
        root = mutant_tree(tmp_path)
        run_scope(root, tmp_path / "out", tmp_path / "work", ["cscan", "dc", "ac", "bw", "static", "mc"])
        assert scope_diffs(tmp_path / "out") == []

    def test_set_overrides_a_parameter_records_it_and_refuses_an_unknown_one(self, tmp_path):
        """the sensitivity cases (--set Cn_par=...) move the answer, say so in meta.json, and a typo is an error, not a baseline run"""
        run_scope(AFE, tmp_path / "base", tmp_path / "w0", ["ac"])
        _run([AFE / "v2/sim/scope/run.py", "--out", tmp_path / "sens", "--work", tmp_path / "w1", "--set", "Cn_par=4.31e-12", "ac"], cwd=AFE / "v2/sim/scope")
        base, sens = (json.loads((tmp_path / d / "results" / "ac.json").read_text()) for d in ("base", "sens"))
        assert sens["shelf_pct"] != base["shelf_pct"] and abs(base["shelf_pct"] - scope_golden_ac()["shelf_pct"]) < 1e-9
        assert json.loads((tmp_path / "sens" / "results" / "meta.json").read_text())["overrides"] == {"Cn_par": 4.31e-12}
        r = _run([AFE / "v2/sim/scope/run.py", "--out", tmp_path / "bad", "--work", tmp_path / "w2", "--set", "Cn_parr=1e-12", "ac"],
                 cwd=AFE / "v2/sim/scope", check=False)
        assert r.returncode != 0 and "not a scalar parameter" in r.stderr

    def test_report_arm(self, tmp_path):
        root = mutant_tree(tmp_path, [("v2/sim/scope/report.py", "by {10 - e12:.1f} mA at -12 V**: thin", "by {11 - e12:.1f} mA at -12 V**: thin")])
        shutil.copytree(GOLD / "scope" / "results", tmp_path / "res" / "results")
        _run([root / "v2/sim/scope/report.py", tmp_path / "res"], cwd=root / "v2/sim/scope")
        assert (tmp_path / "res" / "report.md").read_text() != (GOLD / "scope" / "report.md").read_text()

    def test_vendor_derivation_arm(self):
        """a derivation that did not remove the tc1 (or removed more) is refused by its hash, not run"""
        from simtools import vendor
        assert vendor.derive_tph2501("R1 a b 1k tc1=0.001\n") == "R1 a b 1k\n"
        src = vendor.TPH2501_SRC.read_bytes()
        assert vendor.hashlib.sha256(vendor.derive_tph2501(src.decode("latin-1")).encode("latin-1")).hexdigest() == vendor.TPH2501_DERIVED_SHA
        assert vendor.hashlib.sha256(src).hexdigest() != vendor.TPH2501_DERIVED_SHA          # the raw file would have been refused
