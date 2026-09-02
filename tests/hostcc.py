"""Finding, and correctly invoking, a host C compiler.

Several board-free tests build and *run* firmware C on the host -
`test_framer_close.py`, whose measurable power over `5d6e7ab` is the
point of it, `test_console_out.py`'s byte-budget and guard-page
harnesses, and `test_ctl_fuzz.py`'s control-parser fuzz target. They
need the same three things: where the compiler is, the environment it
has to be invoked in, and the sanitizer flags they all share.

They are here rather than in `helpers.py` because `helpers` imports
`measure`, and these are the board-free tier: a tier-1 file should not
pull the host stack in to ask where `gcc` is.

**GNU only.** MSVC is ruled out by the owner and by `frame.h`, which
declares the frame header `__attribute__((packed))` while MSVC wants
`#pragma pack` - admitting it would mean changing the packing semantics
of the shared wire contract. See CLAUDE.md.
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

#: What every native harness is built with, in one place so a harness
#: cannot quietly be the one that is not instrumented.
#:
#: `-fno-sanitize-recover=all` is the half that is easy to leave out and
#: costs the most: without it UBSan prints its finding and lets the
#: program run on to exit 0, so a suite that reads exit status sees a
#: pass. `tests/test_sanitizers.py` builds a deliberate signed overflow
#: and requires a non-zero exit, which is that flag and nothing else.
#:
#: -O1 rather than -O0 because at -O0 gcc keeps every dead store and the
#: sanitizers then spend their time on code the real build deletes;
#: -fno-omit-frame-pointer is what makes an ASan report name the frame
#: that wrote the byte.
SANITIZE = ("-g", "-O1",
            "-fsanitize=address,undefined",
            "-fno-sanitize-recover=all",
            "-fno-omit-frame-pointer")

_sanitize_probe = None


def cc():
    """A host C compiler, or None. GNU dialect only.

    PATH first, which is every POSIX bench and costs nothing. Then the
    registry, because on Windows nothing is on PATH - the same reason
    `tools/toolchain.py` exists for cmake, ninja and the ARM toolchain,
    and the rule CLAUDE.md states for all of them.

    Windows benches had no host compiler at all until 2026-08-30, so
    these files skipped there: a tier-1 test whose whole documented
    purpose is measurable power contributed nothing and said nothing
    about it. `test_framer_close.py` learned to ask the registry the
    day the compiler was installed; `test_console_out.py` did not, and
    went on skipping on `windows-desk` with "install gcc or clang"
    while `tools/toolchain.py` resolved one the whole time. That is why
    this is one function and not two.
    """
    for name in ("cc", "gcc", "clang"):
        path = shutil.which(name)
        if path:
            return path
    try:
        sys.path.insert(0, os.path.join(REPO, "tools"))
        import toolchain
        _dir, exe = toolchain.resolve("host_cc")
        if exe:
            return exe
    except Exception:                                        # noqa: BLE001
        pass
    return None


def cc_env():
    """The environment a MinGW gcc needs, and the reason it is not optional.

    A MinGW toolchain's driver loads its own DLLs - libisl, libmpc,
    libgmp, libwinpthread - from the directory it lives in, and finds
    them only if that directory is on PATH. Invoked by absolute path
    from a process without it, `gcc` exits **1 with an empty stderr**:
    no diagnostic, no missing-DLL dialog, nothing to read. A build
    assertion that prints `proc.stderr` shows a blank failure, which is
    a bad half-hour for whoever meets it next.

    Harmless where the compiler came off PATH already, which is every
    POSIX bench: prepending its own directory changes nothing there.
    """
    found = cc()
    env = dict(os.environ)
    if found:
        env["PATH"] = os.path.dirname(found) + os.pathsep + env.get("PATH", "")
    return env


def sanitize_flags():
    """`SANITIZE` if this compiler links it, `()` if it does not.

    Probed by building and running a program, once per session, rather
    than inferred from the compiler's name: a MinGW gcc accepts
    `-fsanitize=address` on the command line and fails at the link, and
    a GCC whose `libasan` was never installed does the same. The probe
    *runs* what it built, because the ASan runtime can link and then
    refuse to start.

    Returning `()` rather than raising is deliberate: a bench without
    the runtimes still gets the harnesses, unsanitized, which is what it
    had before. What it must not get is a silent claim that they were
    instrumented, and `tests/test_sanitizers.py` is what says so out
    loud - it skips with the compiler named.
    """
    global _sanitize_probe

    if _sanitize_probe is not None:
        return _sanitize_probe
    _sanitize_probe = ()
    found = cc()
    if not found:
        return _sanitize_probe

    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "probe.c")
        exe = os.path.join(d, "probe" + (".exe" if os.name == "nt" else ""))
        with open(src, "w") as fh:
            fh.write("int main(void) { return 0; }\n")
        try:
            build = subprocess.run([found, "-std=c11", *SANITIZE,
                                    "-o", exe, src],
                                   capture_output=True, text=True,
                                   env=cc_env(), timeout=120)
            if build.returncode != 0:
                return _sanitize_probe
            run = subprocess.run([exe], capture_output=True, text=True,
                                 env=cc_env(), timeout=120)
            if run.returncode == 0:
                _sanitize_probe = SANITIZE
        except (OSError, subprocess.SubprocessError):
            pass
    return _sanitize_probe
