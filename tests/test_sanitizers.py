"""The sanitizers, proven to be linked rather than assumed to be.

The host-run tier is the only place in this project where firmware C is
compiled and *executed* - `stream_core.c` behind `stream_port.h`, the
console emitters, and the control parser behind `ctl_port.h`. It is
therefore the only place ASan and UBSan can run at all: they need a
process, a heap and a runtime, and the target is bare metal with none of
the three. `docs/build-container.md` records that as a constraint, which
is why this is a host tier and not a firmware build option.

**A sanitizer that is not linked looks exactly like clean code.** The
harnesses pass, the tier is green, and nothing anywhere says the
instrumentation was absent - which is the shape CLAUDE.md's four
cannot-fail guards had. So the flags are demonstrated: four deliberate
defects, one per check the harnesses rely on, each of which must be
caught, plus a clean build of the same file that must not be.

The fourth defect is about `-fno-sanitize-recover=all` rather than about
UBSan. A signed overflow is diagnosed either way; without that flag
UBSan prints its line and the program runs on to return 0, so every
harness that is scored on exit status reads a pass. That is one flag,
and it is the one worth a test of its own.

Board-free, and about two seconds.
"""

import os
import subprocess

import pytest

import hostcc

pytestmark = pytest.mark.smoke

HERE = os.path.dirname(os.path.abspath(__file__))
CANARY = os.path.join(HERE, "sanitize", "canary.c")

#: What each injected defect must produce. A list, because which
#: sanitizer speaks first is a property of the compiler and not of the
#: defect: on GCC 15.2.0 UBSan's object-size check reports the heap
#: over-run before ASan's redzone does, and `-fno-sanitize-recover=all`
#: then ends the process before ASan is consulted at all. The
#: use-after-free has no such ambiguity and is what proves ASan itself
#: is in the link.
CAUGHT = {
    1: ["AddressSanitizer: heap-buffer-overflow",
        "runtime error: store to address"],
    2: ["AddressSanitizer: heap-use-after-free"],
    3: ["runtime error: signed integer overflow"],
    4: ["runtime error: load of misaligned address"],
}

WHAT = {
    1: "a write one byte past a malloc'd block",
    2: "a read from a freed block",
    3: "a signed integer overflow",
    4: "a load through a misaligned pointer",
}


def _require():
    if hostcc.cc() is None:
        pytest.skip("no host C compiler")
    if not hostcc.sanitize_flags():
        pytest.skip(
            f"{hostcc.cc()} does not link -fsanitize=address,undefined, so "
            f"the native harnesses in this run are NOT instrumented")


def _build(tmp_path, defect):
    exe = str(tmp_path / f"canary{defect}")
    proc = subprocess.run(
        [hostcc.cc(), "-std=c11", "-Wall", "-Wextra",
         *hostcc.sanitize_flags(), f"-DDEFECT={defect}", "-o", exe, CANARY],
        capture_output=True, text=True, env=hostcc.cc_env(), timeout=300)
    assert proc.returncode == 0, f"canary build failed:\n{proc.stderr}"
    return exe


def test_the_canary_is_clean_when_nothing_is_wrong_with_it(tmp_path):
    """The same file, same flags, no defect. It must exit 0.

    Without this the four below would pass against a harness that
    aborted on everything - a detector that always fires detects
    nothing.
    """
    _require()
    proc = subprocess.run([_build(tmp_path, 0)], capture_output=True,
                          text=True, env=hostcc.cc_env(), timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "clean" in proc.stdout


@pytest.mark.parametrize("defect", sorted(CAUGHT))
def test_an_injected_defect_is_caught_and_fails_the_process(tmp_path, defect):
    """One defect per class, each of which must end the process.

    Both halves are asserted. A sanitizer that reports and returns 0
    would satisfy an assertion on the message alone, and a process that
    died for some other reason would satisfy one on the exit status
    alone.
    """
    _require()
    proc = subprocess.run([_build(tmp_path, defect)], capture_output=True,
                          text=True, env=hostcc.cc_env(), timeout=300)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, (
        f"{WHAT[defect]} did not fail the process, so a finding in a "
        f"native harness would be printed and scored as a pass:\n{out}")
    assert any(m in out for m in CAUGHT[defect]), (
        f"{WHAT[defect]} produced no recognised report. Expected one of "
        f"{CAUGHT[defect]}:\n{out}")
