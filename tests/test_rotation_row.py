"""tools/rotation_row.py writes one attributable row per rotation cell.

Three boards across three benches is six cells of about thirty figures
each, and the alternative to this tool is copying census lines out of
six pytest logs by hand - which is how the wrap-displacement comparison
went wrong for four sessions. Everything here runs with the hardware
steps replaced, so it holds the tool's promises without a board:

- the `census:` line parses on a fail and on a pass;
- the n=5 summary drops run 1 BY INDEX, not the smallest value;
- a row is refused without a declared phase and idle time, without a
  programming port, on a dirty tree, on the wrong track, and on an
  image that is not the tree's own commit;
- a row carries the board's two identities and every conditions() key;
- a tail tool that crashed is a MISSING scale with its status and exit 3,
  never an empty measurement in a row that exited 0; a parity tie is
  retried once with `--parity 0` and the row says so;
- `--image-rev` pins the image the board must carry so the tree may
  move ahead of it; without it the image must be the tree's.
"""

import argparse
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import rotation_row as rr                                       # noqa: E402

FAIL_LINE = ("census: 97 steps > 45 codes (allowance 100), largest 58.0, "
             "gap 45..45, fold z 2.5 control 4.0 peak -0.3")
PASS_LINE = ("census: 0 steps > 45 codes (allowance 100), largest 44.0, "
             "gap 45..45, fold z 2.1 control 2.9 peak -0.2")
SERIAL = "134484749393514068D5"
UID = "5f3c1a2b9e8d7c6b5a4f3e2d1c0b9a87"

CONDITIONS = {
    "bench": "linux-x1", "repo_rev": "63080da", "board_serial": SERIAL,
    "board_uid": UID, "checkout": REPO, "checkout_fs": "ext4",
    "suite_context": None, "tool": {"name": "rotation_row.py", "rev": "63080da"},
    "via": None, "uptime_ms": None, "taken_at": "2026-09-20T20:00:00",
    "track": "b", "fw_build": "63080da",
}


def _ident(track="b", build="63080da", uid=UID):
    return {"track": track, "build": build, "uid": uid,
            "fw_version": "0.2.0", "ctl_version": 4, "frame_version": 3}


def _steps(cond=None, ident=None):
    c = dict(CONDITIONS if cond is None else cond)
    i = _ident() if ident is None else ident
    return lambda: {"identity_line": "# id: track=B ...", "ident": i,
                    "temperatures": [{"code": 1050.5, "code_min": 1046,
                                      "code_max": 1055, "samples": 256,
                                      "adc_mr": 0x1f3f0100, "adc_acr": 0x111,
                                      "dev_us": 1}] * 3,
                    "conditions": c}


def _census_texts(counts):
    lines = [f"census: {n} steps > 45 codes (allowance 100), largest "
             f"{40 + n / 10:.1f}, gap 45..45, fold z 2.0 control 3.0 peak 0.2"
             f"\n1 {'passed' if n <= 100 else 'failed'} in 8.5s"
             for n in counts]
    it = iter(lines)
    return lambda _python: next(it)


SCALE_TEXT = ("baseline        run 1: A0 tail/s {6: 704.6, 10: 152.0, 15: 37.1} scale 2.27  A1 tail/s {6: 648.7, 10: 131.2, 15: 24.8} "
            "scale 2.14  (parity 0/0, pair spread 1/1)\n"
            "baseline        run 2: A0 tail/s {6: 687.8, 10: 150.0, 15: 44.9} scale 2.34  A1 tail/s {6: 641.7, 10: 138.4, 15: 22.8} "
            "scale 2.28  (parity 0/0, pair spread 1/1)\n"
            "rows -> records/issue82-arms-linux-x1.jsonl\n")


def _scale(_python, _bench, extra=()):
    return 0, SCALE_TEXT


def _args(**kw):
    d = dict(phase="before", idle_seconds=1200, note="", bench=None,
             python=sys.executable, out=None, image_rev=None)
    d.update(kw)
    return argparse.Namespace(**d)


