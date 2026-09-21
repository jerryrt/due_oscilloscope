"""One profile per known board, generated from the record and never typed.

`tools/board_profile.py` writes records/boards/<board_uid>.json from
records/rotation.jsonl and calibration.json. What is held here:

- the profile's history is grouped by bench and its converter entries
  trace one-to-one to rotation rows;
- figures are summarised PER PHASE - an arrangement - and never pooled
  across phases, because the rotation's rows and the shield-v3 rows are
  different arrangements of the same board;
- the large-tail flag is a label judged on the rotation phases only,
  firing at a rested median of 53 and not at 45;
- one uid with two serials is refused, because the record is then
  inconsistent and no profile can say which board it describes;
- `--check` fails on a profile edited by hand and passes untouched;
- every uid in the real records/rotation.jsonl has a profile on disk.
"""

import copy
import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.smoke

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import board_profile as bp                                    # noqa: E402

UID_A = "442032204e52344d3230323239313032"
UID_B = "442032204e52344d3030363139303038"
SER_A = "134484749393514068D5"
SER_B = "1344847493935140A666"


def _row(uid, serial, bench, phase, taken_at, largest, idle=1200,
         counts=(0, 2)):
    lo, med, hi = largest
    return {
        "schema": "rotation/1", "board_uid": uid, "board_serial": serial,
        "bench": bench, "phase": phase, "taken_at": taken_at,
        "idle_before_s": idle,
        "identity": {"build": "d25f9e3", "track": "B", "uid": uid},
        "census_summary": {"largest_min": lo, "largest_median": med,
                           "largest_max": hi, "count_min": counts[0],
                           "count_max": counts[1], "n": 5},
        "tail_scale": [{"arm": "baseline", "run": 1,
                        "a0_scale_codes": 2.35, "a1_scale_codes": 2.24},
                       {"arm": "sync-off", "run": 1,
                        "a0_scale_codes": 2.31, "a1_scale_codes": 2.18}],
        "tail_scale_status": "ok",
        "temperatures": [{"code": 1043.0}, {"code": 1042.5}],
    }


ROWS = [
    _row(UID_A, SER_A, "linux-x1", "before", "2026-09-20T20:32:00-0400",
         (53.0, 54.5, 55.5), counts=(84, 113)),
    _row(UID_A, SER_A, "mac-bench", "after", "2026-09-20T21:40:00-0400",
         (50.5, 53.0, 54.0), counts=(44, 67)),
    _row(UID_B, SER_B, "windows-desk", "before", "2026-09-20T20:45:00-0400",
         (43.0, 45.0, 46.0)),
]


def test_history_groups_rows_by_bench_in_order_and_entries_trace_to_rows():
    p = bp.build_profiles(ROWS, {})
    a = p[UID_A]
    assert [h["bench"] for h in a["history"]] == ["linux-x1", "mac-bench"]
    assert a["history"][0]["rows"] == 1 and a["first_seen"] == ROWS[0]["taken_at"]
    assert [e["row_taken_at"] for e in a["converter"]] == [
        ROWS[0]["taken_at"], ROWS[1]["taken_at"]]
    assert a["converter"][0]["tail_scale_a0"] == [2.35]      # baseline only
    assert a["converter"][0]["die_code_mean"] == 1042.75
    assert a["board_serial"] == SER_A
    assert p[UID_B]["history"] == [{"bench": "windows-desk",
                                    "first": ROWS[2]["taken_at"],
                                    "last": ROWS[2]["taken_at"], "rows": 1}]


def test_the_summary_is_per_phase_and_never_pooled():
    """The rotation's rows and the shield-v3 rows are different
    arrangements of one board; a median over both would describe
    neither."""
    rows = ROWS[:2] + [_row(UID_A, SER_A, "mac-bench", "shield-v3",
                            "2026-09-21T00:10:00-0400", (46.0, 47.0, 48.0))]
    a = bp.build_profiles(rows, {})[UID_A]
    s = a["converter_summary"]
    assert set(s) == {"before", "after", "shield-v3"}
    assert s["before"]["rested_largest_median"] == 54.5
    assert s["after"]["rested_largest_median"] == 53.0
    assert s["shield-v3"]["rested_largest_median"] == 47.0
    assert s["shield-v3"]["benches"] == ["mac-bench"]
    assert "rested_largest_median" not in s          # no pooled figure
    assert [x["phase"] for x in a["arrangements"]] == ["before", "after",
                                                      "shield-v3"]
    assert a["arrangements"][2]["first"] == rows[2]["taken_at"]


