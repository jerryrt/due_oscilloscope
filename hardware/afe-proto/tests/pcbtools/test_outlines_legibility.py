"""LR-11 on the integrated v2 layout: the outlines drawn on the silkscreen (extracted, compared with the one table the config
reads), the shared-part rule, and the designator legibility check. Pure text / numpy except the one pcbnew-marked board run."""
import importlib.util
import os
import pathlib
import sys

import numpy as np
import pytest

from pcbtools import boardio, rules as R

from synth import Synth, cfg

LAYOUT = pathlib.Path(__file__).resolve().parents[2] / 'v2' / 'layout'
BOARD = LAYOUT / 'integrated' / 'afe-v2-integrated.kicad_pcb'
sys.path.insert(0, str(LAYOUT))
import draw_outlines as D  # noqa: E402
import outlines as TABLE  # noqa: E402
import outlines_from_silk as X  # noqa: E402


# ----------------------------------------------------------------------------- the extraction, on a synthetic dashed outline
def dashed(x0, y0, x1, y1, dash=0.6, gap=1.2, skip=()):
    """gr_line text for a dashed rectangle in KiCad sheet mm; `skip` = (x_lo, x_hi) windows left undrawn on the horizontal sides"""
    out = []

    def line(a, b, c, d, w=0.15):
        out.append(f'\t(gr_line\n\t\t(start {a} {b})\n\t\t(end {c} {d})\n\t\t(stroke\n\t\t\t(width {w})\n\t\t\t(type default)\n\t\t)\n'
                   f'\t\t(layer "F.SilkS")\n\t\t(uuid "00000000-0000-4000-8000-000000000000")\n\t)\n')

    def run(lo, hi, fn, windows=()):
        t = lo
        while t < hi:
            u = min(t + dash, hi)
            if not any(w0 <= t <= w1 for w0, w1 in windows):
                fn(t, u)
            t += dash + gap
    run(x0, x1, lambda a, b: line(a, y0, b, y0), skip)
    run(x0, x1, lambda a, b: line(a, y1, b, y1), skip)
    run(y0, y1, lambda a, b: line(x0, a, x0, b))
    run(y0, y1, lambda a, b: line(x1, a, x1, b))
    return ''.join(out)


# sheet rectangles (x0, y0, x1, y1), y down; their Due equivalents are (x0 - 50, 150 - y1, x1 - 50, 150 - y0)
SHEET = [(70, 120, 95, 140), (96, 120, 110, 133), (112, 100, 140, 118), (112, 119, 140, 131)]
DUE = sorted((a - 50, 150 - d, c - 50, 150 - b) for a, b, c, d in SHEET)


def synth_text(shift=None):
    t = ''
    for i, r in enumerate(SHEET):
        if shift and i == shift[0]:
            r = (r[0] + shift[1], r[1], r[2] + shift[1], r[3])
        t += dashed(*r, skip=((r[0] + 5, r[0] + 6.9),) if i == 2 else ())
    # an arrow shaft and head at 0.2 mm, and a diagonal: not outline sides
    t += '\t(gr_line\n\t\t(start 80 150)\n\t\t(end 84 150)\n\t\t(stroke\n\t\t\t(width 0.2)\n\t\t\t(type default)\n\t\t)\n\t\t(layer "F.SilkS")\n\t)\n'
    t += '\t(gr_line\n\t\t(start 84 150)\n\t\t(end 83 151)\n\t\t(stroke\n\t\t\t(width 0.15)\n\t\t\t(type default)\n\t\t)\n\t\t(layer "F.SilkS")\n\t)\n'
    return '(kicad_pcb\n' + t + ')\n'


def extract(text):
    return sorted(X.to_due_rect(r) for r in X.rects_from_segments(X.silk_segments(text)))


def test_extraction_recovers_known_rectangles_from_dashed_outlines():
    got = extract(synth_text())
    assert X.same(got, DUE, tol=0.01), (got, DUE)


def test_extraction_ignores_other_layers_and_widths():
    back = dashed(150, 100, 170, 120).replace('F.SilkS', 'B.SilkS')                    # a whole outline, on the back silk
    wide = dashed(150, 130, 170, 145).replace('(width 0.15)', '(width 0.3)')           # and one at another stroke width
    t = synth_text()[:-2] + back + wide + ')\n'
    assert X.same(extract(t), DUE, tol=0.01)


def test_extraction_of_a_one_millimetre_shift_differs():
    got = extract(synth_text(shift=(1, 1.0)))
    assert not X.same(got, DUE, tol=0.15)
    moved = sorted(DUE[:1] + [(r[0] + 1, r[1], r[2] + 1, r[3]) for r in DUE[1:2]] + DUE[2:])
    assert X.same(got, moved, tol=0.01), (got, moved)


