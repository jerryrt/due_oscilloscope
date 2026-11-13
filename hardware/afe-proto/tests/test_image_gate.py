"""The image's own guards, checked from the HOST (they need docker, so the numpy tier leaves them out).

Each one is a control for something the in-image gate cannot say about itself:
a gate run in an image without ngspice must FAIL; docker's cap must kill an
over-allocating job with 137; the timeout must give 124; and the same
golden computed twice in the image must be byte-identical.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
RUN = REPO / "docker" / "pcb" / "run.sh"
KICAD = "10.0.8"
import json as _json
CFG = _json.loads((REPO / "docker" / "pcb" / "image-revisions.json").read_text())
PINNED = f"{CFG['registry']}@{CFG['digest']}"                      # what run.sh runs by default
CONTROL = f"pcb-tools:{CFG['kicad']}-r{CFG['current']}-no-ngspice"   # the gate's own control, built by the test
SUMMARY = re.compile(r"^capped: peak_rss_kb=(\S+) wall_s=(\S+) exit=(\d+) cap=(\S+) limit_s=(\d+)(?: image=(\S+))?(?: installed=(\S+))?$", re.M)

pytestmark = [pytest.mark.docker, pytest.mark.slow]


def have_image(tag):
    return shutil.which("docker") and subprocess.run(["docker", "image", "inspect", tag],
                                                     capture_output=True).returncode == 0


def run_in(image, *cmd, m="1G", t=120):
    import os
    env = {k: v for k, v in os.environ.items() if k != "DUE_PCB_IMAGE"}
    if image is not None:                       # None = the pinned default, exactly as a user runs it
        env["DUE_PCB_IMAGE"] = image
    r = subprocess.run(["bash", str(RUN), "-m", m, "-t", str(t), *cmd], capture_output=True, text=True,
                       env=env, timeout=t + 60)
    return r


@pytest.fixture(scope="module")
def main_image():
    # absence is handled by the `docker` probe in conftest: a skip by default, a failure under
    # --require-tool=docker, so a missing image is an error only where the image is required.
    # None means "no override": run.sh pulls and checks the pinned digest, the path a user takes.
    return None


def test_gate_fails_in_an_image_without_ngspice(main_image):
    if not have_image(CONTROL):
        # self-contained: build the control image from the same recipe (docker caches the shared layers)
        import os
        b = subprocess.run(["bash", str(REPO / "docker" / "pcb" / "build-image.sh")], capture_output=True, text=True,
                           env=dict(os.environ, DUE_PCB_WITHOUT_NGSPICE="1"), timeout=1800)
        assert b.returncode == 0 and have_image(CONTROL), b.stdout[-500:] + b.stderr[-500:]
    sel = ["docker/pcb/run-gate.sh", "-m", "ngspice and not jobcap and not slow"]   # the slow sim studies are 20+ min and prove nothing more here
    good = run_in(main_image, *sel, m="2G", t=300)
    assert good.returncode == 0 and re.search(r"\d+ passed", good.stdout), good.stdout[-800:]   # the control's control
    bad = run_in(CONTROL, *sel, m="2G", t=300)
    assert bad.returncode != 0, bad.stdout[-800:]
    assert "--require-tool given but needs ngspice on PATH" in bad.stdout
    assert "skipped" not in bad.stdout.splitlines()[-3:].__str__() or "failed" in bad.stdout


def test_the_container_cap_kills_with_137(main_image):
    r = run_in(main_image, "python3", "-c", "b = bytearray(600_000_000); print('ok')", m="200M", t=60)
    assert r.returncode == 137 and "ok" not in r.stdout, (r.returncode, r.stderr[-300:])
    assert int(SUMMARY.search(r.stderr).group(3)) == 137


def test_the_timeout_gives_124_and_is_bounded(main_image):
    r = run_in(main_image, "sleep", "60", m="200M", t=2)
    assert r.returncode == 124 and float(SUMMARY.search(r.stderr).group(2)) < 15


def test_the_summary_line_carries_peak_cap_and_image_id(main_image):
    r = run_in(main_image, "python3", "-c", "b = bytearray(150_000_000)", m="1G", t=60)
    m = SUMMARY.search(r.stderr)
    assert r.returncode == 0 and m and m.group(4) == "1G" and m.group(6) == CFG["digest"]
    assert 140_000 < int(m.group(1)) < 600_000                       # KB, the cgroup peak


def test_the_same_golden_twice_is_byte_identical_and_matches_the_committed_one(main_image):
    cmd = ["python3", "-I", "-c",
           "import sys; sys.path.insert(0, 'hardware/afe-proto/tests'); import netlib_snapshot as s; "
           "sys.stdout.write(s.v1_text() + '\\x00' + s.v2_text())"]
    a, b = run_in(main_image, *cmd), run_in(main_image, *cmd)
    assert a.returncode == 0 and a.stdout == b.stdout and len(a.stdout) > 5000
    gold = REPO / "hardware/afe-proto/tests/golden"
    assert a.stdout == (gold / "netlib_v1.txt").read_text() + "\x00" + (gold / "netlib_v2.txt").read_text()


def test_the_same_ngspice_run_twice_decodes_to_identical_arrays(main_image):
    """Raw FILES are not byte-identical: ngspice writes uninitialised memory into the imaginary
    half of the AC frequency column (80 bytes in this deck, nothing else differs). What is
    compared is what the reader hands back, which drops that half; a difference anywhere
    else would still show."""
    code = r"""
