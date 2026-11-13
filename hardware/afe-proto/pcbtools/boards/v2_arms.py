"""The mutation arms of the v2 board: ARMS = [(name, rule, arm)] (OLD_ARMS: the old tool's, ported one for one; NEW_ARMS: what the
review of the port added, each for one defect the old arms could not see) where arm(b, cfg) -> BoardArrays breaks the board the way
its rule forbids and the rule must then FAIL. Ported one for one from lr_check.py's ARMS (27 numpy arms as the old tool, plus 'LR-4 top GND zone near FB' for the zone test; the 28th, LR-10's
0.1 mm track, is pcbtools.drc.lr10_arm because it needs a file and kicad-cli)."""
import numpy as np

from .. import mutate as M
from .. import rules as R


def mut1(b, cfg):
    c = R.pos(b, 'U101')
    return M.add_segment(b, '/CH1_N', 'B', (c[0] - 1, c[1]), (c[0] + 1, c[1]))


def mut2(b, cfg):
    return M.move_footprint(b, 'R107', x=R.pos(b, 'U101')[0] - 5)


def mut3(b, cfg):
    return M.add_via(b, '/CH1_N', M.pad_center(b, 'R102', '2'))


def mut4(b, cfg):
    s = M.first_segment(b, '/A0')
    return M.add_via(b, '/A0', (s[0], s[1]))


def mut4b(b, cfg):
    # old: a point in `extra_top_gnd`; here a short top GND track 0.3 mm from the AWG inverting pad
    p = M.pad_center(b, 'R303', '2')
    return M.add_segment(b, '/GND', 'F', (p[0] + 0.3, p[1]), (p[0] + 0.8, p[1]))


def mut4f(b, cfg):
    # a top GND pour whose edge lies 0.4 mm from the AWG inverting pad: the zone test (hole-aware), not the track test
    p = M.pad_center(b, 'R303', '2')
    return M.add_zone(b, '/GND', 'F', [([(p[0] + 0.2, p[1] - 1), (p[0] + 2, p[1] - 1), (p[0] + 2, p[1] + 1), (p[0] + 0.2, p[1] + 1)], False)])


def mut5(b, cfg):
    c = R.pos(b, cfg.GEN[0])
    return M.add_segment(b, '/VREF', 'F', (c[0] + 4, c[1] + 4), (c[0] + 4, c[1] + 6))


def mut6(b, cfg):
    b = M.add_segment(b, '/+3V3A', 'F', M.pad_center(b, 'U101', '8'), M.pad_center(b, 'U301', '8'))
    b = M.set_pad_net(b, 'U101', '8', '/+3V3A')
    return M.set_pad_net(b, 'C104', '1', '/+3V3A')


def mut7(b, cfg):
    return M.add_segment(b, '/DAC0', 'F', (30.0, 30.0), (60.0, 30.0))


def mut8(b, cfg):
    return M.add_segment(b, '/VREF', 'F', M.pad_center(b, 'R506', '2'), M.pad_center(b, 'U502', '4'))


def mut9(b, cfg):
    c = R.pos(b, 'U101')
    return M.add_segment(b, '/SDA', 'F', (c[0] - 2, c[1]), (c[0] + 2, c[1]))


def mut11(b, cfg):
    return M.move_footprint(b, 'R201', x=30.0, y=40.0)          # well outside every outline


def mut11b(b, cfg):
    r_h, on = b.r_h.copy(), b.r_on_silk.copy()
    k = int(np.flatnonzero(b.r_fp == 0)[0])                      # the first footprint's designator
    r_h[k], on[k] = 0.5, False
    return b.replace(r_h=r_h, r_on_silk=on)


def mut11c(b, cfg):
    return M.drop_pads(b, [(r, p) == ('TP301', '1') for r, p in zip((b.fp_ref[i] for i in b.p_fp), b.p_pin)])


def mut1i(b, cfg):
    """the via of a non-exempt ground pad (R407.2) removed"""
    c = M.pad_center(b, 'R407', '2')
    d = np.where(b.v_net == b.net_id('/GND'), np.hypot(b.v_x - c[0], b.v_y - c[1]), 1e9)
    m = np.zeros(len(b.v_idx), bool)
    m[int(np.argmin(d))] = True
    return M.drop_vias(b, m)


def mut1b(b, cfg):
    return M.add_segment(b, '/SCL', 'B', (4.0, 40.0), (8.0, 40.0))           # a 4 mm hop on a free net, clear of every fence


def _mid(b, net):
    s = M.first_segment(b, net)
    return ((s[0] + s[2]) / 2, (s[1] + s[3]) / 2)


def mut1c(b, cfg):
    c = _mid(b, '/A0')
    return M.add_segment(b, '/SCL', 'B', (c[0] - 0.5, c[1]), (c[0] + 0.5, c[1]))


def _cross(b, net, under):
    c = _mid(b, net)
    b = M.add_segment(b, under, 'B', (c[0] - 0.5, c[1]), (c[0] + 0.5, c[1]))
    return M.add_segment(b, under, 'B', (c[0], c[1] - 0.5), (c[0], c[1] + 0.5))


