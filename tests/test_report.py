"""The generated tables in the docs still say what the records say.

Board-free. Issue #6, item 7.

What this protects is not the tables - anyone can regenerate those - but
the property that makes generating them worth doing at all: that a figure
in `docs/status.md` cannot quietly disagree with `tests/baseline.json`.
Hand-copied figures in this project have outlived their measurements three
times (a noise floor, a settling tail, a transport reading), which is why
`status.md` opens with an audit of which of its own numbers predate which
fix. A generated region that nothing checks would be a fourth way to do
the same thing, just faster.

So the test is the deliverable, not the generator.
"""
import io
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
REPORT = os.path.join(REPO, "tools", "report.py")
STATUS = os.path.join(REPO, "docs", "status.md")

sys.path.insert(0, os.path.join(REPO, "tools"))
import report  # noqa: E402


@pytest.mark.smoke
def test_the_generated_regions_match_the_records():
    """The check the whole arrangement exists for."""
    r = subprocess.run([sys.executable, REPORT, "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        "docs/status.md has drifted from tests/baseline.json.\n"
        "Run: python3 tools/report.py --write\n\n" + r.stdout + r.stderr)


@pytest.mark.smoke
def test_check_actually_fails_when_a_figure_is_edited():
    """A check that cannot fail is worse than no check.

    Asserted rather than assumed because the failure mode is silent: if
    the marker regex stopped matching - a renamed table, a reformatted
    comment - `--check` would pass on every document forever and the
    suite would report that the docs agree with the records when nothing
    had been compared.
    """
    with io.open(STATUS, encoding="utf-8") as fh:
        text = fh.read()
    b = report._load(report.BASELINE)
    c = report._load(report.CALIBRATION)

    generated, _ = report.apply_to(text, b, c)
    assert generated == text, "fixture precondition: docs are already current"

    # Corrupt one generated cell and confirm it is noticed.
    marker = report.BEGIN % "rates"
    i = text.index(marker)
    j = text.index(report.END, i)
    body = text[i:j]
    assert "|" in body, "the rates region should contain a table"
    damaged = text[:i] + body.replace("|", "!", 1) + text[j:]

    restored, _ = report.apply_to(damaged, b, c)
    assert restored == text, (
        "regeneration did not repair an edited cell, so --check would not "
        "have caught it either")


@pytest.mark.smoke
def test_every_table_has_a_region_in_the_document():
    """A table nobody renders is a table nobody checks."""
    with io.open(STATUS, encoding="utf-8") as fh:
        text = fh.read()
    missing = [n for n in report.TABLES if (report.BEGIN % n) not in text]
    assert not missing, (
        "tools/report.py renders %s but docs/status.md has no region for "
        "them, so they are generated into nothing" % ", ".join(missing))


@pytest.mark.smoke
def test_nothing_hand_written_is_inside_a_region():
    """The boundary is the contract, so it is asserted.

    Regeneration discards everything between the markers. If prose ends
    up in there - a caveat added next to a number it qualifies, which is
    the natural thing to do - it is destroyed on the next `--write` with
    no warning. The narrow rule that catches that: a generated region is
    a table and nothing else.
    """
    with io.open(STATUS, encoding="utf-8") as fh:
        text = fh.read()
    for name in report.TABLES:
        begin = report.BEGIN % name
        if begin not in text:
            continue
        i = text.index(begin) + len(begin)
        body = text[i:text.index(report.END, i)].strip()
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("|") or line.startswith("*"):
                continue
            # Trailing sentences that the renderer itself emits are fine;
            # what must not appear is anything a person put there.
            assert line in report.render(name, report._load(report.BASELINE),
                                         report._load(report.CALIBRATION)), (
                "%r is inside the %s region but is not generated - it will "
                "be destroyed by the next --write. Move it outside the "
                "markers." % (line[:60], name))