import sys, tempfile, hashlib
sys.path.insert(0, 'hardware/afe-proto')
from simtools import ngspice_run as nr
deck = "d\nV1 in 0 PULSE(0 1 0 1n 1n 5u 10u) AC 1\nR1 in out 1k\nC1 out 0 1n\n.tran 0.1u 20u\n.ac dec 5 1k 1meg\n.end\n"
hs = []
for k in range(2):
    d = tempfile.mkdtemp()
    r = nr.run(deck, save=['v(out)'], workdir=d, name='x', timeout=60)
    hs.append(hashlib.sha256(b''.join(p.data.tobytes() for p in r.plots().values())).hexdigest())
print(hs[0] == hs[1], hs[0])
"""
    r = run_in(main_image, "python3", "-I", "-c", code)
    assert r.returncode == 0 and r.stdout.startswith("True"), r.stdout + r.stderr[-500:]


def test_the_gate_run_twice_passes_twice(main_image):
    """The gate must leave the tree as it found it. The first version wrote __pycache__ into a
    fixture directory and the second run failed on the first one's leavings. This is about state leaking between runs, not about
    timing the full gate (28 min), so it runs the quick tier (-m "not slow", about 4.5 min) twice, each in a fresh container."""
    before = subprocess.run(["git", "status", "--porcelain", "--ignored", "hardware/afe-proto"], cwd=REPO,
                            capture_output=True, text=True).stdout
    sel = ["docker/pcb/run-gate.sh", "-m", "not slow"]
    for n in ("first", "second"):
        r = run_in(main_image, *sel, m="4G", t=1200)
        assert r.returncode == 0, f"{n} run: " + r.stdout[-600:] + r.stderr[-300:]
        assert "gate guard: fixtures and goldens unchanged" in r.stderr, f"{n} run: the guard did not report" + r.stderr[-300:]
    after = subprocess.run(["git", "status", "--porcelain", "--ignored", "hardware/afe-proto"], cwd=REPO,
                           capture_output=True, text=True).stdout
    new = set(after.splitlines()) - set(before.splitlines())
    assert not [l for l in new if "__pycache__" in l or ".pyc" in l], new


def test_the_installed_set_hash_is_stable_across_two_asks(main_image):
    ids = REPO / "docker" / "pcb" / "image-id.sh"
    a = subprocess.run(["bash", str(ids), "installed", PINNED], capture_output=True, text=True).stdout.strip()
    b = subprocess.run(["bash", str(ids), "installed", PINNED], capture_output=True, text=True).stdout.strip()
    assert re.fullmatch(r"[0-9a-f]{64}", a) and a == b


def _run_default(*cmd, digest=None, t=60):
    """run.sh with NO image override: the pinned-digest path."""
    import os
    env = {k: v for k, v in os.environ.items() if k != "DUE_PCB_IMAGE"}
    if digest:
        env["DUE_PCB_DIGEST"] = digest
    return subprocess.run(["bash", str(RUN), "-m", "1G", "-t", str(t), *cmd], capture_output=True, text=True,
                          env=env, timeout=t + 120)


def test_the_default_run_uses_the_pinned_digest_and_reports_it(main_image):
    import json
    cfg = json.loads((REPO / "docker" / "pcb" / "image-revisions.json").read_text())
    r = _run_default("python3", "-c", "print('hi')")
    m = SUMMARY.search(r.stderr)
    assert r.returncode == 0 and "hi" in r.stdout, r.stderr[-400:]
    assert m.group(6) == cfg["digest"] and m.group(7) == cfg["installed"], m.groups()


def test_a_digest_that_is_not_the_pinned_image_is_refused(main_image):
    r = _run_default("python3", "-c", "print('ran')", digest="sha256:" + "0" * 64)
    assert r.returncode == 2 and "ran" not in r.stdout, (r.returncode, r.stderr[-300:])


TOUCH = REPO / "hardware" / "afe-proto" / "tests" / "test_zz_touch_fixture.py"
TOUCH_SRC = '''
import pathlib

def test_touches_a_fixture():
    here = pathlib.Path(__file__).resolve().parent
    (here / "fixtures" / "zz-touched.txt").write_text("x")
'''


def _gate_with_a_test_that_touches_a_fixture(env_extra):
    import os
    TOUCH.write_text(TOUCH_SRC)
    try:
        env = {k: v for k, v in os.environ.items() if k != "DUE_PCB_IMAGE"} | env_extra
        return subprocess.run(["bash", str(RUN), "-m", "1G", "-t", "200", "docker/pcb/run-gate.sh",
                               "-k", "test_touches_a_fixture"], capture_output=True, text=True, env=env, timeout=400)
    finally:
        TOUCH.unlink(missing_ok=True)
        (REPO / "hardware/afe-proto/tests/fixtures/zz-touched.txt").unlink(missing_ok=True)


def test_a_test_that_writes_a_fixture_fails_the_gate_and_names_the_file(main_image):
    # opted out of the read-only mount (the default since r4), so the write succeeds and it is the guard that must catch it
    r = _gate_with_a_test_that_touches_a_fixture({"DUE_PCB_RO_FIXTURES": "0"})
    assert r.returncode == 3, (r.returncode, r.stdout[-300:], r.stderr[-300:])
    assert "new: hardware/afe-proto/tests/fixtures/zz-touched.txt" in r.stderr


def test_the_same_write_fails_at_the_writing_test_under_a_read_only_mount(main_image):
    r = _gate_with_a_test_that_touches_a_fixture({"DUE_PCB_RO_FIXTURES": "1"})
    assert r.returncode != 0 and ("Read-only file system" in r.stdout or "PermissionError" in r.stdout), r.stdout[-400:]
    assert "test_touches_a_fixture" in r.stdout


def test_the_gate_refuses_to_start_over_leftovers_of_an_earlier_run(main_image):
    stray = REPO / "hardware/afe-proto/tests/fixtures/zz-stray.kicad_prl"
    stray.write_text("x")
    try:
        r = run_in(main_image, "docker/pcb/run-gate.sh", "-k", "test_nothing_matches_this")
    finally:
        stray.unlink(missing_ok=True)
    assert r.returncode == 4 and "leftover: hardware/afe-proto/tests/fixtures/zz-stray.kicad_prl" in r.stderr, (r.returncode, r.stderr[-300:])


THREAD_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")


@pytest.mark.parametrize("cpus, want", [("2", "2"), ("3", "3"), ("1.5", "1"), ("0.5", "1")])
def test_the_container_sees_thread_counts_equal_to_floor_of_the_cpu_quota(main_image, cpus, want):
    import os
    code = "import os; print(' '.join(os.environ.get(v, 'unset') for v in %r))" % (THREAD_VARS,)
    env = {k: v for k, v in os.environ.items() if k != "DUE_PCB_IMAGE"}
    for v in THREAD_VARS:
        env.pop(v, None)
    r = subprocess.run(["bash", str(RUN), "-m", "1G", "-t", "60", "-c", cpus, "python3", "-c", code],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0 and r.stdout.split() == [want] * 4, (cpus, r.stdout, r.stderr[-200:])


def test_an_image_override_is_labelled_unpinned_in_the_summary_line(main_image):
    r = run_in(PINNED, "python3", "-c", "print('x')")          # an explicit override, even of the pinned ref itself
    m = SUMMARY.search(r.stderr)
    assert r.returncode == 0 and m.group(6) == "UNPINNED:" + PINNED, m.groups()


def test_bench_refuses_to_write_budgets_from_an_unpinned_run(main_image):
    import hashlib
    files = [REPO / "hardware/afe-proto/tests" / n for n in ("bench-results.json", "bench-results.md", "budgets.json")]
    before = [hashlib.sha256(f.read_bytes()).hexdigest() for f in files]
    r = run_in(PINNED, "python3", "hardware/afe-proto/tests/bench.py", "--runs", "1", "--only", "ngspice-rc", "--write", t=120)
    assert r.returncode != 0 and "not a pinned digest" in r.stderr + r.stdout, (r.returncode, r.stderr[-300:])
    assert [hashlib.sha256(f.read_bytes()).hexdigest() for f in files] == before          # and wrote nothing


def test_the_ro_mount_is_the_default_and_due_pcb_ro_fixtures_0_opts_out(main_image):
    fx = REPO / "hardware/afe-proto/tests/fixtures/zz-ro-probe.txt"
    try:
        code = "open('hardware/afe-proto/tests/fixtures/zz-ro-probe.txt','w').write('x'); print('WROTE')"
        default = run_in(None, "python3", "-c", code)
        assert "WROTE" not in default.stdout and default.returncode != 0, default.stdout + default.stderr[-200:]
        import os
        env = {k: v for k, v in os.environ.items() if k != "DUE_PCB_IMAGE"} | {"DUE_PCB_RO_FIXTURES": "0"}
        out = subprocess.run(["bash", str(RUN), "-m", "1G", "-t", "60", "python3", "-c", code], capture_output=True,
                             text=True, env=env, timeout=120)
        assert "WROTE" in out.stdout, out.stdout + out.stderr[-200:]
    finally:
        fx.unlink(missing_ok=True)


def test_two_gate_runs_do_not_share_a_guard_file():
    src = (REPO / "docker/pcb/run-gate.sh").read_text()
    assert "mktemp" in src and "/tmp/gate-guard.txt" not in src


def test_the_docker_probe_looks_for_the_pinned_digest_not_a_local_tag(pcb_image_ref):
    """A bench that only pulled by digest has no pcb-tools:<ver> tag; the probe must use image-revisions.json
    exactly as run.sh does."""
    assert pcb_image_ref == PINNED


CONTROL_NO_ROUTER = f"pcb-tools:{CFG['kicad']}-r{CFG['current']}-no-freerouting"


def test_the_gate_fails_in_an_image_without_the_router(main_image):
    """The control for Freerouting: a missing jar is an error, never a skip. Built from the same recipe with
    WITH_FREEROUTING=0 (docker shares every layer before the router's)."""
    import os
    if not have_image(CONTROL_NO_ROUTER):
        b = subprocess.run(["bash", str(REPO / "docker" / "pcb" / "build-image.sh")], capture_output=True, text=True,
                           env=dict(os.environ, DUE_PCB_WITHOUT_FREEROUTING="1"), timeout=1800)
        assert b.returncode == 0 and have_image(CONTROL_NO_ROUTER), b.stdout[-500:] + b.stderr[-500:]
    sel = ["docker/pcb/run-gate.sh", "-k", "test_the_round_trip_leaves_no_unconnected_items"]
    bad = run_in(CONTROL_NO_ROUTER, *sel)
    assert bad.returncode != 0, bad.stdout[-600:]
    assert "--require-tool given but needs Freerouting" in bad.stdout


def test_a_gate_run_without_the_vendor_models_fails_rather_than_skips(main_image, tmp_path):
    """The gate requires the vendor models (--require-tool=vendor). An empty directory is mounted over models/, so
    the run sees none, and a vendor-marked test must FAIL the run with the reason, not skip."""
    import os
    empty = tmp_path / "no-models"
    empty.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "DUE_PCB_IMAGE"}
    env["DUE_PCB_EXTRA_VOLUMES"] = f"{empty}:/work/hardware/afe-proto/models:ro"
    r = subprocess.run(["bash", str(RUN), "-m", "1G", "-t", "200", "docker/pcb/run-gate.sh", "-k",
                        "test_v1_scope_hz_reproduces_its_golden"], capture_output=True, text=True, env=env, timeout=400)
    assert r.returncode != 0, r.stdout[-400:]
    assert "--require-tool given but needs the vendor SPICE models" in r.stdout, r.stdout[-600:]
    assert " skipped" not in r.stdout.splitlines()[-4].replace("deselected", "") or "failed" in r.stdout


def test_the_host_gate_script_fetches_before_it_runs_and_requires_the_models():
    src = (REPO / "docker" / "pcb" / "gate-host.sh").read_text()
    assert src.index("fetch_models.py") < src.index("docker/pcb/run-gate.sh"), "the fetch must come first"
    # the host tier: this file's own tests run on the host, after the container gate, under --require-tool=docker
    assert src.index("docker/pcb/run-gate.sh") < src.index("test_image_gate.py"), "the host tier follows the container gate"
    assert "hardware/afe-proto/tests/test_image_gate.py --require-tool=docker -q)" in src, "the host tier must fail, not skip, without docker"
    gate = (REPO / "docker" / "pcb" / "run-gate.sh").read_text()
    for tool in ("pcbnew", "ngspice", "freerouting", "networkx", "vendor"):
        assert tool in gate.rsplit("--require-tool=", 1)[1].split()[0], tool
