"""The post-flash boot check. No board required.

bossac reports "Verify successful" for a write that lands perfectly and
still leaves the board in ROM SAM-BA - measured at roughly two attempts
in three on macOS on 2026-08-25, with no diagnostic anywhere. The board
then has no native port and answers nothing, which is indistinguishable
from firmware that hangs on boot. In one session it produced three false
conclusions, the worst of which was "this branch does not boot" about a
branch that boots fine; an interleaved control against `main` was what
disproved it, after `main` failed two attempts in three in the same
rotation.

So the check is not a convenience. An image A/B is the core experimental
method in the issue #5 investigation, and a flash that silently does not
run corrupts every one of them.
"""

import os
import pytest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import flash  # noqa: E402

SAMBA_NODE = "/dev/cu.usbmodem141301"


def _nodes(seq):
    """Stand in for samba_nodes(), returning one answer per call so a
    bootloader node can be made to disappear partway through a wait."""
    it = iter(seq)
    last = []

    def f():
        nonlocal last
        try:
            last = next(it)
        except StopIteration:
            pass
        return last
    return f


def test_a_bootloader_node_that_goes_away_is_a_boot(monkeypatch):
    monkeypatch.setattr(flash, "samba_nodes",
                        _nodes([[SAMBA_NODE], [SAMBA_NODE], []]))
    assert flash.wait_for_boot({SAMBA_NODE}, timeout=5.0)


def test_a_bootloader_node_that_stays_is_not_a_boot(monkeypatch):
    monkeypatch.setattr(flash, "samba_nodes", _nodes([[SAMBA_NODE]]))
    assert not flash.wait_for_boot({SAMBA_NODE}, timeout=1.5)


def test_the_board_coming_back_at_a_new_bootloader_path_is_not_a_boot(
        monkeypatch):
    """Re-enumeration need not reuse the device path, so identity of the
    node is not what is being tested - presence of any bootloader is.
    Testing `& watched` alone would call this a boot."""
    monkeypatch.setattr(flash, "samba_nodes",
                        _nodes([[SAMBA_NODE], ["/dev/cu.usbmodem141401"]]))
    assert not flash.wait_for_boot({SAMBA_NODE}, timeout=1.5)


def test_nothing_to_watch_is_not_reported_as_a_failure(monkeypatch):
    """Flashed through the programming port: no bootloader node was ever
    attributed to this board, so there is no negative evidence to be had
    and the check must not invent a failure from its own blindness."""
    monkeypatch.setattr(flash, "samba_nodes", _nodes([[SAMBA_NODE]]))
    assert flash.wait_for_boot(set(), timeout=1.5)


# ------------------------------------------------- a port someone else holds

class _FakeSerial:
    """serial.Serial, refusing to open the first `refuse` times."""
    refuse = 0
    opened = 0

    def __init__(self):
        self.port = None
        self.baudrate = None

    def open(self):
        import serial
        if _FakeSerial.opened < _FakeSerial.refuse:
            _FakeSerial.opened += 1
            raise serial.SerialException(
                "could not open port 'COM7': "
                "PermissionError(13, 'Access is denied.', None, 5)")
        _FakeSerial.opened += 1

    def close(self):
        pass


def test_a_held_port_is_waited_out_rather_than_failed(monkeypatch):
    """A killed test run leaves its Python holding the programming port
    and Windows reports the next open as "Access is denied", which reads
    like a permissions problem and is not one. The handle goes when the
    process does, a moment later than the kill."""
    import serial
    _FakeSerial.refuse, _FakeSerial.opened = 3, 0
    monkeypatch.setattr(serial, "Serial", _FakeSerial)
    s = flash.open_port("COM7", 1200, tries=6, delay=0.0)
    assert s is not None
    assert _FakeSerial.opened == 4          # three refusals then the open


