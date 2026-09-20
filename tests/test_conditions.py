"""A row's conditions have one home, and every standing tool uses it.

`provenance.conditions()` replaced three entry points on 2026-09-20 -
`collect()`, `run_fields()` and the dataclasses' `via` - after a count
of the call sites found 32 tools on one, 11 on the other, and two that
called both. The old names remain as aliases for one release.

Two of the fields it adds were never recorded anywhere: `checkout` and
`checkout_fs`, without which windows-desk's drvfs-against-ext4 results
were comparable only by hand labels in issue comments; and `tool`,
which says which instrument at which revision wrote the row.

THE GUARD IS DERIVED FROM THE TREE, BY A RULE. The set of record-writing
tools is every `tools/*.py` that names a path under `records/` and
writes rows - an append-mode open, a JSON line, `--append`, or the
`repeat.Recorder`; a write-mode open alone is a reader producing a page - EXCEPT tools named for an issue (`issue<N>`
anywhere in the name). Those are one-shot experiment scripts for closed
investigations whose rows will not be written again; holding them to a
new call means editing frozen scripts so a guard can stay green, which
is how a guard becomes expensive and acquires a `-k`. The exclusion is
stated here as a rule rather than kept as a list, so it cannot rot.

A floor on the set's size is what stops an empty glob passing: a guard
that examined nothing and reported the property protected is the
failure this project names first.
"""

import glob
import os
import re
import subprocess
import sys

import pytest

pytestmark = pytest.mark.smoke

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "host"))

import provenance                                             # noqa: E402

#: Fewer standing record-writing tools than this and the set was not
#: taken from the tree. Eight on 2026-09-20.
FLOOR = 8

_ISSUE_TOOL = re.compile(r"issue\d+")
#: Rows, not files: an append-mode open, a JSON line, `--append`, or the
#: Recorder. A write-mode open alone is a page or a summary being
#: written from a record, which is a reader - the first draft of this
#: selector counted `stack_report.py` and `temp_bands.py` for exactly
#: that, and would have held two readers to a writer's obligation.
_WRITES_ROWS = re.compile(
    r'open\((?:[^()]|\([^()]*\))*?["\']ab?["\']'      # an append-mode open
    r'|\.write\(json\.dumps'                          # a JSON line
    r'|--append'                                      # a row appended by flag
    r'|repeat\.Recorder\(')                           # rows through Recorder
_REACHES = re.compile(r"\b(?:provenance|prov)\.(conditions|collect|run_fields)\(")


def _source(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def standing_record_writers():
    """Every standing tool that writes rows under records/, from the tree."""
    out = []
    for path in sorted(glob.glob(os.path.join(REPO, "tools", "*.py"))):
        if _ISSUE_TOOL.search(os.path.basename(path)):
            continue
        src = _source(path)
        if "records/" in src and _WRITES_ROWS.search(src):
            out.append(path)
    return out


def _calls(src):
    """Call lines only: a docstring naming `provenance.collect()` is not
    a call, and the first draft of this guard was satisfied by one."""
    hits = 0
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("`"):
            continue
        if _REACHES.search(line):
            hits += 1
    return hits


def test_the_set_is_taken_from_the_tree_and_is_not_empty():
    tools = standing_record_writers()
    assert len(tools) >= FLOOR, (
        f"{len(tools)} standing record-writing tools found, below the "
        f"floor of {FLOOR}: the selector is not seeing the tree, or tools "
        f"were renamed to look like issue one-shots. Found: "
        f"{[os.path.basename(t) for t in tools]}")


def test_every_standing_record_writer_reaches_conditions():
    tools = standing_record_writers()
    missing = [os.path.basename(t) for t in tools if _calls(_source(t)) == 0]
    assert not missing, (
        f"standing record-writing tools that never reach "
        f"provenance.conditions() (or its aliases): {missing}. A row "
        f"written without it carries fewer fields than the last one, and "
        f"a null is indistinguishable from 'not measured here' once the "
        f"session ends")


#: The keys the two old entry points returned on 2026-09-20, read off
#: their implementations before they became aliases - hardcoded here on
#: purpose, so that a key dropped from conditions() fails this rather
#: than being snapshotted back from the function under test.
_COLLECT_KEYS = {"taken_at", "host_os", "host_machine", "python",
                 "repo_rev", "wiring", "wiring_since", "wiring_source",
                 "bench", "instrument"}
_RUN_FIELDS_KEYS = {"track", "fw_repo_rev", "repo_rev", "fw_build",
                    "fw_cc", "fw_layout", "fw_build_env",
                    "fw_build_image_content"}
_NEW_KEYS = {"checkout", "checkout_fs", "suite_context", "tool", "via",
             "uptime_ms", "board_serial"}


def test_conditions_carries_every_key_the_old_names_did_and_the_new_ones():
    c = provenance.conditions()
    r = provenance.run_fields()
    old = provenance.collect()
    assert _COLLECT_KEYS <= set(old), _COLLECT_KEYS - set(old)
    assert _RUN_FIELDS_KEYS <= set(r), _RUN_FIELDS_KEYS - set(r)
    assert _NEW_KEYS <= set(c), _NEW_KEYS - set(c)
    # The aliases return the one dict, not their old subsets.
    assert set(old) == set(c) and set(r) == set(c) | {"track"}
    assert r["track"] == "unknown", "run_fields keeps its board-free default"


def test_checkout_fs_is_read_from_the_mount_table_and_matches_findmnt():
    c = provenance.conditions()
    assert c["checkout"] == REPO
    if not os.path.exists(provenance.MOUNTS):
        pytest.skip("no mount table on this host, so checkout_fs is null "
                    "by design")
    want = subprocess.run(["findmnt", "-no", "FSTYPE", "--target", REPO],
                          capture_output=True, text=True)
    if want.returncode != 0:
        pytest.skip("findmnt is not available to check against")
    assert c["checkout_fs"] == want.stdout.strip()


def test_a_missing_mount_table_gives_null_rather_than_a_guess(tmp_path,
                                                              monkeypatch):
    monkeypatch.setattr(provenance, "MOUNTS", str(tmp_path / "no-such"))
    assert provenance.conditions()["checkout_fs"] is None
    # And the longest matching mount point wins over `/`.
    table = tmp_path / "mounts"
    table.write_text("rootfs / ext4 rw 0 0\n"
                     f"C:\\134 {REPO} 9p rw 0 0\n", encoding="utf-8")
    monkeypatch.setattr(provenance, "MOUNTS", str(table))
    assert provenance.conditions()["checkout_fs"] == "9p"


def test_the_tool_carries_the_trees_revision():
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                          capture_output=True, text=True, check=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                           capture_output=True, text=True, check=True)
    want = head.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")
    tool = provenance.conditions()["tool"]
    assert tool["rev"] == want and tool["name"]
    # A caller's own identity is kept verbatim.
    mine = {"name": "x", "rev": "y"}
    assert provenance.conditions(tool=mine)["tool"] == mine


