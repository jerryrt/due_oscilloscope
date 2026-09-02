"""What an image says it was built from.

The `build=` field of the `# id:` line, and the `build[24]` field of the
control channel's IDENTITY record, both carry `FW_GIT_REV` - the commit
the image was built from, with the working-tree delta hash appended when
the tree was dirty. Nothing else in the image varies between two builds
of one source state, which is what makes `tools/reproducible.py` report
zero and what lets a measurement name one image rather than a class of
them.

None of that needs a board. `console_identity()` touches no register, so
the firmware's own source is compiled and run here and the line it
prints is read back through `measure.parse_identity` - the same function
the suite uses against a real one. The control-channel copy cannot be
run on a host (`drivers/ctl_port.c` reaches `sam.h`), so it is held by
source, per track, which is the same shape `test_shared_source.py` uses
for the fields it guards.
"""

import os
import re
import subprocess

import pytest

import hostcc

pytestmark = pytest.mark.smoke

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SHARED = os.path.join(REPO, "lib", "due_shared", "src")
HARNESS = os.path.join(HERE, "identity", "harness.c")

#: A value no build could produce, so a line carrying it can only have
#: got it from the header this test wrote. The dirty form, because it is
#: the longer of the two and the one with a character - `+` - that a
#: parser could choke on.
SENTINEL = "0ddba11+f00dfeed"

#: Every source file compiled into a firmware image. `tools/` and
#: `host/` are excluded on purpose: they are not on a board, and
#: `tools/flash.py` legitimately discusses the old stamp.
FIRMWARE_DIRS = (
    os.path.join(REPO, "lib", "due_shared", "src"),
    os.path.join(REPO, "drivers"),
    os.path.join(REPO, "bsp"),
    os.path.join(REPO, "apps"),
    os.path.join(REPO, "sketches"),
)


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


def _code(text):
    """Source with comments removed.

    The same reason `test_console_out.py` strips first and asks second:
    three source-scanning guards written on this project have matched
    text in a comment before they matched code.
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


@pytest.fixture(scope="module")
def identity_line(tmp_path_factory):
    """The `# id:` line the firmware source emits, built here and run.

    `FW_GIT_REV` comes from a header this test writes rather than from
    the build tree, so the value on the line is one only this file could
    have supplied. A test that read the build tree's header would agree
    with an image built from `__DATE__` as readily as with one built
    from the commit.
    """
    cc = hostcc.cc()
    if not cc:
        pytest.skip("no host C compiler; install gcc or clang to run this")

    tmp = tmp_path_factory.mktemp("identity")
    inc = tmp / "gen"
    inc.mkdir()
    (inc / "fw_git_rev.h").write_text(
        "#ifndef FW_GIT_REV_H\n"
        "#define FW_GIT_REV_H\n"
        '#define FW_GIT_REV "%s"\n'
        "#endif\n" % SENTINEL)

    exe = str(tmp / "identity")
    proc = subprocess.run(
        [cc, "-std=c11", "-Wall", "-Wextra", "-I", SHARED, "-I", str(inc),
         "-o", exe,
         os.path.join(SHARED, "console.c"),
         os.path.join(SHARED, "console_out.c"),
         HARNESS],
        capture_output=True, text=True, env=hostcc.cc_env())
    assert proc.returncode == 0, proc.stderr

    run = subprocess.run([exe], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return run.stdout


def test_the_identity_line_carries_the_build_revision(identity_line):
    """`build=` is FW_GIT_REV and nothing else.

    The whole of phase 0 rests on this one substitution: a wall-clock
    stamp cannot be compared across timezones and cannot name a source
    state, and it is the only thing that differed between two builds of
    one tree.
    """
    import measure

    ident = measure.parse_identity(identity_line)
    assert ident is not None, (
        "the firmware's own identity line does not parse: %r"
        % identity_line)
    assert ident["build"] == SENTINEL, (
        "build=%r on a line built with FW_GIT_REV=%r"
        % (ident["build"], SENTINEL))
    assert ident["track"] == "b"
    assert ident["mck_hz"] == 78000000


def test_the_identity_line_reports_the_shared_control_version(identity_line):
    """`ctlver` on the line is `CTL_VERSION`, not a number typed twice."""
    import measure

    m = re.search(r"^#define CTL_VERSION\s+(\d+)\s*$",
                  _read(os.path.join("lib", "due_shared", "src",
                                     "ctl_wire.h")), re.M)
    assert m, "ctl_wire.h no longer defines CTL_VERSION on one line"
    assert measure.parse_identity(identity_line)["ctl_version"] == int(
        m.group(1))


def test_the_host_speaks_the_version_the_device_answers():
    """`host/control.py` and `ctl_wire.h` name one number.

    The device refuses a frame whose version is not its own, so a host
    left behind fails on the first exchange - loudly, which is the
    design. This is the guard that makes the bump mechanical: the two
    constants live in different languages and there is nothing else
    holding them equal.
    """
    m = re.search(r"^#define CTL_VERSION\s+(\d+)\s*$",
                  _read(os.path.join("lib", "due_shared", "src",
                                     "ctl_wire.h")), re.M)
    h = re.search(r"^VERSION = (\d+)\s*$",
                  _read(os.path.join("host", "control.py")), re.M)
    assert m and h, "one of the two version constants moved or changed shape"
    assert int(m.group(1)) == int(h.group(1)), (
        "ctl_wire.h says CTL_VERSION %s and host/control.py says VERSION %s; "
        "a host and a board that disagree cannot exchange one frame"
        % (m.group(1), h.group(1)))


def test_every_track_sends_the_build_revision_on_the_wire():
    """Both `ctl_port` copies fill `build[24]` from FW_GIT_REV.

    `main()` is not the only file with a copy per track: the per-opcode
    data is too, and there are two of these. CLAUDE.md's rule for
    `main()` - when you add to one track, grep the others - applies here
    for the same reason, and the console line above cannot see either of
    them.
    """
    for rel in (os.path.join("drivers", "ctl_port.c"),
                os.path.join("sketches", "bringup", "ctl_port.cpp")):
        code = _code(_read(rel))
        assert "static const char build[] = FW_GIT_REV;" in code, (
            "%s does not fill IDENTITY's build field from FW_GIT_REV" % rel)


def test_no_firmware_source_stamps_a_wall_clock():
    """`__DATE__` and `__TIME__` are gone from everything on a board.

    Not tidiness. They are the only non-determinism the build had, so
    one reintroduced anywhere takes `tools/reproducible.py` back to a
    non-zero report and takes every image back to naming a class rather
    than a state.
    """
    hits = []
    for root in FIRMWARE_DIRS:
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if not name.endswith((".c", ".h", ".cpp", ".ino")):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8", errors="replace") as fh:
                    code = _code(fh.read())
                if "__DATE__" in code or "__TIME__" in code:
                    hits.append(os.path.relpath(path, REPO))
    assert not hits, (
        "a wall-clock stamp is compiled into firmware source: %s"
        % ", ".join(sorted(hits)))
