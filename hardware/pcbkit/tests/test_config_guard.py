"""pcbkit.config: the registry of declared names and the typo guard. An unrecognised name is listed and never raises; a near-miss of a
declared name raises naming both; a declared name never raises."""
import pytest

from pcbkit import config as C
from pcbkit import rules

CFG = dict(GND='GND', PLANE_LAYER='B', HOP_FENCES=[], HOP_SENSITIVE=[], HOP_KEEPOUT_PARTS=[])


def test_the_registry_holds_every_name_the_modules_declare():
    for n in ('GND', 'PLANE_LAYER', 'COPPER_LAYERS', 'GND_VIA_REACH', 'HOP_MAX', 'HOP_FENCES', 'HOP_SENSITIVE_CLEAR', 'FRAME'):
        assert n in C.DECLARED
    assert C.DECLARED['GND'] == {'ground_plane', 'bottom_hops', 'sensitive_nets', 'pour_gap', 'fill_quality'}
    assert C.DECLARED['KEEPOUT_DIST'] == {'keepout_ring'} and 'DECOUPLING_MAX' in C.DECLARED


def test_an_unrecognised_name_is_listed_and_does_not_raise():
    cfg = {**CFG, 'ADC_NETS': 1, 'XSENS': 2, 'GEN': 3}
    assert C.check_names(cfg) == ['ADC_NETS', 'GEN', 'XSENS']
    text = rules.effective_config(cfg, 'bottom_hops')
    assert 'unrecognised' in text and 'ADC_NETS, GEN, XSENS' in text
    rules.bottom_hops(__import__('arrays').Arr('GND').build(), cfg)         # and the rule runs
    assert 'unrecognised' not in rules.effective_config(CFG, 'bottom_hops')


@pytest.mark.parametrize('typo,declared', [('HOP_MAXX', 'HOP_MAX'), ('HOP_FENCE', 'HOP_FENCES'), ('HOP_SENSTIVE', 'HOP_SENSITIVE'),
                                           ('GND_VIA_REACHH', 'GND_VIA_REACH'), ('COPPER_LAYER', 'COPPER_LAYERS')])
def test_a_near_miss_raises_naming_both_names(typo, declared):
    with pytest.raises(C.ConfigError) as e:
        C.check_names({**CFG, typo: 1})
    assert typo in str(e.value) and declared in str(e.value)
    with pytest.raises(C.ConfigError, match=typo):
        rules.ground_plane(__import__('arrays').Arr('GND').build(), {**CFG, typo: 1})        # every rule runs the guard
    with pytest.raises(C.ConfigError, match=typo):
        rules.effective_config({**CFG, typo: 1}, 'ground_plane')


def test_a_declared_name_never_raises_even_when_near_another_declared_name():
    pairs = C.declared_pairs_near()                                           # declared names near each other exist (INK_H / MIN_H): both are fine
    assert ('DESIGNATOR_INK_H', 'DESIGNATOR_MIN_H') in pairs
    assert C.check_names({'DESIGNATOR_INK_H': 1, 'DESIGNATOR_MIN_H': 2}) == []
    C.declare('probe', ['PROBE_ABCDEF', 'PROBE_ABCDEG'])                      # two declared names one edit apart
    try:
        assert C.check_names({'PROBE_ABCDEF': 1, 'PROBE_ABCDEG': 2}) == []
        assert ('PROBE_ABCDEF', 'PROBE_ABCDEG') in C.declared_pairs_near()
        with pytest.raises(C.ConfigError):
            C.check_names({'PROBE_ABCDEH': 1})
    finally:
        for n in ('PROBE_ABCDEF', 'PROBE_ABCDEG'):
            del C.DECLARED[n]


def test_short_names_are_never_typo_candidates_and_distance_two_needs_six_characters():
    assert not C.near('GEN', 'GND') and not C.near('GND', 'GNDX')
    assert C.near('ABCDE', 'ABCDEF') and not C.near('ABCDE', 'ABCXYE')            # 4-5 characters: one edit
    assert C.near('ABCDEF', 'ABCDXX') and not C.near('ABCDEF', 'ABCXXX')           # 6+: two edits
    assert C.distance('kitten', 'sitting') == 3 and C.distance('', 'ab') == 2 and C.distance('same', 'same') == 0


def test_a_module_or_object_configuration_is_read_by_its_upper_case_names():
    import types
    ns = types.SimpleNamespace(**CFG, HOP_MAXX=1, lower=2)
    with pytest.raises(C.ConfigError, match='HOP_MAXX'):
        C.check_names(ns)
    assert C.config_names(types.SimpleNamespace(A=1, b=2)) == ['A']