# ----------------------------------------------------------------------------- LR-11 membership from extracted outlines, and its mutation
def outline_cfg(rects, **over):
    d = dict(BLOCK={'R101': 'CH1', 'TP101': 'CH1', 'R201': 'CH2'}, BLOCK_OVERRIDE={}, OUTLINE={'CH1': [rects[0]], 'CH2': [rects[1]]},
             TEST_BLOCKS=('CH1',), TP_NETS={'TP101': '/A1'}, SILK_WORDS=('CH1',), LR_HUNDREDS={'1': 'CH1', '2': 'CH2'})
    d.update(over)
    return cfg(**d)


def membership_board():
    s = Synth('/A1', '/GND')
    s.part('R101', 30, 20).part('TP101', 10.5, 25).p('TP101', '1', 10.5, 25, '/A1').part('R201', 30, 6.0)
    return s.text('CH1').build()


def test_lr11_follows_the_drawn_outlines_and_fails_when_one_is_shifted():
    chs = [(10.0, 17.0, 40.0, 32.0), (10.0, 0.0, 40.0, 15.0)]
    r = R.lr11(membership_board(), outline_cfg(chs))
    assert r.ok, r.detail
    shifted = [(chs[0][0] + 1.0, *chs[0][1:]), chs[1]]                         # outline moved 1 mm east: TP101 (x 10.5) falls out
    r = R.lr11(membership_board(), outline_cfg(shifted))
    assert not r.ok and "lacks ['TP101']" in r.detail, r.detail


def test_shared_part_is_held_to_its_home_outline_and_is_no_extra_elsewhere():
    s = Synth('/A1', '/GND').part('U101', 20, 16.0).part('TP101', 20.5, 25).p('TP101', '1', 20.5, 25, '/A1').part('R201', 30, 6.0)
    s.text('CH1')
    b = s.build()
    chs = [(10.0, 16.0, 40.0, 32.0), (10.0, 0.0, 40.0, 16.0)]                  # U101 centre on the fence line y = 16 mm: in both rectangles
    base = dict(BLOCK={'U101': 'CH1', 'TP101': 'CH1', 'R201': 'CH2'})
    r = R.lr11(b, outline_cfg(chs, **base))
    assert not r.ok and "CH2: outline holds ['U101'] extra" in r.detail           # without the declaration it passes by accident or not at all
    r = R.lr11(b, outline_cfg(chs, SHARED_PARTS={'U101': 'CH1'}, SHARED_MARGIN=0.25, **base))
    assert r.ok, r.detail
    chs2 = [(10.0, 16.1, 40.0, 32.0), (10.0, 0.0, 40.0, 15.9)]                 # drawn 0.1 mm either side of the centre: held within the margin
    assert R.lr11(b, outline_cfg(chs2, SHARED_PARTS={'U101': 'CH1'}, SHARED_MARGIN=0.25, **base)).ok
    chs3 = [(10.0, 17.0, 40.0, 32.0), (10.0, 0.0, 40.0, 15.0)]                 # a millimetre off its home outline: no longer held
    r = R.lr11(b, outline_cfg(chs3, SHARED_PARTS={'U101': 'CH1'}, SHARED_MARGIN=0.25, **base))
    assert not r.ok and "lacks ['U101']" in r.detail


# ----------------------------------------------------------------------------- designator legibility
LEG = dict(DESIGNATOR_ADVANCE=0.95, DESIGNATOR_INK_H=1.2, DESIGNATOR_GAP_MIN=0.8, DESIGNATOR_DIST_MAX=3.0)


def leg_board(dx=6.0, label_dy=2.0, h=1.0, dy2=0.0):
    """two 0402-like parts, dx apart, each with a pad pair, designator text label_dy above its part"""
    s = Synth('/A1', '/GND')
    for ref, x in (('R101', 20.0), ('R102', 20.0 + dx)):
        s.part(ref, x, 10.0, h=h)
        s.p(ref, '1', x - 0.5, 10.0, '/A1', size=0.6).p(ref, '2', x + 0.5, 10.0, '/GND', size=0.6)
    s.rt[0] = (20.0, 10.0 + label_dy, h, h, 0.15, 0.0, 0, True, 0)
    s.rt[1] = (20.0 + dx, 10.0 + label_dy + dy2, h, h, 0.15, 0.0, 0, True, 1)
    return s.build()


