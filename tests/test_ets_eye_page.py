"""The eye page generator: what goes into a page is what comes out of it.

Board-free. A small hand-built eye stands in for an `ets_cross.py eye` file,
and the page's script is syntax-checked with node where node exists.
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ets_eye_page  # noqa: E402


def _eye(label="one", ui=29, k=10):
    nx = 2 * ui * k
    return {"provenance": {"analysis": "test", "raw": "r.bin", "taken_at": "t", "label": label},
            "rc_dac": ui, "rc_adc": 46, "k": k, "tick_ns": 22.2, "ui_ticks": ui,
            "nx": nx, "ny": 350, "ylo": 1000.0, "yb": 4.0, "samples": 1000,
            "delta_ppm": -2.3, "model_adequate": True, "lattice_gcd": 1,
            "time_axis_sigma_ns": 0.12, "curve_k": 1, "b0_ticks": 0.5,
            "bits": [1, 0, 0, 1, 1, 0, 1], "curve_mv": [1500.0] * (7 * ui),
            "rise_ns": 136.0, "fall_ns": 127.0,
            "dens": [[x, 100 + (x % 5), 3] for x in range(0, nx, 3)]}


def _page_data(page):
    m = re.search(r"const D = (\{.*?\});\n", page, re.S)
    return json.loads(m.group(1))


def test_the_data_in_the_page_is_the_data_given():
    eyes = [_eye("a"), _eye("b", ui=28)]
    page = ets_eye_page.build(eyes, title="T", lede="L")
    assert "/*DATA*/" not in page
    data = _page_data(page)
    assert data["title"] == "T" and data["lede"] == "L"
    assert [e["ui_ticks"] for e in data["eyes"]] == [29, 28]
    assert data["eyes"][1]["dens"] == eyes[1]["dens"]


def test_a_label_given_on_the_command_line_wins_over_the_file_s():
    page = ets_eye_page.build([_eye("from file")], labels=["from args"])
    assert _page_data(page)["eyes"][0]["label"] == "from args"


def test_one_or_two_eyes_are_drawn_and_no_other_number():
    with pytest.raises(ValueError):
        ets_eye_page.build([])
    with pytest.raises(ValueError):
        ets_eye_page.build([_eye(), _eye(), _eye()])


def test_a_file_that_is_not_an_eye_is_refused_by_name(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text(json.dumps({"dens": []}), encoding="utf-8")
    with pytest.raises(SystemExit) as err:
        ets_eye_page.load(str(bad))
    assert "curve_mv" in str(err.value)


def test_the_page_script_parses(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node to parse the page's script")
    page = ets_eye_page.build([_eye("a"), _eye("b")])
    js = re.search(r"<script>(.*)</script>", page, re.S).group(1)
    src = tmp_path / "page.js"
    src.write_text(js, encoding="utf-8")
    done = subprocess.run([node, "--check", str(src)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
