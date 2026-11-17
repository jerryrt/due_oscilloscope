"""Fixture: both approved AFE boards against pcbkit.labels. Every approved label passes `validate` except the findings the owner accepted knowingly, the approved block names and outline lines pass
`validate_names` and `validate_outline`, and the placer's own plan (labels, names, outline lines) passes too.

Run in the PCB image from hardware/afe-proto:   python3 pcbkit_regress/labels.py v1|v2        (exit 1 unless the fixture passes)
This file is the AFE's side: it reads the AFE configurations (boards/v1_layout, boards/v2_layout); pcbkit itself imports nothing from here."""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..', '..', 'pcbkit'), os.path.join(HERE, '..')]
from pcbkit import labels as L
from pcbkit.labels import from_board as FB

FRAME = (50.0, 150.0)
BOARDS = {
    'v1': dict(path='kicad/afe-proto.kicad_pcb', cfgmod='pcbtools.boards.v1_layout', passive='courtyard',
               priority=('TP405', 'D201', 'D501', 'D502', 'D101'), force={'TP401': (39.6, 6.5, 90), 'TP201': (76.6, 25.6, 90)},
               bnc={'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'},
               names={'POWER': 'POWER', 'REFCAL': 'REF/CAL', 'AWG': 'AWG', 'CH1': 'CH1', 'CH2': 'CH2'}, ignore=[(57.2, 8.4, 59.8, 9.4)]),     # the ON mark's drawn box in REF/CAL is not an outline line
    'v2': dict(path='v2/layout/integrated/afe-v2-integrated.kicad_pcb', cfgmod='pcbtools.boards.v2_layout', passive='body',
               priority=(), force={}, bnc={'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'},
               names={'POWER': 'POWER', 'REFCAL': 'REF / CAL', 'AWG': 'AWG', 'CH1': 'CH1', 'CH2': 'CH2'}, ignore=[]),
}
ACCEPTED = {   # findings the owner approved knowingly; the check still reports them and the fixture expects exactly these
    'v1': {},
    'v2': {'J605': 'two-way from the part: BNC function texts 0.545 mm away, own label 0.480 (margin 0.065, needs 0.15): owner approved AFE-2 with this shortfall (recorded 2026-11-17)'},
}


def load(which):
    """(LabelBoard, configuration mapping, board entry, board configuration module)"""
    B = BOARDS[which]
    C = __import__(B['cfgmod'], fromlist=['x'])
    lb = FB.read(B['path'], {'FRAME': FRAME}, fixed_text_owner={fn: r for r, fn in B['bnc'].items()}, block_names=set(B['names'].values()))
    cfg = dict(SILK_REQUIRED_PREFIXES=C.SILK_REQUIRED_PREFIXES, NO_LABEL_PREFIXES=('MH',), BLOCK=C.BLOCK, OUTLINE=C.OUTLINE, OUTLINE_STRAYS=tuple(C.OUTLINE_STRAYS) if hasattr(C, 'OUTLINE_STRAYS') else (),
               PASSIVE_TEST=B['passive'], PRIORITY=B['priority'], FORCE=B['force'], LABEL_AREA=tuple(C.DUE_RECT) if which == 'v1' else None)
    return lb, cfg, B, C


def name_rects(which, C):
    """the rectangle each block name sits at: a block's first rectangle, and for v1's one SCOPE block its two channel rectangles (CH1, CH2)"""
    o = C.OUTLINE
    if which == 'v1':
        return {'POWER': o['POWER'], 'REFCAL': o['REFCAL'], 'AWG': o['AWG'], 'CH1': [o['SCOPE'][0]], 'CH2': [o['SCOPE'][1]]}
    return o


def decor_validate(which, lb, cfg, B, C, approved):
    cfg = dict(cfg, BNC=B['bnc'], BLOCK_NAMES=B['names'], OUTLINE=name_rects(which, C))
    boxes = {b: lb.fixed['name_' + t] for b, t in B['names'].items() if 'name_' + t in lb.fixed}
    others = {r: L.lab_box(L.placer.Cfg(cfg), r, *v) for r, v in approved.items()}
    others.update(L.bnc_layout(lb, cfg)['fixed'])
    bad_n = L.validate_names(lb, boxes, cfg, others)
    for k, w in bad_n.items():
        print('   APPROVED NAME', k, w)
    cfg2 = dict(cfg, OUTLINE=C.OUTLINE, FORCE=B['force'], OUTLINE_IGNORE=B['ignore'])
    bad_o = L.validate_outline(lb, lb.outline_lines, cfg2)
    lb2 = lb.__class__(**{**lb.__dict__, 'fixed': {}})
    cfg3 = dict(cfg, FORCE=B['force'])
    nm = L.place_names(lb2, cfg3, others)
    nb = {b: L.names.name_box(L.placer.Cfg(cfg3), B['names'][b], v[0], v[1]) for b, v in nm.items()}
    plan_n = L.validate_names(lb2, nb, cfg3, others)
    segs = L.outline_segments(lb2, dict(cfg2, OUTLINE=C.OUTLINE))
    plan_o = L.validate_outline(lb2, [q for v in segs.values() for q in v], dict(cfg2, OUTLINE=C.OUTLINE))
    print(which, 'names placed', {b: v[3] for b, v in nm.items()}, 'missing', sorted(set(B['names']) - set(nm)))
    return sorted(bad_n), bad_o, sorted(plan_n), plan_o


def validate_fixture(which):
    lb, cfg, B, C = load(which)
    cfg['FIXED_LABELS'] = {r: lb.labels[r][:3] for r in B['bnc']}
    print('effective configuration (%s):' % which)
    print(L.effective_config(cfg))
    skip = set(B['bnc']) | set(B['force'])
    approved = {r: (v[0], v[1], v[2]) for r, v in lb.labels.items() if v[3] and r in lb.parts}
    bad = L.validate(lb, approved, cfg, skip)
    plan = L.place(lb, cfg)
    bad2 = L.validate(lb, dict(plan), cfg, skip)
    print(which, 'approved labels', len(approved), 'failing validate', len(bad), '| the placer\'s plan', sum(1 for v in plan.values() if v), 'labels, failing validate', len(bad2))
    for r, w in sorted(bad.items()):
        print('  APPROVED', r, approved[r]); [print('       ', t) for t in w]
    for r, w in sorted(bad2.items()):
        print('  PLAN', r, plan[r], plan.tier[r]); [print('       ', t) for t in w]
    bad_n, bad_o, plan_n, plan_o = decor_validate(which, lb, cfg, B, C, approved)
    print(which, 'block names: approved failing', bad_n, '| plan failing', plan_n)
    print(which, 'outline: approved problems', len(bad_o), '| plan problems', len(plan_o))
    for q in bad_o[:12]: print('   APPROVED LINE', q)
    for q in plan_o[:12]: print('   PLAN LINE', q)
    new = sorted(set(bad) - set(ACCEPTED[which])); gone = sorted(set(ACCEPTED[which]) - set(bad))
    print(which, 'accepted findings', sorted(ACCEPTED[which]), '| NEW', new, '| ACCEPTED BUT GONE', gone, '| plan failures', sorted(bad2))
    ok = not new and not gone and not bad2 and not bad_n and not bad_o and not plan_n and not plan_o
    print('FIXTURE', 'PASS' if ok else 'FAIL')
    return ok


if __name__ == '__main__':
    sys.exit(0 if validate_fixture(sys.argv[1]) else 1)
