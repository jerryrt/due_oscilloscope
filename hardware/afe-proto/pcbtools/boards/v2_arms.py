"""The mutation arms of the v2 board: ARMS = [(name, rule, arm)] where arm(b, cfg) -> BoardArrays breaks the board the way
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
    for cap in cfg.DECOUP:
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


ARMS = [('LR-1', R.lr1, mut1), ('LR-1 4 mm hop', R.lr1, mut1b), ('LR-1 under A0', R.lr1, mut1c),
        ('LR-1 SCL under AREF', R.lr1, mut1f), ('LR-1 +3V3A under AREF', R.lr1, mut1g),
        ('LR-1 inside AWG fence', R.lr1, mut1d), ('LR-1 ground via removed (R407.2)', R.lr1, mut1i),
        ('LR-1 under FB pad', R.lr1, mut1e), ('LR-4 via on AWG FB', R.lr4, mut4c), ('LR-4 bottom copper on CH1_N', R.lr4, mut4d),
        ('LR-2', R.lr2, mut2), ('LR-3', R.lr3, mut3), ('LR-4 via in A0', R.lr4, mut4), ('LR-4 pour near FB', R.lr4, mut4b), ('LR-4 top GND zone near FB', R.lr4, mut4f),
        ('LR-4 INV_MAX: 6 mm detour on each node', R.lr4_inv, mut4e), ('LR-12 all caps 5 mm away', R.lr12, mut12),
        ('LR-12 C305 5 mm away', R.lr12, mut12b), ('LR-5', R.lr5, mut5), ('LR-6', R.lr6, mut6), ('LR-7', R.lr7, mut7),
        ('LR-8', R.lr8, mut8), ('LR-9', R.lr9, mut9), ('LR-11 part out of its outline', R.lr11, mut11),
        ('LR-11 missing designator', R.lr11, mut11b), ('LR-11 missing test point', R.lr11, mut11c),
        ('LR-11 wrong-numbered designator', R.lr11, mut11d), ('LR-11 block without a TP', R.lr11, mut11e)]
