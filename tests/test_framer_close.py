"""The close-mid-transfer window in the shared framer, driven.

`5d6e7ab` stops `stream_core_service()`'s not-ready path releasing the
head buffer while a USB DMA is reading it. That commit says plainly
what it lacked: "no test exercises the window, and I would not claim one
does". `tools/soak_close_stream.py` cannot supply one - it is
*identical* on the pre-fix image, because the corrupted bytes go to a
host that has already closed and the stop that follows resets all
framer state.

So the window is driven rather than soaked. `stream_port.h` is a
complete record of what the framer reaches outside itself - the property
issue #14 built it for - so the whole seam mocks on a host compiler and
the state machine steps one service call at a time.
`tests/framer/harness.c` holds the scenario.

**This test's own power is the point of it.** It builds the harness
twice: once against `stream_core.c` as it stands, and once against a
copy with the two-line guard mechanically removed. The real build must
pass and the mutant must fail. A regression test for a bug nobody can
reproduce is worth exactly what its mutant score says it is, and #28's
transferable lesson is "measure your test's power, not just its result".

Board-free, and about a second.
"""

import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.smoke

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SHARED = os.path.join(REPO, "lib", "due_shared", "src")
HARNESS = os.path.join(HERE, "framer", "harness.c")

# The guard 5d6e7ab added, verbatim. Removing it reconstructs the
# pre-fix behaviour without needing the old revision checked out, and
# the exact-match assertion means a reworded guard fails here loudly
# rather than leaving the mutant silently identical to the original -
# which is how a mutation test rots into a tautology.
GUARD = ("\t\tif (tx_phase == TX_DMA && usb_dma_in_busy())\n"
         "\t\t\treturn;\n")


def _cc():
    for name in ("cc", "gcc", "clang"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _build(tmp_path, core_c, name):
    exe = str(tmp_path / name)
    cc = _cc()
    proc = subprocess.run(
        [cc, "-std=c11", "-Wall", "-I", SHARED, "-o", exe,
         HARNESS, core_c, os.path.join(SHARED, "crc32.c")],
        capture_output=True, text=True)
    assert proc.returncode == 0, f"harness build failed:\n{proc.stderr}"
    return exe


@pytest.fixture(scope="module")
def core_src():
    with open(os.path.join(SHARED, "stream_core.c")) as fh:
        return fh.read()


@pytest.mark.skipif(_cc() is None, reason="no host C compiler")
def test_close_mid_transfer_does_not_touch_the_active_buffer(tmp_path):
    """A host closing the port must not disturb a transfer in flight.

    Both of 5d6e7ab's consequences are asserted by the harness: the head
    buffer is not released while its DMA runs, and no header is written
    into a buffer the controller is sourcing. It also checks that
    waiting is not wedging - once the transfer completes the frame is
    released and the framer returns to idle.
    """
    exe = _build(tmp_path, os.path.join(SHARED, "stream_core.c"), "real")
    proc = subprocess.run([exe], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS" in proc.stdout


@pytest.mark.skipif(_cc() is None, reason="no host C compiler")
def test_the_harness_catches_the_bug_it_was_written_for(tmp_path, core_src):
    """Without the guard, the harness must fail.

    Not a test of the framer - a test of the test above. It is the only
    thing standing between "the window is covered" and a harness that
    would pass against the defect as happily as against the fix, which
    is what the soak tool turned out to be.
    """
    assert core_src.count(GUARD) == 1, (
        "the guard 5d6e7ab added is no longer in stream_core.c verbatim. "
        "If it was reworded, update GUARD; if it was removed, that is "
        "the regression this file exists to catch.")
    mutant = tmp_path / "stream_core_mutant.c"
    mutant.write_text(core_src.replace(GUARD, "", 1))

    exe = _build(tmp_path, str(mutant), "mutant")
    proc = subprocess.run([exe], capture_output=True, text=True)
    assert proc.returncode != 0, (
        "the pre-fix framer passed the harness, so the harness has no "
        "power over this bug:\n" + proc.stdout)
    assert "released the head buffer while its DMA ran" in proc.stdout
    assert "wrote a header into an active DMA source" in proc.stdout