def test_a_port_held_for_ever_says_what_to_do(monkeypatch):
    """Three flashes failed this way in one session and each looked like
    a different problem, so the message has to name the cause."""
    import serial
    _FakeSerial.refuse, _FakeSerial.opened = 99, 0
    monkeypatch.setattr(serial, "Serial", _FakeSerial)
    with pytest.raises(SystemExit) as e:
        flash.open_port("COM7", 1200, tries=3, delay=0.0)
    assert "still held" in str(e.value)
    assert "Stop-Process" in str(e.value)


def test_a_real_failure_is_not_retried(monkeypatch):
    """Only a held handle is worth waiting on. A port that does not exist
    must fail at once rather than after six seconds of hope."""
    import serial

    class _Missing(_FakeSerial):
        def open(self):
            raise serial.SerialException("could not open port 'COM99': "
                                         "FileNotFoundError(2, ...)")

    monkeypatch.setattr(serial, "Serial", _Missing)
    with pytest.raises(serial.SerialException):
        flash.open_port("COM99", 1200, tries=6, delay=0.0)


# ------------------------------------------------ the image against its source

def test_an_image_older_than_its_sources_is_refused(tmp_path, monkeypatch):
    """Issue #35: a stale image logged under the current commit.

    `enforce_clean_build` runs `--target clean` as a dependency of the
    link. On windows-desk's Ninja the clean deleted the objects the same
    plan was about to link, the build failed, and `flash.py` then
    flashed the *previous* image and `_log_flash` wrote the current
    commit beside its sha. Anyone reading `records/flash-log.jsonl`
    afterwards would conclude the board ran a commit it had never run.

    That is the one thing the flash log must not do, because
    `host/provenance.py` and every baseline are built on believing it.
    So the last thing that touches the image checks it.
    """
    binary = tmp_path / "baremetal_bringup.bin"
    binary.write_bytes(b"\x00" * 16)
    src = tmp_path / "src" / "clock.c"
    src.parent.mkdir()
    src.write_text("int x;\n")
    os.utime(binary, (1000, 1000))
    os.utime(src, (2000, 2000))

    monkeypatch.setattr(flash, "newest_source",
                        lambda b: (str(src), 2000.0))
    with pytest.raises(SystemExit) as e:
        flash.check_not_stale(str(binary), allow=False)
    assert "older than the firmware source" in str(e.value)


def test_a_current_image_is_not_refused(tmp_path, monkeypatch):
    binary = tmp_path / "baremetal_bringup.bin"
    binary.write_bytes(b"\x00" * 16)
    os.utime(binary, (3000, 3000))
    monkeypatch.setattr(flash, "newest_source", lambda b: ("whatever", 2000.0))
    flash.check_not_stale(str(binary), allow=False)     # must not raise


def test_stale_ok_flashes_but_says_so(tmp_path, monkeypatch, capsys):
    """The override exists because a checkout can move an mtime back.

    A false alarm is the safe direction, so it must be escapable - but
    never silently, because the log entry it produces is the thing at
    stake.
    """
    binary = tmp_path / "baremetal_bringup.bin"
    binary.write_bytes(b"\x00" * 16)
    os.utime(binary, (1000, 1000))
    monkeypatch.setattr(flash, "newest_source", lambda b: ("src.c", 2000.0))
    flash.check_not_stale(str(binary), allow=True)      # must not raise
    assert "stale image on request" in capsys.readouterr().out


def test_the_source_list_is_the_provenance_one(tmp_path):
    """One definition of what a firmware image is built from.

    If this script and `host/provenance.py` kept separate lists they
    would drift, and the drift would be invisible: the flash would pass
    a check the provenance report would have failed, or the reverse.
    `bsp/` was missing from the provenance list until 2026-08-30 and
    nothing noticed for months.
    """
    sys.path.insert(0, os.path.join(flash.REPO, "host"))
    import provenance

    # A Track B binary is checked against Track B's sources, and the
    # track comes from the binary's own path.
    b = os.path.join(flash.REPO, "build", "baremetal_bringup.bin")
    assert provenance.track_of_binary(b) == "B"
    newest, at = flash.newest_source(b)
    assert newest is not None and at > 0
    rel = os.path.relpath(newest, flash.REPO)
    assert rel.split(os.sep)[0] in provenance.FW_SOURCE_TRACKS["B"], (
        f"flash.py looked at {rel}, which is not in the provenance "
        f"list for Track B")


