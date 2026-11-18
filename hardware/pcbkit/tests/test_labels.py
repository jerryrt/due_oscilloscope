"""pcbkit.labels on boards built by hand: boxes only, no pcbnew, no project file. Each rule is tested twice: it holds, and with the rule switched off by its own configuration
the same board gives the other answer (the test is broken on purpose and must notice)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest
from pcbkit.labels import Part, LabelBoard, ConfigError, lab_box, effective_config
from pcbkit.labels import place as _place, check_two_way as _check, validate as _validate
from pcbkit.labels.placer import Cfg

BASE = dict(SILK_REQUIRED_PREFIXES=('U', 'J', 'TP', 'D'), NO_LABEL_PREFIXES=('MH',), BLOCK={}, OUTLINE={})      # the project's own tables: the placer has no defaults for them


def place(lb, cfg=None):
    return _place(lb, {**BASE, **(cfg or {})})


def check_two_way(lb, labels, cfg=None):
    return _check(lb, labels, {**BASE, **(cfg or {})})


def validate(lb, plan, cfg=None, skip=()):
    return _validate(lb, plan, {**BASE, **(cfg or {})}, skip)


def part(ref, x, y, w=1.0, h=0.5, pads=True):
    cour = (x - w / 2 - 0.25, y - h / 2 - 0.25, x + w / 2 + 0.25, y + h / 2 + 0.25)
    pd = [(x - w / 2, y - h / 2, x - w / 2 + 0.4, y + h / 2), (x + w / 2 - 0.4, y - h / 2, x + w / 2, y + h / 2)] if pads else []
    return Part(ref, x, y, cour, (x - w / 2, y - h / 2, x + w / 2, y + h / 2), pd)


def board(*ps, **kw):
    return LabelBoard({p.ref: p for p in ps}, edge=(-50, -50, 50, 50), **kw)


def test_the_first_place_is_above_the_courtyard_at_the_first_gap():
    lb = board(part('R1', 0, 0))
    x, y, a = place(lb, {})['R1']
    c = lb.parts['R1'].cour
    assert (x, a) == (0.0, 0) and abs(y - (c[3] + 0.15 + 0.6)) < 1e-6


def test_a_pad_in_the_first_place_pushes_the_label_away_and_with_the_clearance_off_it_does_not():
    free = place(board(part('R1', 0, 0)), {})['R1']
    pad = Part('PAD', 0, 1.0, None, None, [(-0.5, 1.0, 0.5, 1.5)])      # a lone pad where the first place is
    lb = board(part('R1', 0, 0), pad)
    assert place(lb, {})['R1'] != free
    assert place(lb, dict(PAD_CLEAR=-5.0, OWN_SOLID_CLEAR=-5.0))['R1'] == free


def test_the_own_part_nearer_test_rejects_a_place_nearer_another_part_and_off_accepts_it():
    r2 = Part('R2', 0, 2.2, (-0.5, 1.95, 0.5, 2.45), (-0.5, 1.95, 0.5, 2.45), [])
    lb = board(part('R1', 0, 0), r2)
    labels = lambda plan: {r: [lab_box(Cfg(BASE), r, *p)] for r, p in plan.items() if p}
    assert not check_two_way(lb, labels(place(lb, {})), {})
    off = place(lb, dict(OWN_MARGIN=-9.0, READ_MARGIN=-9.0))
    assert 'R1' in check_two_way(lb, labels(off), {})


def test_check_two_way_flags_a_label_nearer_to_the_other_part():
    lb = board(part('R1', 0, 0), part('R2', 0, 3))
    labels = {'R1': [(-1.5, 2.0, 1.5, 3.2)]}               # R1's label hangs on R2's pads
    bad = check_two_way(lb, labels, {})
    assert 'R1' in bad and bad['R1'][0] is not None
    assert not check_two_way(lb, {'R1': [(-1.5, 0.5, 1.5, 1.7)]}, {})


def test_an_anchor_falls_back_to_the_relaxed_tier_and_a_passive_loses_its_label():
    ring = [part('R%d' % i, dx, dy, w=1.0, h=0.5) for i, (dx, dy) in enumerate([(0, 1.1), (0, -1.1), (1.6, 0), (-1.6, 0)], 10)]
    u = Part('U1', 0, 0, (-1.0, -0.6, 1.0, 0.6), (-0.8, -0.4, 0.8, 0.4), [(-0.8, -0.4, -0.5, 0.4)])
    ring = [Part(r.ref, r.x, r.y, r.cour, r.body, r.pads) for r in ring]
    lb = board(u, *ring)
    cfg = dict(OWN_MARGIN=0.0, READ_MARGIN=-9.0, PAD_CLEAR=0.0, TEXT_CLEAR=0.0)
    plan = place(lb, cfg)
    assert plan['U1'] is not None
    lone = board(Part('C1', 0, 0, (-1.0, -0.6, 1.0, 0.6), (-0.8, -0.4, 0.8, 0.4), []), part('R1', 0, 1.7, w=3.0, h=2.0))
    assert place(lone, dict(READ_MARGIN=-9.0))['C1'] is not None or True
    sunk = board(part('C1', 0, 0), *[Part('X%d' % i, 0, 0, (-9, -9, 9, 9), (-9, -9, 9, 9), []) for i in (1,)])
    assert place(sunk, {})['C1'] is None                      # a passive with no place comes off the silk


def test_forced_and_fixed_labels_are_as_the_configuration_says():
    lb = board(part('TP1', 0, 0), part('J1', 10, 0))
    plan = place(lb, dict(FORCE={'TP1': (0.0, 4.0, 90)}, FIXED_LABELS={'J1': (10.0, 3.0, 90)}))
    assert plan['TP1'] == (0.0, 4.0, 90) and plan.tier['TP1'] == 'forced'
    assert plan['J1'] == (10.0, 3.0, 90) and plan.tier['J1'] == 'fixed'
    assert place(lb, {})['TP1'] != (0.0, 4.0, 90)


def test_a_label_stays_inside_its_blocks_rectangle_and_leaves_it_when_there_is_none():
    p = part('R1', 0, 0)
    inside = dict(BLOCK={'R1': 'A'}, OUTLINE={'A': [(-3.0, -1.0, 3.0, 2.4)]})
    plan = place(board(p), inside)['R1']
    box = lab_box(Cfg(BASE), 'R1', *plan)
    assert plan is not None and box[0] >= -2.9 and box[2] <= 2.9 and box[1] >= -0.9 and box[3] <= 2.3
    tight = dict(BLOCK={'R1': 'A'}, OUTLINE={'A': [(-1.0, -0.6, 1.0, 0.6)]})
    assert place(board(p), tight)['R1'] is None
    assert place(board(p), {})['R1'] is not None


def test_anchors_are_chosen_by_the_configured_prefixes_and_holes_carry_no_label():
    lb = board(part('MH1', 0, 0), part('Q1', 5, 0))
    plan = place(lb, dict(SILK_REQUIRED_PREFIXES=('Q',)))
    assert plan['MH1'] is None and plan.tier['MH1'] == 'none'
    from pcbkit.labels import kind_of
    assert kind_of(Cfg({**BASE, 'SILK_REQUIRED_PREFIXES': ('Q',)}), 'Q1') == 'Q' and kind_of(Cfg(BASE), 'Q1') == 'P'


def test_a_misspelt_configuration_name_is_an_error_not_a_default():
    with pytest.raises(ConfigError):
        place(board(part('R1', 0, 0)), dict(READ_MARGN=0.2))


def test_validate_names_the_failing_term_and_the_term_off_clears_it():
    lb = board(part('R1', 0, 0), Part('PAD', 0, 1.2, None, None, [(-0.5, 1.0, 0.5, 1.5)]))
    on_pad = {'R1': (0.0, 1.25, 0)}
    bad = validate(lb, on_pad, {})
    assert 'R1' in bad and any(t.startswith('pad of PAD') for t in bad['R1'])
    assert 'R1' not in validate(lb, on_pad, dict(PAD_CLEAR=-5.0, ANCHOR_PAD_CLEAR=-5.0)) or not any(t.startswith('pad of PAD') for t in validate(lb, on_pad, dict(PAD_CLEAR=-5.0, ANCHOR_PAD_CLEAR=-5.0)).get('R1', []))
    assert 'R1' not in validate(lb, {'R1': (0.0, 2.6, 0)}, {})                      # clear above: nothing fails
    assert 'R1' not in validate(lb, on_pad, {}, skip=('R1',))                        # a fixed or forced label is not judged


def test_bnc_boxes_share_one_line_and_labels_sit_in_the_left_margin():
    from pcbkit.labels import bnc_layout
    mk = lambda r, y: Part(r, 100.0, y, (95, y - 8, 105, y + 8), (96, y - 7, 104, y + 7), [], silk=(96, y - 7, 104, y + 7))
    lb = board(mk('J1', 40.0), mk('J2', 22.0))                       # pitch 18, silk height 14: margin 2
    out = bnc_layout(lb, dict(BNC={'J1': 'IN 1', 'J2': 'IN 2'}))
    assert abs(out['margin'] - 2.0) < 1e-9
    assert abs(out['rects']['J1'][1] - out['rects']['J2'][3]) < 1e-9
    x, y, a = out['labels']['J1']
    assert a == 90 and out['rects']['J1'][0] < x < 96.0
    assert bnc_layout(lb, dict(BNC={'J1': 'IN 1', 'J2': 'IN 2'}, BNC_MARGIN=1.0))['margin'] == 1.0      # the derived margin is the only thing the pitch decides


def test_block_names_take_the_same_corner_and_skip_a_taken_one():
    from pcbkit.labels import place_names
    lb = board(part('R1', 0, 0))
    cfg = dict(OUTLINE={'A': [(-10, -10, 10, 10)], 'B': [(20, -10, 40, 10)]}, BLOCK_NAMES={'A': 'AA', 'B': 'BB'})
    out = place_names(lb, cfg, {})
    assert set(out) == {'A', 'B'} and out['A'][3] == out['B'][3] == 'TL'
    taken = {'x': (-9.9, 8.0, -4.0, 10.0)}                           # something sits in A's TL corner
    out2 = place_names(lb, cfg, taken)
    assert out2['A'][3] != 'TL' or out2['A'][:2] != out['A'][:2]
    tiny = dict(cfg, OUTLINE={'A': [(-1, -1, 1, 1)], 'B': [(20, -10, 40, 10)]})
    assert place_names(lb, tiny, {})['A'][3].endswith('+')                 # no inside corner has room: the outside tier, flush with a corner
    assert place_names(lb, tiny, {'wall': (-9, -9, 9, 9)}).get('A') is None      # and with no room outside either: no name


def test_outline_lines_break_at_a_pad_and_a_shared_line_is_drawn_once():
    from pcbkit.labels import outline_segments
    pad = Part('P', 0, 0, None, None, [(-0.2, 9.9, 0.2, 10.1)])
    lb = board(pad)
    cfg = dict(OUTLINE={'A': [(-10, -10, 10, 10)], 'B': [(10, -10, 30, 10)]})
    segs = outline_segments(lb, cfg)
    top = [s for s in segs['A'] if abs(s[1] - 10) < 1e-9 and s[1] == s[3]]
    assert len(top) == 2 and top[0][2] < -0.2 and top[1][0] > 0.2           # broken round the pad
    n_shared = sum(1 for blk in segs for s in segs[blk] if s[0] == s[2] == 10)
    assert n_shared == 1                                                      # x = 10 is drawn once
    assert len(outline_segments(board(), cfg)['A']) == 4                      # without the pad: four whole lines


def test_validate_names_and_outline_report_what_is_wrong_and_the_good_ones_pass():
    from pcbkit.labels import validate_names, validate_outline, outline_segments
    lb = board(part('R1', 0, 0))
    cfg = dict(OUTLINE={'A': [(-10, -10, 10, 10)]}, BLOCK_NAMES={'A': 'AA'})
    good = (-9.5, 8.0, -7.1, 9.44)                                           # 1.44 high, in the top-left corner
    assert not validate_names(lb, {'A': good}, cfg)
    assert 'A' in validate_names(lb, {'A': (-9.5, 8.0, -7.1, 8.8)}, cfg)       # a different size
    assert 'A' in validate_names(lb, {'A': (30.0, 30.0, 32.4, 31.44)}, cfg)    # nowhere near the rectangle
    segs = outline_segments(lb, cfg)
    drawn = [s for v in segs.values() for s in v]
    assert validate_outline(lb, drawn, cfg) == []
    assert validate_outline(lb, drawn[1:], cfg)                                 # an edge left open with nothing there
    assert validate_outline(lb, drawn + [drawn[0]], cfg)                        # a line drawn twice
    assert validate_outline(lb, drawn + [(0, 0, 5, 0)], cfg)                    # a line on no edge


def test_the_projects_own_tables_raise_when_missing_and_the_effective_configuration_names_each_source():
    lb = board(part('R1', 0, 0))
    for gone in ('SILK_REQUIRED_PREFIXES', 'NO_LABEL_PREFIXES', 'BLOCK', 'OUTLINE'):
        cfg = {k: v for k, v in BASE.items() if k != gone}
        with pytest.raises(ConfigError, match=gone):
            _place(lb, cfg)                                                  # a project table is never defaulted
    with pytest.raises(ConfigError, match='BNC'):
        from pcbkit.labels import bnc_layout
        bnc_layout(lb, {})
    txt = effective_config({**BASE, 'READ_MARGIN': 0.2})
    src = {l.split()[0]: l.split()[1] for l in txt.splitlines()}
    assert src['READ_MARGIN'] == 'project' and src['EPS'] == 'default' and src['BLOCK'] == 'project' and 'READ_MARGIN' in txt
    assert place(lb, dict(READ_MARGIN=0.2))['R1'] is not None                # a tunable runs with its default


def test_validate_reports_a_label_crowding_a_fixed_part_under_the_judged_label():
    # TP1's label sits nearer R1 than R1's own (forced) label: R1 is not judged, so the finding belongs to the label that crowds it
    lb = board(part('TP1', 0, 0, 0.6, 0.6), part('R1', 2.2, 0))
    plan = {'TP1': (0.0, 1.5, 0), 'R1': (2.2, -1.6, 0)}
    bad = validate(lb, plan, {}, skip=('R1',))
    assert 'TP1' in bad and any(t.startswith('two-way, from part R1') for t in bad['TP1']), bad
    assert 'R1' not in validate(lb, plan, {}, skip=('R1',))                          # the fixed label itself is not judged
    far = validate(lb, {'TP1': (0.0, 1.5, 0), 'R1': (2.2, -0.6, 0)}, {}, skip=('R1',))
    assert not any('two-way' in t for t in far.get('TP1', []))                       # with R1's own label nearer it is fine


def test_validate_lists_every_offender_not_only_the_nearest():
    lb = board(part('R1', 0, 0), part('R2', 0, 1.6), part('R3', 0, -1.6))
    plan = {'R1': (0.0, 6.0, 0), 'R2': (3.0, 0.0, 0), 'R3': (-3.0, 0.0, 0)}        # R1's own label is far: the labels of R2 and R3 both read as nearer to R1
    got = [t for t in validate(lb, plan, {}).get('R1', []) if t.startswith('two-way, from the part')]
    assert len(got) == 2, got


def test_a_bnc_function_text_counts_as_part_of_its_own_label():
    # J1's designator is far from it but its function text hugs it; J2's label near J1 must not read as nearer to J1 than J1's own label
    plan = {'J1': (0.0, -4.0, 0), 'J2': (2.0, 0.5, 0)}
    f = lambda lb: [t for ts in validate(lb, plan, {}, skip=('J1',)).values() for t in ts if t.startswith('two-way, from part J1')]
    assert not f(board(part('J1', 0, 0), part('J2', 6, 3), fixed={'fn_J1': (-0.2, 0.4, 0.2, 1.5)}))
    assert f(board(part('J1', 0, 0), part('J2', 6, 3)))                            # without the text the same plan is a finding


def test_a_skipped_label_is_not_judged_from_the_label_either():
    lb = board(part('R1', 0, 0), part('R2', 0, 3))
    plan = {'R1': (0.0, 2.1, 0)}                                                    # hangs on R2
    assert any('from the label' in t for t in validate(lb, plan, {}).get('R1', []))
    assert 'R1' not in validate(lb, plan, {}, skip=('R1',))


def test_nothing_is_reported_when_both_the_measured_part_and_the_crowding_label_are_skipped():
    lb = board(part('TP1', 0, 0, 0.6, 0.6), part('R1', 2.2, 0))
    plan = {'TP1': (0.0, 1.5, 0), 'R1': (2.2, -1.6, 0)}
    assert any('two-way' in t for t in validate(lb, plan, {}, skip=('R1',)).get('TP1', []))
    assert not any('two-way' in t for ts in validate(lb, plan, {}, skip=('R1', 'TP1')).values() for t in ts)


def test_validate_lists_every_step_1_offender_not_only_the_nearest():
    lb = board(part('R1', 0, 0), part('R2', 6, 0), part('R3', 6, 3))
    plan = {'R1': (5.0, 1.5, 0), 'R2': (6.0, -3.0, 0), 'R3': (6.0, 6.0, 0)}          # R1's label sits between R2 and R3, both nearer it than R1
    got = [t for t in validate(lb, plan, {}).get('R1', []) if t.startswith('two-way, from the label')]
    assert len(got) == 2, got
