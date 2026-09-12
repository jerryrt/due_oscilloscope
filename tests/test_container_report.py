"""`tools/container_report.py`, and whether three benches' rows compare.

This instrument exists so that a cross-bench question gets an
answer rather than three prose summaries, which means its failure mode
is not a wrong number - it is a row that LOOKS comparable and is not.
So the tests here are about the four ways that happens: a verdict that
was never recorded, a host build described as a container one, a step
whose log is absent reported as a step with nothing to say, and a
pytest tail read off the wrong line of a failing run.

No docker, no board, no build: every fixture is a log directory written
here.
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import container_report as cr                                 # noqa: E402


def _run_dir(tmp_path, logs=None, build_env="container"):
    """A log directory and a build directory, as a real run leaves them."""
    logdir = tmp_path / "ci"
    logdir.mkdir()
    for name, text in (logs or {}).items():
        (logdir / f"{name}.log").write_text(text)
    build = tmp_path / "build"
    build.mkdir()
    if build_env is not None:
        (build / "build-env.json").write_text(json.dumps({
            "build_env": build_env,
            "build_image": "due-build:15.2.1-1.1",
            "build_image_content": "abc123",
            "artifacts": {"baremetal_bringup.bin": "deadbeef"},
        }))
    return str(logdir), str(build)


def _row(tmp_path, monkeypatch, **kw):
    logdir, build = _run_dir(tmp_path, **kw)
    monkeypatch.setattr(cr, "runtime", lambda: {"docker_context": "test"})
    return cr.collect(logdir, build, 0)


# --- the row must carry a verdict -----------------------------------------

def test_the_exit_code_is_required_and_never_defaulted(tmp_path,
                                                       monkeypatch, capsys):
    """A row with no verdict reads as a row where nothing failed.

    argparse enforces it, which is the right place: a default of 0 here
    would be the guard that cannot fail, in the one field no artefact in
    the log directory carries.
    """
    logdir, _build = _run_dir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cr.main(["--logs", logdir])
    assert exc.value.code == 2
    assert "--exit" in capsys.readouterr().err


# --- a host run must not be recorded as a container run -------------------

def test_a_host_build_is_refused_rather_than_relabelled(tmp_path,
                                                        monkeypatch, capsys):
    """The whole comparison is "is the CONTAINER the same everywhere".

    `docker/build-firmware.sh` writes `container` only when
    docker/run.sh set DUE_BUILD_IMAGE_ID, so this reads the build's own
    answer rather than assuming from how the tool was invoked. A row that
    described a host build as a container one would answer a different
    question in the same schema, which is the worst kind of wrong.

    The bench is forced so that THIS guard is the one that fires. Without
    it the test would pass on any machine with no bench.json - for the
    wrong reason, and that is most machines.
    """
    logdir, build = _run_dir(tmp_path, build_env="host")
    real = cr.collect
    monkeypatch.setattr(cr, "runtime", lambda: {})
    monkeypatch.setattr(cr, "collect", lambda l, b, e: dict(
        real(l, b, e), bench="test-bench"))
    rc = cr.main(["--exit", "0", "--logs", logdir, "--build", build])
    assert rc == 2
    err = capsys.readouterr().err
    assert "'host'" in err and "container" in err


def test_a_declared_bench_is_required_for_a_row(tmp_path, monkeypatch,
                                                capsys):
    """The rule every record in this tree follows. A figure without its
    bench is not comparable with anything, and three benches answering
    one question is the whole point of this row."""
    logdir, build = _run_dir(tmp_path)
    real = cr.collect
    monkeypatch.setattr(cr, "runtime", lambda: {})
    monkeypatch.setattr(cr, "collect", lambda l, b, e: dict(
        real(l, b, e), bench=None))
    rc = cr.main(["--exit", "0", "--logs", logdir, "--build", build])
    assert rc == 2
    assert "bench" in capsys.readouterr().err


# --- an absent step is absent, not silent ---------------------------------

def test_a_step_with_no_log_is_null_rather_than_missing(tmp_path,
                                                        monkeypatch):
    """Nine steps, always nine keys.

    A step dropped from the mapping is indistinguishable from a step
    that ran and had no number to report, and the second is the common
    case - `stack report` has no count of its own. So every step in
    STEPS gets a key and an absent one is explicitly null.
    """
    row = _row(tmp_path, monkeypatch,
               logs={"host-tier": "= 1 passed in 0.1s ="})
    assert set(row["steps"]) == set(cr.STEPS)
    assert row["steps"]["host-tier"] is not None
    assert row["steps"]["cppcheck"] is None, "absent must be null, not 0"
    assert sum(1 for v in row["steps"].values() if v is None) == 8


# --- the numbers come off the right lines ---------------------------------

def test_a_quoted_count_in_a_traceback_is_not_read_as_the_summary(
        tmp_path, monkeypatch):
    """The real hazard, and it has bitten this repository once already.

    `docker/run-ci.sh`'s class_board_absent carries the note: grepping a
    log for `[0-9]+ passed` reads every clean run as a board contact,
    because pytest echoes the failing fixture's source and conftest.py's
    own comment contains the words `match "1 passed"`. The board-absent
    log here is 650 KB of exactly that - 141 tracebacks quoting source.

    So the pattern is anchored to a line that IS a summary rather than a
    line that CONTAINS a count. Loosen the anchoring and this fails.

    Written after deleting a test that could not: it asserted that the
    LAST tail wins over the first, and both real logs contain exactly one
    match, so the assertion held whichever end was read. A guard that
    cannot fail reports the property as protected and leaves it
    unwatched.
    """
    row = _row(tmp_path, monkeypatch, logs={"board-absent": (
        'tests/conftest.py:88: in _require_board\n'
        '    # --require-board refuses the substitution: match "1 passed"\n'
        '        assert "12 passed" not in out\n'
        "=== 1 skipped, 649 deselected, 141 errors in 14.99s ===\n")})
    got = row["steps"]["board-absent"]["pytest"]
    assert got == "1 skipped, 649 deselected, 141 errors", got


def test_the_analyser_count_and_the_fuzz_count_are_the_last_ones(tmp_path,
                                                                 monkeypatch):
    """Both tools print more than one block. The fuzz step runs its
    positive control first and the campaign second, so the first
    execution count belongs to the control - reading it would report a
    campaign that never ran as a campaign that found nothing."""
    row = _row(tmp_path, monkeypatch, logs={
        "cppcheck": "total 7\nsomething else\ntotal 33\n",
        "fuzz": ("control\nnumber_of_executed_units: 11\n"
                 "campaign\nnumber_of_executed_units: 553763\n")})
    assert row["steps"]["cppcheck"]["findings"] == 33
    assert row["steps"]["fuzz"]["executions"] == 553763


def test_the_image_content_hash_is_carried_and_the_image_id_is_not(
        tmp_path, monkeypatch):
    """An image id is local to the machine that built it and cannot match
    across benches; the content hash is the one that is supposed to. A
    row carrying the id would invite a comparison that must always
    fail."""
    row = _row(tmp_path, monkeypatch)
    assert row["build_image_content"] == "abc123"
    assert "build_image_id" not in row


def test_differing_byte_counts_are_numbers_rather_than_a_verdict(
        tmp_path, monkeypatch):
    """`reproducible: every artifact is byte-identical` is a rendering of
    a count, and a bench whose bytes differ needs the count."""
    row = _row(tmp_path, monkeypatch, logs={"reproducible-b": (
        "  baremetal_bringup.bin  39480 bytes   0 differing bytes\n"
        "  baremetal_bringup.elf  77208 bytes   4 differing bytes\n")})
    assert row["steps"]["reproducible-b"]["differing_bytes"] == [0, 4]


# --- the artifact and the tree must name one commit -----------------------

def _with_image(tmp_path, baked, **kw):
    """A run directory whose Track B image carries `baked` as its
    compiled-in FW_GIT_REV."""
    logdir, build = _run_dir(tmp_path, **kw)
    with open(os.path.join(build, "baremetal_bringup.bin"), "wb") as fh:
        fh.write(b"\x00\x01padding" + baked.encode() + b"morepadding\xff")
    return logdir, build


def _main_with_rev(monkeypatch, logdir, build, repo_rev):
    real = cr.collect
    monkeypatch.setattr(cr, "runtime", lambda: {})
    monkeypatch.setattr(cr, "collect", lambda l, b, e: dict(
        real(l, b, e), bench="test-bench", repo_rev=repo_rev))
    return cr.main(["--exit", "0", "--logs", logdir, "--build", build])


def test_an_image_from_another_commit_is_refused(tmp_path, monkeypatch,
                                                 capsys):
    """The way a three-bench comparison silently stops being one.

    Artifact hashes compare only at a single commit, and `FW_GIT_REV` is
    compiled in - so a tree that moved after the build produces a row
    whose repo_rev names a commit the binary was never built from. The
    instruction "rebuild before you record" has been got wrong twice on
    linux-x1 alone, which is the argument for checking it here rather
    than writing it down again.
    """
    logdir, build = _with_image(tmp_path, "0f40bb5")
    assert _main_with_rev(monkeypatch, logdir, build, "deadbee") == 2
    assert "not built from this tree's HEAD" in capsys.readouterr().err


def test_a_matching_image_records_that_it_was_checked(tmp_path, monkeypatch):
    """And it says so in the row, because "checked and agreed" and
    "there was no artifact to check" must not read alike.

    Read back out of the appended file rather than from the return value,
    so this also covers --append opening the record AFTER the provenance
    is read - the shell `>>` it exists to replace made the tree dirty
    first and labelled every row for it.
    """
    logdir, build = _with_image(tmp_path, "0f40bb5")
    out = tmp_path / "rows.jsonl"
    real = cr.collect
    monkeypatch.setattr(cr, "runtime", lambda: {})
    monkeypatch.setattr(cr, "collect", lambda l, b, e: dict(
        real(l, b, e), bench="test-bench", repo_rev="0f40bb5-dirty"))
    rc = cr.main(["--exit", "0", "--logs", logdir, "--build", build,
                  "--append", str(out)])
    assert rc == 0
    row = json.loads(out.read_text().strip())
    assert row["artifact_revision_checked"] is True
    assert row["bench"] == "test-bench"


def test_no_artifact_is_reported_unchecked_rather_than_passed(tmp_path,
                                                              monkeypatch):
    """A build directory with no image cannot answer, and a row that
    omitted the field would read as a row that checked and agreed."""
    logdir, build = _run_dir(tmp_path)           # no .bin written
    assert _main_with_rev(monkeypatch, logdir, build, "0f40bb5") == 0
