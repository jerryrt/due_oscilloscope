"""merge.py: merge per-block board copies into one integrator board.

    res = merge(base_path, {'AWG': 'awg.kicad_pcb', 'POWER': 'power.kicad_pcb'}, out_path, cfg)

Each block board is a copy of the base in which one block's agent worked. For every block, in the order given:
  fence.check_fence() judges it against the ORIGINAL base; a block that moved a foreign part or changed copper outside its
  fences is REFUSED (reported, not merged, the others still merge). A clean block contributes (a) the position and rotation
  of every part it owns, with its designator text pose, and (b) its tracks and vias wholly inside its fences; the base's own
  tracks and vias wholly inside those fences are removed first. Zones are the base's (refill the pour afterwards).

Both boards are read once into arrays (boardio.read_board); every decision is a boolean mask on those arrays; the board is
changed in ONE edit() call. cfg: the names fence.py reads (FENCES, HUNDREDS, OWNER_OVERRIDE, TOL_MM).
"""
from __future__ import annotations

import dataclasses

import numpy as np

from . import boardio, fence
from .editor import edit

_LAYER = {0: 'F', 1: 'B'}


@dataclasses.dataclass
class MergeResult:
    merged: list
    refused: dict            # block -> [violation lines]
    report: list             # the old tool's printed lines
    items: dict              # block -> number of tracks and vias added
    ok: bool = True

    def __post_init__(self):
        self.ok = not self.refused


def _overlaps(cfg):
    rects = [(b, r) for b, rs in cfg.FENCES.items() for r in rs]
    out = []
    for i, (b1, r1) in enumerate(rects):
        for b2, r2 in rects[i + 1:]:
            if b1 != b2 and r1[0] < r2[2] and r2[0] < r1[2] and r1[1] < r2[3] and r2[1] < r1[3]:
                out.append(f'warning: fences of {b1} and {b2} overlap: {r1} / {r2}')
    return out


def merge(base_path, blocks, out_path, cfg):
    base = boardio.read_board(base_path)
    report = _overlaps(cfg)
    merged, refused, items = [], {}, {}
    plan = []                                    # (block, blk arrays, base masks, blk masks)
    for name, path in blocks.items():
        blk = boardio.read_board(path)
        res = fence.check_fence(base, blk, name, cfg)
        if res.violations:
            refused[name] = list(res.violations)
            report += [f'{name}: REFUSED: {m}' for m in res.violations]
            continue
        bs, ba, bv = fence.inside_masks(base, name, cfg)
        ks, ka, kv = fence.inside_masks(blk, name, cfg)
        if ka.any():
            raise NotImplementedError(f'{name}: arcs inside its fences are not merged (none exist on any board so far)')
        n = int(ks.sum() + kv.sum())
        report.append(f'{name}: merged ({n} tracks/vias in its fences)')
        items[name] = n
        merged.append(name)
        plan.append((name, blk, (bs, ba, bv), (ks, ka, kv)))

    with edit(base_path, out=out_path) as e:
        for name, blk, (bs, ba, bv), (ks, ka, kv) in plan:
            # (a) the parts the block owns
            for i, ref in enumerate(blk.fp_ref):
                if fence.owner_of(ref, cfg) != name or ref not in base.fp_ref:
                    continue
                e.move(ref, float(blk.fp_x[i]), float(blk.fp_y[i]), float(blk.fp_rot[i]))
                j = np.flatnonzero(blk.r_fp == i)
                if len(j):
                    j = int(j[0])
                    e.set_ref_pose(ref, float(blk.r_x[j]), float(blk.r_y[j]), float(blk.r_ang[j]))
            # (b) copper: remove the base's inside the fences, add the block's
            e.remove_tracks(base.s_idx[bs])
            e.remove_vias(base.v_idx[bv])
            _add_segments(e, blk, ks)
            _add_vias(e, blk, kv)
    return MergeResult(merged, refused, report, items)


def _add_segments(e, b, mask):
    idx = np.flatnonzero(mask)
    if not len(idx):
        return
    key = np.stack([b.s_net[idx], b.s_layer[idx].astype(np.int64), np.round(b.s_w[idx] * 1e6).astype(np.int64)], axis=1)
    for k in np.unique(key, axis=0):
        sel = idx[(key == k).all(axis=1)]
        e.add_tracks(b.nets[int(k[0])], _LAYER[int(k[1])], b.s_x0[sel], b.s_y0[sel], b.s_x1[sel], b.s_y1[sel], k[2] / 1e6)


def _add_vias(e, b, mask):
    idx = np.flatnonzero(mask)
    if not len(idx):
        return
    key = np.stack([b.v_net[idx], np.round(b.v_dia[idx] * 1e6).astype(np.int64), np.round(b.v_drill[idx] * 1e6).astype(np.int64)], axis=1)
    for k in np.unique(key, axis=0):
        sel = idx[(key == k).all(axis=1)]
        e.add_vias(b.nets[int(k[0])], b.v_x[sel], b.v_y[sel], k[1] / 1e6, k[2] / 1e6)
