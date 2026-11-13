"""pcbtools.planar: known answers on hand-built blocks (the graph construction: stars, body rings, the fence ring, the reading of
the planarity certificate), the v2 integrated board's four blocks as built, and the v1 REFCAL acceptance case.

networkx does the planarity test and is required: without it every test skips WITH A REASON, and with
PCBTOOLS_REQUIRE_NETWORKX=1 (the image gate, once the r4 image carries it) a missing networkx FAILS, never skips."""
import itertools
import os
import pathlib

import pytest

try:
    import networkx  # noqa: F401
    HAVE_NX = True
except ImportError:
    HAVE_NX = False

HERE = pathlib.Path(__file__).resolve().parent
ARRAYS = HERE.parent / 'fixtures' / 'arrays'


@pytest.fixture(autouse=True)
def _need_networkx():
    if not HAVE_NX:
        if os.environ.get('PCBTOOLS_REQUIRE_NETWORKX') == '1':
            pytest.fail('PCBTOOLS_REQUIRE_NETWORKX=1 but networkx is not importable (requirements-pcb.txt)')
        pytest.skip('networkx is not installed in this interpreter (requirements-pcb.txt; the r4 image carries it); '
                    'run with the host venv .venv-pcb')


from pcbtools import planar            # noqa: E402  (after the skip fixture is defined; the import itself needs no networkx)


def graph_nets(edges):
    """a graph as a block: one single-pin part per vertex (no body), one two-terminal net per edge"""
    return {f'N{u}_{v}': [(f'P{u}', '1'), (f'P{v}', '1')] for u, v in edges}


def run(nets, boundary=(), rotation=None, protected=(), **kw):
    return planar.check(nets, {}, rotation, list(boundary), protected, **kw)


K5 = list(itertools.combinations(range(5), 2))
K33 = [(i, 3 + j) for i in range(3) for j in range(3)]
PETERSEN = [(i, (i + 1) % 5) for i in range(5)] + [(i, i + 5) for i in range(5)] + [(5 + i, 5 + (i + 2) % 5) for i in range(5)]
GRID = [((r, c), (r, c + 1)) for r in range(4) for c in range(3)] + [((r, c), (r + 1, c)) for r in range(3) for c in range(4)]


# ------------------------------------------------------------------------------------------------ known answers
def alternating(order):
    """two 2-terminal nets A, B, no pads, whose edge points are in `order` around the fence"""
    return run({'A': [], 'B': []}, [(o, o[0].upper()) for o in order], protected=())


def ic_rotation(order):
    """a 4-pin IC, nets 1-3 and 2-4: the two chords alternate around the body unless the pin order is 1,3,2,4"""
    return run({'A': [('U', '1'), ('U', '3')], 'B': [('U', '2'), ('U', '4')]}, rotation={'U': order})


def known_answers():
    """-> list of names of the known answers that do NOT hold (the mutation proof runs this under a broken module)"""
    bad = []

    def expect(name, cond):
        if not cond:
            bad.append(name)
    r = run(graph_nets(GRID))
    expect('grid planar', r.planar and r.min_crossings == 0 and not r.suggested_bridges)
    r = run(graph_nets(K33))
    expect('K3,3', not r.planar and r.min_crossings == 1 and len(r.suggested_bridges) == 1)
    r = run(graph_nets(K5))
    expect('K5', not r.planar and r.min_crossings == 1)
    r = run(graph_nets(PETERSEN))
    expect('Petersen', not r.planar and r.min_crossings == 2)
    r = alternating(['a1', 'b1', 'a2', 'b2'])
    expect('boundary alternation crosses', not r.planar and r.min_crossings == 1)
    r = alternating(['a1', 'a2', 'b1', 'b2'])
    expect('boundary nested does not', r.planar)
    expect('IC pins 1,2,3,4 cross', not ic_rotation(['1', '2', '3', '4']).planar)
    expect('IC pins 1,3,2,4 do not', ic_rotation(['1', '3', '2', '4']).planar)
    return bad


def test_known_answers_hold():
    assert known_answers() == []


