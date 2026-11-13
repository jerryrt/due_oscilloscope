"""gate3 package generator (pcbtools.gate3): the pure parts (bridge table, hop table, classification, connectivity) on small synthetic
boards with known answers, and the v2 table's evidence rows against the study file on disk.
The flagging mutation: if classify_net stops recognising ADC / divider / VREF nets, the ADC-crossing test must fail."""
import importlib
import pathlib

import pytest

from synth import Synth

from pcbtools.boards import gate3_v2 as TABLE

AFE = pathlib.Path(__file__).resolve().parents[2]
CLASSES = dict(adc={'/A0', '/A1'}, divider={'/CH1_N'}, vref_prefix=('/VREF',), other={'/AREF'})
BRIDGES = [('BR1', 'X', 'Y', 'CH1', 'test bridge')]


def load():
    """the engine, freshly executed: a test that patches a function of it (the mutation tests) must not leak into the next"""
    import pcbtools.gate3.connectivity as conn
    import pcbtools.gate3.engine as eng
    importlib.reload(conn)
    importlib.reload(eng)
    eng.CONN = conn
    return eng


def board(foreign=None, layer='F', width=0.2, x=10.75):
    s = Synth('/X', '/Y', '/A0', '/AREF', '/Q').part('BR1', 10.75, 10.0)
    s.p('BR1', '1', 10.0, 10.0, '/X').p('BR1', '2', 11.5, 10.0, '/Y')
    s.s('/X', 'F', 9.0, 10.0, 10.0, 10.0)                       # the bridge's own nets are never "crossed"
    if foreign:
        s.s(foreign, layer, x, 9.0, x, 11.0, w=width)
    return s.build()


def check(gate3):
    """the assertions; the mutation test runs them against a module whose classify_net is broken"""
    m = gate3.bridge_table(board('/A0'), BRIDGES, CLASSES)[0]
    assert [c['net'] for c in m['crossed']] == ['/A0'] and m['crossed'][0]['layer'] == 'F.Cu'
    assert m['needs_ruling'] and m['ruling_classes'] == ['adc']
    assert (m['net_a'], m['net_b']) == ('/X', '/Y') and m['pad_pitch_mm'] == pytest.approx(1.5)
    o = gate3.bridge_table(board('/AREF'), BRIDGES, CLASSES)[0]          # sensitive but not a ruling class
    assert o['crossed'][0]['cls'] == 'other-sensitive' and not o['needs_ruling']
    q = gate3.bridge_table(board('/Q'), BRIDGES, CLASSES)[0]             # an ordinary net: listed, not flagged
    assert [c['net'] for c in q['crossed']] == ['/Q'] and not q['needs_ruling']


def test_crossing_and_flags():
    check(load())


def test_no_track_under_the_body():
    g = load()
    assert g.bridge_table(board(), BRIDGES, CLASSES)[0]['crossed'] == []
    far = g.bridge_table(board('/A0', x=10.75), BRIDGES, CLASSES, half_w=0.4)          # control: same board, hit
    assert far[0]['crossed']
    beside = Synth('/X', '/Y', '/A0').part('BR1', 10.75, 10.0)
    beside.p('BR1', '1', 10.0, 10.0, '/X').p('BR1', '2', 11.5, 10.0, '/Y').s('/A0', 'F', 9.0, 11.2, 12.0, 11.2)     # 1.2 mm beside the axis
    assert g.bridge_table(beside.build(), BRIDGES, CLASSES)[0]['crossed'] == []


def test_bottom_track_under_the_body_is_listed_with_its_layer():
    r = load().bridge_table(board('/A0', layer='B'), BRIDGES, CLASSES)[0]
    assert r['crossed'][0]['layer'] == 'B.Cu'


def test_classes():
    g = load()
    assert [g.classify_net(n, CLASSES) for n in ('/A1', '/CH1_N', '/VREF', '/VREF_M', '/AREF', '/GND')] == ['adc', 'divider', 'vref', 'vref', 'other-sensitive', None]


def test_hop_table_length_vias_and_jumped_nets():
    s = Synth('/H', '/SCL', '/SDA').part('R1', 0, 0)
    s.s('/H', 'B', 5.0, 5.0, 7.5, 5.0, w=0.3).v('/H', 5.0, 5.0).v('/H', 7.5, 5.0)
    s.s('/SCL', 'F', 6.0, 4.0, 6.0, 6.0).s('/SDA', 'F', 7.0, 4.0, 7.0, 6.0)
    h = load().hop_table(s.build(), CLASSES)
    assert len(h) == 1 and h[0]['length_mm'] == pytest.approx(2.5) and h[0]['vias'] == 2
    assert [c['net'] for c in h[0]['crosses']] == ['/SCL', '/SDA']