def test_the_large_tail_flag_fires_at_53_not_45_and_is_judged_per_phase():
    p = bp.build_profiles(ROWS, {})
    assert p[UID_A]["flags"] == {"before": ["large-tail"],
                                 "after": ["large-tail"]}
    assert p[UID_B]["flags"] == {"before": []}
    # A later arrangement gets its own entry and does not overwrite the
    # rotation's: the label is judged per phase, on that phase's rested
    # median alone, so a board that lost its tail under a shield keeps
    # the flag on its rotation phases and none on the shield's, and a
    # board that carries the tail only under the shield is flagged
    # there and nowhere else.
    rows = ROWS[:2] + [_row(UID_A, SER_A, "mac-bench", "shield-v3",
                            "2026-09-21T00:10:00-0400", (43.5, 44.0, 44.5)),
                       _row(UID_B, SER_B, "linux-x1", "shield-v3",
                            "2026-09-21T00:11:00-0400", (51.0, 51.5, 52.0))]
    f = bp.build_profiles(rows, {})
    assert f[UID_A]["flags"] == {"before": ["large-tail"],
                                 "after": ["large-tail"], "shield-v3": []}
    assert f[UID_B]["flags"] == {"shield-v3": ["large-tail"]}


def test_a_warm_row_does_not_enter_the_rested_median():
    rows = [ROWS[2], _row(UID_B, SER_B, "windows-desk", "before",
                          "2026-09-20T20:50:00-0400", (60.0, 65.0, 70.0),
                          idle=0)]
    s = bp.build_profiles(rows, {})[UID_B]["converter_summary"]["before"]
    assert s["rested_largest_median"] == 45.0 and s["n_rows"] == 2
    assert s["n_rested_rows"] == 1


def test_one_uid_with_two_serials_is_refused():
    rows = [ROWS[0], dict(ROWS[1], board_serial="1344DIFFERENT")]
    with pytest.raises(ValueError, match="one uid, two serials"):
        bp.build_profiles(rows, {})


def test_calibration_is_copied_for_its_board_and_null_for_the_others():
    cal = {"_comment": ["x"], "dac_mv": {"span_lo": 578, "span_hi": 2771},
           "adc_transfer": {"advref_mv": 3270},
           "board": {"board_uid": UID_B, "board_serial": SER_B,
                     "measured_on_bench": "mac-bench, before the rotation"}}
    p = bp.build_profiles(ROWS, cal)
    assert p[UID_B]["calibration"]["adc_transfer"] == {"advref_mv": 3270}
    assert p[UID_B]["calibration"]["source"] == "calibration.json"
    assert p[UID_B]["calibration"]["measured_on_bench"].startswith("mac-bench")
    assert p[UID_A]["calibration"]["adc_transfer"] is None
    assert "not measured" in p[UID_A]["calibration"]["note"]


def _write_fixture(tmp_path):
    rot = tmp_path / "rotation.jsonl"
    rot.write_text("".join(json.dumps(r) + "\n" for r in ROWS),
                   encoding="utf-8")
    cal = tmp_path / "calibration.json"
    cal.write_text("{}", encoding="utf-8")
    boards = tmp_path / "boards"
    return rot, cal, boards