def mut1f(b, cfg):
    return _cross(b, '/AREF', '/SCL')


def mut1g(b, cfg):
    return _cross(b, '/AREF', '/+3V3A')


def mut1d(b, cfg):
    r = cfg.OUTLINE['AWG'][1]
    return M.add_segment(b, '/SCL', 'B', (r[0] + 1, r[1] + 1), (r[0] + 2, r[1] + 1))


def mut1e(b, cfg):
    p = M.pad_center(b, 'R303', '2')
    return M.add_segment(b, '/SCL', 'B', (p[0] - 0.5, p[1]), (p[0] + 0.5, p[1]))


def mut4c(b, cfg):
    return M.add_via(b, '/AWG_FB', M.pad_center(b, 'R303', '2'))


def mut4d(b, cfg):
    return M.add_segment(b, '/CH1_N', 'B', (3.0, 3.0), (4.0, 3.0))


def mut4e(b, cfg):
    for n in cfg.INV_NODES:
        p = M.first_segment(b, n)
        b = M.add_segment(b, n, 'F', (p[0], p[1]), (p[0] + 6.0, p[1]))
    return b


def mut12(b, cfg):
    for cap, _ic, _pin in cfg.DECOUP:
        for k in ('1', '2'):
            b = M.shift_pad(b, cap, k, dx=5.0)
    return b


def mut12b(b, cfg):
    for k in ('1', '2'):
        b = M.shift_pad(b, 'C305', k, dy=5.0)
    return b


def mut11d(b, cfg):
    return M.add_footprint_like(b, 'R399', 'R101')            # a CH1 part numbered 399: its hundreds digit says AWG


def mut11e(b, cfg):
    tps = {r for r in b.fp_ref if r.startswith('TP') and cfg.BLOCK.get(r) == 'REFCAL'}
    m = [(b.fp_ref[i] in tps and p == '1') for i, p in zip(b.p_fp, b.p_pin)]
    return M.drop_pads(b, m)


OLD_ARMS = [('LR-1', R.lr1, mut1), ('LR-1 4 mm hop', R.lr1, mut1b), ('LR-1 under A0', R.lr1, mut1c),
        ('LR-1 SCL under AREF', R.lr1, mut1f), ('LR-1 +3V3A under AREF', R.lr1, mut1g),
        ('LR-1 inside AWG fence', R.lr1, mut1d), ('LR-1 ground via removed (R407.2)', R.lr1, mut1i),
        ('LR-1 under FB pad', R.lr1, mut1e), ('LR-4 via on AWG FB', R.lr4, mut4c), ('LR-4 bottom copper on CH1_N', R.lr4, mut4d),
        ('LR-2', R.lr2, mut2), ('LR-3', R.lr3, mut3), ('LR-4 via in A0', R.lr4, mut4), ('LR-4 pour near FB', R.lr4, mut4b), ('LR-4 top GND zone near FB', R.lr4, mut4f),
        ('LR-4 INV_MAX: 6 mm detour on each node', R.lr4_inv, mut4e), ('LR-12 all caps 5 mm away', R.lr12, mut12),
        ('LR-12 C305 5 mm away', R.lr12, mut12b), ('LR-5', R.lr5, mut5), ('LR-6', R.lr6, mut6), ('LR-7', R.lr7, mut7),
        ('LR-8', R.lr8, mut8), ('LR-9', R.lr9, mut9), ('LR-11 part out of its outline', R.lr11, mut11),
        ('LR-11 missing designator', R.lr11, mut11b), ('LR-11 missing test point', R.lr11, mut11c),
        ('LR-11 wrong-numbered designator', R.lr11, mut11d), ('LR-11 block without a TP', R.lr11, mut11e)]