def test_the_log_says_which_dirty_not_merely_that_it_was(tmp_path,
                                                         monkeypatch):
    """Issue #35: two dirty images from one commit were indistinguishable.

    `repo_rev` is identical for every dirty state of one commit, so on
    its own it says only that the tree was dirty. mac-bench's log has a
    deliberately-reverted control image and a `main` image on adjacent
    lines, both `(dirty)`, with nothing to tell them apart. A hash of
    the working-tree delta tells them apart: same commit and same edits
    share it, a revert changes it. It is the quantity the board reports
    the first eight characters of, after the `+` in `build=`.

    Driven through the real `_log_flash` with a fake `git`, because the
    property under test is what the record contains and not what git
    says - and a test that shelled out to a real repository would be
    measuring this checkout's tidiness.
    """
    import json

    binary = tmp_path / "img.bin"
    binary.write_bytes(b"\x00" * 32)
    log = tmp_path / "flash-log.jsonl"
    monkeypatch.setattr(flash, "FLASH_LOG", str(log))

    state = {"diff": "--- a/drivers/acq.c\n+++ b/drivers/acq.c\n+one\n"}

    def fake_run(cmd, **kw):
        class R:
            pass
        r = R()
        if cmd[:2] == ("git", "diff"):
            r.stdout = state["diff"]
        elif cmd[:2] == ("git", "status"):
            r.stdout = " M drivers/acq.c\n"
        elif "rev-parse" in cmd:
            r.stdout = "abc1234\n"
        else:
            r.stdout = ""
        return r

    monkeypatch.setattr(flash.subprocess, "run", fake_run)

    flash._log_flash(str(binary))
    state["diff"] = "--- a/drivers/acq.c\n+++ b/drivers/acq.c\n+two\n"
    flash._log_flash(str(binary))

    rows = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
    assert len(rows) == 2
    a, b = rows

    assert a["repo_rev"] == b["repo_rev"], "the fake git moved; test is wrong"
    assert a["dirty"] is True and b["dirty"] is True
    assert a["sha256"] == b["sha256"], (
        "the binary differs, so this proves nothing about the delta hash")

    assert a["dirty_sha"] != b["dirty_sha"], (
        "two different working trees at one commit produced the same "
        "dirty_sha; the log still cannot say which dirty an image was "
        "built from, which is the whole of issue #35's open item")


def test_a_clean_tree_logs_no_dirty_sha(tmp_path, monkeypatch):
    """None rather than the hash of an empty diff.

    A hash of "" is a real-looking value that would compare equal
    between two clean builds and unequal to nothing, which invites
    reading it as evidence. Absence is the honest spelling.
    """
    import json

    binary = tmp_path / "img.bin"
    binary.write_bytes(b"\x00" * 32)
    log = tmp_path / "flash-log.jsonl"
    monkeypatch.setattr(flash, "FLASH_LOG", str(log))

    def fake_run(cmd, **kw):
        class R:
            pass
        r = R()
        r.stdout = "abc1234\n" if "rev-parse" in cmd else ""
        return r

    monkeypatch.setattr(flash.subprocess, "run", fake_run)
    flash._log_flash(str(binary))

    rec = json.loads(log.read_text().splitlines()[0])
    assert rec["dirty"] is False
    assert rec["dirty_sha"] is None


# ---------------------------------------------------------------------
# The two defects found on linux-x1 while building #35's fallback arm.
# Neither is macOS-specific, and neither was reachable before a touch
# that resets the board twice existed.


