"""Finding, and correctly invoking, a host C compiler.

Two board-free tests build and *run* a harness on the host -
`test_framer_close.py`, whose measurable power over `5d6e7ab` is the
point of it, and `test_console_out.py`'s byte-budget harness. Both need
the same two things, and both had to learn them separately.

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
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


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