# ------------------------------------------------------------------------------------------------ added by the review of the port
def _sq(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def mut6b(b, cfg):
    """two groups share copper on the REAL nets: the scope's feed (+3V3A_U, behind the bridges) is tied to the AWG's pad (+3V3A) by
    a track; no pad is re-netted (mut6 re-nets pads onto +3V3A, which hid that no scope part is on it)"""
    return M.add_segment(b, '/+3V3A_U', 'F', M.pad_center(b, 'U101', '8'), M.pad_center(b, 'U301', '8'))


def mut6c(b, cfg):
    """the AWG branch is unrouted: every track end at U301.8 deleted"""
    return M.drop_segments(b, M.segments_at_pad(b, '/+3V3A', 'U301', '8'))


def mut6d(b, cfg):
    """the rail is unrouted: every /+3V3A (and bridge-joined) track deleted"""
    on = np.isin(b.s_net, [b.net_id(n) for n in sorted(R.family(cfg, '/+3V3A'))])
    return M.drop_segments(b, on)


def mut6e(b, cfg):
    """two groups joined through a bottom hop: a via on each pad and a B.Cu track between them"""
    a, c = M.pad_center(b, 'U101', '8'), M.pad_center(b, 'U301', '8')
    b = M.add_via(b, '/+3V3A', a)
    b = M.add_via(b, '/+3V3A', c)
    return M.add_segment(b, '/+3V3A', 'B', a, c)


def mut8b(b, cfg):
    """one branch unrouted: every VREF track end at R514.1 deleted"""
    return M.drop_segments(b, M.segments_at_pad(b, '/VREF', 'R514', '1'))


def mut8c(b, cfg):
    """the reference is unrouted: every VREF track deleted"""
    return M.drop_segments(b, b.s_net == b.net_id('/VREF'))


def mut1h(b, cfg):
    """a second bottom zone, of another net: the plane is split"""
    return M.add_zone(b, '/SCL', 'B', [(_sq(1, 1, 3, 3), False)])


def mut1j(b, cfg):
    """a second bottom GND zone"""
    return M.add_zone(b, '/GND', 'B', [(_sq(1, 1, 3, 3), False)])


def mut1k(b, cfg):
    """a 4.5 mm bottom hop built as two segments that meet at a T (each is under the 3 mm limit alone)"""
    b = M.add_segment(b, '/SCL', 'B', (4.0, 40.0), (6.5, 40.0))
    return M.add_segment(b, '/SCL', 'B', (5.0, 40.0), (5.0, 42.0))


def mut4g(b, cfg):
    """a top GND pour whose edge is 0.6 mm from the AWG inverting pad's CENTRE, i.e. 0.2 mm from its copper: the old axial probes,
    0.5 mm out from the centre, miss it"""
    p = M.pad_center(b, 'R303', '2')
    return M.add_zone(b, '/GND', 'F', [(_sq(p[0] + 0.6, p[1] - 1, p[0] + 3, p[1] + 1), False)])


def _gen_gap_probe(b, cfg, dist):
    """(x0, y0, x1, y1) of a segment parallel to a side of the generator IC's courtyard whose CENTRE LINE is `dist` mm from it and
    from the flying capacitor's courtyard, on whichever side of the IC that holds"""
    g = [R.box(b, r) for r in cfg.GEN]
    bx = g[0]
    for side in ('E', 'W', 'N', 'S'):
        if side == 'E':
            s = (bx[2] + dist, bx[1], bx[2] + dist, bx[3])
        elif side == 'W':
            s = (bx[0] - dist, bx[1], bx[0] - dist, bx[3])
        elif side == 'N':
            s = (bx[0], bx[3] + dist, bx[2], bx[3] + dist)
        else:
            s = (bx[0], bx[1] - dist, bx[2], bx[1] - dist)
        d = min(float(R.seg_box_dist(np.array([s]), x)[0]) for x in g)
        if abs(d - dist) < 1e-6:
            return s
    raise ValueError('no side of the generator keeps the probe away from the flying capacitor')


def mut5b(b, cfg):
    """a 1 mm wide sensitive track whose centre line is 10.3 mm from the generator (> 10) and whose EDGE is 9.8 mm: only a rule
    that subtracts the half width sees it"""
    s = _gen_gap_probe(b, cfg, cfg.KEEPOUT + 0.3)
    return M.add_segment(b, '/VREF', 'F', (s[0], s[1]), (s[2], s[3]), w=1.0)


def mut5c(b, cfg):
    """the sensitive pad nearest the generator grows (its CENTRE stays where it was, beyond 10 mm): its extent now reaches in"""
    pt = R.pads(b)
    sens = R.net_prefix(b, cfg.SENSITIVE)
    g = [R.box(b, r) for r in cfg.GEN]
    best = None
    for j in np.flatnonzero(sens[pt.net]):
        k = pt.keys[j]
        if k[0] in cfg.GENERATOR_BLOCK:
            continue
        r = pt.rows[j]
        c = np.array([[b.p_x[r], b.p_y[r]]])
        d = min(float(R.pt_box_dist(c, x)[0]) for x in g)
        if best is None or d < best[0]:
            best = (d, k)
    d, (ref, pin) = best
    side = 2.0 * (d - cfg.KEEPOUT) + 4.0                  # reaches in by side / 2 > d - KEEPOUT, whatever the direction
    return M.set_pad_size(b, ref, pin, side, side)


NEW_ARMS = [('LR-1 second bottom zone of another net', R.lr1, mut1h), ('LR-1 second bottom GND zone', R.lr1, mut1j),
            ('LR-1 4.5 mm hop as a T of two segments', R.lr1, mut1k),
            ('LR-4 pour edge 0.2 mm from the pad copper', R.lr4, mut4g),
            ('LR-5 track edge inside 10 mm, centre line outside', R.lr5, mut5b), ('LR-5 pad extent inside 10 mm', R.lr5, mut5c),
            ('LR-6 scope and AWG share copper on the real nets', R.lr6, mut6b), ('LR-6 AWG branch unrouted', R.lr6, mut6c),
            ('LR-6 rail unrouted', R.lr6, mut6d), ('LR-6 groups joined through a bottom hop', R.lr6, mut6e),
            ('LR-8 one branch unrouted', R.lr8, mut8b), ('LR-8 reference unrouted', R.lr8, mut8c)]
ARMS = OLD_ARMS + NEW_ARMS