def test_a_bootloader_node_seen_once_is_not_believed(monkeypatch):
    """A sighting during the churn is provisional.

    The close-at-1200 arm resets the board, and on a host that also
    re-fires on the reopen it resets a second time. The first bootloader
    node then appears, goes, and comes back under a different name. Take
    the first sighting and bossac is handed a path that no longer
    exists.
    """
    monkeypatch.setattr(flash, "samba_nodes",
                        _nodes([[], ["/dev/ttyACM1"], [], [],
                                ["/dev/ttyACM2"], ["/dev/ttyACM2"]]))
    assert flash._await_samba(set(), timeout=5.0) == "/dev/ttyACM2"


def test_a_settled_bootloader_node_is_returned(monkeypatch):
    monkeypatch.setattr(flash, "samba_nodes",
                        _nodes([["/dev/ttyACM1"], ["/dev/ttyACM1"]]))
    assert flash._await_samba(set(), timeout=5.0) == "/dev/ttyACM1"


def test_no_bootloader_node_is_not_seen_rather_than_failed(monkeypatch):
    """None means "not seen". It never means "the touch failed" - only
    usb_nodes() separates those, and the caller does that itself."""
    monkeypatch.setattr(flash, "samba_nodes", _nodes([[]]))
    assert flash._await_samba(set(), timeout=1.5) is None


def test_bossac_is_bounded(monkeypatch):
    """bossac given a port that is not there spins at 100% CPU for ever
    with no output and no exit - measured on linux-x1, four minutes
    before it was killed by hand. Unbounded, the flash simply never
    returns, which reads as a wedged board rather than a wrong argument.
    """
    assert flash.BOSSAC_TIMEOUT_S > 0
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tools", "flash.py")).read()
    assert "timeout=BOSSAC_TIMEOUT_S" in src, \
        "the bossac invocation lost its bound"
    assert "subprocess.TimeoutExpired" in src, \
        "the bound is not caught, so it raises instead of failing the route"


def test_a_board_already_in_the_bootloader_is_not_diagnosed(monkeypatch):
    """The discriminator has nothing to measure on an erased board.

    "Nothing on the bus moved" means the touch was not seen - but only
    when there was something to move. A board already in ROM SAM-BA has
    no firmware nodes to lose and its bootloader node is not fresh, so
    the bus looks identical however well the touch worked. Measured on
    linux-x1: `--port` against such a board took the macOS-shaped
    fallback on Linux, harmlessly and for the wrong reason.
    """
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tools", "flash.py")).read()
    assert "and not before and not args.close_at_1200" in src, (
        "the fallback no longer excludes a board that was already in "
        "the bootloader; it will report 'nothing on the bus moved' "
        "about a board that reset perfectly")


# ------------------------------------------ the layout field in the log
#
# Every flash logs `layout`, and the field's whole job is to say whether
# two benches ran the same image. It can only do that if it is a
# property of the ELF. `nm` emits symbols that share an address in
# whatever order it pleases - 8 addresses in a Track B image carry more
# than one symbol, most of them weak aliases for `Default_Handler` - so
# a hash over its raw output is partly a hash of the reader, and one ELF
# read by Debian's binutils and by xPack's hashed two ways.

import image_fingerprint  # noqa: E402

#: One symbol table, as `nm --defined-only` prints it. Two addresses
#: carry more than one symbol, and one of those pairs differs only in
#: the type column - so a key of (address, name) is not total over it.
_TIED = [
    "00080000 T exception_table",
    "00080000 T _sfixed",
    "00080000 W Default_Handler",
    "000800f4 t h_fws",
    "20070000 D _sdata",
    "20070000 B _sdata",
    "20071000 B ring",
]


def _layout(monkeypatch, lines):
    monkeypatch.setattr(image_fingerprint, "_run",
                        lambda argv: "\n".join(lines))
    return image_fingerprint.layout("no-such.elf")


def _parts(monkeypatch, lines):
    monkeypatch.setattr(image_fingerprint, "_run",
                        lambda argv: "\n".join(lines))
    return image_fingerprint.layout_parts("no-such.elf")