def test_a_planar_block():
    """a chain of three parts, a net leaving each side: nothing to cross"""
    nets = {'X': [('R1', '1'), ('EDGE', 'x')][:1] + [('R2', '1')], 'Y': [('R2', '2'), ('R3', '1')]}
    r = run(nets, [('w', 'X'), ('e', 'Y')])
    assert r.planar and r.min_crossings == 0 and r.crossings == [] and r.suggested_bridges == []
    assert 'planar' in r.detail


@pytest.mark.parametrize('name,edges,k', [('K5', K5, 1), ('K3,3', K33, 1), ('Petersen', PETERSEN, 2)])
def test_b_nonplanar_graphs(name, edges, k):
    """the classic non-planar graphs, as nets between single pads: the minimum number of nets to remove is the graph's
    skewness (K5 1, K3,3 1, Petersen 2)"""
    r = run(graph_nets(edges))
    assert not r.planar and r.min_crossings == k and r.exact
    assert len(r.suggested_bridges) == k
    pairs = {frozenset(c) for c in r.crossings}
    assert pairs and all(a in graph_nets(edges) and b in graph_nets(edges) for a, b in r.crossings)


def test_b_k33_bridge_plan_is_one_split():
    """the suggested net can be split into two segments joined by a part and then the block is planar"""
    r = run(graph_nets(K33))
    net = r.suggested_bridges[0]
    plan = r.bridge_plans[net]
    assert plan is not None and len(plan[0]) and len(plan[1])
    assert sorted(plan[0] + plan[1]) == sorted(graph_nets(K33)[net])


def test_b_k33_as_two_rows_of_pins():
    """two parts of three pins each, every pin of one to every pin of the other: the bodies are walls, and the model needs
    three nets bridged, not one (K3,3 itself, with no bodies, needs one)"""
    nets = {f'N{i}{j}': [('U1', str(i)), ('U2', str(j))] for i in range(3) for j in range(3)}
    r = run(nets)
    assert not r.planar and r.min_crossings == 3


def test_c_boundary_alternation():
    r = alternating(['a1', 'b1', 'a2', 'b2'])
    assert not r.planar and r.min_crossings == 1 and r.suggested_bridges[0] in ('A', 'B')
    assert alternating(['a1', 'a2', 'b1', 'b2']).planar
    assert alternating(['b1', 'a1', 'b2', 'a2']).planar is False        # rotating the order keeps the alternation


def test_c_alternation_with_pads():
    """nets that also have pads inside the block: the alternation of their edge points is the same crossing"""
    nets = {'A': [('R1', '1')], 'B': [('R2', '1')]}
    r = run(nets, [('a1', 'A'), ('b1', 'B'), ('a2', 'A'), ('b2', 'B')])
    assert not r.planar and r.min_crossings == 1 and r.crossings == [(r.suggested_bridges[0], 'B' if r.suggested_bridges[0] == 'A' else 'A')]
    assert run(nets, [('a1', 'A'), ('a2', 'A'), ('b1', 'B'), ('b2', 'B')]).planar


def test_d_protected_net_is_never_suggested():
    bd = [(o, o[0].upper()) for o in ['a1', 'b1', 'a2', 'b2']]
    nets = {'A': [], 'B': []}
    r = planar.check(nets, {}, None, bd, protected=('A',))
    assert r.suggested_bridges == ['B'] and r.allowed_crossings == 1 and r.min_crossings == 1
    r = planar.check(nets, {}, None, bd, protected=('B',))
    assert r.suggested_bridges == ['A']
    r = planar.check(nets, {}, None, bd, protected=('A', 'B'))
    assert r.suggested_bridges == [] and 'no allowed bridge' in r.detail and r.allowed_crossings is None
    assert not r.planar and r.min_crossings == 1                       # the crossing is still reported


