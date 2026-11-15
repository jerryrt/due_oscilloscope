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
