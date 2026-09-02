"""The metric pipeline's portability, which is a property worth a test.

`tools/metrics.py` produces the report this project quotes, and the
reason it can be re-run on another bench is that it needs **no
instrument**: the ADC is the instrument, the board is opened directly,
and nothing imports `host/scope.py` or touches USBTMC.

That is easy to lose. One `import` added for one convenience turns a
report anybody can reproduce into one that only the desk with a DS1102E
on it can, and nothing would fail on this desk to say so - the scope is
plugged in here. So the check runs in a subprocess and asserts the
absence, the same shape as the GUI suite's "importing `gui.stream` must
not pull in PySide6".
"""
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _in_subprocess(code):
    """Import in a clean interpreter: this one has already imported the
    world, so `sys.modules` here proves nothing."""
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout.strip()


def test_the_metric_pipeline_needs_no_instrument():
    """The property that lets another bench reproduce the report."""
    got = _in_subprocess(
        "import sys; sys.path.insert(0,'host'); sys.path.insert(0,'tools');"
        "import metrics;"
        "bad=[m for m in ('scope','usb','usb1','libusb_package')"
        " if m in sys.modules];"
        "print(','.join(bad))")
    assert got == "", (
        f"tools/metrics.py pulled in {got}. The report is quotable on any "
        f"bench precisely because it needs no instrument; an import that "
        f"reaches for one takes that away silently, because the scope is "
        f"attached on the desk where this was written.")


def test_the_pipeline_reports_firmware_and_not_a_daemon():
    """Scope is one program on purpose. A report qualified by two
    version sets invites the reader to wonder which one a figure
    depended on."""
    got = _in_subprocess(
        "import sys; sys.path.insert(0,'host'); sys.path.insert(0,'tools');"
        "import metrics, inspect;"
        "src=inspect.getsource(metrics.render);"
        "print('daemon_rev' in src or 'daemon_code_rev' in src)")
    assert got == "False"


def test_provenance_requires_the_firmware_commit():
    """`fw_version` is bumped by hand and says what somebody intended.
    Two benches reported 0.2.0 four hours and three DAC commits apart."""
    sys.path.insert(0, os.path.join(REPO, "host"))
    import provenance as prov
    assert "fw_repo_rev" in prov.REQUIRED
    assert "bench" in prov.REQUIRED
    # And an empty one is refused rather than recorded.
    assert "fw_repo_rev" in prov.missing({"track": "b"})


def test_an_unlogged_flash_cannot_produce_a_report(tmp_path, monkeypatch):
    """A board flashed by something that does not log has unknown
    provenance, and that is a refusal rather than a blank field."""
    sys.path.insert(0, os.path.join(REPO, "host"))
    import provenance as prov
    monkeypatch.setattr(prov, "FLASH_LOG", str(tmp_path / "nothing.jsonl"))
    fw = prov.firmware("Aug 27 2026 16:14:27")
    assert fw == {"fw_provenance": "unlogged"}
    assert "fw_repo_rev" in prov.missing(fw)


# ------------------------------------------------- provenance source lists

def _repo_read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


def _cmake_source_dirs():
    """Top-level dirs CMake actually compiles into the Track B image.

    Read out of `add_executable(...)` rather than listed here, because a
    second hand-written list is the thing this test exists to catch.
    `${...}` entries are the vendored CMSIS device tree and are outside
    the repository's source dirs.
    """
    import re
    cmake = _repo_read("CMakeLists.txt")
    block = cmake[cmake.index("add_executable(baremetal_bringup"):]
    block = block[:block.index(")")]
    dirs = set()
    for line in block.splitlines()[1:]:
        src = line.strip()
        if not src or src.startswith("#") or src.startswith("${"):
            continue
        dirs.add(src.split("/")[0])
    return dirs


def test_fw_source_covers_every_directory_each_track_builds_from():
    """A provenance flag that misses a source dir is worse than none.

    `bsp` was absent from `FW_SOURCE` until 2026-08-29 while CMake
    compiled seven files out of it, so `fw_source_current` would have
    reported "current" across a change to `bsp/clock.c` - which sets
    MCK, the one constant this repository warns hardest about. That is a
    false negative, and a false negative is what a provenance flag is
    built to make impossible.

    So the covering set is derived from the build files here rather than
    written down a second time. A new source directory added to either
    build fails this until it is declared.
    """
    sys.path.insert(0, os.path.join(REPO, "host"))
    import provenance as prov

    missing = _cmake_source_dirs() - set(prov.FW_SOURCE_TRACKS["B"])
    assert not missing, (
        f"CMake compiles {sorted(missing)} into the Track B image and "
        f"provenance does not watch it: fw_source_current would report "
        f"'current' across a change to it")

    # Track A: the sketch directory and the shared library dir, which
    # cmake/track_a.cmake globs (#55). This read tools/sketch.py's
    # arduino-cli argv before Track A moved onto CMake and sketch.py was
    # deleted; the question is unchanged - does provenance watch what
    # actually gets compiled - and only the file that answers it moved.
    ta = _repo_read("cmake/track_a.cmake")
    assert re.search(r"file\(GLOB\s+\w+\s+\$\{CMAKE_SOURCE_DIR\}/sketches/",
                     ta), (
        "cmake/track_a.cmake no longer globs sketches/; the Track A "
        "provenance list is now guessing")
    assert re.search(r"file\(GLOB\s+\w+\s+\$\{CMAKE_SOURCE_DIR\}/lib/due_shared/",
                     ta), (
        "cmake/track_a.cmake no longer compiles lib/due_shared; the "
        "shared wire contract has left Track A's provenance list")
    for d in ("sketches", "lib"):
        assert d in prov.FW_SOURCE_TRACKS["A"], (
            f"Track A builds from {d}/ and provenance does not watch it")

    # Both tracks link a script out of linker/, so it is in neither
    # track's list by accident.
    for track in ("A", "B"):
        assert "linker" in prov.FW_SOURCE_TRACKS[track]


def test_fw_source_union_is_the_unknown_track_answer():
    """Over-report when the track is unknown, never under-report.

    A false "check your image" costs a rebuild. A false "your image is
    current" costs a published figure, and this project has paid that
    once already.
    """
    sys.path.insert(0, os.path.join(REPO, "host"))
    import provenance as prov

    for track in ("A", "B"):
        assert set(prov.FW_SOURCE_TRACKS[track]) <= set(prov.FW_SOURCE)
    assert prov.fw_source_paths(None) == prov.FW_SOURCE
    assert prov.fw_source_paths("nonsense") == prov.FW_SOURCE
    assert prov.fw_source_paths("b") == prov.FW_SOURCE_TRACKS["B"]
    assert prov.fw_source_paths("A") == prov.FW_SOURCE_TRACKS["A"]


def test_a_flash_record_for_the_other_track_is_not_this_boards_image():
    """The log names the binary, so the track is already in every record.

    A bench that alternates tracks - linux-x1 does, several times a
    session - could otherwise attribute a Track B board to the Track A
    flash that happened to be newest.
    """
    sys.path.insert(0, os.path.join(REPO, "host"))
    import provenance as prov

    assert prov.track_of_binary("build/track_a/bringup.ino.bin") == "A"
    assert prov.track_of_binary("build/baremetal_bringup.bin") == "B"
    assert prov.track_of_binary(r"build\track_a\bringup.ino.bin") == "A"
    assert prov.track_of_binary(None) is None
    assert prov.track_of_binary("build/something_else.bin") is None
