"""The PAM eye page generator: what goes into a page is what comes out of it.

Board-free. A small hand-built eye document stands in for the one
`host/etspam.py` writes, and the page's script is syntax-checked with node
where node exists.
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
import ets_pam_page  # noqa: E402


def _doc(pam=4):
    levels = [{"level": i, "code": 1000 + 600 * i, "n": 100, "mean": 1400.0 + 410 * i,
               "std": 1.8, "lo": 1390.0 + 410 * i, "hi": 1410.0 + 410 * i} for i in range(pam)]
    eyes = [{"eye": i, "height_codes": 380.0, "width_symbols": 0.8, "height_by_position": 380.0}
            for i in range(pam - 1)]
    return {"provenance": {"analysis": "test", "raw": "r.bin", "taken_at": "t", "bench": "b"},
            "eye": {"pam": pam, "levels": levels, "eyes": eyes, "residual_codes": [0.1] * pam,
                    "gates": {"A3": {"passed": True, "why": "ok"}, "A4": {"passed": True, "why": "ok"},
                              "A5": {"passed": True, "why": "ok"}, "A6": {"passed": True, "why": "ok"}},
                    "cells": [[x, 1400 + (x % 1300), 3] for x in range(0, 580, 4)],
                    "nx": 580, "k": 10, "tick_ns": 22.2, "ui_ticks": 29, "ymin_code": 1380,
                    "ymax_code": 2700, "adc_mv_per_code": 0.806, "samples": 1000,
                    "centre_hist": [1] * 1321, "rc_dac": 29, "rc_adc": 46,
                    "pattern": {"pam": pam, "n": 7, "length": 127, "swing_mv": 1000.0,
                                "codes": [1123, 1740, 2356, 2973]}}}


def _data(page):
    return json.loads(re.search(r"const D = (\{.*?\});\n", page, re.S).group(1))


def test_the_data_in_the_page_is_the_data_given():
    doc = _doc()
    page = ets_pam_page.build(doc, title="T", lede="L")
    assert "/*DATA*/" not in page
    data = _data(page)
    assert data["title"] == "T" and data["lede"] == "L"
    assert data["eye"]["cells"] == doc["eye"]["cells"]
    assert data["provenance"]["raw"] == "r.bin"


def test_the_default_title_names_the_level_count():
    assert _data(ets_pam_page.build(_doc(16)))["title"] == "PAM16 Eye"


def test_a_file_that_is_not_a_pam_eye_is_refused_by_name(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text(json.dumps({"cells": []}), encoding="utf-8")
    with pytest.raises(SystemExit) as err:
        ets_pam_page.load(str(bad))
    assert "centre_hist" in str(err.value)


def test_the_page_script_parses(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node to parse the page's script")
    js = re.search(r"<script>(.*)</script>", ets_pam_page.build(_doc()), re.S).group(1)
    src = tmp_path / "page.js"
    src.write_text(js, encoding="utf-8")
    done = subprocess.run([node, "--check", str(src)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_the_browser_tab_names_the_level_count():
    assert "<title>PAM16 Eye</title>" in ets_pam_page.build(_doc(16))
    assert "<title>PAM Eye</title>" not in ets_pam_page.build(_doc(4))


def _scope_trace(pam, seed=11, per_level=900):
    """A scope record of an 8-bit instrument: random levels held flat, with a ramp between."""
    import random
    rng = random.Random(seed)
    lo, step = 0.75, 1.5 / (pam - 1)
    v = []
    prev = lo
    for _ in range(per_level):
        target = lo + rng.randrange(pam) * step
        for t in range(6):
            v.append(prev + (target - prev) * (t + 1) / 6.0)
        v += [target] * rng.randrange(6, 14)
        prev = target
    quant = 0.008
    return [round((x + rng.gauss(0, 0.002)) / quant) * quant for x in v]


def test_the_rigol_clustering_recovers_the_levels_of_the_trace():
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
    import ets_pam
    for pam in (4, 16, 64):
        v = _scope_trace(pam)
        flat, cent = ets_pam._cluster(v, pam)
        truth = [(0.75 + i * 1.5 / (pam - 1)) * 1000.0 for i in range(pam)]
        assert len(flat) > 1000 and len(cent) == pam, pam
        assert max(abs(c - t) for c, t in zip(cent, truth)) < 6.0, pam    # within one 8 mV scope step
    # the control: asked for the wrong level count the centroids cannot match the truth
    wrong = ets_pam._cluster(_scope_trace(16), 8)[1]
    truth16 = [(0.75 + i * 1.5 / 15) * 1000.0 for i in range(16)]
    assert min(abs(c - t) for c in wrong for t in truth16) < 40.0
    assert max(abs(c - t) for c, t in zip(wrong, truth16[:8])) > 100.0
