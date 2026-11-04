"""The H7 on the real unit, through the real daemon, the unmodified client and the window: targets/h7tool/measure/h7_daemon_gate.py as a test.

It resolves `h7_unit`, so it carries the `h7` and `board` markers and the board-free gate never selects it; with no unit running an image it SKIPS
naming why (boot loader, or absent) and --require-h7 turns that into a failure. The checks live in the gate script and nowhere else, so there is
one definition of what "the H7 works" means. It needs the GUI venv (numpy, PySide6) and VOUT wired as the gate declares (H7_GATE_VOUT, default CH1)."""
import os
import subprocess
import sys

import pytest

import pacing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(ROOT, "targets", "h7tool", "measure", "h7_daemon_gate.py")
WRONG_VENV = "you are in the wrong venv: the gate needs numpy and PySide6 (.venv-gui); this skip is NOT a pass"


def test_the_gate_passes_on_the_real_unit(h7_unit):
    pytest.importorskip("numpy", reason=WRONG_VENV)
    pytest.importorskip("PySide6", reason=WRONG_VENV)
    r = subprocess.run([sys.executable, "-I", GATE, "5"], capture_output=True, text=True, encoding="utf-8", timeout=pacing.SLOW,
                       env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
    assert r.returncode == 0 and "H7 daemon gate: all checks passed" in r.stdout, r.stdout[-2000:] + r.stderr[-1000:]