def test_uptime_and_via_are_null_unless_a_caller_read_them():
    c = provenance.conditions()
    assert c["uptime_ms"] is None and c["via"] is None
    d = provenance.conditions(via="control", uptime_ms=1234)
    assert d["via"] == "control" and d["uptime_ms"] == 1234


# --- which Due wrote the row -----------------------------------------------
#
# The owner is rotating the three boards across the three benches, and
# until this field no row said which board produced it: bench.json says
# the wiring, the flash log the image. The identity is the programming
# port's USB serial - the ATmega16U2's per-unit string. The native
# port's serial is `B-01`, firmware-defined and the same on every board
# of a track, so it would name the track and not the board.

def _fake_nodes(monkeypatch, nodes):
    import ports
    monkeypatch.setattr(ports, "_pyserial_nodes", lambda: nodes)


def test_board_serial_is_the_programming_ports_serial(monkeypatch):
    _fake_nodes(monkeypatch, [
        ("/dev/ttyACM1", 0x2341, 0x003E, 0, "B-01"),
        ("/dev/ttyACM0", 0x2341, 0x003D, 0, "134484749393514068D5"),
        ("/dev/ttyACM2", 0x2341, 0x003E, 2, "B-01"),
    ])
    assert provenance.conditions()["board_serial"] == "134484749393514068D5"


def test_no_programming_port_is_null_not_a_guess(monkeypatch):
    _fake_nodes(monkeypatch, [])
    assert provenance.conditions()["board_serial"] is None


def test_the_native_ports_serial_is_never_taken(monkeypatch):
    """`B-01` is the track's name for itself, not the board's."""
    _fake_nodes(monkeypatch, [
        ("/dev/ttyACM1", 0x2341, 0x003E, 0, "B-01"),
        ("/dev/ttyACM2", 0x2341, 0x003E, 2, "B-01"),
    ])
    got = provenance.conditions()["board_serial"]
    assert got is None and got != "B-01"


def test_two_boards_give_a_list_rather_than_one_of_them(monkeypatch):
    _fake_nodes(monkeypatch, [
        ("/dev/ttyACM0", 0x2341, 0x003D, 0, "AAAA"),
        ("/dev/ttyACM3", 0x2341, 0x003D, 0, "BBBB"),
    ])
    assert provenance.conditions()["board_serial"] == ["AAAA", "BBBB"]


def test_conditions_does_not_wait_for_a_board(monkeypatch):
    """`ports.find_all_ports()` sleeps up to 8 s with nothing attached;
    a row's conditions must not. Enumeration only, under a second."""
    import time
    _fake_nodes(monkeypatch, [])
    t0 = time.monotonic()
    provenance.conditions()
    assert time.monotonic() - t0 < 1.0


def test_this_benchs_board_reads_a_real_serial():
    got = provenance.conditions()["board_serial"]
    if got is None:
        pytest.skip("no programming port attached, so no board to name")
    assert isinstance(got, str) and re.fullmatch(r"[0-9A-F]{20}", got), got

