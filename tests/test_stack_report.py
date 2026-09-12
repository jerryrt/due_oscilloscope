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
import re
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
    # THE FIGURE IS READ OUT OF THE RECORD, NOT TYPED HERE. A bound is
    # whatever the bench that recorded last measured - 916 B on Debian
    # 14.2.1, 912 B on xPack 15.2.1 - so a hard-coded one makes this test
    # fail on every bench but the one it was written on, and the failure
    # reads as a broken check rather than as a stale fixture. It cost two
    # reds the first time a second bench recorded.
    text = _doc()
    recs = sr.load()
    deepest = max(recs["b"]["roots"], key=lambda r: r["bytes"])
    intact = "| b | %s | %d |" % (deepest["root"], deepest["bytes"])
    assert intact in text, (
        "fixture precondition: the bounds region should carry Track B's "
        "deepest root as the record has it. Regenerate the document: "
        + intact)

    damaged = tmp_path / "stack-depth.md"
    damaged.write_text(text.replace(intact, "| b | %s | 216 |"
                                    % deepest["root"]),
                       encoding="utf-8")

    r = subprocess.run([sys.executable, REPORT, "--check",
                        "--doc", str(damaged)],
                       capture_output=True, text=True)
    assert r.returncode != 0, (
        "%d B was edited to 216 B and --check passed. The comparison is "
        "not reaching the table, so every figure in the document is "
        "unwatched" % deepest["bytes"])
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
    assert diagram.startswith("```mermaid")
    # The fence closes, and anything after it is the note naming a track
    # that could not be drawn - so the region no longer ends at the fence.
    assert len(diagram.split("```")) >= 3, "the mermaid block is not closed"
    assert "==>" in diagram, "the worst-case chain should be drawn heavy"
    for track in recs:
        assert "sg_%s" % track in diagram, (
            "track %r is not in the diagram at all, drawn or declined"
            % track)
    prov = sr.render("provenance", recs)
    for field in ("bench", "repo_rev", "cc", "elf_sha256", "taken_at"):
        assert field in prov


def _blocked_row(recs, track="z"):
    """A row in the state the producer uses when it will not give a number.

    Built rather than taken from the record, so these assertions hold on a
    bench whose every track happens to be bounded. Which track is blocked
    is a property of the firmware and moves; that a blocked track is
    rendered at all is a property of this tool and must not.
    """
    row = dict(recs[sorted(recs)[0]])
    row.update(track=track, state="refused", roots=[],
               blocked=[{"what": "emac_handler",
                         "why": "an indirect target with no call-graph node"}])
    return row


def test_every_track_in_the_record_is_in_every_table():
    """Three tracks compared in one place, which is the point of the doc.

    A track missing from a table is not a smaller table - it is a
    comparison that reads as agreement, and nothing in the document says
    a track was left out.
    """
    recs = sr.load()
    assert len(recs) >= 3, (
        "fixture precondition: the record should carry all three tracks")
    for name in ("bounds", "chains", "provenance"):
        out = sr.render(name, recs)
        for track in recs:
            assert re.search(r"^\| %s \|" % re.escape(track), out, re.M), (
                "track %r has no row in the %s table" % (track, name))


def test_a_track_with_no_bound_renders_its_state_and_its_reason():
    """`(no bound)` and the blocker, in the same table as the numbers.

    Not a zero, not a dash, and not a table of its own: the producer
    answers in three states and the report has to carry the two that are
    not a number all the way to the page.
    """
    recs = sr.load()
    row = _blocked_row(recs)
    recs = dict(recs)
    recs[row["track"]] = row

    bounds = sr.render("bounds", recs)
    line = [l for l in bounds.splitlines() if l.startswith("| z |")]
    assert len(line) == 1, bounds
    cells = [c.strip() for c in line[0].strip("|").split("|")]
    assert sr.NO_BOUND in cells, cells
    assert "refused" in cells, cells
    # The census columns legitimately carry numbers - how many functions
    # the graph held, how many indirect sites and targets - and they are
    # taken from the row rather than typed here, because they are a
    # property of the IMAGE and differ by code generator: 452 functions
    # on Debian 14.2.1 against 510 on xPack 15.2.1. What must not appear
    # is a BOUND, which is the thing the row refused to give.
    census = {str(row.get(k)) for k in
              ("functions", "indirect_sites", "indirect_targets")}
    assert not any(c.isdigit() and c not in census for c in cells), (
        "a refused row carries a number that is not a census column: "
        "%r, census %r" % (cells, sorted(census)))
    assert "emac_handler" in line[0] and "no call-graph node" in line[0]

    chains = sr.render("chains", recs)
    zrow = [l for l in chains.splitlines() if l.startswith("| z |")]
    assert len(zrow) == 1 and sr.NO_BOUND in zrow[0], chains
    assert "emac_handler" in zrow[0]


def test_the_diagram_says_which_track_it_could_not_draw():
    """Skipping is allowed here; skipping silently is not.

    A missing subgraph reads as a track with no stack, which is the one
    reading a stack document must never produce by accident.
    """
    recs = dict(sr.load())
    row = _blocked_row(recs)
    recs[row["track"]] = row
    out = sr.render("diagram", recs)
    assert out.startswith("```mermaid") and "```" in out
    assert "sg_z" in out, "the skipped track has no box at all"
    assert "emac_handler" in out, "the box does not say why it was skipped"
    assert "track z" in out.split("```")[-1], (
        "nothing under the diagram names the track that was not drawn")
    assert "z0" not in out, "a track with no chain should have no chain nodes"


def test_check_fails_when_a_blocked_row_reason_is_edited(tmp_path):
    """The break-on-purpose, extended to the cells that carry no number.

    The figures are watched by the test above; a refusal is watched by
    nothing unless this fails. Built on a synthetic record so it runs on
    every bench rather than only on one whose firmware happens to refuse
    - a test that skips is worse than one that fails, because the rest of
    the file endorses it.
    """
    recs = sr.load()
    row = _blocked_row(recs)
    bounded = recs[sorted(recs)[0]]
    records = tmp_path / "stack-depth.jsonl"
    records.write_text(json.dumps(bounded) + "\n" + json.dumps(row) + "\n",
                       encoding="utf-8")

    doc = tmp_path / "stack-depth.md"
    doc.write_text("\n".join("%s\n%s" % (sr.BEGIN % n, sr.END)
                             for n in sorted(sr.REGIONS)) + "\n",
                   encoding="utf-8")
    w = subprocess.run([sys.executable, REPORT, "--write",
                        "--records", str(records), "--doc", str(doc)],
                       capture_output=True, text=True)
    assert w.returncode == 0, w.stdout + w.stderr

    ok = subprocess.run([sys.executable, REPORT, "--check",
                         "--records", str(records), "--doc", str(doc)],
                        capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr

    text = doc.read_text(encoding="utf-8")
    assert "emac_handler: an indirect target with no call-graph node" in text
    doc.write_text(text.replace("an indirect target with no call-graph node",
                                "nothing at all, this is fine"),
                   encoding="utf-8")
    bad = subprocess.run([sys.executable, REPORT, "--check",
                          "--records", str(records), "--doc", str(doc)],
                         capture_output=True, text=True)
    assert bad.returncode != 0, (
        "the reason a track carries no bound was rewritten and --check "
        "passed, so the refusal is the one thing in the document nobody "
        "is watching")
    assert "bounds" in bad.stderr, bad.stderr
