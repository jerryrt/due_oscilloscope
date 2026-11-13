"""The mutation arms of the v1 board: ARMS = [(name, rule, arm)] in the form pcbtools.check wants (arm(b, cfg) -> BoardArrays breaks
the board the way its rule forbids and the rule must then FAIL), ported from the old kicad/lr_check.py (frozen at 34b2e51: 44 arms
and 4 repairs, outputs in tests/golden/v1-34b2e51-image/lr_check_mutate.out).

The v1 board is unrouted, so most rows FAIL on the clean board for legitimate reasons and a bare "the row failed" would certify
nothing. The old tool therefore demanded a NEW reason that contains the arm's keyword, after an optional `prep` that brings the
facet under test to a clean state. Here that is a wrapped rule, `_Keyed`: it runs the real rule on the (prepared) board and passes
exactly when no reason names the keyword, so an arm is evidence only when it makes the rule name the defect that was put in.
A REPAIR is the same wrapper turned round (`_Gone`): it passes while the named reason is there and fails once the repair has
removed it, which shows the rule can pass.

Changes from the old arms, each a consequence of the rules' new shapes (pcbtools/CONFIG_FIELDS.md), not of this port:
  * 'LR-4 100 nF far from U301.8' is an LR-12 arm (the decoupling distance is its own row, per named cap).
  * 'LR-9 SCL1 inside the AWG fence' and 'LR-11 test point in the wrong block' are dropped: the shared LR-9 no longer looks at
    fences (only courtyards) and the shared LR-11 takes a test point's block from the config, which an array mutation cannot change.
  * the old 'bridge away from its floorplan point' is an outline arm: a bridge is inside its block's outline at its floorplan point.
"""
import numpy as np

from .. import mutate as M
from .. import rules as R

OPEN = (20.0, 30.0)         # a spot clear of every fence and courtyard (west of REFCAL, above POWER)


# ---------------------------------------------------------------------------------------------------------- the wrappers
def _reasons(res):
    return [] if res.ok else res.detail.split('; ')


_MUTANTS = {}              # id -> board: the boards an arm has already prepared and broken (kept alive so an id is not reused)


class _Keyed:
    """the rule `rule` as the old tool judged an arm: passes unless a reason contains `key`. `prep` runs on the clean board
    here and, for a mutant, BEFORE the mutation (see `_a`): a mutant is never prepped again, which would undo the mutation"""

    def __init__(self, rule, key, prep=None):
        self.rule, self.key, self.prep, self.__name__ = rule, key, prep, rule.__name__

    def __call__(self, b, cfg):
        if self.prep and id(b) not in _MUTANTS:
            b = self.prep(b, cfg)
        res = self.rule(b, cfg)
        hit = [x for x in _reasons(res) if self.key in x]
        return R.Result(not hit, '; '.join(hit) or res.detail, res.figures)


class _Gone(_Keyed):
    """a repair, the same wrapper turned round. A repair is evidence that the rule CAN pass only where the repair is the whole story:
    on the clean board the named reason must be there, and must be gone after the repair. A board where it stays (the facet has
    other defects, e.g. a rail unrouted outside the block) cannot show it, and the arm then reports NOT TESTABLE (this wrapper
    fails the clean board, which pcbtools.check reads as 'the clean board fails, so a mutant proves nothing'), never NOT CAUGHT.
    On a board an arm has already repaired (see `_a`) it passes while the reason is still named, so a repair that did not clear it
    is the failure"""

    def __init__(self, rule, key, fix):
        super().__init__(rule, key)
        self.fix = fix

    def _hit(self, b, cfg):
        res = self.rule(b, cfg)
        return [x for x in _reasons(res) if self.key in x], res

    def __call__(self, b, cfg):
        hit, res = self._hit(b, cfg)
        if id(b) in _MUTANTS:                                  # the repaired board: the reason must be gone
            return R.Result(bool(hit), '; '.join(hit) or f'no reason names {self.key!r} any more', res.figures)
        if not hit:
            return R.Result(False, f'nothing to repair: no reason names {self.key!r} on this board', res.figures)
        after, _ = self._hit(self.fix(b, cfg), cfg)
        if after:
            return R.Result(False, f'not testable here: {self.key!r} is still named after the repair (other causes): ' + '; '.join(after[:2]),
                            res.figures)
        return R.Result(True, '; '.join(hit), res.figures)


