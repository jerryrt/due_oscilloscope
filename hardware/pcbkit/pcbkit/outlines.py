"""Block rectangles and block membership: which part belongs to which block, which block's rectangle holds which part.

Pure functions on a pcbkit.board.BoardArrays and resolved configuration values (rules.blocks and rules.test_points read the names; see CONFIG.md).
The lines of an outline (breaks where a line would cross a pad or footprint silk) are drawn by pcbkit.labels, not here.
"""
from __future__ import annotations

import numpy as np


def in_rects(P, rects):
    """bool (N,): the point lies in one of the rects (closed)"""
    R = np.array(rects, float).reshape(-1, 4)
    return ((P[:, None, 0] >= R[None, :, 0]) & (P[:, None, 0] <= R[None, :, 2])
            & (P[:, None, 1] >= R[None, :, 1]) & (P[:, None, 1] <= R[None, :, 3])).any(axis=1)


def block_of_parts(b, block, outline):
    """the block of every footprint (a list in footprint order): the configured block of its designator, else the first outline that holds its
    origin, else None"""
    refs = list(b.fp_ref)
    P = np.column_stack([b.fp_x, b.fp_y])
    inout = {k: in_rects(P, rects) for k, rects in outline.items()}

    def of(i):
        v = block.get(refs[i])
        if v is None:
            v = next((k for k in outline if inout[k][i]), None)
        return v
    return [of(i) for i in range(len(refs))]


def membership_findings(b, block, outline, strays=(), edge_block=None, override=(), shared=None, shared_margin=0.0):
    """one finding per block whose rectangles do not hold exactly its parts: 'BLOCK: outline holds [extra] extra, lacks [missing]'.
    Parts of `edge_block` belong to no outline unless listed in `override`; a part in `shared` (ref -> home block) is a part that straddles
    two rectangles: held to its home block's outline within `shared_margin` and counted in no other; `strays` are named parts allowed outside
    their own block's rectangles, but never inside another's"""
    shared = shared or {}
    blocks = {}
    for r, blk in block.items():
        if blk != edge_block or r in override:
            blocks.setdefault(blk, set()).add(r)
    blocks.pop(edge_block, None)
    refs = list(b.fp_ref)
    P = np.column_stack([b.fp_x, b.fp_y])
    candidate = np.array([(r in block and block[r] != edge_block) or r in override for r in refs], bool)
    bad = []
    for blk, rects in outline.items():
        inside = {refs[i] for i in np.flatnonzero(candidate & in_rects(P, rects))}
        for r, home in shared.items():
            if r in refs:
                i = refs.index(r)
                inside.discard(r)
                if home == blk and in_rects(P[i:i + 1], [(x0 - shared_margin, y0 - shared_margin, x1 + shared_margin, y1 + shared_margin)
                                                         for x0, y0, x1, y1 in rects])[0]:
                    inside.add(r)
        want = blocks.get(blk, set()) - set(strays)
        inside -= set(strays) & blocks.get(blk, set())
        if inside != want:
            bad.append(f'{blk}: outline holds {sorted(inside - want)[:5]} extra, lacks {sorted(want - inside)[:5]}')
    return bad
