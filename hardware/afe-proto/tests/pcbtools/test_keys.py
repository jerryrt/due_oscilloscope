"""pcbtools.keys: the cluster-key generator (D30 1b). Pure numpy / text except the one pcbnew-marked run on the real board.

Ground truth is built by the tests: a synthetic occupancy grid with a known free rectangle, CH2's part positions read from the board text, and
the edit's own diff. Broken once on purpose, as the suite requires."""
import pathlib
import re
import types

import numpy as np
import pytest

from pcbtools import keys as K
from pcbtools.boards import v2_layout as CFG

BOARD = pathlib.Path(__file__).resolve().parents[2] / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb'


def positions(text, refs):
    out = {}
    for r in refs:
        s, e = K._fp_span(text, r)
        m = re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)', text[s:e])
        out[r] = (float(m.group(1)) - 50.0, 150.0 - float(m.group(2)))
    return out


def test_ch2_rows_and_columns_follow_the_parts_in_order():
    refs = list(CFG.KEYS['CH2']['parts'])
    xy = positions(BOARD.read_text(), refs)
    rows, ncols, col_of = K.layout(refs, xy, CFG)
    # the board's pattern, top (largest y) to bottom, left to right: R208 C203 / R207 R202 R201 / C202 C201 / R206 R205 R203 R204
    assert rows == [['R208', 'C203'], ['R207', 'R202', 'R201'], ['C202', 'C201'], ['R206', 'R205', 'R203', 'R204']]
    assert ncols == 4
    for row in rows:                                                    # within a row the columns increase with x
        cols = [col_of[r] for r in row]
        assert cols == sorted(cols) and len(set(cols)) == len(cols)
    assert col_of['R208'] == col_of['R206'] and col_of['C203'] == col_of['R207'] == col_of['C202'] == col_of['R205']


def test_broken_once_a_row_tolerance_that_merges_rows_is_caught():
    refs = list(CFG.KEYS['CH2']['parts'])
    xy = positions(BOARD.read_text(), refs)
    bad = types.SimpleNamespace(**{k: getattr(CFG, k) for k in dir(CFG) if k.startswith('KEY_')})
    bad.KEY_ROW_TOL = 2.0
    rows, _, _ = K.layout(refs, xy, bad)
    assert rows != [['R208', 'C203'], ['R207', 'R202', 'R201'], ['C202', 'C201'], ['R206', 'R205', 'R203', 'R204']] and len(rows) < 4


def test_key_size_is_from_the_config():
    refs = list(CFG.KEYS['CH2']['parts'])
    w, h = K.size(refs, 4, 4, CFG)
    longest = 4 * CFG.KEY_ADVANCE * CFG.KEY_TEXT_H
    assert w == pytest.approx(3 * (longest + CFG.KEY_COL_GAP) + longest + 2 * CFG.KEY_MARGIN)
    assert h == pytest.approx(3 * CFG.KEY_ROW_PITCH + CFG.KEY_INK_H * CFG.KEY_TEXT_H + 2 * CFG.KEY_MARGIN)


def test_free_positions_find_exactly_the_free_rectangle():
    g = K.Grid((0.0, 0.0, 20.0, 10.0))
    g.mark(0, 0, 20, 10)                                                # everything taken ...
    g.occ[20:50, 30:150] = False                                        # ... but y 2..5, x 3..15 (3 x 12 mm)
    x, y = g.free_positions(12.0, 3.0)
    assert (len(x), round(x[0], 1), round(y[0], 1)) == (1, 3.0, 2.0)
    assert len(g.free_positions(12.1, 3.0)[0]) == 0 and len(g.free_positions(12.0, 3.1)[0]) == 0     # one step bigger fits nowhere
    x, y = g.free_positions(6.0, 3.0)
    assert len(x) == 61 and x.min() == pytest.approx(3.0) and x.max() == pytest.approx(9.0)


def _plan():
    refs = list(CFG.KEYS['CH2']['parts'])
    rows = [['R208', 'C203'], ['R207', 'R202', 'R201'], ['C202', 'C201'], ['R206', 'R205', 'R203', 'R204']]
    texts = {r: (40.0 + 4.5 * i + 2, 40.0 + 1.6 * j) for j, row in enumerate(rows) for i, r in enumerate(row)}
    return K.Plan('CH2', (40.0, 39.0, 58.3, 46.0), texts, rows, 0.0), refs