def test_one_symbol_table_hashes_one_way_however_it_arrived(monkeypatch):
    """The same records in a different order are the same image.

    Reversing each tie group is what the two binutils builds actually
    differ by; the full reversal is the stronger statement, that no
    ordering of these records reaches a second hash.
    """
    ties_swapped = [_TIED[2], _TIED[1], _TIED[0], _TIED[3],
                    _TIED[5], _TIED[4], _TIED[6]]

    first = _layout(monkeypatch, _TIED)
    assert _layout(monkeypatch, ties_swapped) == first, \
        "symbols sharing an address hash differently depending on order"
    assert _layout(monkeypatch, list(reversed(_TIED))) == first
    assert _layout(monkeypatch, sorted(_TIED)) == first


def test_a_moved_symbol_still_moves_the_hash(monkeypatch):
    """The guard above passes trivially if the hash stops watching.

    An order-independent hash that is also content-independent is worse
    than none, so hold the three ways an image can actually differ:
    an address, a name, and the type column that (address, name) alone
    would drop.
    """
    first = _layout(monkeypatch, _TIED)
    moved = list(_TIED)
    moved[6] = "20071004 B ring"
    renamed = list(_TIED)
    renamed[3] = "000800f4 t h_reset"
    retyped = list(_TIED)
    retyped[2] = "00080000 T Default_Handler"

    assert _layout(monkeypatch, moved) != first, "a moved symbol went unseen"
    assert _layout(monkeypatch, renamed) != first
    assert _layout(monkeypatch, retyped) != first, \
        "the type column is not hashed, so the sort key is not total"


def test_the_parts_read_the_table_the_layout_hashes(monkeypatch):
    """`symbols` and `addresses` split `layout`, so they share its order.

    Two readers of `nm` in one file is how the split acquires a
    disagreement of its own.
    """
    parts = _parts(monkeypatch, _TIED)
    assert parts["n_symbols"] == len(_TIED)
    assert parts["n_addresses"] == 4
    assert _parts(monkeypatch, list(reversed(_TIED))) == parts


def test_the_flash_log_does_not_compute_a_layout_of_its_own(tmp_path,
                                                            monkeypatch):
    """One definition, or two answers to "is this the same image".

    `tools/flash.py` writes the field and `image_fingerprint` defines
    it; a copy there would drift from the one the fingerprint tool
    prints, and the two are compared across benches by hand.
    """
    binary = tmp_path / "baremetal_bringup.bin"
    binary.write_bytes(b"\x00")
    (tmp_path / "baremetal_bringup.elf").write_bytes(b"\x7fELF")

    monkeypatch.setattr(image_fingerprint, "compiler",
                        lambda elf: "CC-SENTINEL")
    monkeypatch.setattr(image_fingerprint, "layout",
                        lambda elf: "LAYOUT-SENTINEL")

    assert flash._image_identity(str(binary)) == {
        "cc": "CC-SENTINEL", "layout": "LAYOUT-SENTINEL"}


# --------------------------------------- which environment built the image
#
# `cc` says which compiler and `layout` says where it put things. Neither
# says what the compiler was running inside, so a containerised build is
# otherwise attributable to a commit and a compiler and to nothing else.
# `docker/build-firmware.sh` writes the answer beside the artifacts and
# `_build_env` reads it back.
#
# Three states, and the third is the one that needs a mechanism: a build
# directory outlives the build that filled it, so a record that merely
# sits in the right place names the environment of whatever was built
# there last. Every artifact is hashed into the record for that reason.

import hashlib                                              # noqa: E402
import json                                                 # noqa: E402

CONTAINER = {
    "build_env": "container",
    "build_image": "due-build:15.2.1-1.1",
    "build_image_id": "sha256:" + "e" * 64,
    "build_image_content": "c" * 64,
}