def test_check_passes_untouched_and_fails_on_a_hand_edit(tmp_path, capsys):
    rot, cal, boards = _write_fixture(tmp_path)
    args = ["--rotation", str(rot), "--calibration", str(cal),
            "--boards-dir", str(boards), "--no-generated"]
    assert bp.main(["--write"] + args) == 0
    assert bp.main(["--check"] + args) == 0
    path = boards / f"{UID_B}.json"
    p = json.loads(path.read_text(encoding="utf-8"))
    p["converter_summary"]["before"]["rested_largest_median"] = 44.0
    path.write_text(json.dumps(p, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    assert bp.main(["--check"] + args) == 1
    assert "differs from the record" in capsys.readouterr().err
    # A profile on disk that no row names is drift too.
    (boards / "ffffffffffffffffffffffffffffffff.json").write_text(
        "{}", encoding="utf-8")
    path.write_text(bp.render(bp.build_profiles(ROWS, {})[UID_B]),
                    encoding="utf-8")
    assert bp.main(["--check"] + args) == 1
    assert "no row names this board" in capsys.readouterr().err


def test_every_uid_in_the_real_record_has_a_profile_on_disk():
    """The committed profiles regenerate identically from committed
    records; a missing one is a board the record names and the profiles
    do not."""
    rot = os.path.join(REPO, "records", "rotation.jsonl")
    if not os.path.exists(rot):
        pytest.skip("no records/rotation.jsonl in this tree")
    uids = {json.loads(l)["board_uid"] for l in open(rot, encoding="utf-8")
            if l.strip()}
    assert uids, "the real record names no board"
    for uid in uids:
        assert os.path.exists(bp.profile_path(bp.BOARDS_DIR, uid)), uid
    r = subprocess.run([sys.executable, os.path.join(TOOLS, "board_profile.py"),
                        "--check"], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stderr + r.stdout


def test_a_write_leaves_an_unchanged_profile_alone(tmp_path):
    """A bench regenerating after its own row must not restamp the
    profiles it did not measure: with the data unchanged, the file on
    disk - its generated block included - is not touched. A file whose
    data the record has moved is rewritten."""
    rot, cal, boards = _write_fixture(tmp_path)
    args = ["--rotation", str(rot), "--calibration", str(cal),
            "--boards-dir", str(boards)]
    assert bp.main(["--write"] + args) == 0
    path = boards / f"{UID_A}.json"
    p = json.loads(path.read_text(encoding="utf-8"))
    p["generated"] = {"tool": "tools/board_profile.py", "generated_on": "0000000",
                      "bench": "elsewhere"}
    path.write_text(bp.render(p), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    assert bp.main(["--write"] + args) == 0
    assert path.read_text(encoding="utf-8") == before, (
        "an unchanged profile was rewritten")
    # move the data: the rested median is part of the profile
    rows = [json.loads(l) for l in rot.read_text(encoding="utf-8").splitlines()]
    rows[0]["census_summary"]["largest_median"] += 1.0
    rot.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                   encoding="utf-8")
    assert bp.main(["--write"] + args) == 0
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["generated"]["bench"] != "elsewhere"


def test_check_ignores_who_generated_the_file(tmp_path):
    """The generated block names the bench and revision that wrote the
    profile; both differ on the next commit and the next bench, and a
    check that compared them would drift everywhere but where it was
    written."""
    rot, cal, boards = _write_fixture(tmp_path)
    args = ["--rotation", str(rot), "--calibration", str(cal),
            "--boards-dir", str(boards)]
    assert bp.main(["--write"] + args) == 0
    path = boards / f"{UID_A}.json"
    p = json.loads(path.read_text(encoding="utf-8"))
    assert p["generated"]["tool"] == "tools/board_profile.py"
    # The stamp is the commit generated on top of, never the working
    # tree's revision: this test runs in a tree that is usually dirty,
    # and a `-dirty` here is the defect every committed profile had.
    assert p["generated"]["generated_on"]
    assert "dirty" not in p["generated"]["generated_on"]
    assert "rev" not in p["generated"]
    p["generated"] = {"tool": "tools/board_profile.py",
                      "generated_on": "0000000", "bench": "elsewhere"}
    path.write_text(bp.render(p), encoding="utf-8")
    assert bp.main(["--check"] + args) == 0


def test_a_hand_kept_note_is_merged_and_an_unknown_uid_is_refused(tmp_path,
                                                                  capsys):
    rot, cal, boards = _write_fixture(tmp_path)
    boards.mkdir()
    (boards / bp.NOTES_NAME).write_text(json.dumps(
        {UID_B: ["off every bench; cannot take the shield"]}), encoding="utf-8")
    args = ["--rotation", str(rot), "--calibration", str(cal),
            "--boards-dir", str(boards), "--no-generated"]
    assert bp.main(["--write"] + args) == 0
    p = json.loads((boards / f"{UID_B}.json").read_text(encoding="utf-8"))
    assert p["notes"] == ["off every bench; cannot take the shield"]
    assert bp.main(["--check"] + args) == 0
    (boards / bp.NOTES_NAME).write_text(json.dumps(
        {"ffffffffffffffffffffffffffffffff": ["typo"]}), encoding="utf-8")
    assert bp.main(["--check"] + args) == 2
    assert "no row names" in capsys.readouterr().err

