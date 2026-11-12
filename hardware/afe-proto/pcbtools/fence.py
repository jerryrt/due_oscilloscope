"""Fence rule (the old fence_check.py) on BoardArrays: a block board is a copy of the base in which one block's agent
worked. Rules: (1) every part that does not belong to the block has the position, rotation and side it has in the base;
(2) the tracks and vias that are not wholly inside one of the block's fences are identical to the base's. Zones and silk
are not compared.

    owner_of(ref, cfg) -> str | None
    inside_masks(b, block, cfg) -> (seg_mask, arc_mask, via_mask)     wholly inside ONE fence of the block (closed, 1e-6)
    violations(base, blk, block, cfg) -> list[str]                     the old tool's printed lines, as data
    check_fence(base, blk, block, cfg) -> FenceResult

cfg names: FENCES {block: [(x0, y0, x1, y1)]}, HUNDREDS {digit: block | None}, OWNER_OVERRIDE {ref: block}, TOL_MM.
Arcs (not on any fixture; the old tool read an arc as a chord) are compared by start and end like the old tool, and are
"inside" only when start, mid and end are all inside one fence.
KiCad layer numbers appear in the item keys as the old tool printed them (F.Cu 0, B.Cu 2) and part sides as 0 (front) / 31.
"""
from __future__ import annotations

import dataclasses

import numpy as np

EPS = 1e-6


@dataclasses.dataclass
class FenceResult:
    violations: list
    foreign_moved: list                 # refs of parts outside the block that moved, vanished or appeared
    outside_changed_idx: dict           # {'base': {'s_idx', 'a_idx', 'v_idx'}, 'blk': {...}}: outside copper that differs
    ok: bool = True

    def __post_init__(self):
        self.ok = not self.violations


def owner_of(ref, cfg):
    if ref in cfg.OWNER_OVERRIDE:
        return cfg.OWNER_OVERRIDE[ref]
    d = ''.join(ch for ch in ref if ch.isdigit())
    return cfg.HUNDREDS.get(d[:1]) if len(d) >= 3 else None


def _in_one_fence(X, Y, rects):
    """X, Y: (n, k) point coordinates per item; True where all k points lie in one and the same rect"""
    ok = np.zeros(len(X), bool)
    for (x0, y0, x1, y1) in rects:
        ok |= ((X >= x0 - EPS) & (X <= x1 + EPS) & (Y >= y0 - EPS) & (Y <= y1 + EPS)).all(axis=1)
    return ok


def inside_masks(b, block, cfg):
    rects = cfg.FENCES[block]
    s = _in_one_fence(np.column_stack([b.s_x0, b.s_x1]), np.column_stack([b.s_y0, b.s_y1]), rects) if len(b.s_idx) else np.zeros(0, bool)
    a = _in_one_fence(np.column_stack([b.a_x0, b.a_xm, b.a_x1]), np.column_stack([b.a_y0, b.a_ym, b.a_y1]), rects) if len(b.a_idx) else np.zeros(0, bool)
    v = _in_one_fence(b.v_x[:, None], b.v_y[:, None], rects) if len(b.v_idx) else np.zeros(0, bool)
    return s, a, v


def _r(v):
    return round(float(v), 3)


def _layer(code):
    return 0 if code == 0 else 2 if code == 1 else 4


def _outside(b, block, cfg):
    """[(key, kind, s_idx/a_idx/v_idx)] of every item not wholly inside one fence, keyed as the old tool keyed it"""
    ms, ma, mv = inside_masks(b, block, cfg)
    out = []
    for i in np.flatnonzero(~ms):
        p, q = sorted(((_r(b.s_x0[i]), _r(b.s_y0[i])), (_r(b.s_x1[i]), _r(b.s_y1[i]))))
        out.append((('trk', b.nets[b.s_net[i]], _layer(b.s_layer[i]), p, q, _r(b.s_w[i])), 's', int(b.s_idx[i])))
    for i in np.flatnonzero(~ma):
        p, q = sorted(((_r(b.a_x0[i]), _r(b.a_y0[i])), (_r(b.a_x1[i]), _r(b.a_y1[i]))))
        out.append((('trk', b.nets[b.a_net[i]], _layer(b.a_layer[i]), p, q, _r(b.a_w[i])), 'a', int(b.a_idx[i])))
    for i in np.flatnonzero(~mv):
        out.append((('via', b.nets[b.v_net[i]], _r(b.v_x[i]), _r(b.v_y[i]), _r(b.v_dia[i]), _r(b.v_drill[i])), 'v', int(b.v_idx[i])))
    return out


def _parts(b):
    return {r: (_r(b.fp_x[i]), _r(b.fp_y[i]), round(float(b.fp_rot[i] % 360), 2), 0 if b.fp_side[i] == 0 else 31)
            for i, r in enumerate(b.fp_ref)}


def check_fence(base, blk, block, cfg):
    bad, moved = [], []
    pb, pa = _parts(base), _parts(blk)
    for r in sorted(set(pb) | set(pa)):
        if owner_of(r, cfg) == block:
            continue
        if r not in pa or r not in pb:
            bad.append(f'{r}: part {"missing from the block board" if r not in pa else "not in the base"}')
            moved.append(r)
        elif max(abs(pa[r][0] - pb[r][0]), abs(pa[r][1] - pb[r][1])) > cfg.TOL_MM or pa[r][2:] != pb[r][2:]:
            bad.append(f'{r} (belongs to {owner_of(r, cfg)}): moved {pb[r]} -> {pa[r]}')
            moved.append(r)
    ob, oa = _outside(base, block, cfg), _outside(blk, block, cfg)
    kb, ka = [x[0] for x in ob], [x[0] for x in oa]
    sb, sa = set(kb), set(ka)
    for k in sorted(sb - sa):
        bad.append(f'copper outside the {block} fence removed or changed: {k}')
    for k in sorted(sa - sb):
        bad.append(f'copper outside the {block} fence added or changed: {k}')
    if len(kb) != len(ka) and sb == sa:
        bad.append(f'copper outside the {block} fence: duplicate items differ ({len(kb)} vs {len(ka)})')

    def idx(items, other):
        d = {'s_idx': [], 'a_idx': [], 'v_idx': []}
        for k, kind, i in items:
            if k not in other:
                d[kind + '_idx'].append(i)
        return {n: np.array(v, np.int64) for n, v in d.items()}
    return FenceResult(bad, moved, {'base': idx(ob, sa), 'blk': idx(oa, sb)})


def violations(base, blk, block, cfg):
    return check_fence(base, blk, block, cfg).violations