# --- the parsers --------------------------------------------------------------

def test_the_census_line_parses_on_a_fail_and_on_a_pass():
    f = rr.parse_census(FAIL_LINE + "\n1 failed in 8.51s")
    assert f["count"] == 97 and f["threshold"] == 45 and f["allowance"] == 100
    assert f["largest"] == 58.0 and (f["gap_lo"], f["gap_hi"]) == (45, 45)
    assert (f["fold_z"], f["fold_control_z"], f["fold_peak"]) == (2.5, 4.0, -0.3)
    assert f["verdict"] == "failed" and f["line"] == FAIL_LINE
    p = rr.parse_census("== Captured stdout call ==\n" + PASS_LINE +
                        "\nPASSED tests/x\n1 passed in 8.5s")
    assert p["count"] == 0 and p["largest"] == 44.0 and p["verdict"] == "passed"
    assert rr.parse_census("no census here\n1 passed in 1s") is None


def test_the_tail_scales_parse_per_arm_and_run():
    s = rr.parse_scales(SCALE_TEXT)
    assert [(x["arm"], x["run"], x["a0_scale_codes"], x["a1_scale_codes"])
            for x in s] == [("baseline", 1, 2.27, 2.14), ("baseline", 2, 2.34, 2.28)]


# --- the aggregation drops by index -----------------------------------------

def test_the_summary_drops_run_one_by_index_not_the_smallest():
    """Run 1 is the smallest here; a drop-by-value would keep it and
    drop nothing, and the max would still be right - only the min and
    the n tell the two apart, so both are asserted."""
    rows = [rr.parse_census(_census_texts([c])(None))
            for c in (5, 90, 80, 95, 85, 100)]
    s = rr.summarise(rows)
    assert s["n"] == 5 and s["dropped"] == "run 1 by index"
    assert s["count_min"] == 80 and s["count_max"] == 100
    assert s["largest_min"] == 48.0 and s["largest_max"] == 50.0
    assert s["count_median"] == 90


# --- the refusals -------------------------------------------------------------

def test_phase_and_idle_seconds_are_required_on_the_command_line(capsys):
    with pytest.raises(SystemExit) as e:
        rr.main(["--idle-seconds", "0"])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        rr.main(["--phase", "before"])
    assert e.value.code == 2
    assert "idle-seconds" in capsys.readouterr().err


@pytest.mark.parametrize("cond_patch, ident_patch, needle", [
    ({"board_serial": None}, {}, "board_serial"),
    ({"repo_rev": "63080da-dirty"}, {}, "dirty"),
    ({"repo_rev": "63080da+ee5c634a"}, {}, "dirty"),
    ({}, {"track": "c"}, "track"),
    ({}, {"build": "2b20140"}, "flash this tree's image"),
])
def test_an_unattributable_row_is_refused(cond_patch, ident_patch, needle):
    cond = dict(CONDITIONS, **cond_patch)
    ident = dict(_ident(), **ident_patch)
    with pytest.raises(rr.Refused) as e:
        rr.collect_row(_args(), board_steps=_steps(cond, ident),
                       run_census=_census_texts([0] * 6),
                       run_tail_scale=_scale)
    assert needle in str(e.value)


# --- the row ------------------------------------------------------------------