def test_legibility_passes_for_well_separated_designators():
    close, over, far, n = R.designator_findings(leg_board(dx=6.0), cfg(**LEG))
    assert (close, over, far, n) == ([], [], [], 2)


def test_legibility_fails_when_two_designators_are_moved_together():
    c = cfg(**LEG)
    assert not R.designator_findings(leg_board(dx=6.0), c)[0]
    close = R.designator_findings(leg_board(dx=4.0), c)[0]                         # 4 mm pitch, 3.8 mm labels: 0.2 mm apart
    assert [(a, b) for a, b, g in close] == [('R101', 'R102')] and close[0][2] == pytest.approx(0.2, abs=0.01)
    close = R.designator_findings(leg_board(dx=3.0), c)[0]                         # overlapping
    assert close and close[0][2] == 0.0
    # the gap is the config's: at 0.1 mm the 0.2 mm pair is fine
    assert not R.designator_findings(leg_board(dx=4.0), cfg(**{**LEG, 'DESIGNATOR_GAP_MIN': 0.1}))[0]


def test_legibility_vertical_text_uses_the_rotated_box():
    s = Synth('/A1', '/GND')
    for ref, x in (('R101', 20.0), ('R102', 22.0)):
        s.part(ref, x, 10.0).p(ref, '1', x, 10.0, '/A1').p(ref, '2', x, 10.5, '/GND')
    s.rt[0] = (20.0, 12.0, 1.0, 1.0, 0.15, 90.0, 0, True, 0)
    s.rt[1] = (22.1, 12.0, 1.0, 1.0, 0.15, 90.0, 0, True, 1)
    c = cfg(**LEG)
    # vertical boxes 1.2 wide, 3.8 tall, 2.1 mm apart centre to centre: 0.9 mm between them, over the 0.8 limit
    assert R.designator_findings(s.build(), c)[0] == []
    s.rt[1] = (21.8, 12.0, 1.0, 1.0, 0.15, 90.0, 0, True, 1)                         # 1.8 apart: 0.6 mm between them
    assert len(R.designator_findings(s.build(), c)[0]) == 1


def test_legibility_fails_over_another_parts_pad_and_far_from_its_own():
    s = Synth('/A1', '/GND')
    s.part('R101', 20.0, 10.0).p('R101', '1', 19.5, 10.0, '/A1').p('R101', '2', 20.5, 10.0, '/GND')
    s.part('R102', 40.0, 10.0).p('R102', '1', 39.5, 10.0, '/A1').p('R102', '2', 40.5, 10.0, '/GND')
    s.rt[0] = (40.0, 10.0, 1.0, 1.0, 0.15, 0.0, 0, True, 0)                       # R101's label sits on R102's pads
    s.rt[1] = (40.0, 12.0, 1.0, 1.0, 0.15, 0.0, 0, True, 1)
    close, over, far, _ = R.designator_findings(s.build(), cfg(**LEG))
    assert ('R101', 'R102') in over and [f[0] for f in far] == ['R101']
    r = R.lr11(s.text('CH1').build(), cfg(BLOCK={'R101': 'CH1', 'R102': 'CH1'}, BLOCK_OVERRIDE={}, OUTLINE={'CH1': [(0, 0, 60, 30)]},
                                          TEST_BLOCKS=(), TP_NETS={}, SILK_WORDS=('CH1',), LR_HUNDREDS={'1': 'CH1'}, **LEG))
    assert not r.ok and 'over another part' in r.detail and 'from its part' in r.detail


def test_lr11_reports_close_pairs_by_name_and_is_off_without_the_thresholds():
    s = leg_board(dx=4.0)
    base = dict(BLOCK={'R101': 'CH1', 'R102': 'CH1'}, BLOCK_OVERRIDE={}, OUTLINE={'CH1': [(0, 0, 60, 30)]}, TEST_BLOCKS=(), TP_NETS={},
                SILK_WORDS=(), LR_HUNDREDS={'1': 'CH1'})
    r = R.lr11(s, cfg(**base, **LEG))
    assert not r.ok and 'R101/R102 0.2' in r.detail
    assert R.lr11(s, cfg(**base)).ok                                               # a config without DESIGNATOR_GAP_MIN is not held to it