# ---------------------------------------------------------------------------------------------------------- preps
def _all_pads(b, ref, net):
    return [(ref_, pin) for ref_, pin, n in zip((b.fp_ref[i] for i in b.p_fp), b.p_pin, b.p_net) if ref_ == ref and b.nets[n] == net]


def _join(b, net, p, q, dia=0.6, drill=0.3):
    """copper that joins the points: a via at each end and a bottom track between them (a bottom track touches nothing else)"""
    b = M.add_via(b, net, p, dia=dia, drill=drill)
    b = M.add_via(b, net, q, dia=dia, drill=drill)
    return M.add_segment(b, net, 'B', p, q)


def _rail_groups(b, cfg, net):
    fam = R.family(cfg, net)                              # the nets a bridge joins are the rail (VNEG | VNEG_O across R410)
    on = {(b.fp_ref[i], p) for i, p, n in zip(b.p_fp, b.p_pin, b.p_net) if b.nets[n] in fam}
    return {g: sorted(k for k in on if k[0] in refs) for g, refs in cfg.GROUPS[net].items()}


def prep_silk(b, cfg):
    r_h, on = np.full_like(b.r_h, max(1.0, cfg.DESIGNATOR_MIN_H)), np.ones_like(b.r_on_silk)
    b = b.replace(r_h=r_h, r_on_silk=on)
    for w in cfg.SILK_WORDS:
        b = M._append(b, 'silk', t_text=w, t_x=0.0, t_y=0.0, t_h=1.0)
    return b


def prep_gnd_vias(b, cfg):
    for r in np.flatnonzero((b.p_net == b.net_id(cfg.GND)) & b.p_smd):
        b = M.add_via(b, cfg.GND, (float(b.p_x[r]) + 0.8, float(b.p_y[r])))
    return b


def prep_connected_rails(b, cfg):
    """every consumer group's supply pads one piece and tied to a star pad of its own (group i to the rail's i-th star pad)"""
    for net, star in cfg.STAR.items():
        for i, (g, keys) in enumerate(_rail_groups(b, cfg, net).items()):
            pts = [M.pad_center(b, *k) for k in keys]
            for p, q in zip(pts, pts[1:]):
                b = _join(b, net, p, q)
            if pts:
                b = _join(b, net, M.pad_center(b, *star[i % len(star)]), pts[0])
    return b


