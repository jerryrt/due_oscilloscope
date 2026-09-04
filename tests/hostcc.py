"""Finding, and correctly invoking, a host C compiler.

Several board-free tests build and *run* firmware C on the host -
`test_framer_close.py`, whose measurable power over `5d6e7ab` is the
point of it, `test_console_out.py`'s byte-budget and guard-page
harnesses, and the two parser fuzz targets in `test_ctl_fuzz.py` and
`test_console_fuzz.py`. They need the same four things: where the
compiler is, the environment it has to be invoked in, the sanitizer
flags they all share, and which ABI they are built for.

They are here rather than in `helpers.py` because `helpers` imports
`measure`, and these are the board-free tier: a tier-1 file should not
pull the host stack in to ask where `gcc` is.

**THE ABI IS PART OF WHAT A HARNESS PROVES, AND THE DEFAULT IS THE
WRONG ONE.** The target is a 32-bit Cortex-M3: `size_t`, `unsigned`,
`uintptr_t` and every pointer are four bytes, and `unsigned long` is
four as well. Every bench here is x86-64 LP64, where three of those are
eight. So a firmware defect that needs 32-bit widths - a length that
wraps, a cast that truncates, a struct that pads differently, a
pointer difference that does not fit - is invisible to the whole
host-run tier, and invisible in the direction that matters, because
LP64 is the *wider* type in each case and hides the overflow the target
would take.

`-m32` closes that, and `abis()` says which of them this machine can
actually build and run: the 32-bit runtimes are a separate install
(`gcc-multilib` and the `lib32` sanitizer libraries) and most benches do
not have them. A file that wants both parametrises on `ABIS` and skips
what `abis()` does not offer.

`DUE_HOSTCC_ABI` selects one for the harnesses that do not parametrise,
so a whole tier can be re-run at 32 bits without editing them. It
**raises** rather than skipping when the ABI it names cannot be built:
the caller asked for it explicitly, and a skip scored as a pass is how
this project voided a ten-step bisect.

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

#: The ABIs a harness may be built for, and the flag that selects each.
#:
#: "native" carries no flag at all rather than `-m64`, because `-m64` is
#: not an option on every host GCC this project might meet - an aarch64
#: bench would reject it and every harness would then skip on a machine
#: that builds them perfectly well today. The named ABI is the one that
#: differs from the target; the default is whatever the bench is.
ABI_FLAGS = {"native": (), "32": ("-m32",)}
ABIS = tuple(ABI_FLAGS)

#: Which ABI `sanitize_flags()` hands out, for the harnesses that take
#: one ABI rather than parametrising over both. Read once, so a run
#: cannot change it half way through.
ABI_ENV = "DUE_HOSTCC_ABI"

_sanitize_probe = {}
_abi_probe = {}


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


def _builds_and_runs(flags):
    """Build a trivial program with `flags` and run it. True if both work.

    Running it is not optional at either end of this. A MinGW gcc
    accepts `-fsanitize=address` on the command line and fails at the
    link; a GCC whose `libasan` was never installed does the same; and
    the ASan runtime can link and then refuse to start. `-m32` fails
    later still - the compiler front end takes it and the link then
    cannot find `Scrt1.o`, which is a linker path in the diagnostic
    rather than a package name.
    """
    found = cc()
    if not found:
        return False
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "probe.c")
        exe = os.path.join(d, "probe" + (".exe" if os.name == "nt" else ""))
        with open(src, "w") as fh:
            fh.write("int main(void) { return 0; }\n")
        try:
            build = subprocess.run([found, "-std=c11", *flags, "-o", exe, src],
                                   capture_output=True, text=True,
                                   env=cc_env(), timeout=120)
            if build.returncode != 0:
                return False
            run = subprocess.run([exe], capture_output=True, text=True,
                                 env=cc_env(), timeout=120)
            return run.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False


def abis():
    """The ABIs this bench can build a harness for and then run it.

    Probed by building and running, once per ABI per session, for the
    reason `_builds_and_runs` gives: nothing about `-m32` fails at the
    point where it was asked for.

    A bench with no 32-bit runtimes gets `("native",)` and the files
    that parametrise on `ABIS` skip the other arm. That skip is the
    honest answer - it is not a pass, and a tier that reports it is
    saying that the width the target actually has went unexercised here.
    """
    for name, flags in ABI_FLAGS.items():
        if name not in _abi_probe:
            _abi_probe[name] = _builds_and_runs(flags + SANITIZE) \
                or _builds_and_runs(flags)
    return tuple(n for n in ABIS if _abi_probe[n])


def sanitize_probe(abi="native"):
    """`SANITIZE` if this compiler links it for `abi`, `()` if it does not.

    Returning `()` rather than raising is deliberate: a bench without
    the runtimes still gets the harnesses, unsanitized, which is what it
    had before. What it must not get is a silent claim that they were
    instrumented, and `tests/test_sanitizers.py` is what says so out
    loud - it skips with the compiler named.
    """
    if abi not in _sanitize_probe:
        _sanitize_probe[abi] = (SANITIZE
                                if _builds_and_runs(ABI_FLAGS[abi] + SANITIZE)
                                else ())
    return _sanitize_probe[abi]


def build_flags(abi="native"):
    """Everything a native harness is compiled with, for one ABI.

    The ABI flag comes first so a `-m32` that the compiler refuses fails
    on its own line in the diagnostic rather than inside the sanitizer
    arguments.
    """
    if abi not in ABI_FLAGS:
        raise ValueError(f"no such ABI: {abi!r}; expected one of {ABIS}")
    return ABI_FLAGS[abi] + sanitize_probe(abi)


def selected_abi():
    """The ABI `sanitize_flags()` hands out, from `DUE_HOSTCC_ABI`.

    Unset means native, which is what every harness got before this
    existed. A value that names an ABI this bench cannot build raises,
    because the caller asked for it by name: the alternative is a run
    that silently measures the ABI it was trying to get away from.
    """
    want = os.environ.get(ABI_ENV, "native")
    if want not in ABI_FLAGS:
        raise RuntimeError(
            f"{ABI_ENV}={want!r} is not one of {ABIS}")
    if want not in abis():
        raise RuntimeError(
            f"{ABI_ENV}={want!r} was asked for and {cc()} cannot build and "
            f"run it. Install the 32-bit runtimes (gcc-multilib and the "
            f"lib32 sanitizer libraries) or unset {ABI_ENV} - this is not "
            f"skipped, because a skip scored as a pass is how a bisect got "
            f"voided here.")
    return want


def sanitize_flags():
    """What a harness that does not choose an ABI is built with.

    Every native harness composes its command line as `cc()`, its own
    arguments, and this - so this is the one place an ABI can be applied
    to all of them at once, which is why the flag lives here rather than
    beside a name that only says "sanitize". `DUE_HOSTCC_ABI` picks it;
    unset, this is exactly what it always was.
    """
    return build_flags(selected_abi())