def test_a_waived_pair_passes_on_its_recorded_floor_and_fails_below_it():
    s = leg_board(dx=4.0)                                                          # the pair is 0.2 mm apart, under the 0.8 limit
    base = dict(BLOCK={'R101': 'CH1', 'R102': 'CH1'}, BLOCK_OVERRIDE={}, OUTLINE={'CH1': [(0, 0, 60, 30)]}, TEST_BLOCKS=(), TP_NETS={},
                SILK_WORDS=(), LR_HUNDREDS={'1': 'CH1'}, **LEG)
    r = R.lr11(s, cfg(DESIGNATOR_GAP_WAIVED={('R101', 'R102'): 0.15}, **base))
    assert r.ok and r.figures['waived_pairs'] == 1 and '1 designator pairs under the gap' in r.detail
    r = R.lr11(s, cfg(DESIGNATOR_GAP_WAIVED={('R101', 'R102'): 0.25}, **base))        # moved closer than the floor it was recorded at
    assert not r.ok and 'R101/R102 0.2' in r.detail
    assert not R.lr11(s, cfg(DESIGNATOR_GAP_WAIVED={('R101', 'R103'): 0.0}, **base)).ok   # a waiver names its pair


# ----------------------------------------------------------------------------- drawing what the silk lacks
def test_draw_adds_only_the_missing_rectangle_and_is_idempotent():
    text = synth_text()
    table = [r for r in DUE] + [(80.0, 5.0, 90.0, 15.0)]
    new, added = D.draw(text, table)
    assert added == [(80.0, 5.0, 90.0, 15.0)]
    assert X.same(extract(new), sorted(table), tol=0.01)
    again, added2 = D.draw(new, table)
    assert added2 == [] and again == new


def test_draw_skips_what_is_already_drawn_on_a_side():
    # Due x 50..60, y 5..15 = sheet x 100..110, y 135..145
    assert len(D.rect_segments((50.0, 5.0, 60.0, 15.0), [(100.0, 140.0, 110.0, 140.0)])) == 4       # a line through it is no side
    assert len(D.rect_segments((50.0, 5.0, 60.0, 15.0), [(100.0, 145.0, 110.0, 145.0)])) == 3       # the y = 145 side already drawn
    left = D.rect_segments((50.0, 5.0, 60.0, 15.0), [(100.0, 145.0, 104.0, 145.0)])                 # half of it drawn: the rest is added
    assert sorted(s for s in left if s[1] == s[3] == 145.0) == [(104.0, 145.0, 110.0, 145.0)]


# ----------------------------------------------------------------------------- the board of record
def _board_text():
    return BOARD.read_text()


def test_board_silk_outlines_equal_the_table():
    found = extract(_board_text())
    want = TABLE.all_rects()
    assert X.same(found, want), (found, sorted(want))


def test_board_silk_shifted_one_millimetre_no_longer_equals_the_table():
    segs = X.silk_segments(_board_text())
    in_ch1 = lambda g: 113.8 <= min(g[0], g[2]) and max(g[0], g[2]) <= 143.05 and 99.9 <= min(g[1], g[3]) and max(g[1], g[3]) <= 117.05
    assert sum(in_ch1(g) for g in segs) > 10                                           # CH1's main rectangle: many dashes
    shifted = [(g[0] + 1.0, g[1], g[2] + 1.0, g[3]) if in_ch1(g) else g for g in segs]
    got = sorted(X.to_due_rect(r) for r in X.rects_from_segments(shifted))
    assert not X.same(got, TABLE.all_rects())


def test_v2_layout_config_carries_the_table_and_the_frozen_config_is_unchanged():
    from pcbtools.boards import v2, v2_layout
    assert {k: [tuple(r) for r in v] for k, v in v2_layout.OUTLINE.items()} == {k: list(v) for k, v in TABLE.RECTS.items()}
    assert v2_layout.SHARED_PARTS == {'U101': 'CH1'} == TABLE.SHARED_PARTS
    assert not hasattr(v2, 'SHARED_PARTS') and not hasattr(v2, 'DESIGNATOR_GAP_MIN')
    assert v2_layout.ANALOG_FENCE == v2.ANALOG_FENCE and v2_layout.BLOCK == v2.BLOCK