def test_margin_rows():
    m = load().margin_rows([('r', 'a', 4.95, 5.0, 'max'), ('r', 'b', 12.0, 10.0, 'min')])
    assert m[0]['marginal'] and m[0]['margin'] == pytest.approx(0.05) and not m[1]['marginal']


def test_mutation_broken_flagging_is_caught():
    """break the flagging (classify_net recognises nothing): check() must fail; then the unbroken module must pass again"""
    g = load()
    g.classify_net = lambda name, classes: None
    with pytest.raises(AssertionError):
        check(g)
    check(load())


# ---------------------------------------------------------------------------------------------------- PW-2 rows
PW2 = dict(limit_mv=20.0, outp_ideal=0.1322, outp_ab=0.1379, outn_ideal=0.04426, outn_ab=0.04942,
           vin_dc1m_ideal=5.744810556, vin_dc1m_ab=5.695303341)
PW2_BLOCK = next(b for b in TABLE.EVIDENCE if b.get('id') == 'pw2_rows')


def pw2_rows(p):
    """the three rows of the ripple table as the engine renders them from the v2 table: OUT+ and OUT- are PW-2 nodes judged against the limit;
    VIN is not a PW-2 node, so it carries no PW-2 verdict (the study JSON's own verdict.vin applies the OUT limit to it and is never quoted)"""
    return load().table_rows(PW2_BLOCK, dict(pw2=p))


def test_pw2_vin_row_is_not_a_pw2_verdict_and_takes_its_numbers_from_the_data():
    rows = {r[0]: r for r in pw2_rows(PW2)}
    vin = rows['VIN (+5V_F)']
    assert vin[1] == 'not a PW-2 node; judged by PW-4 in band (DC-1 MHz)'
    assert vin[2] == ('ideal 5.745 vs as-built 5.695 mV rms, equal; no PW-4 pass claimed (VT-8 bench); 10-30 MHz content unvalidated')
    assert 'fail' not in ' '.join(vin).lower() and vin[3] == 'no PW-2 verdict'
    assert rows['OUT+ (+3V3A)'][3] == rows['OUT- (VNEG)'][3] == 'PW-2 pass' and '20 mV' in rows['OUT+ (+3V3A)'][1]
    assert '0.132 / 0.138' in rows['OUT+ (+3V3A)'][2] and '0.044 / 0.049' in rows['OUT- (VNEG)'][2]
    q = dict(PW2, vin_dc1m_ideal=1.5, vin_dc1m_ab=2.25)             # a different input moves the row: nothing is typed in
    assert 'ideal 1.5 vs as-built 2.25 mV rms' in {r[0]: r for r in pw2_rows(q)}['VIN (+5V_F)'][2]


def test_pw2_rows_match_the_study_json_on_disk():
    """the table's dotted paths read the study file, and the row built from what they read quotes its figures"""
    g = load()
    old = g.REPO
    try:
        ctx, written = g.load_evidence(TABLE)
    finally:
        assert g.REPO == old
    assert list(written['pw2.json']) == list(TABLE.EVIDENCE_DATA[2]['values'])         # the data file keeps its keys, in order
    vin = {r[0]: r for r in g.table_rows(PW2_BLOCK, ctx)}['VIN (+5V_F)']
    assert 'ideal 5.745 vs as-built 5.695 mV rms' in vin[2]


def test_decoupling_row_is_labelled_lr4():
    row, label, field = TABLE.LR_RENAMES[0]
    assert (row, field) == ('LR-12 DECOUP_MAX', 'DECOUP_MAX') and label.format(3.0) == 'LR-4 decoupling (DECOUP_MAX 3.0 mm)'


def test_template_number_format_and_missing_inputs():
    g = load()
    assert g.tpl('{a:n3} {b:n2} {c[k]:n4}', a=0.1322, b=5.0, c=dict(k=0.52)) == '0.132 5 0.52'
    assert g._derive(dict(name='t', op='add', args=('awg.x', 'awg.y')), dict(awg=None)) is None          # a `find` that found nothing
    assert g._derive(dict(name='t', op='add', args=('awg.x', 2.0)), dict(awg=dict(x=1.5))) == 3.5


