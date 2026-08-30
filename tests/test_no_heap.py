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
    for exe in ("arm-none-eabi-nm", "nm"):
        p = shutil.which(exe)
        if p and "arm-none-eabi" in exe:
            return p
    return shutil.which("arm-none-eabi-nm")


def _defined_symbols(elf):
    nm = _nm()
    if not nm:
        pytest.skip("arm-none-eabi-nm not on PATH; run tools/toolchain.py")
    out = subprocess.run([nm, "--defined-only", elf],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr[-500:]
    return {m.group(1)
            for m in re.finditer(r"^\S+\s+\S\s+(\S+)$", out.stdout, re.M)}


@pytest.mark.xfail(reason="issue #49: 110 printf call sites still reach "
                          "stdout, which links findfp and therefore the "
                          "heap. Fails once the migration to console_fmt "
                          "lands - remove the xfail with it",
                   strict=True)
def test_the_firmware_image_has_no_heap():
    """The rule, checked where it can be checked: the linked image.

    Marked strict, so completing #49's migration fails this test until
    the xfail is removed with it. A silently-passing xfail is how a
    fixed defect keeps a test that no longer tests anything - the same
    reasoning test_startup_frames.py carries.
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
