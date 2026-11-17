"""rules.test_points on boards built here from numbers; each property broken once on purpose by mutate_kit.py."""
import pytest

from arrays import Arr
from pcbkit import rules
from pcbkit.config import ConfigError

OUT = {'A': [(0, 0, 10, 10)], 'B': [(20, 0, 30, 10)]}
CFG = dict(BLOCK={'TP1': 'A', 'TP2': 'B'}, OUTLINE=OUT, TEST_BLOCKS=['A', 'B'], TP_NETS={'TP1': 'N1', 'TP2': 'N2'}, TP_PREFIX='TP', TP_PIN='1')


def board(n2='N2', skip=()):
    a = Arr('N1', 'N2', 'N3')
    for ref, (x, n) in {'TP1': (5, 'N1'), 'TP2': (25, n2)}.items():
        a.part(ref, x, 5)
        if ref not in skip:
            a.p(ref, '1', x, 5, n)
    return a


def run(a, **over):
    return rules.test_points(a.build(), {**CFG, **over})


def test_every_listed_block_has_a_test_point_on_its_net():
    r = run(board())
    assert r.ok and r.detail == 'every listed block has a test point, each on its net'


def test_a_block_without_a_test_point_and_a_test_point_on_the_wrong_net_are_found_in_that_order():
    r = run(board(skip=('TP2',)))
    assert not r.ok and r.detail == 'block B has no test point; TP2: missing or not on N2'
    r = run(board(n2='N3'))
    assert not r.ok and r.detail == 'TP2: missing or not on N2'


def test_only_the_prefix_and_the_pin_count():
    a = Arr('N1', 'N2').part('TP1', 5, 5).p('TP1', '2', 5, 5, 'N1').part('TP2', 25, 5).p('TP2', '1', 25, 5, 'N2')
    r = run(a)
    assert not r.ok and 'block A has no test point' in r.detail                  # the pin carrying the net is TP_PIN
    r = run(board(), TP_PREFIX='X')
    assert not r.ok and 'block A has no test point' in r.detail and 'block B has no test point' in r.detail
    assert run(board(), TEST_BLOCKS=['A']).ok and run(board(), TEST_BLOCKS=[]).ok


def test_a_part_without_a_block_takes_the_outline_that_holds_it():
    a = board()
    r = run(a, BLOCK={'TP1': 'A'})                                                # TP2 has no block of its own: it is in B's rectangle
    assert r.ok


def test_project_names_raise_naming_the_key():
    a = board().build()
    for k in CFG:
        with pytest.raises(ConfigError, match=k):
            rules.test_points(a, {kk: v for kk, v in CFG.items() if kk != k})