def _built(tmp_path, body=b"firmware", record=None, name=None):
    """A binary, optionally beside the record a build would have left."""
    binary = tmp_path / "baremetal_bringup.bin"
    binary.write_bytes(body)
    if record is not None:
        rec = dict(record)
        rec.setdefault("artifacts", {
            name or binary.name: hashlib.sha256(body).hexdigest()})
        (tmp_path / flash.BUILD_ENV_FILE).write_text(json.dumps(rec))
    return str(binary)


def test_a_container_build_names_the_image_that_ran_it(tmp_path):
    assert flash._build_env(_built(tmp_path, record=CONTAINER)) == CONTAINER


def test_a_build_outside_a_container_says_so(tmp_path):
    """`host` is a claim the build made, not one this inferred."""
    got = flash._build_env(_built(tmp_path, record={"build_env": "host"}))
    assert got == {"build_env": "host", "build_image": None,
                   "build_image_id": None, "build_image_content": None}


def test_a_build_that_said_nothing_is_not_called_a_host_build(tmp_path):
    """The plausible wrong answer is `host`, because most builds are.

    It would also be right most of the time, which is what makes it
    dangerous: this cannot tell a bench build from a container build
    whose record was lost, and a field that is there gets trusted where
    a missing one gets questioned.
    """
    got = flash._build_env(_built(tmp_path))
    assert got["build_env"] == flash.UNRECORDED_ENV
    assert got["build_image"] is None
    assert got["build_image_content"] is None


def test_a_rebuild_does_not_inherit_the_previous_builds_container(tmp_path):
    """The failure this whole binding exists for.

    A container build leaves its record in the directory; a later build
    there overwrites the binary and not the record, and every field
    would then name an environment that did not produce these bytes.
    """
    binary = _built(tmp_path, record=CONTAINER)
    assert flash._build_env(binary)["build_env"] == "container"

    with open(binary, "wb") as f:
        f.write(b"rebuilt by something else")

    got = flash._build_env(binary)
    assert got["build_env"] == flash.UNRECORDED_ENV, (
        f"a rebuilt binary kept the previous build's environment: {got!r}")
    assert got["build_image_id"] is None


def test_a_record_that_describes_another_artifact_is_not_this_ones(tmp_path):
    """One record covers a whole build directory, so the name is part of
    the match. Track A's binary must not answer for Track B's."""
    binary = _built(tmp_path, record=CONTAINER, name="track_a_bringup.bin")
    assert flash._build_env(binary)["build_env"] == flash.UNRECORDED_ENV


def test_the_flashing_host_cannot_supply_the_container_itself(monkeypatch,
                                                              tmp_path):
    """`flash.py` runs on the bench, outside any container.

    Reading the environment here rather than the record would let it
    claim whichever shell it was launched from - and a shell that has
    exported these is exactly where a flash gets run.
    """
    monkeypatch.setenv("DUE_BUILD_IMAGE", "due-build:15.2.1-1.1")
    monkeypatch.setenv("DUE_BUILD_IMAGE_ID", "sha256:" + "e" * 64)
    monkeypatch.setenv("DUE_BUILD_IMAGE_CONTENT", "c" * 64)
    got = flash._build_env(_built(tmp_path))
    assert got["build_env"] == flash.UNRECORDED_ENV, (
        f"the flashing host's environment reached the log: {got!r}")


def test_the_log_records_the_environment_that_built_the_image(tmp_path,
                                                              monkeypatch):
    """Through the real `_log_flash`, because the fields are worth
    something only if they reach the file a reader opens."""
    binary = _built(tmp_path, record=CONTAINER)
    monkeypatch.setattr(flash, "FLASH_LOG", str(tmp_path / "log.jsonl"))
    monkeypatch.setattr(flash, "image_work_tree", lambda b: None)

    flash._log_flash(binary)

    with open(tmp_path / "log.jsonl", encoding="utf-8") as fh:
        rec = json.loads(fh.readline())
    for k, v in CONTAINER.items():
        assert rec[k] == v, f"{k} reached the log as {rec[k]!r}"