# ---------------------------------------------------------------------------------------------------- connectivity proof
SQ = lambda x0, y0, x1, y1: [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def two_pads(**kw):
    s = Synth('/N', '/OTHER').part('A', 0, 0).part('B', 10, 0)
    s.p('A', '1', 0.0, 0.0, '/N').p('B', '1', 10.0, 0.0, '/N')
    return s


def comps(c, g):
    return c.components(g)


def test_zone_fill_joins_two_pads_and_removing_it_separates_them():
    g3 = load()
    c = g3.CONN
    b = two_pads().z('/N', 'F', [(SQ(-2, -2, 12, 2), 0)]).build()
    on = c.copper_graph(b, '/N')
    assert on['pad_comp']['A.1'] == on['pad_comp']['B.1'] and c.join_path(on, 'A.1', 'B.1')[1][1] == 'pad inside fill'
    off = c.copper_graph(b, '/N', zones=False)
    assert off['pad_comp']['A.1'] != off['pad_comp']['B.1'] and c.join_path(off, 'A.1', 'B.1') is None


def test_only_a_filled_copper_zone_of_the_same_net_on_the_pads_layer_joins():
    c = load().CONN
    for kw, why in ((dict(net='/OTHER', layer='F'), 'foreign net'), (dict(net='/N', layer='B'), 'other layer (pads are on F.Cu only)'),
                    (dict(net='/N', layer='F', keepout=True), 'rule area'), (dict(net='/N', layer='F', filled=False), 'unfilled')):
        b = two_pads().z(kw.get('net'), kw.get('layer'), [(SQ(-2, -2, 12, 2), 0)], filled=kw.get('filled', True), keepout=kw.get('keepout', False)).build()
        g = c.copper_graph(b, '/N')
        assert g['pad_comp']['A.1'] != g['pad_comp']['B.1'], why


def test_two_fill_islands_do_not_join_and_a_pad_in_a_hole_is_not_in_the_fill():
    c = load().CONN
    two = two_pads().z('/N', 'F', [(SQ(-2, -2, 4, 2), 0), (SQ(6, -2, 12, 2), 0)]).build()          # a slot cuts the fill in two islands
    g = c.copper_graph(two, '/N')
    assert g['pad_comp']['A.1'] != g['pad_comp']['B.1'] and g['counts']['zone_fills'] == 2
    holed = two_pads().z('/N', 'F', [(SQ(-2, -2, 12, 2), 0), (SQ(-1, -1, 1, 1), 1)]).build()       # A.1 sits inside a hole of the one island
    g2 = c.copper_graph(holed, '/N')
    assert g2['pad_comp']['A.1'] != g2['pad_comp']['B.1']
    assert c.copper_graph(two_pads().z('/N', 'F', [(SQ(-2, -2, 12, 2), 0)]).build(), '/N')['counts']['zone_fills'] == 1


def chain():
    """A.1 - track - track (corner, ends 0.14 mm apart, inside each other's width) - track - via - B.Cu track - via - track - B.1"""
    s = two_pads()
    s.s('/N', 'F', 0.0, 0.0, 3.0, 0.0, w=0.3).s('/N', 'F', 3.1, 0.1, 5.0, 0.1, w=0.3).v('/N', 5.0, 0.1)
    s.s('/N', 'B', 5.0, 0.1, 8.0, 0.1, w=0.3).v('/N', 8.0, 0.1).s('/N', 'F', 8.0, 0.1, 10.0, 0.0, w=0.3)
    return s


def test_tracks_vias_and_overlapping_corners_join_and_a_foreign_track_does_not():
    c = load().CONN
    g = c.copper_graph(chain().build(), '/N')
    assert g['pad_comp']['A.1'] == g['pad_comp']['B.1'] and g['counts'] == dict(tracks=4, vias=2, pads=2, zone_fills=0)
    assert [x[1] for x in c.join_path(g, 'A.1', 'B.1')][1:4] == ['track reaches pad', 'track end meets track', 'track reaches via']
    s = chain().s('/OTHER', 'F', 4.0, -1.0, 4.0, 1.0)              # crossing the chain on the same layer: other net, never joined
    g2 = c.copper_graph(s.build(), '/N')
    assert g2['counts']['tracks'] == 4 and g2['pad_comp']['A.1'] == g2['pad_comp']['B.1']


def test_broken_once_every_track_of_the_chain_separates_the_pads():
    """the arm that can fail: remove each of the four tracks in turn and the pads must be separate; the via is bridged only by the B.Cu track"""
    c = load().CONN
    b = chain().build()
    assert len(b.s_idx) == 4
    for k in range(4):
        g = c.copper_graph(b, '/N', drop={k})
        assert g['pad_comp']['A.1'] != g['pad_comp']['B.1'], k
    with_zone = chain().z('/N', 'F', [(SQ(-2, -2, 12, 2), 0)]).build()      # a pour over everything: no single cut separates them
    assert all(c.copper_graph(with_zone, '/N', drop={k})['pad_comp']['A.1'] == c.copper_graph(with_zone, '/N', drop={k})['pad_comp']['B.1'] for k in range(4))


BOARD_TEXT = '''(kicad_pcb
\t(segment
\t\t(start 50 150)
\t\t(end 53 150)
\t\t(width 0.3)
\t\t(layer "F.Cu")
\t\t(net "/N")
\t\t(uuid "a")
\t)
\t(segment
\t\t(start 53.1 149.9)
\t\t(end 55 149.9)
\t\t(width 0.3)
\t\t(layer "F.Cu")
\t\t(net "/N")
\t\t(uuid "b")
\t)
\t(zone
\t\t(net "/GND")
\t\t(layer "F.Cu")
\t\t(priority 2)
\t\t(hatch edge 0.5)
\t\t(polygon
\t\t\t(pts
\t\t\t\t(xy 0 0) (xy 1 0) (xy 1 1)
\t\t\t)
\t\t)
\t)
\t(zone
\t\t(layers "F.Cu" "B.Cu")
\t\t(name "band")
\t\t(keepout
\t\t\t(tracks not_allowed)
\t\t)
\t\t(polygon
\t\t\t(pts
\t\t\t\t(xy 0 0) (xy 1 0) (xy 1 1) (xy 0 1)
\t\t\t)
\t\t)
\t)
)
'''


def test_cut_segment_text_removes_exactly_one_track_by_coordinates():
    c = load().CONN
    new, n = c.cut_segment_text(BOARD_TEXT, (3.1, 0.1, 5.0, 0.1))
    assert n == 1 and '(start 53.1 149.9)' not in new and '(start 50 150)' in new and new.count('(segment') == 1
    new2, n2 = c.cut_segment_text(BOARD_TEXT, (5.0, 0.1, 3.1, 0.1))                    # either end order
    assert n2 == 1 and new2 == new
    same, n3 = c.cut_segment_text(BOARD_TEXT, (7.0, 7.0, 8.0, 8.0))
    assert n3 == 0 and same == BOARD_TEXT


def test_board_zones_names_nets_layers_priority_and_rule_areas():
    z = load().CONN.board_zones(BOARD_TEXT)
    assert [(x['net'], x['layers'], x['keepout'], x['priority'], x['name']) for x in z] == [('/GND', ['F.Cu'], False, 2, ''), ('', ['F.Cu', 'B.Cu'], True, 0, 'band')]


def test_drc_unconnected_names_pads_and_lost_pads_follow_the_graph():
    g3 = load()
    rep = dict(unconnected_items=[dict(items=[dict(description='Pad 12 [/+5V_F] of U401 on F.Cu'), dict(description='Track [/+5V_F] on F.Cu, length 0.2828 mm')])])
    u = g3.drc_unconnected(rep)
    assert u[0]['pads'] == ['U401.12'] and u[0]['nets'] == ['/+5V_F']
    assert g3.drc_unconnected({}) == []
    c = g3.CONN
    b = chain().build()
    assert g3.lost_pads(c.copper_graph(b, '/N', drop={2}), 'A.1') == ['B.1']
    assert g3.lost_pads(c.copper_graph(b, '/N'), 'A.1') == []


def test_mutation_broken_connectivity_is_caught():
    """a graph that never joins tracks to pads must fail the chain test, and the unbroken module must pass again"""
    g = load()
    g.CONN.seg_box = lambda s, box: 9e9
    with pytest.raises(AssertionError):
        _chain_check(g)
    _chain_check(load())


def _chain_check(g):
    c = g.CONN
    gr = c.copper_graph(chain().build(), '/N')
    assert gr['pad_comp']['A.1'] == gr['pad_comp']['B.1']