def test_the_row_carries_both_identities_and_every_condition(tmp_path,
                                                             monkeypatch):
    out = tmp_path / "rotation.jsonl"
    monkeypatch.setattr(rr, "_board_steps", _steps())
    monkeypatch.setattr(rr, "_run_census",
                        _census_texts([97, 75, 84, 79, 87, 91]))
    monkeypatch.setattr(rr, "_run_tail_scale", _scale)
    rc = rr.main(["--phase", "after", "--idle-seconds", "1200",
                  "--note", "board arrived from mac-bench",
                  "--out", str(out)])
    assert rc == 0
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["schema"] == "rotation/1"
    assert row["board_serial"] == SERIAL and row["board_uid"] == UID
    assert row["phase"] == "after" and row["idle_before_s"] == 1200
    assert row["note"] == "board arrived from mac-bench"
    for k in CONDITIONS:
        assert k in row["conditions"], k
    assert [c["run"] for c in row["census"]] == [1, 2, 3, 4, 5, 6]
    assert [c["count"] for c in row["census"]] == [97, 75, 84, 79, 87, 91]
    assert row["census_summary"]["n"] == 5
    assert row["census_summary"]["count_min"] == 75
    assert len(row["census_raw"]) == 6 and len(row["temperatures"]) == 3
    assert [x["a0_scale_codes"] for x in row["tail_scale"]] == [2.27, 2.34]
    assert "issue82-arms-linux-x1" in row["tail_scale_rows_went_to"]


def test_a_missing_uid_is_recorded_as_null_not_dropped(tmp_path, monkeypatch):
    """An image built before 63080da carries no uid=; the row says so."""
    out = tmp_path / "rotation.jsonl"
    monkeypatch.setattr(rr, "_board_steps", _steps(ident=_ident(uid=None)))
    monkeypatch.setattr(rr, "_run_census", _census_texts([0] * 6))
    monkeypatch.setattr(rr, "_run_tail_scale", _scale)
    assert rr.main(["--phase", "before", "--idle-seconds", "0",
                    "--out", str(out)]) == 0
    row = json.loads(out.read_text(encoding="utf-8"))
    assert "board_uid" in row and row["board_uid"] is None
    assert row["idle_before_s"] == 0


def test_the_scale_parser_reads_the_tools_real_line():
    """The tool prints the rates as a dict with spaces inside the braces.

    A pattern written as \S+ for that dict matched nothing on a real
    line, and the first rotation row went out with `tail_scale: []`
    while its raw text carried four perfectly good lines. These are two
    lines, verbatim from linux-x1's first rotation row.
    """
    text = ("baseline        run 1: A0 tail/s {6: 704.6, 10: 152.0, 15: 37.1} "
            "scale 2.35  A1 tail/s {6: 648.7, 10: 131.2, 15: 24.8} scale 2.24  "
            "(parity 1/0, pair spread 1/1.0)\n"
            "sync-off        run 2: A0 tail/s {6: 681.1, 10: 146.4, 15: 45.6} "
            "scale 2.33  A1 tail/s {6: 677.8, 10: 137.9, 15: 20.8} scale 2.16  "
            "(parity 1/0, pair spread 1/1.0)\n")
    got = rr.parse_scales(text)
    assert [(g["arm"], g["run"], g["a0_scale_codes"], g["a1_scale_codes"])
            for g in got] == [("baseline", 1, 2.35, 2.24),
                              ("sync-off", 2, 2.33, 2.16)], got


# --- the tail tool's exit code is not swallowed ------------------------------

TIE_TEXT = ("provenance: bench=mac-bench\n"
            "Traceback (most recent call last):\n"
            "  File \"tools/issue82_arms.py\", line 71, in parity\n"
            "ValueError: hold parity is a tie (1.0 vs 1); pass the parity "
            "known from the other channel\n")


def test_a_crashed_tail_tool_is_a_missing_scale_with_exit_3(tmp_path,
                                                            monkeypatch,
                                                            capsys):
    """mac-bench's before-row: the tail tool raised before printing a
    line, the first tool returned its output regardless, and the row
    went out with an empty measurement and exit 0."""
    out = tmp_path / "rotation.jsonl"
    monkeypatch.setattr(rr, "_board_steps", _steps())
    monkeypatch.setattr(rr, "_run_census", _census_texts([0] * 6))
    crash = ("provenance: bench=x\nTraceback (most recent call last):\n"
             "RuntimeError: the capture returned no A0 series\n")
    monkeypatch.setattr(rr, "_run_tail_scale",
                        lambda _p, _b, extra=(): (1, crash))
    rc = rr.main(["--phase", "before", "--idle-seconds", "1200",
                  "--out", str(out)])
    assert rc == 3
    row = json.loads(out.read_text(encoding="utf-8"))
    assert row["tail_scale"] == []
    assert row["tail_scale_status"].startswith("tool exit 1: RuntimeError")
    assert row["tail_scale_parity_forced"] is None
    cap = capsys.readouterr()
    assert "scale MISSING (tool exit 1" in cap.out
    assert "MISSING" in cap.err