def test_d_protected_patterns_are_fnmatch_and_ignore_the_slash():
    nets = {'/CH1_NP': [], '/X': []}
    bd = [('a1', '/CH1_NP'), ('b1', '/X'), ('a2', '/CH1_NP'), ('b2', '/X')]
    r = planar.check(nets, {}, None, bd, protected=('/CH?_NP',))
    assert r.suggested_bridges == ['/X']
    r = planar.check(nets, {}, None, bd, protected=('CH?_NP',))
    assert r.suggested_bridges == ['/X']


def test_e_pin_order_changes_the_verdict():
    assert not ic_rotation(['1', '2', '3', '4']).planar
    assert ic_rotation(['1', '3', '2', '4']).planar
    assert ic_rotation(['2', '3', '4', '1']).planar is False           # a cyclic shift of 1,2,3,4 is still 1,2,3,4
    assert ic_rotation(['4', '3', '2', '1']).planar is False           # and so is its mirror


def test_e_pin_order_from_pad_positions():
    """with no rotation given, the order is the angular order of the pads: a square of pads 1,2,3,4 round the body"""
    pads = {('U', '1'): (0, 0), ('U', '2'): (2, 0), ('U', '3'): (2, 2), ('U', '4'): (0, 2)}
    assert planar.rotation_from_pads(pads)['U'] in (['1', '2', '3', '4'], ['1', '4', '3', '2'], ['2', '3', '4', '1'],
                                                    ['2', '1', '4', '3'], ['3', '4', '1', '2'], ['3', '2', '1', '4'],
                                                    ['4', '1', '2', '3'], ['4', '3', '2', '1'])
    nets = {'A': [('U', '1'), ('U', '3')], 'B': [('U', '2'), ('U', '4')]}
    assert not planar.check(nets, pads, None, [], ()).planar          # the diagonals of a square cross
    swapped = dict(pads)
    swapped[('U', '2')], swapped[('U', '3')] = pads[('U', '3')], pads[('U', '2')]
    assert planar.check(nets, swapped, None, [], ()).planar           # pads 2 and 3 exchanged: now 1,3 are neighbours


def test_rows_of_a_header_are_found():
    """one row of pads is a chain in pad order (collinear: angular order is meaningless), two rows are two chains"""
    one = {('J', str(i)): (2.54 * i, 0.0) for i in range(4)}
    assert planar.rotation_from_pads(one)['J'] in (['0', '1', '2', '3'], ['3', '2', '1', '0'])
    two = {('U', '1'): (0, 0), ('U', '2'): (1.27, 0), ('U', '3'): (2.54, 0), ('U', '4'): (0, 5), ('U', '5'): (1.27, 5), ('U', '6'): (2.54, 5)}
    ch = planar._chains(__import__('numpy').array([two[k] for k in sorted(two)]), [k[1] for k in sorted(two)])
    assert sorted(map(sorted, ch)) == [['1', '2', '3'], ['4', '5', '6']]


def test_passable_part_lets_a_net_pass_between_its_pads():
    """chord e1-e3 separates e2 from e4; R's pads are on N(e2) and M(e4): a wall between R.1 and R.2 crosses the chord, a
    bridge part (passable) does not"""
    nets = {'U': [], 'N': [('R', '1')], 'M': [('R', '2')]}
    bd = [('e1', 'U'), ('e2', 'N'), ('e3', 'U'), ('e4', 'M')]
    assert not planar.check(nets, {}, None, bd, (), body='wall').planar
    assert planar.check(nets, {}, None, bd, (), body='wall', passable=('R',)).planar


def test_gnd_is_not_a_net():
    nets = graph_nets(K5)
    nets['/GND'] = [(f'P{i}', '1') for i in range(5)]
    r = planar.check(nets, {}, None, [], (), gnd='/GND')
    assert r.min_crossings == 1


def test_single_terminal_nets_are_dropped():
    r = run({'X': [('R1', '1')], 'Y': [('R2', '1'), ('R3', '1')]})
    assert r.planar