def test_apply_edits_only_the_designators_and_adds_the_key_and_is_idempotent():
    p, refs = _plan()
    text = BOARD.read_text()
    new = K.apply(text, p, CFG)
    assert K.apply(new, p, CFG) == new                                   # twice changes nothing
    a, b = text.splitlines(), new.splitlines()
    import difflib
    removed = [l for l in difflib.unified_diff(a, b, lineterm='', n=0) if l.startswith('-') and not l.startswith('---')]
    added = [l for l in difflib.unified_diff(a, b, lineterm='', n=0) if l.startswith('+') and not l.startswith('+++')]
    assert len(removed) == len(refs) and all('"F.SilkS"' in l for l in removed)       # one layer line per keyed designator
    assert sum('(gr_rect' in l for l in added) == 1 and not any('(gr_line' in l for l in added) and sum('(gr_text' in l for l in added) == len(refs)
    assert sum('"F.Fab"' in l for l in added) == len(refs)
    for r in refs:
        s, e = K._fp_span(new, r)
        assert re.search(r'\(property "Reference" "%s"\n\t\t\t\(at [^)]*\)\n\t\t\t\(layer "F\.Fab"\)' % r, new[s:e])


def test_any_residue_list_gets_its_own_rows_and_columns_and_the_adjoin_limit_is_two_mm():
    assert CFG.KEY_ADJOIN_MAX == 2.0
    text = BOARD.read_text()
    res = ['R202', 'R203', 'C201', 'C203', 'R207', 'R205']                    # a residue of 6: two columns (x 84.4 and 87.5), four rows
    xy = positions(text, res)
    rows, ncols, _ = K.layout(res, xy, CFG)
    assert rows == [['C203'], ['R207', 'R202'], ['C201'], ['R205', 'R203']] and ncols == 2        # y 27.24 / 25.43 / 23.87 / 22.31; x 84.4 and 87.5
    assert sorted(r for row in rows for r in row) == sorted(res)              # exactly the listed parts, once each
    w, h = K.size(res, ncols, len(rows), CFG)
    assert w < K.size(list(CFG.KEYS['CH2']['parts']), 4, 4, CFG)[0]           # a smaller residue is a smaller key


def test_broken_once_a_key_for_a_part_the_board_lacks_is_refused():
    p, _ = _plan()
    p.texts['R999'] = (45.0, 40.0)
    with pytest.raises(KeyError):
        K.apply(BOARD.read_text(), p, CFG)


@pytest.mark.pcbnew
def test_ch2_has_no_free_area_adjoining_it_and_the_generator_says_so(pcbnew_required):
    from pcbtools import boardio
    text = BOARD.read_text()
    r = K.plan(boardio.read_board(str(BOARD)), text, CFG, 'CH2')
    assert isinstance(r, K.NoFit)
    assert r.need == pytest.approx(K.size(list(CFG.KEYS['CH2']['parts']), 4, 4, CFG))
    assert r.biggest_adjoining[0] < r.need[0] and r.biggest_adjoining[1] < r.need[1] or r.biggest_adjoining[0] * r.biggest_adjoining[1] < r.need[0] * r.need[1]
    assert r.nearest_gap > 10                                            # the nearest place it would fit is a different area of the board


# ------------------------------------------------------------------------------------------------ headings, the legend, compact layout
def fake_board(parts):
    """just what keys.legend reads: part positions {ref: (x, y)}"""
    refs = list(parts)
    return types.SimpleNamespace(ref_index=refs.index, fp_x=np.array([parts[r][0] for r in refs]), fp_y=np.array([parts[r][1] for r in refs]))


CH1 = {'R101': (10.0, 20.0), 'R102': (13.0, 20.0), 'C101': (10.1, 17.0), 'C102': (13.0, 17.0)}          # 2 x 2
CH2 = {'R201': (30.0, 20.0), 'R202': (32.0, 20.0), 'R203': (34.0, 20.0), 'C201': (31.0, 18.0), 'C202': (33.0, 18.0), 'U201': (35.0, 18.0)}
PARTS = {**CH1, **CH2}
FREE = K.Grid((0.0, 0.0, 80.0, 60.0))


