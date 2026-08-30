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
import os
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_track_b_cmake_forces_a_full_build():
    """CMake cleans before every build of the firmware target.

    Checked at the source rather than by building, so it fails on the
    change that removes it rather than on the measurement that trusts
    it. Both halves matter: a target nothing depends on does nothing.
    """
    cml = _read("CMakeLists.txt")

    assert "add_custom_target(enforce_clean_build" in cml, (
        "CMakeLists.txt no longer defines enforce_clean_build, so "
        "`cmake --build build` is incremental again and can link a "
        "mixed-revision image")
    assert re.search(r"--target\s+clean", cml), (
        "enforce_clean_build no longer invokes CMake's clean target; an "
        "rm -rf of the object directory is not equivalent, it removes "
        "build.make and the build fails outright")
    assert re.search(r"add_dependencies\(\s*baremetal_bringup\s+"
                     r"enforce_clean_build\s*\)", cml), (
        "enforce_clean_build exists but baremetal_bringup does not "
        "depend on it, so it never runs")


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

    offenders = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs
                   if d not in {".git", "build", ".venv", ".venv-gui",
                                "vendor", "__pycache__", "records"}]
        for name in files:
            if not name.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(root, name), REPO)
            if rel in ALLOWED or rel == os.path.relpath(__file__, REPO):
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
