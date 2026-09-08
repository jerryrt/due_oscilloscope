"""The stack-depth document still says what the record says.

Board-free, and no build: the generator reads JSON and writes Markdown.

What this protects is not the tables - anyone can regenerate those - but
the property that makes generating them worth doing: that a figure in
`docs/stack-depth.md` cannot quietly disagree with
`records/stack-depth.jsonl`. A stack bound is exactly the figure that
rots dangerously. It is one plausible number, nobody re-derives it by
hand, and a copy that outlives its measurement reads as a guarantee.

WHAT THESE TESTS DO NOT CLAIM. Every assertion below is about the
document matching the record. None of them says the record is current -
that needs a `-DFIRMWARE_CALLGRAPH=ON` build against the image on the
bench, and no test here builds one. A stale record and a document
generated from it agree perfectly. Saying so is not a disclaimer: a
check that was believed to cover the firmware when it covers a JSON file
is the "guard that cannot fail" shape this project keeps finding.
"""
import io
import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.smoke

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
REPORT = os.path.join(REPO, "tools", "stack_report.py")

sys.path.insert(0, os.path.join(REPO, "tools"))
import stack_report as sr                                     # noqa: E402


def _doc():
    with io.open(sr.DOC, encoding="utf-8") as fh:
        return fh.read()


def test_the_generated_regions_match_the_record():
    """The check the whole arrangement exists for."""
    r = subprocess.run([sys.executable, REPORT, "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        "docs/stack-depth.md has drifted from records/stack-depth.jsonl.\n"
        "Run: python3 tools/stack_report.py --write\n\n" + r.stdout + r.stderr)


def test_check_actually_fails_when_a_figure_is_edited(tmp_path):
    """A check that cannot fail is worse than no check.

    Asserted rather than assumed because the failure mode is silent. If
    the marker regex stopped matching - a renamed region, a reformatted
    comment - `--check` would pass on every document for ever and the
    suite would report that the bounds agree with the record when
    nothing had been compared.

    So a real bound is edited in a copy of the real document, and the
    real command is run against that copy: it must exit non-zero AND
    name the region that moved, because a failure that does not say
    where sends the reader to diff four regions by eye.
    """
    text = _doc()
    assert "| b | Reset_Handler | 916 |" in text, (
        "fixture precondition: the bounds region should carry Track B's "
        "916 B root. Re-read the record before changing this")

    damaged = tmp_path / "stack-depth.md"
    damaged.write_text(text.replace("| b | Reset_Handler | 916 |",
                                    "| b | Reset_Handler | 216 |"),
                       encoding="utf-8")

    r = subprocess.run([sys.executable, REPORT, "--check",
                        "--doc", str(damaged)],
                       capture_output=True, text=True)
    assert r.returncode != 0, (
        "916 B was edited to 216 B and --check passed. The comparison is "
        "not reaching the table, so every figure in the document is "
        "unwatched")
    assert "bounds" in r.stderr, (
        "--check failed but did not name the region that drifted; it said "
        + repr(r.stderr))

    # And put it back: the same command on the untouched document passes,
    # so the failure above was the edit and not the harness.
    ok = subprocess.run([sys.executable, REPORT, "--check"],
                        capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_regeneration_repairs_an_edited_cell(tmp_path):
    """`--write` and `--check` have to agree about what belongs there."""
    text = _doc()
    damaged = tmp_path / "stack-depth.md"
    damaged.write_text(text.replace("| ctl_error | 488 |",
                                    "| ctl_error | 48 |"), encoding="utf-8")

    w = subprocess.run([sys.executable, REPORT, "--write",
                        "--doc", str(damaged)], capture_output=True, text=True)
    assert w.returncode == 0, w.stdout + w.stderr
    assert damaged.read_text(encoding="utf-8") == text, (
        "regeneration did not restore an edited cell, so --check would not "
        "have caught it either")


def test_write_disturbs_nothing_outside_the_markers(tmp_path):
    """The prose is the half a generator cannot check. It must survive."""
    text = _doc()
    sentinel = "\nA hand-written line that regeneration must not touch.\n"
    marker = "## Reading the diagram"
    assert marker in text
    seeded = tmp_path / "stack-depth.md"
    seeded.write_text(text.replace(marker, sentinel + marker), encoding="utf-8")

    subprocess.run([sys.executable, REPORT, "--write", "--doc", str(seeded)],
                   capture_output=True, text=True, check=True)
    after = seeded.read_text(encoding="utf-8")
    assert sentinel in after
    assert after == text.replace(marker, sentinel + marker)


def test_nothing_hand_written_is_inside_a_region():
    """The boundary is the contract, so it is asserted.

    Regeneration discards everything between the markers. Prose put
    there - a caveat next to the number it qualifies, which is the
    natural thing to do - is destroyed on the next `--write` with no
    warning.
    """
    text = _doc()
    recs = sr.load()
    for name in sr.REGIONS:
        begin = sr.BEGIN % name
        assert begin in text, (
            "tools/stack_report.py renders %r and docs/stack-depth.md has "
            "no region for it, so it is generated into nothing" % name)
        i = text.index(begin) + len(begin)
        body = text[i:text.index(sr.END, i)]
        assert body.strip("\n") == sr.render(name, recs)


def test_a_missing_record_is_an_error_not_an_empty_table(tmp_path):
    """An empty table would read as a firmware with no stack.

    And `--check` would then pass against a document that says so, which
    is the vacuous pass this file exists to refuse.
    """
    with pytest.raises(SystemExit):
        sr.load(str(tmp_path / "nothing.jsonl"))

    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        sr.load(str(empty))

    r = subprocess.run([sys.executable, REPORT, "--check",
                        "--records", str(empty)],
                       capture_output=True, text=True)
    assert r.returncode != 0


def test_a_row_of_another_schema_stops_the_run(tmp_path):
    """Fields may have moved, so reading it as if they had not is a guess."""
    row = dict(next(iter(sr.load().values())))
    row["schema"] = "stack-depth/2"
    path = tmp_path / "future.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        sr.load(str(path))


def test_an_absent_field_says_so_rather_than_reading_as_a_measurement():
    """`(absent)`, not 0 and not a dash.

    The producer answers in three states and one of them is "no number".
    A report that filled the blank would undo that at the last step.
    """
    row = dict(next(iter(sr.load().values())))
    row["bench"] = None
    row["cc"] = None
    out = sr.render("provenance", {row["track"]: row})
    assert sr.ABSENT in out
    assert "| 0 |" not in out


def test_the_regions_carry_the_shapes_the_document_needs():
    """A region that renders nothing would satisfy every check above."""
    recs = sr.load()
    assert set(sr.REGIONS) >= {"bounds", "chains", "diagram", "provenance"}
    bounds = sr.render("bounds", recs)
    assert bounds.count("\n|") >= 4 and "state" in bounds
    diagram = sr.render("diagram", recs)
    assert diagram.startswith("```mermaid") and diagram.endswith("```")
    assert "==>" in diagram, "the worst-case chain should be drawn heavy"
    prov = sr.render("provenance", recs)
    for field in ("bench", "repo_rev", "cc", "elf_sha256", "taken_at"):
        assert field in prov
