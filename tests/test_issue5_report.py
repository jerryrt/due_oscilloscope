"""The report page must be generated, and must not reference what is absent.

`tools/issue5_report.py` builds `docs/issue5-report.html` from the
committed records. The page draws its charts in the browser from a JSON
blob the generator injects, and **this bench has no JavaScript runtime**,
so nothing here executes the drawing code. What it does instead is check
the two things that actually break such a page and that a reader would
not notice:

  * a chart mounted on an element id that does not exist in the markup -
    the chart silently does not appear;
  * a `DATA.<key>` the drawing code reads and the generator never
    writes - the chart appears empty, or throws and takes every chart
    after it down with it.

Both are checked by comparing the template's script against the
template's markup and against the real generated blob, so they are
checked against the data the page will actually carry rather than
against a fixture.

**Stated plainly, because a check that overstates itself is worse than
none:** this does not show the page renders correctly. It shows the page
cannot fail in the two ways that leave no trace. A visual check is still
a visual check.
"""
import json
import os
import re
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "tools", "issue5_report.py")
TMPL = os.path.join(REPO, "tools", "issue5_report.tmpl.html")


@pytest.fixture(scope="module")
def template():
    with open(TMPL, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def data():
    out = subprocess.run([sys.executable, TOOL, "--data-only"], cwd=REPO,
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def script_of(template):
    m = re.search(r"<script>(.*?)</script>", template, re.S)
    assert m, "the template has no script block"
    return m.group(1)


def test_every_chart_mount_exists_in_the_markup(template):
    ids = set(re.findall(r'id="([^"]+)"', template))
    used = set(re.findall(r'getElementById\("([^"]+)"\)', template))
    missing = sorted(used - ids)
    assert not missing, f"drawn onto ids that do not exist: {missing}"


def test_every_table_host_exists(template):
    ids = set(re.findall(r'id="([^"]+)"', template))
    hosts = set(re.findall(r'table\("([^"]+)"', template))
    assert not sorted(hosts - ids), sorted(hosts - ids)


def test_every_data_key_the_page_reads_is_written(template, data):
    """`DATA.foo` in the drawing code must be a key the generator emits.

    Only top-level keys: deeper paths are conditional in several charts
    and asserting them would mean re-implementing the drawing logic
    here, which is the kind of second home this project avoids.
    """
    keys = set(re.findall(r"\bDATA\.([A-Za-z_][A-Za-z0-9_]*)", template))
    missing = sorted(k for k in keys if k not in data)
    assert not missing, f"the page reads DATA.{{{','.join(missing)}}}, " \
                        f"generator writes {sorted(data)}"


def test_the_generator_produces_a_page_with_the_data_substituted(tmp_path,
                                                                 data):
    out = tmp_path / "p.html"
    subprocess.run([sys.executable, TOOL, "-o", str(out)], cwd=REPO,
                   capture_output=True, text=True, check=True)
    page = out.read_text(encoding="utf-8")
    assert "__ISSUE5_DATA__" not in page, "the placeholder survived"
    assert "<title>" in page[:8192]
    # The blob is really in there, and is really this data.
    m = re.search(r"const DATA = (\{.*?\});\n", page, re.S)
    assert m, "no DATA assignment in the generated page"
    assert json.loads(m.group(1))["bins"] == data["bins"]


def test_the_page_carries_the_censoring_and_the_comb(data):
    """The two findings the page exists to report must be in its data,
    not only in its prose - a caption is not a measurement."""
    fws6 = [b["fws"]["6"] for b in data["benches"]]
    assert all(not f["censoring"]["complete"] for f in fws6), (
        "every FWS 6 arm is truncated; if this passes trivially the "
        "censoring section has nothing to draw")
    assert data["comb_period"] == 21
    # Six, not seven: the `8` this once carried was a wrap bug in
    # `lattice()`, corrected after it had already gone into a
    # pre-registered prediction on #5.
    assert data["predicted_missing"] == [54, 75, 96, 201, 222, 243]
    for b in data["benches"]:
        c = data["spectrum"][b["id"]]["cross"]["by_fws"]["6"]
        assert c["R"] == pytest.approx(1.0, abs=1e-6), b["id"]


def test_a_missing_mount_id_is_caught(template, tmp_path):
    """Break-on-purpose. The id check must fail on a template whose
    chart is mounted on a typo."""
    broken = template.replace('getElementById("c-freq")',
                              'getElementById("c-freqq")')
    assert broken != template
    ids = set(re.findall(r'id="([^"]+)"', broken))
    used = set(re.findall(r'getElementById\("([^"]+)"\)', broken))
    assert sorted(used - ids) == ["c-freqq"], (
        "the id check would not have noticed a typo'd mount")


def test_a_missing_data_key_is_caught(template, data):
    """Break-on-purpose for the data-key check."""
    broken = template.replace("DATA.comb_period", "DATA.comb_periodd")
    assert broken != template
    keys = set(re.findall(r"\bDATA\.([A-Za-z_][A-Za-z0-9_]*)", broken))
    assert "comb_periodd" in keys and "comb_periodd" not in data