def order_ok(ly, xy, tol=0.5):
    """silkread's order test on a layout: pairs of parts further apart than tol keep their order in the text positions (never a tie)"""
    pos = {r: (dx, -row) for r, (dx, row) in ly.cells.items()}
    for a in ly.refs:
        for c in ly.refs:
            for ax in (0, 1):
                dp = xy[c][ax] - xy[a][ax]
                dt = pos[c][ax] - pos[a][ax]
                if abs(dp) > tol and np.sign(dp) != np.sign(dt):
                    return False
    return True


@pytest.mark.parametrize('compact', [False, True])
def test_both_layouts_keep_the_parts_order_and_the_texts_apart(compact):
    xy = {**PARTS, 'R204': (36.0, 20.3), 'R205': (30.4, 18.0)}
    refs = list(CH2) + ['R204', 'R205']
    ly = K.build(refs, xy, CFG, heading='CH2', compact=compact)
    assert order_ok(ly, xy) and ly.heading == 'CH2'
    for r, (dx, row) in ly.cells.items():
        assert CFG.KEY_MARGIN - 1e-9 <= dx - len(r) * CFG.KEY_ADVANCE / 2 and dx + len(r) * CFG.KEY_ADVANCE / 2 <= ly.W - CFG.KEY_MARGIN + 1e-9, r
        assert row >= 1                                                    # row 0 is the heading
    for a in refs:                                                         # no two texts of one row overlap
        for c in refs:
            if a < c and ly.cells[a][1] == ly.cells[c][1]:
                assert abs(ly.cells[a][0] - ly.cells[c][0]) >= (len(a) + len(c)) * CFG.KEY_ADVANCE / 2 + CFG.KEY_COL_GAP - 1e-9


def test_compact_is_never_wider_than_the_grid_and_often_narrower():
    xy = {f'R{i}01': (10.0 + 3.0 * i, 20.0 + 2.0 * i) for i in range(6)}                           # a diagonal: 6 columns, 6 rows
    refs = list(xy)
    g, c = K.build(refs, xy, CFG), K.build(refs, xy, CFG, compact=True)
    assert c.W <= g.W + 1e-9 and c.W < g.W / 2 and c.H == pytest.approx(g.H) and order_ok(c, xy)


def test_a_legend_packs_headed_keys_into_one_region_without_touching_and_names_each_block():
    items = [('CH1', list(CH1)), ('CH2', list(CH2))]
    res = K.legend(fake_board(PARTS), '', CFG, items, [(0.0, 0.0, 40.0, 20.0)], grid=FREE)
    assert [p.heading for p in res] == ['CH1', 'CH2'] and all(p.mode == 'grid' for p in res)
    for p in res:
        assert p.box[0] >= 0 and p.box[2] <= 40.0 and p.box[1] >= 0 and p.box[3] <= 20.0
        for ref, (x, y) in p.texts.items():
            assert p.box[0] < x < p.box[2] and p.box[1] < y < p.box[3], ref
        assert p.box[0] < p.heading_at[0] < p.box[2] and p.heading_at[1] > max(y for _, y in p.texts.values())      # heading above its designators
    a, c = res[0].box, res[1].box
    assert a[2] + CFG.KEY_GAP <= c[0] + 1e-9 or c[2] + CFG.KEY_GAP <= a[0] + 1e-9 or a[3] + CFG.KEY_GAP <= c[1] + 1e-9 or c[3] + CFG.KEY_GAP <= a[1] + 1e-9