@pytest.mark.pcbnew
def test_integrated_board_lr11_passes_and_the_shared_parts_sit_where_the_finding_says(pcbnew_required):
    from pcbtools.boards import v2_layout as c
    b = boardio.read_board(str(BOARD))
    r = R.lr11(b, c)
    assert r.ok, r.detail
    refs = list(b.fp_ref)
    P = np.column_stack([b.fp_x, b.fp_y])
    inside = {k: {refs[i] for i in np.flatnonzero(R._in_rects(P, v))} for k, v in c.OUTLINE.items()}
    grown = [(x0 - c.SHARED_MARGIN, y0 - c.SHARED_MARGIN, x1 + c.SHARED_MARGIN, y1 + c.SHARED_MARGIN) for x0, y0, x1, y1 in c.OUTLINE['CH1']]
    i = refs.index('U101')
    assert R._in_rects(P[i:i + 1], grown)[0] and 'U101' not in inside['CH2']           # the shared dual: held to CH1, no extra in CH2
    assert 'TP101' in inside['CH1'] and 'D201' in inside['CH2'] and 'D201' not in inside['CH1']
    close, over, far, n = R.designator_findings(b, c)
    assert over == [] and far == [] and n == 112
    assert 0 < len(close) <= len(c.DESIGNATOR_GAP_WAIVED) == 8                           # 74 pairs were under 1.0 mm before the placement
    assert all(g >= c.DESIGNATOR_GAP_WAIVED[(a, b_)] and g >= 0.3 for a, b_, g in close)   # each on its recorded floor, none touching
    assert c.DESIGNATOR_FOREIGN_WAIVED == {'BR501': 'CH2', 'BR504': 'CH2'}               # R203 and R204 left the waived set when the CH2 array moved north
    refs_ = list(b.fp_ref)
    for ref_ in ('R203', 'R204'):                                                    # their labels sit inside the CH2 outline, with no waiver
        k = [k for k in range(len(b.r_fp)) if refs_[int(b.r_fp[k])] == ref_][0]
        assert any(x0 <= b.r_x[k] <= x1 and y0 <= b.r_y[k] <= y1 for x0, y0, x1, y1 in c.OUTLINE['CH2']), ref_
    assert R.one_label_pairs(b, c) == [] and R.foreign_labels(b, c) == []                  # nothing reads as one label; no label in a foreign outline
    assert not [k for k in c.DESIGNATOR_GAP_WAIVED if k not in {(a, b_) for a, b_, g in close}]   # every waiver names a live pair


# ----------------------------------------------------------------------------- reads as one label, and a label in a foreign outline
def test_two_labels_at_0_3_mm_on_one_baseline_fail_and_a_waiver_cannot_cover_them():
    s = leg_board(dx=4.1)                                                          # 3.8 mm boxes, 4.1 pitch: 0.3 mm apart, same baseline
    base = dict(BLOCK={'R101': 'CH1', 'R102': 'CH1'}, BLOCK_OVERRIDE={}, OUTLINE={'CH1': [(0, 0, 60, 30)]}, TEST_BLOCKS=(), TP_NETS={},
                SILK_WORDS=(), LR_HUNDREDS={'1': 'CH1'}, DESIGNATOR_GAP_ONE_LABEL=0.6, **LEG)
    assert [(a, b_) for a, b_, g in R.one_label_pairs(s, cfg(**base))] == [('R101', 'R102')]
    r = R.lr11(s, cfg(DESIGNATOR_GAP_WAIVED={('R101', 'R102'): 0.25}, **base))
    assert not r.ok and 'read as one label' in r.detail
    assert R.lr11(s, cfg(DESIGNATOR_GAP_WAIVED={('R101', 'R102'): 0.25}, **{**base, 'DESIGNATOR_GAP_ONE_LABEL': 0.25})).ok   # the limit is the config's
    assert not R.one_label_pairs(leg_board(dx=4.5), cfg(**base))                   # 0.7 mm apart: not one label


def test_offset_rows_under_the_limit_are_not_one_label():
    s = leg_board(dx=4.1, dy2=1.4)                                                 # 1.4 mm higher: next line, not the same baseline
    assert not R.one_label_pairs(s, cfg(DESIGNATOR_GAP_ONE_LABEL=0.6, **LEG))


def test_a_label_centred_in_another_blocks_outline_fails_unless_waived_exactly():
    s = leg_board(dx=6.0)
    base = dict(BLOCK={'R101': 'CH1', 'R102': 'CH1'}, BLOCK_OVERRIDE={}, OUTLINE={'CH1': [(0, 0, 24, 30)], 'CH2': [(24.5, 0, 60, 30)]},
                TEST_BLOCKS=(), TP_NETS={}, SILK_WORDS=(), LR_HUNDREDS={'1': 'CH1'}, EDGE_BLOCK='EDGE', **LEG)
    assert R.foreign_labels(s, cfg(**base)) == [('R102', 'CH2')]                   # R102's label sits at x 26, in CH2's outline
    r = R.lr11(s, cfg(**base))
    assert not r.ok and "inside another block's outline: R102 in CH2" in r.detail
    assert not R.foreign_labels(s, cfg(DESIGNATOR_FOREIGN_WAIVED={'R102': 'CH2'}, **base))
    assert R.foreign_labels(s, cfg(DESIGNATOR_FOREIGN_WAIVED={'R102': 'AWG'}, **base))
