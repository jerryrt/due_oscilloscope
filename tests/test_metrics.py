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
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _in_subprocess(code, env=None):
    """Import in a clean interpreter: this one has already imported the
    world, so `sys.modules` here proves nothing.

    `env` overlays the current environment, which is how a zone is set:
    `TZ` is read once per process by the C library and `time.tzset()`
    in this interpreter would leak into every test after it.
    """
    e = dict(os.environ, **env) if env else None
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO,
                         capture_output=True, text=True, timeout=120, env=e)
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


# ------------------------------------------ the build field of an identity
#
# The identity's `build` field states the commit that produced the image
# - the short revision, plus `+` and the first 8 hex of the working-tree
# delta when the tree was dirty. `records/flash-log.jsonl` holds 139
# records written against the wall-clock stamp that preceded it, so both
# forms have to resolve and the tests below hold each one open.

_B = "build/baremetal_bringup.bin"


def _rec(rev, when, dirty_sha=None, binary=_B):
    """One flash-log record, in the shape `tools/flash.py` writes."""
    return {"binary": binary, "repo_rev": rev, "when": when,
            "dirty": dirty_sha is not None, "dirty_sha": dirty_sha,
            "sha256": "0" * 64, "cc": "GCC 14.2.1", "layout": "cafef00d"}


def _with_log(tmp_path, monkeypatch, *records):
    """`provenance`, reading a log holding exactly these records.

    `REPO` is left alone so the repository questions still run against
    the real checkout; only the log moves.
    """
    import json
    sys.path.insert(0, os.path.join(REPO, "host"))
    import provenance as prov
    path = tmp_path / "flash-log.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    monkeypatch.setattr(prov, "FLASH_LOG", str(path))
    return prov


def test_build_commit_tells_a_commit_from_a_wall_clock():
    """One place decides which question a `build` field can answer.

    A caller that sniffed the string itself would be a second decision
    that drifts, and the two forms have to coexist for as long as the
    139 stamped records do.
    """
    sys.path.insert(0, os.path.join(REPO, "host"))
    import provenance as prov

    assert prov.build_commit("a905380") == ("a905380", None)
    assert prov.build_commit("a905380+1f2e3d4a") == ("a905380", "1f2e3d4a")
    assert prov.build_commit(" A905380 ") == ("a905380", None)
    # The legacy stamp, the no-repository answer, and nothing at all.
    assert prov.build_commit("Aug 27 2026 16:14:27") is None
    assert prov.build_commit("unknown") is None
    assert prov.build_commit("") is None
    assert prov.build_commit(None) is None
    # Too short to name a commit, and a delta that is not eight hex.
    assert prov.build_commit("a90538") is None
    assert prov.build_commit("a905380+1f2e3d") is None


def test_a_commit_identity_resolves_by_equality(tmp_path, monkeypatch):
    """The image states its commit, so the log is asked to match it.

    Not "which flash is newest, and did it happen after the build" -
    that is an inference from two wall clocks, and it lands on the
    newest record whenever the arithmetic cannot rule it out.
    """
    prov = _with_log(
        tmp_path, monkeypatch,
        _rec("beefbee", "2026-09-01T09:00:00-0400"),
        _rec("cafecaf", "2026-09-01T10:00:00-0400"))

    fw = prov.firmware("beefbee", "b")
    assert fw["fw_repo_rev"] == "beefbee"
    assert fw["fw_provenance"] == "matched by commit"
    assert fw["fw_flashed_at"] == "2026-09-01T09:00:00-0400"
    # The newer record is the one a timing rule would have returned.
    fw = prov.firmware("cafecaf", "b")
    assert fw["fw_repo_rev"] == "cafecaf"


def test_a_commit_absent_from_the_log_is_a_stated_absence(tmp_path,
                                                          monkeypatch):
    """The plausible wrong answer here is the newest record.

    A board running an image nobody logged has unknown provenance, and
    `missing()` refuses it. Handing back the newest flash instead would
    attribute a figure to a commit the board never ran.
    """
    prov = _with_log(
        tmp_path, monkeypatch,
        _rec("beefbee", "2026-09-01T09:00:00-0400"),
        _rec("cafecaf", "2026-09-01T10:00:00-0400"))

    assert prov.firmware("deadbee", "b") == {"fw_provenance": "unlogged"}
    assert "fw_repo_rev" in prov.missing(prov.firmware("deadbee", "b"))


def test_a_dirty_identity_names_which_dirty(tmp_path, monkeypatch):
    """Two dirty builds of one commit are two images.

    `repo_rev` is identical for every dirty state of a commit, so the
    delta hash is the whole discriminator - the same quantity
    `tools/flash.py` logs as `dirty_sha`, which is why neither side
    derives it a second way.
    """
    prov = _with_log(
        tmp_path, monkeypatch,
        _rec("beefbee", "2026-09-01T09:00:00-0400", "1" * 64),
        _rec("beefbee", "2026-09-01T10:00:00-0400", "2" * 64))

    fw = prov.firmware("beefbee+" + "1" * 8, "b")
    assert fw["fw_dirty_sha"] == "1" * 64
    assert fw["fw_flashed_at"] == "2026-09-01T09:00:00-0400"
    assert fw["fw_repo_rev"] == "beefbee-dirty"

    # A clean image is not either of them, and neither is a third delta.
    assert prov.firmware("beefbee", "b") == {"fw_provenance": "unlogged"}
    assert (prov.firmware("beefbee+" + "3" * 8, "b")
            == {"fw_provenance": "unlogged"})


