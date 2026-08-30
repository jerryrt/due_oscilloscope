"""console_fmt against libc, conversion by conversion.

Issue #49. The firmware's formatter is written here rather than taken
from libc, because neither option libc offers is acceptable: `printf`
reaches a real stdio stream and newlib allocates that stream's buffer
from the heap, and `snprintf` allocates nothing but still drags the
whole engine and is still variable-time.

Writing a formatter is the easy part. **Being sure it agrees with the
one everybody already knows** is the part that needs a test, because
every wrong field is a wrong number in a measurement someone will quote
- and a formatter that is subtly wrong is worse than one that is
obviously missing.

So this is differential rather than expectation-based: the same format
and the same value go to `console_fmt` and to the host's `snprintf`,
and the outputs and the return values must match exactly. Nothing here
encodes what I think printf does.

Board-free, and it compiles the real `console_fmt.c` - not a copy - with
the host compiler, the same shape as `test_framer_close.py`.

It found a real defect on its first run: `%s` truncation returned the
buffer size where snprintf returns the would-be length. Callers append
at the returned offset, so that would have silently corrupted every
appended field once a line got long.
"""
import os
import re
import shutil
import subprocess

import pytest

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


def _cc():
    for name in ("cc", "gcc", "clang"):
        path = shutil.which(name)
        if path:
            return path
    return None


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    cc = _cc()
    if not cc:
        pytest.skip("no host C compiler; install gcc or clang to run this")
    exe = str(tmp_path_factory.mktemp("fmt") / "harness")
    proc = subprocess.run(
        [cc, "-std=c11", "-Wall", "-Wno-format-truncation",
         "-I", SHARED, "-o", exe,
         HARNESS, os.path.join(SHARED, "console_fmt.c")],
        capture_output=True, text=True)
    assert proc.returncode == 0, f"harness build failed:\n{proc.stderr}"
    return exe


def test_console_fmt_agrees_with_libc(harness):
    """Every conversion the firmware uses, against the reference."""
    proc = subprocess.run([harness], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 mismatches" in proc.stdout, proc.stdout


def test_the_differential_test_covers_what_the_firmware_uses():
    """The harness must not drift from the codebase it stands for.

    A differential test is only as good as its cases, and the cases were
    chosen by grepping the firmware for conversions. If a new one
    appears there and not here, this test passes while the formatter is
    unverified for it - which is the failure mode a differential test
    invites, because it looks thorough.
    """
    used = set()
    for d, files in ((os.path.join(REPO, "apps", "baremetal_bringup"), None),
                     (SHARED, None),
                     (os.path.join(REPO, "drivers"), None)):
        for f in os.listdir(d):
            if not f.endswith((".c", ".h")):
                continue
            if f == SELF:
                continue
            for m in re.finditer(r"%[-+ 0#]*\d*(?:l|ll|h)?([diuxXscp%])",
                                 _code(os.path.join(d, f))):
                used.add(m.group(1))
    covered = set(re.findall(r"%[-+ 0#]*\d*(?:l|ll|h)?([diuxXscp%])",
                             _code(HARNESS)))
    missing = sorted(used - covered - {"%"})
    assert not missing, (
        f"the firmware uses conversions {missing} that the differential "
        f"harness never exercises, so console_fmt is unverified for "
        f"them. Add a CHECK to tests/fmt/harness.c")


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