def test_root_and_branches():
    """a net starred at a pin: its branches are separate legs from that pad, so legs that must share a face cannot"""
    nets = {'V': [('U', '1'), ('A', '1'), ('B', '1'), ('C', '1')], 'X': [('A', '2'), ('B', '2')], 'Y': [('B', '3'), ('C', '3')]}
    r = planar.check(nets, {}, None, [], (), roots={'V': ('U', '1')}, branches={'V': [[('A', '1')], [('B', '1')], [('C', '1')]]})
    assert r.planar


# ------------------------------------------------------------------------------------------------ mutation proof
def test_mutation_always_planar(monkeypatch):
    """a planarity check that always says planar: the known answers fail"""
    monkeypatch.setattr(planar._Model, 'conflict', lambda self, active: None)
    bad = known_answers()
    assert 'K3,3' in bad and 'K5' in bad and 'boundary alternation crosses' in bad and 'IC pins 1,2,3,4 cross' in bad


def test_mutation_ignore_the_rotation_ring(monkeypatch):
    """bodies dropped: pin order no longer matters, the pin-order answers fail (and nothing else need)"""
    monkeypatch.setattr(planar, '_bodies', lambda *a, **k: {})
    bad = known_answers()
    assert 'IC pins 1,2,3,4 cross' in bad


def test_mutation_wrong_boundary_order(monkeypatch):
    """edge points in a wrong order (sorted by label instead of along the fence): the alternation answers fail"""
    real = planar._build

    def scrambled(nets, nets_all, bodies, boundary, roots, branches, ordered=()):
        return real(nets, nets_all, bodies, sorted(boundary), roots, branches, ordered)
    monkeypatch.setattr(planar, '_build', scrambled)
    bad = known_answers()
    assert 'boundary alternation crosses' in bad or 'boundary nested does not' in bad


def test_mutation_no_fence_ring(monkeypatch):
    """no fence wheel: edge points are free vertices, an alternation can no longer be seen"""
    real = planar._build
    monkeypatch.setattr(planar, '_build', lambda nets, nets_all, bodies, boundary, *a: real(nets, nets_all, bodies, [], *a))
    assert 'boundary alternation crosses' in known_answers()


# ------------------------------------------------------------------------------------------------ v2 integrated board
V2_BLOCKS = ['POWER', 'REFCAL', 'SCOPE', 'AWG']


@pytest.fixture(scope='module')
def v2board():
    from pcbtools import boardio
    return boardio.load_npz(str(ARRAYS / 'v2-integrated-990d4b03.npz'))


@pytest.fixture(scope='module')
def v2cfg():
    from pcbtools.boards import v2, planar_v2
    import types
    return types.SimpleNamespace(**{k: getattr(v2, k) for k in ('FENCES', 'HUNDREDS', 'OWNER_OVERRIDE', 'GND', 'BRIDGES')},
                                 PROTECTED_NETS=planar_v2.PROTECTED_NETS)


@pytest.mark.parametrize('block', V2_BLOCKS)
def test_v2_block_as_built_is_planar(v2board, v2cfg, block):
    """the consistency test: the routed board is a one-layer board except its bridges and one bottom hop, so each block read
    as built (bridge parts passable, every net as the pieces of copper it has in the fence) must be planar"""
    d = planar.from_board(v2board, v2cfg, block)
    assert len(d['block_nets']) >= 10 and len(d['boundary']) >= 6        # a floor: the block was really examined
    r = planar.check(**d)
    assert r.planar, r.detail


@pytest.mark.parametrize('block', V2_BLOCKS)
def test_v2_block_bridges_as_wires_still_planar(v2board, v2cfg, block):
    """the bridges removed and their nets joined: the model finds NO crossing, in any of the four blocks. Recorded, not hoped:
    topology alone does not need the v2 bridges (a track can go round the end of another's trunk); they exist for geometry
    that a planarity test cannot see (README)"""
    r = planar.check(**planar.from_board(v2board, v2cfg, block, merge_bridges=True))
    assert r.planar, r.detail


def test_v2_strict_bodies_refuse_a_routed_block(v2board, v2cfg):
    """the spec's construction with every body a wall is stricter than the routed board: it reports a crossing in a block that
    is demonstrably routed (tracks pass between the pads of 0603s and run under SOICs), which is why the default for boards is
    body='auto'"""
    d = planar.from_board(v2board, v2cfg, 'AWG')
    d['body'] = 'wall'
    d['body_overrides'] = {}
    assert not planar.check(**d).planar


