import json

import pytest

from simtools.compare import compare_trees, compare_values


def test_equal_within_tolerance_and_different_outside_it():
    a = {"x": [1.0, 2.0], "n": {"v": 3.0}, "s": "abc"}
    assert compare_values(a, {"x": [1.0, 2.0 + 1e-9], "n": {"v": 3.0}, "s": "abc"}) == []
    d = compare_values(a, {"x": [1.0, 2.1], "n": {"v": 3.0}, "s": "abc"})
    assert d and d[0][0] == "/x[1]"


@pytest.mark.parametrize("b", [{"x": [1.0], "s": "a"}, {"x": [1.0, 2.0]}, {"x": [1.0, 2.0], "s": "b"}, {"x": [1.0, 2.0], "s": "a", "y": 1}])
def test_structure_and_text_differences_are_differences(b):
    assert compare_values({"x": [1.0, 2.0], "s": "a"}, b)


def test_a_bool_is_not_a_number():
    assert compare_values({"f": True}, {"f": 1})


def test_trees_report_missing_files_and_refuse_an_empty_golden(tmp_path):
    g, n = tmp_path / "g", tmp_path / "n"
    g.mkdir(); n.mkdir()
    with pytest.raises(ValueError):
        compare_trees(g, n)
    (g / "a.json").write_text(json.dumps({"x": 1.0}))
    assert compare_trees(g, n)[0][1] == "missing in the new tree"
    (n / "a.json").write_text(json.dumps({"x": 1.0}))
    assert compare_trees(g, n) == []
    (n / "a.json").write_text(json.dumps({"x": 1.5}))
    assert compare_trees(g, n)[0][0] == "a.json:/x"


def test_a_nan_equals_a_nan_but_not_a_number():
    nan = float("nan")
    assert compare_values({"v": nan}, {"v": nan}) == []
    assert compare_values({"v": nan}, {"v": 1.0})
