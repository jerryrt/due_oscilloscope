"""Markers, tool probes and the guard against a skip scoring as a pass.

Tiers (see docs/testing.md for the convention they follow):

    numpy tier   -m "not pcbnew and not ngspice"   needs numpy only; the gate
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

import pytest


def pytest_addoption(parser):
    parser.addoption("--require-tool", nargs="?", const="pcbnew,ngspice", default="",
                     metavar="TOOLS",
                     help="comma list of tools (pcbnew,ngspice) whose marked tests FAIL, not skip, "
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


_PROBES = {"pcbnew": (pcbnew_version, lambda v: v is not None and int(v.split(".")[0]) == 10,
                      "KiCad 10.x pcbnew importable in this interpreter"),
           "ngspice": (ngspice_version, lambda v: v is not None, "ngspice on PATH")}


def pytest_collection_modifyitems(config, items):
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
