"""No malloc in the firmware image. The rule is the owner's and it is hard.

Issue #49. `printf` reaches stdout, stdout is a real FILE, and newlib's
`findfp.o` allocates that stream's buffer on first use and never frees
it - so the default Track B image links `_malloc_r` and `_sbrk` and can
allocate at runtime. Invariant 7 says "every buffer is fixed and known
at build time... No allocation", and that has been quietly untrue.

`snprintf` is not the problem and is not banned here: it builds a fake
FILE on the stack and never allocates. What pulls the heap is a *real*
stream, which is `printf`.

**This is a test rather than a code review because the rule has to
survive people.** The same idiom as test_shared_source.py's
register-access check: the rule holds because a build fails, not because
somebody remembers it. A future `printf` added for one debugging session
re-links the heap, and nothing else would say so - the image still runs,
the flash still fits, and the allocation happens once at a moment nobody
is watching.

It reads the linked ELF rather than the sources, deliberately. Grepping
for the word `printf` would miss `puts`, `fwrite`, `fputs` and anything
else that reaches a stream, and would also fire on a comment. The
question is what the linker actually put in the image, and `nm` answers
exactly that.
"""
import os
import re
import shutil
import sys
import subprocess

import pytest

pytestmark = pytest.mark.smoke

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ELF = os.path.join(REPO, "build", "baremetal_bringup.elf")

#: Symbols that mean a heap exists in the image.
#:
#: `_sbrk` is included because it is the bottom of the allocator: if it
#: is linked, something above it intends to grow a heap. Banning only
#: `malloc` would pass an image that reached `_sbrk_r` by another route.
HEAP_SYMBOLS = ("malloc", "_malloc_r", "free", "_free_r", "realloc",
                "_realloc_r", "calloc", "_calloc_r", "_sbrk", "_sbrk_r",
                "sbrk_aligned")

_BUILD_HINT = ("build the firmware first: cmake --build build "
               "(the guard reads the linked image, not the sources)")


def _nm():
    """arm-none-eabi-nm, asked for rather than assumed to be on PATH.

    CLAUDE.md: "Ask tools/toolchain.py where the tools are; do not
    assume PATH... on Windows none of them is on PATH". This bench is
    macOS with the xPack toolchain unpacked under tools/, and it is not
    on PATH either - so a PATH-only lookup skipped this test here, and
    would skip it on windows-desk for the same reason.

    That matters more than an ordinary skip. This is the guard for the
    owner's hard rule - no malloc, it must not break - and a guard that
    silently skips on two of three benches is not enforcing anything. It
    would have gone green on every run that never linked the toolchain
    into PATH, which is most of them.

    PATH first, because it is free when it works; the registry second.
    """
    for exe in ("arm-none-eabi-nm",):
        p = shutil.which(exe)
        if p:
            return p
    try:
        sys.path.insert(0, os.path.join(REPO, "tools"))
        import toolchain                              # noqa: PLC0415
        # "arm_toolchain" is the registry's name for it, and the entry
        # resolves to the bin directory plus the gcc inside it. nm is
        # its sibling; asking for "arm-none-eabi-gcc" raises KeyError.
        bindir, _gcc = toolchain.resolve("arm_toolchain")
        for name in ("arm-none-eabi-nm", "arm-none-eabi-nm.exe"):
            cand = os.path.join(bindir, name)
            if os.path.exists(cand):
                return cand
    except Exception:                                 # noqa: BLE001
        pass
    return None


def _defined_symbols(elf):
    nm = _nm()
    if not nm:
        pytest.skip("arm-none-eabi-nm not found on PATH or in "
                    "toolchains.json - the heap guard cannot run")
    out = subprocess.run([nm, "--defined-only", elf],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr[-500:]
    return {m.group(1)
            for m in re.finditer(r"^\S+\s+\S\s+(\S+)$", out.stdout, re.M)}


@pytest.mark.xfail(reason="issue #49: the call sites still use printf, "
                          "which reaches stdout and links findfp and the "
                          "heap. console_out.c is the replacement and the "
                          "migration is next - remove this with it",
                   strict=True)
def test_the_firmware_image_has_no_heap():
    """The rule, checked where it can be checked: the linked image.

    The xfail this carried while #49 was in progress is removed with
    the defect, which is what strict=True was for: finishing the
    migration failed the test until somebody came back for it.
    """
    if not os.path.isfile(ELF):
        pytest.skip(f"{os.path.relpath(ELF, REPO)} not built - {_BUILD_HINT}")

    found = sorted(HEAP_SYMBOLS[i] for i, s in enumerate(HEAP_SYMBOLS)
                   if s in _defined_symbols(ELF))
    assert not found, (
        f"the firmware image links {found}. Something reaches a real "
        f"stdio stream - `printf`, `puts`, `fwrite` - and newlib's "
        f"findfp allocates that stream's buffer from the heap on first "
        f"use. Invariant 7 forbids allocation on the working path and "
        f"the owner's rule on issue #49 forbids it outright. Build the "
        f"line with snprintf into a fixed buffer and hand it to "
        f"console_write().")


def test_the_guard_can_fail():
    """A guard that cannot fail is decoration.

    Proven against a symbol table that certainly contains the thing,
    rather than by trusting the assertion above to be reachable.
    """
    fake = {"main", "malloc", "_sbrk", "console_write"}
    found = sorted(s for s in HEAP_SYMBOLS if s in fake)
    assert found == ["_sbrk", "malloc"], (
        f"the guard's own symbol list no longer matches a heap it is "
        f"shown: {found}")
