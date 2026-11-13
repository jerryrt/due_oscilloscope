import pytest

from pcbtools import renumber as rn

H = {'ch1': 1, 'ch2': 2, 'awg': 3, 'power': 4, 'cal': 5, 'due': 6}
PARTS = [('R1', 'ch1'), ('R2', 'ch1'), ('R10', 'ch1'), ('R11', 'ch2'), ('C1', 'ch1'), ('U1', 'ch1'), ('U3', 'awg'),
         ('J4', 'due'), ('R100', 'cal'), ('R101', 'power')]


def test_numbers_follow_block_and_old_order():
    m = rn.build_map(PARTS, H)
    assert m['R1'] == 'R101' and m['R2'] == 'R102' and m['R10'] == 'R103'      # old order kept inside the hundred
    assert m['R11'] == 'R201' and m['C1'] == 'C101' and m['U3'] == 'U301' and m['J4'] == 'J601'
    assert m['R100'] == 'R501' and m['R101'] == 'R401'


def test_override_moves_a_part_to_another_block():
    m = rn.build_map(PARTS, H, override={'R100': 'awg'})
    assert m['R100'] == 'R301'


def test_no_collisions_and_all_new_are_unique():
    m = rn.build_map(PARTS, H)
    assert len(set(m.values())) == len(m) == len(PARTS)


def test_errors():
    with pytest.raises(ValueError):
        rn.build_map([('R1', 'nope')], H)
    with pytest.raises(ValueError):
        rn.build_map([('R1', 'ch1'), ('R1', 'ch2')], H)
    with pytest.raises(ValueError):
        rn.build_map([('R1', 'ch1')], H, width=0)
    with pytest.raises(ValueError):
        rn.build_map([('X', 'ch1')], H)


def test_rewrite_is_whole_word_single_pass():
    m = rn.build_map(PARTS, H)
    t = "put('R10', 1) # R1 and R100; U1.2 R101x R1_A 'R2'"
    out = rn.rewrite(t, m)
    assert out == "put('R103', 1) # R101 and R501; U101.2 R101x R1_A 'R102'"
    # a single pass: the output of one rewrite is not rewritten again ('R101' stays R101 inside the same call)
    assert 'R103' in out and out.count('R101') == 2 and 'R101x' in out


def test_rewrite_matches_whole_names():
    out = rn.rewrite('R10 R100 R1', {'R1': 'A', 'R10': 'B', 'R100': 'C'})
    assert out == 'B C A'


def test_empty_map_is_identity():
    assert rn.rewrite('R1', {}) == 'R1'


def test_unmapped_finds_missing_parts():
    m = rn.build_map(PARTS, H)
    assert rn.unmapped('R1 R999 TP1 U1', m) == ['R999', 'TP1']


def test_reproduces_the_v1_renumbering_exactly():
    """golden: the map the old kicad/renumber.py wrote for v1 (34b2e51) is reproduced, part for part"""
    import json
    import pathlib
    g = json.loads((pathlib.Path(__file__).parent / 'golden' / 'v1' / 'renumber_map.json').read_text())
    got = rn.build_map(list(g['block'].items()), H)
    assert got == g['map'] and len(got) == 109
