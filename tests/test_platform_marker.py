"""The `platform` marker: the subset the container cannot answer.

Needs no board and no container. The container image is always Linux, so
a Windows or macOS branch in `host/transport.py`, `host/rt.py` or
`host/ports.py` executes on no bench unless that host runs the test
itself. `docs/testing.md` makes the container run the board-free gate and
`-m "platform and not board"` the native remainder, which is seconds.

The failure this guards is the subset going quietly empty, or a module
that reaches the seam being added without the marker: both leave a
platform branch tested nowhere while every tier stays green.
"""
import ast
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(REPO, "tests")

#: Importing one of these puts a test module on the host's own OS branch.
SEAM = {"ports", "transport", "rt", "host_conditions"}


def _modules_importing_the_seam():
    out = {}
    for name in sorted(os.listdir(TESTS)):
        if not name.startswith("test_") or not name.endswith(".py"):
            continue
        path = os.path.join(TESTS, name)
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src, filename=path)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                imported.add(node.module.split(".")[0])
        if imported & SEAM:
            out[name] = ("pytest.mark.platform" in src
                         or "PLATFORM_SEAM_EXEMPT" in src)
    return out


def _board_free_modules():
    """Modules that collect at least one board-free test, from pytest itself.

    A module that only holds board tests needs no marker: the board tier
    runs natively on the bench that owns the board, so its platform
    branches are exercised there by construction.
    """
    r = subprocess.run([sys.executable, "-m", "pytest", "--track=b", "-q",
                        "-p", "no:cacheprovider", "--collect-only",
                        "-m", "not board", TESTS],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    return {line.split("::")[0].split("/")[-1]
            for line in r.stdout.splitlines() if "::" in line}


def test_every_board_free_module_that_reaches_the_seam_is_marked():
    board_free = _board_free_modules()
    unmarked = sorted(n for n, marked in _modules_importing_the_seam().items()
                      if not marked and n in board_free)
    assert not unmarked, (
        f"these collect board-free tests and import {sorted(SEAM)}, but carry "
        f"neither the `platform` marker nor a PLATFORM_SEAM_EXEMPT reason. "
        f"Mark them, or say why their board-free tests touch no OS branch: "
        f"{unmarked}")


def test_an_exemption_must_carry_a_reason():
    """`PLATFORM_SEAM_EXEMPT = ""` would pass the check above by spelling."""
    import re
    for name in sorted(os.listdir(TESTS)):
        if not name.startswith("test_") or not name.endswith(".py"):
            continue
        with open(os.path.join(TESTS, name), encoding="utf-8") as fh:
            src = fh.read()
        m = re.search(r'PLATFORM_SEAM_EXEMPT\s*=\s*(.+)', src)
        if m and not m.group(1).strip().startswith("#"):
            value = m.group(1).strip()
            assert len(value) > 12 and value[0] in "\"'", (name, value)


def test_the_seam_is_actually_reached_by_some_module():
    """Without this, deleting the seam from every import list passes above."""
    assert _modules_importing_the_seam(), SEAM


def test_the_marker_selects_a_non_empty_board_free_subset():
    r = subprocess.run([sys.executable, "-m", "pytest", "--track=b", "-q",
                        "-p", "no:cacheprovider", "--collect-only",
                        "-m", "platform and not board", TESTS],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    tail = [l for l in r.stdout.strip().splitlines() if "collected" in l]
    assert tail, r.stdout[-2000:]
    n = int(tail[-1].split("/")[0].split()[0])
    assert n >= 5, f"the native platform subset collects {n} tests: {tail[-1]}"