def prep_connected_vref(b, cfg):
    for i, br in enumerate(cfg.VREF_BRANCHES):
        s = M.pad_center(b, *cfg.VREF_SOURCE[i % len(cfg.VREF_SOURCE)])       # two source pads, two branches on each, 0.4 mm apart
        pts = [M.pad_center(b, *k) for k in br]
        for p, q in zip(pts, pts[1:]):
            b = _join(b, cfg.VREF_NET, p, q)
        b = _join(b, cfg.VREF_NET, (s[0] + 0.4 * (i // len(cfg.VREF_SOURCE) * 2 - 1), s[1]), pts[0], dia=0.15, drill=0.08)
    return b


# ---------------------------------------------------------------------------------------------------------- LR-1
def mut1_under(b, cfg):
    c = R.pos(b, 'U101')
    return M.add_segment(b, '/SCL1', 'B', (c[0] - 1, c[1]), (c[0] + 1, c[1]))


def mut1_hop(b, cfg):
    return M.add_segment(b, '/SCL1', 'B', OPEN, (OPEN[0] + 4, OPEN[1]))


def mut1_vias(b, cfg):
    for k in range(3):
        b = M.add_via(b, '/SCL1', (OPEN[0] + k, OPEN[1]))
    b = M.add_segment(b, '/SCL1', 'B', OPEN, (OPEN[0] + 1, OPEN[1]))
    return M.add_segment(b, '/SCL1', 'B', (OPEN[0] + 1, OPEN[1]), (OPEN[0] + 2, OPEN[1]))


def _under(top_net, bot_net):
    def f(b, cfg):
        b = M.add_segment(b, top_net, 'F', (OPEN[0], OPEN[1] - 3), (OPEN[0], OPEN[1] + 3))
        return M.add_segment(b, bot_net, 'B', (OPEN[0] - 1, OPEN[1]), (OPEN[0] + 1, OPEN[1]))
    return f


def _in_fence(block, dx, dy):
    def f(b, cfg):
        r = cfg.FENCES[block][0]
        return M.add_segment(b, '/SCL1', 'B', (r[0] + dx, r[1] + dy), (r[0] + dx + 1, r[1] + dy))
    return f


def mut1_pad(b, cfg):
    p = M.pad_center(b, 'R303', '2')
    return M.add_segment(b, '/SCL1', 'B', (p[0] - 0.5, p[1]), (p[0] + 0.5, p[1]))


def mut1_layers(b, cfg):
    return b.replace(copper_layers=4)


# ---------------------------------------------------------------------------------------------------------- LR-2
def mut2_flow(b, cfg):
    return M.move_footprint(b, 'R107', x=R.pos(b, 'U101')[0] + 5)


def mut2_gen(b, cfg):
    return M.move_footprint(b, 'U401', x=95.0, y=10.0)


def mut2_quiet(b, cfg):
    """U501's courtyard moved to 2 mm east of the generator's (the rules read the courtyard, not the origin)"""
    i, g = b.ref_index('U501'), R.box(b, 'U401')
    d = (g[2] + 2.0) - b.fp_cx0[i]
    c0, c1, y0, y1 = (b.fp_cx0.copy(), b.fp_cx1.copy(), b.fp_cy0.copy(), b.fp_cy1.copy())
    dy = g[1] - b.fp_cy0[i]
    c0[i] += d
    c1[i] += d
    y0[i] += dy
    y1[i] += dy
    return b.replace(fp_cx0=c0, fp_cx1=c1, fp_cy0=y0, fp_cy1=y1)


def mut2_gap(b, cfg):
    p, q = M.pad_center(b, 'R106', '1'), M.pad_center(b, 'R206', '1')
    return M.shift_pad(b, 'R206', '1', dx=p[0] + 1 - q[0], dy=p[1] - q[1])


# ---------------------------------------------------------------------------------------------------------- LR-3
def mut3_via(b, cfg):
    return M.add_via(b, '/CH1_N', M.pad_center(b, 'R104', '1'))


def mut3_long(b, cfg):
    return M.add_segment(b, '/CH2_N', 'F', (80, 20), (96, 20))


def mut3_beside(b, cfg):
    c = M.pad_center(b, 'R104', '1')
    b = M.add_segment(b, '/CH1_N', 'F', (c[0], c[1]), (c[0] + 1, c[1]))
    return M.add_segment(b, '/SCL1', 'F', (c[0], c[1] + 0.5), (c[0] + 1, c[1] + 0.5))


# ---------------------------------------------------------------------------------------------------------- LR-4 / LR-12
def mut4_via_a0(b, cfg):
    return M.add_via(b, '/A0', M.pad_center(b, 'R207', '2'))


def mut4_bot_a1(b, cfg):
    return M.add_segment(b, '/A1', 'B', (60, 40), (61, 40))


def mut4_via_inv(b, cfg):
    return M.add_via(b, '/AWG_INV', M.pad_center(b, 'R303', '2'))


def mut4_long(b, cfg):
    return M.add_segment(b, '/AWG_INV', 'F', (80, 30), (96, 30))


def mut4_pour(b, cfg):
    p = M.pad_center(b, 'R303', '2')
    return M.add_segment(b, '/GND', 'F', (p[0] + 0.3, p[1]), (p[0] + 0.8, p[1]))


def mut12_decoup(b, cfg):
    for k in ('1', '2'):
        b = M.shift_pad(b, 'C302', k, dx=30.0)
    return b


def mut4_riso(b, cfg):
    return M.shift_pad(b, 'R107', '1', dx=40.0)


# ---------------------------------------------------------------------------------------------------------- LR-5
def mut5(b, cfg):
    c = R.pos(b, 'U401')
    return M.add_segment(b, '/VREF', 'F', (c[0] + 4, c[1] + 4), (c[0] + 4, c[1] + 6))


def mut5_pad(b, cfg):
    c, p = R.pos(b, 'U401'), M.pad_center(b, 'R508', '2')
    return M.shift_pad(b, 'R508', '2', dx=c[0] + 4 - p[0], dy=c[1] + 4 - p[1])


# ---------------------------------------------------------------------------------------------------------- LR-6 / LR-7 / LR-8 / LR-9
def mut6_join(b, cfg):
    return _join(b, '/+3V3A', M.pad_center(b, 'U301', '8'), M.pad_center(b, 'U501', '1'))


def mut6_scope_join(b, cfg):
    return _join(b, '/+3V3A', M.pad_center(b, 'R109', '1'), M.pad_center(b, 'U301', '8'))


def mut6_star(b, cfg):
    return M.set_pad_net(b, 'C407', '1', cfg.GND)


def mut7_dac0(b, cfg):
    return M.add_segment(b, '/DAC0', 'F', (30.0, 30.0), (60.0, 30.0))


def mut7_bt(b, cfg):
    return M.move_footprint(b, 'R304', x=50.0, y=30.0)


def mut7_shell(b, cfg):
    j = b.ref_index('J301')
    net = b.p_net.copy()
    net[(b.p_fp == j) & (np.asarray(b.p_pin, dtype=object) == '2')] = b.net_id('/+5V_F')
    return b.replace(p_net=net)


def mut8_join(b, cfg):
    return _join(b, '/VREF', M.pad_center(b, 'R508', '2'), M.pad_center(b, 'U502', '4'))


def mut8_join2(b, cfg):
    return _join(b, '/VREF', M.pad_center(b, 'R307', '1'), M.pad_center(b, 'R512', '2'))


def mut9_ana(b, cfg):
    c = R.pos(b, 'U101')
    return M.add_segment(b, '/SDA1', 'F', (c[0] - 2, c[1]), (c[0] + 2, c[1]))


# ---------------------------------------------------------------------------------------------------------- LR-11
def mut11_out(b, cfg):
    return M.move_footprint(b, 'R201', x=30.0, y=40.0)


def mut11_bridge(b, cfg):
    return M.move_footprint(b, 'R515', x=30.0, y=40.0)


def mut11_silk(b, cfg):
    r_h, on = b.r_h.copy(), b.r_on_silk.copy()
    k = int(np.flatnonzero(b.r_fp == b.ref_index('R101'))[0])
    r_h[k], on[k] = 0.5, False
    return b.replace(r_h=r_h, r_on_silk=on)


def mut11_tp(b, cfg):
    return M.drop_pads(b, [(b.fp_ref[i], p) == ('TP301', '1') for i, p in zip(b.p_fp, b.p_pin)])


def mut11_num(b, cfg):
    return M.add_footprint_like(b, 'R399', 'R101')


def mut11_noblock(b, cfg):
    tps = {r for r in b.fp_ref if r.startswith('TP') and cfg.BLOCK.get(r) == 'REFCAL'}
    return M.drop_pads(b, [(b.fp_ref[i] in tps and p == '1') for i, p in zip(b.p_fp, b.p_pin)])


def mut11_word(b, cfg):
    keep = [i for i, t in enumerate(b.t_text) if t != 'AWG']
    return b.replace(t_text=tuple(b.t_text[i] for i in keep), t_x=b.t_x[keep], t_y=b.t_y[keep], t_h=b.t_h[keep])


def _a(name, rule, key, arm, prep=None):
    def run(b, cfg):
        out = arm(prep(b, cfg) if prep else b, cfg)
        _MUTANTS[id(out)] = out
        return out
    return (name, _Keyed(rule, key, prep), run)


# name, rule judged by the keyword, mutation; the keywords are the words the shared rules' reasons carry
ARMS = [
    _a('LR-1 bottom copper under U101', R.lr1, 'bottom copper under', mut1_under),
    _a('LR-1 4 mm hop', R.lr1, 'bottom run', mut1_hop),
    _a('LR-1 three vias on a hop', R.lr1, '3 vias', mut1_vias),
    _a('LR-1 hop crossing a sensitive top net', R.lr1, 'under /A0', _under('/A0', '/SCL1')),
    _a('LR-1 a supply hop under AREF', R.lr1, 'under /AREF', _under('/AREF', '/+3V3A')),
    _a('LR-1 an SCL hop under AREF', R.lr1, 'under /AREF', _under('/AREF', '/SCL1')),
    _a('LR-1 inside the AWG fence', R.lr1, 'inside', _in_fence('AWG', 3, 1)),
    _a('LR-1 inside the REFCAL fence', R.lr1, 'inside', _in_fence('REFCAL', 12, 20)),
    _a('LR-1 under an AWG_INV pad', R.lr1, 'under pad R303', mut1_pad),
    _a('LR-1 four copper layers', R.lr1, '4 copper layers', mut1_layers),
    _a('LR-2 flow reversed (Riso east of U101)', R.lr2, 'x does not fall', mut2_flow),
    _a('LR-2 generator by the BNC', R.lr2, 'from the 5 V pad', mut2_gen),
    _a('LR-2 reference under the generator', R.lr2, 'U501 only', mut2_quiet),
    _a('LR-2 divider pads of two channels 1 mm apart', R.lr2, 'apart', mut2_gap),
    _a('LR-3 via on CH1_N', R.lr3, 'a via', mut3_via),
    _a('LR-3 16 mm of CH2_N', R.lr3, 'mm of track', mut3_long),
    _a('LR-3 track 0.5 mm beside CH1_N', R.lr3, 'within 0.6 mm', mut3_beside),
    _a('LR-4 via in A0', R.lr4, '/A0: a via', mut4_via_a0),
    _a('LR-4 bottom copper on A1', R.lr4, '/A1: bottom copper', mut4_bot_a1),
    _a('LR-4 via on AWG_INV', R.lr4, 'inverting node has a via', mut4_via_inv),
    _a('LR-4 AWG_INV 16 mm long', R.lr4, 'inverting node', mut4_long),
    _a('LR-4 pour near AWG_INV', R.lr4, 'top ground copper', mut4_pour),
    _a('LR-12 100 nF far from U301.8', R.lr12, 'C302', mut12_decoup),
    _a('LR-4 Riso far from the output pin', R.lr4, 'R107', mut4_riso),
    _a('LR-5 VREF track by the generator', R.lr5, '/VREF', mut5),
    _a('LR-5 VREF pad by the generator', R.lr5, 'pad R508', mut5_pad),
    _a('LR-6 AWG and REF/ADS on one +3V3A piece', R.lr6, 'serves', mut6_join, prep_connected_rails),
    _a('LR-6 SCOPE and AWG on one +3V3A piece', R.lr6, 'serves', mut6_scope_join, prep_connected_rails),
    _a('LR-6 star pad off the rail', R.lr6, 'star pads', mut6_star),
    _a('LR-7 DAC0 30 mm', R.lr7, 'DAC0', mut7_dac0),
    _a('LR-7 R304 far from the BNC', R.lr7, 'R304', mut7_bt),
    _a('LR-7 BNC shell not on ground', R.lr7, 'shell', mut7_shell),
    _a('LR-8 ladder and ADS share VREF copper', R.lr8, 'share copper', mut8_join, prep_connected_vref),
    _a('LR-8 AWG offset and the scope branch share copper', R.lr8, 'share copper', mut8_join2, prep_connected_vref),
    _a('LR-9 SDA1 through U101', R.lr9, 'through U101', mut9_ana),
    _a('LR-11 part out of its fence', R.lr11, "'R201'", mut11_out, prep_silk),
    _a('LR-11 bridge away from its floorplan point', R.lr11, "'R515'", mut11_bridge, prep_silk),
    _a('LR-11 designator under 0.8 mm / not on silk', R.lr11, 'R101: designator', mut11_silk, prep_silk),
    _a('LR-11 missing test point (AWG_OUT)', R.lr11, 'TP301', mut11_tp, prep_silk),
    _a('LR-11 wrong-numbered designator', R.lr11, 'R399', mut11_num, prep_silk),
    _a('LR-11 block without a test point', R.lr11, 'REFCAL has no test point', mut11_noblock, prep_silk),
    _a('LR-11 silk word missing', R.lr11, "silk word 'AWG'", mut11_word, prep_silk),
]


def _repair(name, rule, key, fix):
    def run(b, cfg):
        out = fix(b, cfg)
        _MUTANTS[id(out)] = out
        return out
    return (name, _Gone(rule, key, fix), run)


# the old REPAIRS: the repair adds the copper the rule asks for and the named reason must disappear
ARMS += [
    _repair('REPAIR LR-1 every SMD GND pad gets a via', R.lr1, 'without a via', prep_gnd_vias),
    _repair('REPAIR LR-6 each consumer connected on its rail', R.lr6, 'is not connected to the star', prep_connected_rails),
    _repair('REPAIR LR-8 each branch connected', R.lr8, 'is not connected to the source', prep_connected_vref),
    _repair('REPAIR LR-11 silk added', R.lr11, 'designator not on silk', prep_silk),
]

