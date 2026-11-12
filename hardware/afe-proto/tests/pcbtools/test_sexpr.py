import importlib.util
import pathlib
import time

import pytest

from pcbtools import sexpr as sx

FIX = pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'v1-34b2e51' / 'kicad'


def test_atoms_lists_and_quoted_strings():
    e = sx.parse('(kicad_pcb (version 20240108) (net 1 "/GND") (text "a (b) c" "q\\"uote" "back\\\\slash"))')
    assert e == ['kicad_pcb', ['version', '20240108'], ['net', '1', '/GND'], ['text', 'a (b) c', 'q"uote', 'back\\slash']]
    assert isinstance(e[2][2], sx.Q) and not isinstance(e[2][1], sx.Q)


def test_top_level_forms():
    assert sx.parse('(a)') == ['a']
    assert sx.parse('(a) (b)') == [['a'], ['b']]


def test_escapes_round_trip_including_newline():
    for s in ['plain', 'with "quote"', 'back\\slash', 'line\nbreak', 'mix \\" \n \\n']:
        assert sx.parse(sx.dump([sx.Q(s)]))[0] == s


@pytest.mark.parametrize('bad', ['(a', 'a)', '(a))', '(a "unterminated', '(a) ) (b'])
def test_malformed_input_raises_value_error(bad):
    with pytest.raises(ValueError):
        sx.parse(bad)


def test_deep_nesting_has_no_recursion_limit_on_read():
    t = '(' * 5000 + 'x' + ')' * 5000
    e = sx.parse(t)
    for _ in range(4999):
        e = e[0]
    assert e == ['x']


def test_find_and_first():
    e = sx.parse('(p (net 1) (net 2) (x 3))')
    assert sx.find(e, 'net') == [['net', '1'], ['net', '2']] and sx.first(e, 'x') == ['x', '3'] and sx.first(e, 'y') is None


def test_dump_numbers():
    assert sx.dump(['a', 1, 2.5, 0.0, -0.00001, 3.0]) == '(a 1 2.5 0 0 3)'


def _old():
    spec = importlib.util.spec_from_file_location('old_sexpr', FIX / 'sexpr.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize('name', ['afe-proto.kicad_sch', 'lib/afe.kicad_sym', 'afe-proto.kicad_pcb',
                                  'lib/afe.pretty/BNC_Kinghelm_KH-BNC50-3511_Horizontal.kicad_mod'])
def test_same_tree_as_the_old_reader_on_the_v1_files(name):
    """golden: the old kicad/sexpr.py parse of the frozen v1 files (34b2e51) is reproduced"""
    text = (FIX / name).read_text()
    assert sx.parse(text) == _old().parse(text)


@pytest.mark.parametrize('name', ['afe-proto.kicad_sch', 'afe-proto.kicad_pcb'])
def test_dump_is_a_fixed_point_and_keeps_the_tree(name):
    e = sx.parse((FIX / name).read_text())
    d1 = sx.dump(e)
    e2 = sx.parse(d1)
    assert e2 == e and sx.dump(e2) == d1


def test_reader_is_not_slower_than_the_old_one_on_the_board():
    text = (FIX / 'afe-proto.kicad_pcb').read_text()
    old = _old()
    t0 = time.perf_counter(); old.parse(text); t_old = time.perf_counter() - t0
    t0 = time.perf_counter(); sx.parse(text); t_new = time.perf_counter() - t0
    assert t_new < t_old * 1.5