def test_a_parity_tie_is_retried_once_with_parity_0(tmp_path, monkeypatch):
    """A quiet board's holds barely move, so both parities fit the pair
    spread equally and the tool's tie check refuses; the advice in its
    error was unreachable until the tool took --parity."""
    out = tmp_path / "rotation.jsonl"
    calls = []

    def tool(_python, _bench, extra=()):
        calls.append(tuple(extra))
        if not extra:
            return 1, TIE_TEXT
        return 0, "parity forced: 0\n" + SCALE_TEXT

    monkeypatch.setattr(rr, "_board_steps", _steps())
    monkeypatch.setattr(rr, "_run_census", _census_texts([0] * 6))
    monkeypatch.setattr(rr, "_run_tail_scale", tool)
    rc = rr.main(["--phase", "before", "--idle-seconds", "1200",
                  "--out", str(out)])
    assert rc == 0
    assert calls == [(), ("--parity", "0")], calls
    row = json.loads(out.read_text(encoding="utf-8"))
    assert row["tail_scale_status"] == "ok, parity forced 0 after a tie"
    assert row["tail_scale_parity_forced"] == 0
    assert [x["a0_scale_codes"] for x in row["tail_scale"]] == [2.27, 2.34]
    assert "retry with --parity 0" in row["tail_scale_raw"]


def test_a_clean_exit_with_no_scale_line_is_still_missing(tmp_path,
                                                          monkeypatch):
    out = tmp_path / "rotation.jsonl"
    monkeypatch.setattr(rr, "_board_steps", _steps())
    monkeypatch.setattr(rr, "_run_census", _census_texts([0] * 6))
    monkeypatch.setattr(rr, "_run_tail_scale",
                        lambda _p, _b, extra=(): (0, "rows -> x\n"))
    assert rr.main(["--phase", "before", "--idle-seconds", "0",
                    "--out", str(out)]) == 3
    row = json.loads(out.read_text(encoding="utf-8"))
    assert row["tail_scale_status"] == "exit 0 but no scale line parsed"


# --- the image may be pinned ------------------------------------------------

def test_image_rev_pins_the_board_to_the_rotation_image_not_the_tree():
    """windows-desk: pulling the parser fix would have made the tool
    refuse a rested board carrying the registered image, because the
    tree and the image were one thing."""
    pinned = "d25f9e3"
    # tree ahead of the pinned image, board carries the pinned image
    cond = dict(CONDITIONS, repo_rev="bf9f517")
    row = rr.collect_row(_args(image_rev=pinned),
                         board_steps=_steps(cond, _ident(build=pinned)),
                         run_census=_census_texts([0] * 6),
                         run_tail_scale=_scale)
    assert row["image_rev_pinned"] == pinned
    assert row["conditions"]["repo_rev"] == "bf9f517"
    # board carries neither the pinned image nor the tree's
    with pytest.raises(rr.Refused) as e:
        rr.collect_row(_args(image_rev=pinned),
                       board_steps=_steps(cond, _ident(build="2b20140")),
                       run_census=_census_texts([0] * 6),
                       run_tail_scale=_scale)
    assert "pinned at d25f9e3" in str(e.value)
    # without the pin the old rule stands: the image must be the tree's
    with pytest.raises(rr.Refused) as e:
        rr.collect_row(_args(), board_steps=_steps(cond, _ident(build=pinned)),
                       run_census=_census_texts([0] * 6),
                       run_tail_scale=_scale)
    assert "flash this tree's image" in str(e.value)

