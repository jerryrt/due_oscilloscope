"""The debug emitters: their budgets, and the rules that keep them.

Issue #49. `console_out.h` states a byte bound per call and a memory
budget of no heap, no static buffers and no line buffer. Those are
claims, so they are tested rather than asserted.

Testing the byte count tests the time budget too, without a board or a
clock: at 115200 a byte is 86.8 us and the arithmetic around it is
about 1% - measured, a 42-byte line costs 3618 us against 3646 us of
pure transmission. The byte count IS the cost.

This file replaces a differential test against libc `snprintf`, which
belonged to an earlier design of this issue - a printf-compatible
formatter, chosen so 130 call sites could migrate by rename. That
optimised for the migration rather than for the property the issue is
about. The owner's direction was clean house: deterministic time and
memory, no obligation to the printf feature set, call sites rewritten.
Agreement with printf is no longer the goal, so a test that measured it
would be testing the wrong thing.
"""
import os
import re
import shutil
import subprocess

import pytest

import hostcc

pytestmark = pytest.mark.smoke

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SHARED = os.path.join(REPO, "lib", "due_shared", "src")
HARNESS = os.path.join(HERE, "fmt", "harness.c")


#: The formatter's own source is excluded from both scans below. It is
#: the file that *implements* the conversions, so its comments and its
#: switch discuss every one of them - including the floats it refuses.
#: Scanning it would report the definition as a use.
SELF = "console_fmt.c"


def _code(path):
    """Source with comments removed.

    Three source-scanning guards written today have matched text in a
    comment before they matched code - the register check hit the
    console's own "HOST->DAC->ADC->HOST" help line, console_pairs.py
    counted commented-out calls, and the first version of this file
    found "%f" in a sentence explaining that %f is not supported. Strip
    first, ask second.
    """
    with open(path, encoding="utf-8") as fh:
        t = fh.read()
    t = re.sub(r"/\*.*?\*/", " ", t, flags=re.S)
    return re.sub(r"//[^\n]*", " ", t)


# Resolving a host compiler lives in tests/hostcc.py, shared with
# test_framer_close.py. This file had its own PATH-only copy, which is
# why it went on skipping with "install gcc or clang" on windows-desk
# after the compiler was installed and the registry resolved it.
def _cc():
    return hostcc.cc()


def test_no_floating_point_conversions_in_the_firmware():
    """The formatter refuses floats, so the firmware must not use them.

    Not a style rule. Float formatting is most of what makes libc's
    engine large, and supporting it would drag back the machinery this
    replaces. `console_fmt` emits the conversion character instead of a
    number, so a stray %f is visible rather than silently wrong - but
    visible-and-wrong is still wrong, and this is where it gets caught.
    """
    hits = []
    for d in (os.path.join(REPO, "apps", "baremetal_bringup"), SHARED,
              os.path.join(REPO, "drivers"), os.path.join(REPO, "bsp")):
        for f in sorted(os.listdir(d)):
            if not f.endswith((".c", ".h")):
                continue
            if f == SELF:
                continue
            p = os.path.join(d, f)
            for n, line in enumerate(_code(p).splitlines(), 1):
                if re.search(r"%[-+ 0#]*[\d.]*(?:l|L)?[fgeFGE]\b", line):
                    hits.append(f"{os.path.relpath(p, REPO)}:{n}")
    assert not hits, (
        f"floating-point conversions found: {hits}. console_fmt does not "
        f"format floats and supporting them would drag back the libc "
        f"engine issue #49 removed")


@pytest.fixture(scope="module")
def budget(tmp_path_factory):
    cc = _cc()
    if not cc:
        pytest.skip("no host C compiler; install gcc or clang to run this")
    exe = str(tmp_path_factory.mktemp("bud") / "budget")
    proc = subprocess.run(
        [cc, "-std=c11", "-Wall", *hostcc.sanitize_flags(),
         "-I", SHARED, "-o", exe,
         os.path.join(HERE, "fmt", "budget.c"),
         os.path.join(SHARED, "console_out.c")],
        capture_output=True, text=True, env=hostcc.cc_env())
    assert proc.returncode == 0, f"budget harness build failed:\n{proc.stderr}"
    return exe


def test_the_emitters_stay_inside_their_stated_budgets(budget):
    """console_out.h states a byte bound per call. This is that bound.

    Testing the byte count tests the time budget too, without a board or
    a clock: at 115200 a byte is 86.8 us and the arithmetic is about 1%
    of it - measured, a 42-byte line costs 3618 us against 3646 us of
    pure transmission. So the byte count is the cost.

    Worst cases, not typical ones: 4294967295, INT32_MIN, eight hex
    digits, a pad of 9999 clamped to CON_PAD_MAX, and a string twice
    CON_STR_MAX which must truncate rather than run on.
    """
    proc = subprocess.run([budget], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 failures" in proc.stdout, proc.stdout


def test_the_emitters_have_no_line_buffer():
    """The memory budget is a property of the source, so it is read there.

    A line buffer would make the cost of a call depend on the length of
    the line it is part of, and would give a caller something to
    overflow. There is none: each emitter builds only the few bytes it
    owns, in a scratch bounded by CON_SCRATCH.

    This fails if an array appears that is not one of the small named
    scratches - which is how a "just make it a bit bigger" buffer gets
    added without anyone deciding to.
    """
    import re
    src = _code(os.path.join(SHARED, "console_out.c"))
    arrays = re.findall(r"char\s+\w+\s*\[\s*([^\]]+)\s*\]", src)
    allowed = {"CON_SCRATCH", "2", "9"}
    bad = [a.strip() for a in arrays if a.strip() not in allowed]
    assert not bad, (
        f"console_out.c declares char arrays sized {bad}. The emitters "
        f"have no line buffer by design - each builds only the bytes it "
        f"owns - and an array outside {sorted(allowed)} is either a line "
        f"buffer or a budget nobody has stated")


@pytest.fixture(scope="module")
def guardpage(tmp_path_factory):
    cc = _cc()
    if not cc:
        pytest.skip("no host C compiler; install gcc or clang to run this")
    exe = str(tmp_path_factory.mktemp("guard") / "guardpage")
    proc = subprocess.run(
        [cc, "-std=c11", "-Wall", *hostcc.sanitize_flags(),
         "-I", SHARED, "-o", exe,
         os.path.join(HERE, "fmt", "guardpage.c"),
         os.path.join(SHARED, "console_out.c")],
        capture_output=True, text=True, env=hostcc.cc_env())
    assert proc.returncode == 0, (
        f"guard-page harness build failed:\n{proc.stderr}")
    return exe


@pytest.mark.parametrize("mode,emitted", [("str", 256),
                                          ("strl", 256),
                                          ("terminated", 255)])
def test_the_string_walk_reads_nothing_past_its_bound(guardpage, mode,
                                                      emitted):
    """CON_STR_MAX is the last index an emitter may read, not the first.

    A bound tested after the dereference is off by one, and the byte it
    reads is returned like any other: the output is right, the budget is
    met, and the suite is green. Nothing above the walk can see it, so
    the check is arranged below - the string sits against a page that
    faults on read, and the walk is scored by whether the process
    survived.

    `str` and `strl` are separate cases because they are separate
    walks. cppcheck reported one of them and not the other, which is the
    argument for covering both rather than the tool's list.
    """
    proc = subprocess.run([guardpage, mode], capture_output=True, text=True)
    assert proc.returncode == 0, (
        f"con_{mode} walked off the end of its bound: exit "
        f"{proc.returncode}\n{proc.stdout}{proc.stderr}")
    assert f"emitted {emitted}" in proc.stdout, proc.stdout
