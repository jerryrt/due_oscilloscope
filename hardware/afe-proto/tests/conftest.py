"""Markers, tool probes and the guard against a skip scoring as a pass.

Tiers (see docs/testing.md for the convention they follow):

    numpy tier   -m "not pcbnew and not ngspice and not docker"   needs numpy only; the gate
    ngspice      -m ngspice                        needs ngspice on PATH
    pcbnew       -m pcbnew                         needs KiCad 10.x pcbnew

A marked test whose tool is missing SKIPS by default, and under
--require-tool FAILS. A skip scores as a pass in any harness that greps
for failures, so a bench that means to run the tool tier passes the flag.
"""
import os
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))


def pytest_addoption(parser):
    parser.addoption("--require-tool", nargs="?", const="pcbnew,ngspice", default="",   # bare flag: the two in-image tools; add docker for the host gate
                     metavar="TOOLS",
                     help="comma list of tools (pcbnew,ngspice,docker,vendor,network,freerouting,networkx) whose marked tests FAIL, not skip, "
                          "when the tool is missing; bare flag means both. Write it "
                          "--require-tool=pcbnew or --require-tool pcbnew")


@lru_cache(maxsize=None)
def ngspice_version():
    exe = shutil.which(os.environ.get("DUE_NGSPICE", "ngspice"))
    if not exe:
        return None
    r = subprocess.run([exe, "-v"], capture_output=True, text=True, timeout=30)
    m = re.search(r"ngspice-(\d+(?:\.\d+)*)", r.stdout + r.stderr)
    return m.group(1) if m else None