def test_v2_edge_points_come_from_tracks(v2board, v2cfg):
    d = planar.from_board(v2board, v2cfg, 'POWER')
    labels = [lab for lab, _ in d['boundary']]
    assert any('+5V_DUE' in lab for lab in labels)
    assert all(n in d['block_nets'] for _, n in d['boundary'])


def test_v2_protected_patterns_cover_the_rule():
    from pcbtools.boards import planar_v2
    p = planar_v2.PROTECTED_NETS
    for net in ('/A0', '/A1', '/CH1_N', '/CH2_NP', '/CH1_IN', '/VREF', '/VREF_M', '/VREF_P'):
        assert planar._is_protected(net, p), net
    for net in ('/+3V3A', '/VNEG', '/SNS_B', '/TAP3', '/AWG_BIN'):
        assert not planar._is_protected(net, p), net


# ------------------------------------------------------------------------------------------------ v1 REFCAL acceptance
@pytest.fixture(scope='module')
def v1board():
    from pcbtools import boardio
    return boardio.load_npz(str(HERE / 'planar_v1_34b2e51.npz'))


def v1(b, **kw):
    from pcbtools.boards import planar_v1
    return planar.check(**planar_v1.inputs(b, **kw))


def test_v1_refcal_legs_in_the_order_of_the_ruling_are_not_planar(v1board):
    """the hand derivation's input (VREF's four legs leave U501.2 in the order A, C, B, D; the contract's edge points; the two
    ICs walls): the model finds the frozen design NOT planar, one net short. It is the VREF/TAP3 pair, not SNS_B (see the xfail
    below), and R520 does not change it: this pins what the tool finds so a change in it is seen"""
    r = v1(v1board)
    assert not r.planar and r.min_crossings == 1
    assert set(r.conflict) == {'/TAP3', '/VREF'} and r.suggested_bridges == ['/TAP3']
    assert 'SNS_B' not in ''.join(r.suggested_bridges)
    assert not v1(v1board, r520=True).planar


def test_v1_refcal_without_a_leg_order_is_planar(v1board):
    """no fixed order of the legs at the pin (the topology only): planar, with or without R520. The obstruction the block agent
    derived needs the order of the legs and the placement of the bridges relative to leg D, which are geometry"""
    for r520 in (False, True):
        assert v1(v1board, r520=r520, leg_order='ABCD').planar


def test_v1_refcal_more_bodies_make_sns_b_a_candidate(v1board):
    """with J501, the SOT-23 clamps and the 0603s on the SNS path walls as well, SNS_B appears in the minimum removal sets of
    the frozen design (two nets) together with TAP3 or VREF: the net the hand derivation names is among the candidates, but
    R520 does not cure it in the model"""
    from pcbtools.boards import planar_v1
    r = v1(v1board, walls=planar_v1.WALL_MORE)
    assert not r.planar and r.min_crossings == 2
    assert ['/SNS_B', '/TAP3'] in r.min_sets and ['/SNS_B', '/VREF'] in r.min_sets
    assert 'SNS_B' in ' '.join(r.suggested_bridges)
    assert not planar._is_protected('/SNS_B', planar.DEFAULT_PROTECTED)      # the default rule would not forbid the suggestion


@pytest.mark.xfail(strict=True, reason='the model disagrees with the hand derivation: the frozen design is not found to need '
                   'exactly SNS_B and R520 does not make the block planar (README, "v1 REFCAL"); waiting for the geometry '
                   '(where leg D runs relative to R517-R519) that the hand derivation used and the topology lacks')
def test_v1_refcal_finds_the_hand_found_crossing(v1board):
    frozen = v1(v1board)
    assert not frozen.planar and frozen.min_crossings == 1 and frozen.suggested_bridges == ['/SNS_B']
    assert v1(v1board, r520=True).planar