def test_a_legacy_stamp_still_resolves_by_wall_clock(tmp_path, monkeypatch):
    """139 stored records can be resolved no other way.

    They predate the commit in the identity, so removing the timing path
    would make every one of them unattributable - and an unattributable
    record is what this module exists to refuse.
    """
    prov = _with_log(
        tmp_path, monkeypatch,
        _rec("beefbee", "2026-09-01T09:00:00-0400"),
        _rec("cafecaf", "2026-09-01T10:00:00-0400"))

    fw = prov.firmware("Sep 01 2026 09:30:00", "b")
    assert fw["fw_repo_rev"] == "cafecaf"
    assert fw["fw_provenance"] == "matched by build stamp"

    # An image compiled after every logged flash was flashed by nobody.
    assert (prov.firmware("Sep 01 2026 10:30:00", "b")
            == {"fw_provenance": "unlogged"})


def test_a_track_a_flash_is_not_a_track_b_commit(tmp_path, monkeypatch):
    """The track filter survives the move to equality.

    A bench that alternates tracks can hold one commit flashed to both,
    and the binary path is the only thing in the record that separates
    them.
    """
    prov = _with_log(
        tmp_path, monkeypatch,
        _rec("beefbee", "2026-09-01T09:00:00-0400",
             binary="build-a/track_a_bringup.bin"))

    assert prov.firmware("beefbee", "a")["fw_source_track"] == "A"
    assert prov.firmware("beefbee", "b") == {"fw_provenance": "unlogged"}


def test_parse_identity_carries_a_commit_build_field():
    """The identity line's last field is opaque to the parser.

    A board whose identity fails to parse reports no track, no versions
    and no image at all - the whole line is lost for one field - so the
    parser must not be the thing that has to be edited when the field's
    meaning changes.
    """
    sys.path.insert(0, os.path.join(REPO, "host"))
    import measure
    import provenance as prov

    head = ("# id: track=B fw=0.2.0 ctlver=3 framever=3 mck=78000000 "
            "adcclk=19500000 framebytes=1024 framesamples=496 build=")
    for value in ("a905380", "a905380+1f2e3d4a", "unknown",
                  "Aug 27 2026 16:14:27"):
        ident = measure.parse_identity(head + value + "\n")
        assert ident is not None, f"identity unparsed with build={value}"
        assert ident["build"] == value
        assert ident["track"] == "b"
        assert ident["mck_hz"] == 78000000
    assert prov.build_commit(
        measure.parse_identity(head + "a905380+1f2e3d4a\n")["build"]) == (
            "a905380", "1f2e3d4a")


#: Asks both paths of `build_is_current()` in one interpreter whose zone
#: the caller sets. The legacy stamp is rendered from the newest
#: firmware commit through `gmtime`, so the *string* is identical in
#: every zone and only the reading of it can move.
_TZ_PROBE = """
import subprocess, sys, time
time.tzset()
sys.path.insert(0, 'host')
import provenance as prov
g = lambda *a: subprocess.run(('git',) + a, capture_output=True,
                              text=True).stdout.strip()
rev = g('rev-parse', '--short', 'HEAD')
at = int(g('log', '-1', '--format=%at', '--', *prov.fw_source_paths('B')))
stamp = time.strftime('%b %d %Y %H:%M:%S', time.gmtime(at))
print(prov.build_is_current(rev, 'B'), prov.build_is_current(stamp, 'B'))
"""


@pytest.mark.skipif(not hasattr(time, "tzset"),
                    reason="TZ is not settable per process on this platform")
def test_build_is_current_on_a_commit_consults_no_clock():
    """The commit path answers out of the object graph, in any zone.

    The wall-clock path cannot: the stamp is parsed reader-local against
    a true epoch and nothing cancels, so an image reads current in one
    zone and stale in another - and US Eastern moves to `-0500` on
    2026-11-01, which shifts the answer under a single reader in the
    unsafe direction. That is why the field carries a commit.

    The legacy answers are the positive control. If they agreed, this
    test would be an instrument that cannot see zone dependence, and the
    commit half of it would be worth nothing.
    """
    ny = _in_subprocess(_TZ_PROBE, {"TZ": "America/New_York"}).split()
    sh = _in_subprocess(_TZ_PROBE, {"TZ": "Asia/Shanghai"}).split()

    assert ny[1] != sh[1], (
        f"the legacy stamp read {ny[1]} in America/New_York and {sh[1]} "
        f"in Asia/Shanghai; if those agree this test cannot detect a "
        f"timezone-dependent answer and proves nothing about the other")
    assert ny[0] == sh[0] == "True", (
        f"a commit-bearing build read {ny[0]} in America/New_York and "
        f"{sh[0]} in Asia/Shanghai; HEAD holds the newest firmware "
        f"commit by construction and no zone may change that")