@lru_cache(maxsize=None)
def pcbnew_version():
    """KiCad version as pcbnew reports it, probed in a child so an assert
    in a mismatched build cannot take the test process with it."""
    r = subprocess.run([sys.executable, "-c", "import pcbnew; print(pcbnew.Version())"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return None
    m = re.search(r"\d+\.\d+\.\d+", r.stdout)
    return m.group(0) if m else None


def tool_versions():
    """Recorded with every golden and bench row: a point release can move a
    DRC or a netlist, and that must not read as a tool regression."""
    return {"ngspice": ngspice_version(), "kicad": pcbnew_version(),
            "python": ".".join(map(str, sys.version_info[:3]))}


@lru_cache(maxsize=None)
def pcb_image_tag():
    """The pinned image reference (registry@digest from image-revisions.json, the same source run.sh uses),
    if docker has it, pulling it when it is absent. The `docker` marker's tool. None when it cannot be had."""
    import json
    if shutil.which("docker") is None:
        return None
    cfg = json.loads((Path(__file__).resolve().parents[3] / "docker" / "pcb" / "image-revisions.json").read_text())
    ref = f"{cfg['registry']}@{cfg['digest']}"
    if subprocess.run(["docker", "image", "inspect", ref], capture_output=True).returncode == 0:
        return ref
    pulled = subprocess.run(["docker", "pull", "--quiet", ref], capture_output=True, timeout=1800)
    return ref if pulled.returncode == 0 else None


def networkx_version():
    """networkx's version if this interpreter can import it (the r4 image pins 3.7), else None."""
    try:
        import networkx
        return networkx.__version__
    except ImportError:
        return None


def freerouting_jar():
    """The router's jar if Java and the jar are both in this environment ('present'), else None."""
    jar = Path(os.environ.get("FREEROUTING_JAR", "/opt/freerouting/freerouting.jar"))
    return "present" if shutil.which("java") and jar.is_file() else None


def network_reachable():
    """'up' if the vendor hosts answer on 443 within 5 s (the gate runs --network none, so it does not)."""
    import socket
    try:
        socket.create_connection(("www.ti.com", 443), timeout=5).close()
        return "up"
    except OSError:
        return None


def vendor_models():
    """The hash-verified vendor SPICE models (tools/fetch_models.py), untracked: 'present' or None."""
    m = Path(__file__).resolve().parents[1] / "models"
    needed = (m / "opa365" / "OPA365_PSPICE.lib", m / "tph2501" / "Spice_Model_TPH2501" / "TPH2501.mdl")
    return "present" if all(f.is_file() for f in needed) else None


_PROBES = {"pcbnew": (pcbnew_version, lambda v: v is not None and int(v.split(".")[0]) == 10,
                      "KiCad 10.x pcbnew importable in this interpreter"),
           "ngspice": (ngspice_version, lambda v: v is not None, "ngspice on PATH"),
           "freerouting": (freerouting_jar, lambda v: v is not None, "Freerouting (java + the pinned jar, in the PCB image)"),
           "networkx": (networkx_version, lambda v: v is not None, "networkx (pinned in requirements-pcb.txt; the r4 image carries it)"),
           "network": (network_reachable, lambda v: v is not None, "network access to the vendor hosts (www.ti.com:443)"),
           "vendor": (vendor_models, lambda v: v is not None, "the vendor SPICE models (python3 -I hardware/afe-proto/tools/fetch_models.py)"),
           "docker": (pcb_image_tag, lambda v: v is not None, "docker and the pinned docker/pcb image (pulled by digest from image-revisions.json; docker login first)")}


# pcbtools additions: run the guard test after every other test, count pcbnew-marked passes for it, and a fixture that fails
# (never skips) when the environment claims pcbnew (PCBTOOLS_EXPECT_PCBNEW=1, set by tests/run_pcbnew_tests.sh) and it is missing.
EXPECT = os.environ.get("PCBTOOLS_EXPECT_PCBNEW") == "1"
# the counters live on the session's own config object (made fresh in pytest_configure), never at module level: a second
# pytest session in the same process (pytest.main twice, pytester) re-uses the imported conftest and must start from zero.


def pytest_configure(config):
    config.addinivalue_line("markers", "guard_last: run after every other test")
    config._pcbtools_ran = {"pcbnew_passed": 0, "pcbnew_selected": 0}   # read by tests/pcbtools/test_guard.py


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    rep = (yield).get_result()
    if rep.when == "call" and rep.passed and item.get_closest_marker("pcbnew") and not item.get_closest_marker("guard_last"):
        item.config._pcbtools_ran["pcbnew_passed"] += 1


@pytest.fixture(scope="session")
def pcbnew_required():
    """use in a pcbnew-marked test: fails (never skips) when the environment claims pcbnew and it is missing"""
    if EXPECT and pcbnew_version() is None:
        pytest.fail("PCBTOOLS_EXPECT_PCBNEW=1 but pcbnew cannot be imported")


def pytest_collection_finish(session):
    """count the pcbnew-marked tests that are really going to run: AFTER every modifyitems hook and after -m / -k deselection
    (counting in modifyitems also counted the items the marker expression later deselected, so the guard failed under
    -m "not slow")"""
    session.config._pcbtools_ran["pcbnew_selected"] = sum(
        1 for i in session.items if i.get_closest_marker("pcbnew") and not i.get_closest_marker("guard_last"))


def pytest_collection_modifyitems(config, items):
    last = [i for i in items if i.get_closest_marker("guard_last")]
    rest = [i for i in items if not i.get_closest_marker("guard_last")]
    items[:] = rest + last
    if os.environ.get("DUE_PCB_IMAGE_CONTENT"):           # inside docker/pcb: the cap is the container's
        for item in items:
            if "docker" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="drives docker from the host; never runs inside the image"))
            if "jobcap" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="per-job cap: the container's cap is docker's; see test_image_gate"))
    required = {t.strip() for t in config.getoption("--require-tool").split(",") if t.strip()}
    unknown = required - set(_PROBES)
    if unknown:
        raise pytest.UsageError(f"--require-tool: unknown tool {sorted(unknown)}; known: {sorted(_PROBES)}")
    for item in items:
        for name, (probe, ok, what) in _PROBES.items():
            if name in item.keywords and not ok(probe()):
                msg = f"needs {what}"
                if name in required:
                    item.runtest = _fail_with(msg)
                else:
                    item.add_marker(pytest.mark.skip(reason=msg))


def _fail_with(msg):
    def runtest():
        pytest.fail("--require-tool given but " + msg)
    return runtest


@pytest.fixture(scope="session")
def versions():
    return tool_versions()


@pytest.fixture(scope="session")
def pcb_image_ref():
    """The pinned reference the `docker` probe found (registry@digest); for tests of the probe itself."""
    return pcb_image_tag()
