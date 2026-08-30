"""Every build in this project is a full build, and this fails if not.

Needs no board. It is a guard against drift rather than a behaviour
test: the enforcement itself is two lines in two files, and both are the
kind of line a future reader deletes to make a build faster.

The reason it is worth a test at all is that the failure it prevents is
silent. On 2026-08-29 arduino-cli's object cache produced a Track A
image built from a new `ctl_port.cpp` and a stale `ctl.c`: the
capability word carried the new bit, so the opcode worked, while the
capability *report* omitted it because that table lived in the file the
cache reused. The board answered correctly and described itself wrongly,
nothing in the build output mentioned a cached object, and the only tell
was eight bytes of flash.

A full build is 0.6 s for Track B and 2.2 s for Track A on the slowest
bench here, against measurement runs of nine minutes to eight hours that
quote the resulting image by commit. `tools/metrics.py` already warns
"a build cache probably served a stale object"; this stops it happening.
"""
import fnmatch
import os
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


def _ignored_dirs():
    """Directory patterns .gitignore already excludes.

    The scan below walks the tree looking for project Python, and a
    vendored toolchain unpacked in place is not project Python. This
    bench has `tools/xpack-arm-none-eabi-gcc-15.2.1-1.1/` - 1.0 GB and
    **102 .py files**, one of which is CPython's own
    `badsyntax_pep3120.py`, deliberately not UTF-8. Reading it raised
    UnicodeDecodeError and failed this test outright.

    `.gitignore` already says those directories are not ours -
    `tools/xpack-*/`, `tools/arm-gnu-toolchain-*/`, `tools/toolchain/` -
    so the patterns are read from there rather than copied here. A
    second list would drift from the first, and this test exists to
    stop exactly that kind of drift elsewhere.

    CLAUDE.md tells everyone to use the xPack toolchain, so any bench
    that unpacks it under tools/ hits this.
    """
    pats = []
    try:
        for line in _read(".gitignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line.endswith("/"):
                pats.append(line.rstrip("/"))
    except OSError:
        pass
    return pats


def test_track_b_cmake_forces_a_full_build():
    """CMake cleans before every build of the firmware, in that order.

    Checked at the source rather than by building, so it fails on the
    change that removes it rather than on the measurement that trusts
    it.

    The shape matters as much as the presence, and that is what this
    file got wrong the first time. The original spelling was
    `add_dependencies(baremetal_bringup enforce_clean_build)`, which
    asks the build system to run a clean inside the same graph it is
    about to link. Make re-evaluates between steps and honoured it - 25
    of 25 objects recompiled per invocation, measured - while Ninja
    plans the whole graph first and deleted the objects the same plan
    was about to link, so windows-desk could not build at all and
    `flash.py` then flashed the previous image (issue #35). It had been
    silently Make-works / Ninja-broken since it landed, and neither half
    was visible from either bench alone.

    So the clean and the build are two *child* invocations of CMake,
    sequenced by the shell rather than by the generator, and this pins
    every part of that arrangement - including the absence of the shape
    that failed.
    """
    cml = _read("CMakeLists.txt")

    assert re.search(r"add_custom_target\(\s*firmware\s+ALL", cml), (
        "CMakeLists.txt no longer defines the `firmware ALL` driver, so "
        "`cmake --build build` is incremental again and can link a "
        "mixed-revision image")
    assert re.search(r"--target\s+clean", cml), (
        "the driver no longer invokes CMake's clean target; an rm -rf of "
        "the object directory is not equivalent, it removes build.make "
        "and the build fails outright")
    assert re.search(r"--target\s+baremetal_bringup", cml), (
        "the driver cleans but never builds the firmware; `all` would "
        "now produce no image at all")
    assert re.search(r"add_executable\(\s*baremetal_bringup\s+"
                     r"EXCLUDE_FROM_ALL", cml), (
        "baremetal_bringup is back in `all`, so `cmake --build build` "
        "builds it directly and incrementally, stepping past the clean")

    assert not re.search(r"add_dependencies\(\s*baremetal_bringup\s+"
                         r"\w*clean\w*\s*\)", cml), (
        "the clean is a dependency of the executable again. That is the "
        "shape that broke under Ninja: the generator plans the whole "
        "graph, then the clean deletes the objects the same plan is "
        "about to link. See issue #35")


def test_flashing_track_b_also_gets_a_clean_build():
    """The flash target must not route around the driver.

    `flash` used to say `DEPENDS baremetal_bringup`, which now names a
    target outside `all` and would build it incrementally - a clean
    build for anyone typing `cmake --build build` and a stale one for
    anyone typing `--target flash`, which is the more dangerous of the
    two because its output goes on a board and into the flash log.
    """
    cml = _read("CMakeLists.txt")
    assert re.search(r"add_dependencies\(\s*flash\s+firmware\s*\)", cml), (
        "the flash target does not depend on the `firmware` driver, so "
        "`cmake --build build --target flash` can put an incrementally "
        "built image on the board")
    flash_block = cml[cml.index("add_custom_target(flash\n"):] \
        if "add_custom_target(flash\n" in cml else cml[cml.index("add_custom_target(flash"):]
    flash_block = flash_block[:flash_block.index("add_dependencies(flash")]
    assert "DEPENDS baremetal_bringup" not in flash_block, (
        "the flash target depends on baremetal_bringup directly again, "
        "which bypasses the clean")


def test_track_a_arduino_cli_is_told_not_to_use_its_cache():
    """sketch.py passes --clean, which is the one that has bitten us."""
    sk = _read("tools", "sketch.py")

    assert re.search(r'"compile",\s*"--clean"', sk), (
        "tools/sketch.py no longer passes --clean to arduino-cli. Its "
        "cache does not notice every change under --libraries, which is "
        "how a Track A image shipped with a stale lib/due_shared object")


def test_track_a_upload_builds_before_it_flashes():
    """`sketch.py upload` compiles rather than reusing an artifact.

    This one is not hypothetical. `upload` used to flash whatever .bin
    was in the build path, which is the image for whatever tree last
    compiled and not the image for this one. It put an experimental
    firmware - with issue #33's guard deliberately removed - onto a
    bench whose working tree was clean, and the only tell was that the
    recorded sha did not change.

    A flash is the single moment the tree and the board are supposed to
    agree, so it is the last place to reuse an artifact. `--bin` is
    still honoured, because flash.py and the harness pass an explicit
    path and mean it.
    """
    sk = _read("tools", "sketch.py")

    assert "def compile_sketch(" in sk, (
        "the compile path is no longer a function, so upload cannot "
        "call it and will go back to flashing whatever it finds")
    m = re.search(r'if args\.action == "upload":(.*?)\n    variant|'
                  r'if args\.action == "upload":(.*?)\Z', sk, re.S)
    body = sk[sk.index('if args.action == "upload":'):]
    body = body[:body.index("def compile_sketch(")]
    assert re.search(r"if not args\.bin:\s*\n\s*rc = compile_sketch\(", body), (
        "sketch.py upload no longer compiles before flashing, so it can "
        "put an image on the board that does not match the tree")


def test_nothing_else_builds_behind_the_enforcement():
    """No other caller spawns a compiler.

    The enforcement is one line per build system, which only holds while
    those are the only two ways to produce an image. A third path added
    later would bypass both silently, so this fails on its appearance.

    Matches a build tool named inside a process spawn, not merely the
    word: `host/provenance.py` lists "cmake" as a *directory* in
    FW_SOURCE, and a test that cannot tell those apart is one people
    learn to ignore.
    """
    SPAWN = re.compile(r"subprocess\.(run|call|check_call|check_output|Popen)"
                       r"\(", re.S)
    TOOL = re.compile(r"arduino-cli|\bcmake\b")
    ALLOWED = {"tools/sketch.py", "host/measure.py", "tools/toolchain.py",
               "tools/flash.py"}

    ignored = _ignored_dirs()

    offenders = []
    for root, dirs, files in os.walk(REPO):
        keep = []
        for d in dirs:
            if d in {".git", "build", ".venv", ".venv-gui",
                     "vendor", "__pycache__", "records"}:
                continue
            rel_d = os.path.relpath(os.path.join(root, d),
                                    REPO).replace(os.sep, "/")
            if any(fnmatch.fnmatch(rel_d, pat) for pat in ignored):
                continue
            keep.append(d)
        dirs[:] = keep
        for name in files:
            if not name.endswith(".py"):
                continue
            # Forward slashes on every platform. ALLOWED is written
            # with them, and `os.path.relpath` hands back `host\measure.py`
            # on win32 - so the allowlist matched nothing there and the
            # test reported an *allowed* file as an offender. It failed
            # on windows-desk for the whole of 2026-08-30 and was read as
            # a pre-existing failure to work around rather than a defect
            # in the test, which is what a tier-1 platform failure gets
            # if nobody looks at it.
            rel = os.path.relpath(os.path.join(root, name),
                                  REPO).replace(os.sep, "/")
            here = os.path.relpath(__file__, REPO).replace(os.sep, "/")
            if rel in ALLOWED or rel == here:
                continue
            text = _read(rel)
            for m in SPAWN.finditer(text):
                # The command list, not the rest of the file.
                window = text[m.end():m.end() + 300]
                if TOOL.search(window):
                    offenders.append(f"{rel}:{text[:m.start()].count(chr(10)) + 1}")
    assert not offenders, (
        "these spawn a build tool outside the two enforced paths, so "
        "they can produce an image from a stale cache: "
        + ", ".join(sorted(set(offenders))))