def test_a_legend_in_an_l_of_two_rectangles_puts_each_key_wholly_in_one_and_avoids_taken_cells():
    items = [('CH1', list(CH1)), ('CH2', list(CH2))]
    w1, h1 = K.build(list(CH1), PARTS, CFG, heading='CH1').W, K.build(list(CH1), PARTS, CFG, heading='CH1').H
    w2, h2 = K.build(list(CH2), PARTS, CFG, heading='CH2').W, K.build(list(CH2), PARTS, CFG, heading='CH2').H
    regions = [(0.0, 0.0, w2 + 0.2, h2 + 0.2), (0.0, 40.0, w1 + 0.2, 40.0 + h1 + 0.2)]               # each fits exactly one key
    res = K.legend(fake_board(PARTS), '', CFG, items, regions, grid=FREE)
    assert isinstance(res, list)
    for p in res:
        assert any(r[0] <= p.box[0] and p.box[2] <= r[2] and r[1] <= p.box[1] and p.box[3] <= r[3] for r in regions), p.box
    taken = K.Grid((0.0, 0.0, 80.0, 60.0))
    taken.mark(0.0, 0.0, 80.0, 60.0)
    taken.occ[:, :] = False
    taken.mark(0.0, 0.0, w2 + 0.2, h2 + 0.2)                                                          # the first region is taken
    res2 = K.legend(fake_board(PARTS), '', CFG, [('CH1', list(CH1))], regions, grid=taken)
    assert res2[0].box[1] >= 40.0 - 1e-9                                                                # so the key goes to the second


def test_a_legend_that_does_not_fit_says_what_it_needed_against_what_there_was():
    res = K.legend(fake_board(PARTS), '', CFG, [('CH1', list(CH1)), ('CH2', list(CH2))], [(0.0, 0.0, 9.0, 6.0)], grid=FREE)
    assert isinstance(res, K.LegendNoFit)
    assert res.available == [(9.0, 6.0)] and {n[0] for n in res.needs} == {'CH1', 'CH2'} and res.failed in ('CH1', 'CH2')
    assert 'need' in str(res) and 'CH2' in str(res) and '9.0 x 6.0' in str(res)


def test_the_compact_layout_is_the_fallback_when_the_grids_do_not_fit():
    xy = {f'R{i}01': (10.0 + 3.0 * i, 20.0 + 2.0 * i) for i in range(1, 6)}                         # block 1, a diagonal of 5
    xy = {r.replace('R', 'R1', 1)[:4]: v for r, v in xy.items()}
    refs = list(xy)
    gw = K.build(refs, xy, CFG, heading='CH1').W
    cw = K.build(refs, xy, CFG, heading='CH1', compact=True).W
    assert cw < gw
    res = K.legend(fake_board(xy), '', CFG, [('CH1', refs)], [(0.0, 0.0, (gw + cw) / 2, 30.0)], grid=FREE)
    assert isinstance(res, list) and res[0].mode == 'compact'


def test_broken_once_a_part_from_another_block_or_an_unknown_heading_is_refused():
    with pytest.raises(ValueError):
        K.legend(fake_board(PARTS), '', CFG, [('CH1', list(CH1) + ['R201'])], [(0.0, 0.0, 40.0, 20.0)], grid=FREE)       # R201 is a CH2 part
    with pytest.raises(ValueError):
        K.legend(fake_board(PARTS), '', CFG, [('NOTE', list(CH1))], [(0.0, 0.0, 40.0, 20.0)], grid=FREE)


def test_apply_a_legend_adds_one_rect_and_its_texts_per_key_with_the_heading_and_is_idempotent():
    real = ['R202', 'R203', 'R204', 'C201', 'C202']
    xy = positions(BOARD.read_text(), real)
    res = K.legend(fake_board(xy), '', CFG, [('CH2', real)], [(30.0, 30.0, 60.0, 47.0)], grid=K.Grid((0.0, 0.0, 117.0, 60.0)))
    text = BOARD.read_text()
    new = K.apply(text, res, CFG)
    assert K.apply(new, res, CFG) == new
    assert new.count('(gr_rect') == text.count('(gr_rect') + 1 and new.count('(gr_text "CH2"') == text.count('(gr_text "CH2"') + 1
    for r in real:
        assert new.count(f'(gr_text "{r}"') == 1
        s, e = K._fp_span(new, r)
        assert re.search(r'\(property "Reference" "%s"\n\t\t\t\(at [^)]*\)\n\t\t\t\(layer "F\.Fab"\)' % r, new[s:e])
