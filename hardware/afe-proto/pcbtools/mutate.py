"""Pure-numpy edits of a BoardArrays, the vocabulary of the mutation arms (pcbtools.boards.<board>_arms): each returns a
NEW BoardArrays and leaves its argument alone. Appended tracks and vias take the next free index of the board.track
enumeration, so a mutated board still has a consistent s_idx/a_idx/v_idx partition."""
from __future__ import annotations

import numpy as np

from . import boardio


def _group(name):
    return [n for n, _ in boardio.SPEC[name]]


def _cat(old, new, kind):
    if kind == 'S':
        return tuple(old) + tuple(new)
    return np.concatenate([np.asarray(old), np.asarray(new, np.asarray(old).dtype)])


def _append(b, group, **row):
    kw = {}
    for n in _group(group):
        kind = boardio.KIND[n]
        kw[n] = _cat(getattr(b, n), [row[n]], kind)
    return b.replace(**kw)


def _next_track_idx(b):
    return int(max([-1, *b.s_idx.tolist(), *b.a_idx.tolist(), *b.v_idx.tolist()])) + 1


def net(b, name):
    return b.net_id(name)


def add_segment(b, netname, layer, p0, p1, w=0.2):
    """layer 'F' or 'B'"""
    return _append(b, 'segments', s_idx=_next_track_idx(b), s_x0=p0[0], s_y0=p0[1], s_x1=p1[0], s_y1=p1[1], s_w=w,
                   s_layer=0 if layer == 'F' else 1, s_net=net(b, netname))


def add_via(b, netname, p, dia=0.6, drill=0.3):
    return _append(b, 'vias', v_idx=_next_track_idx(b), v_x=p[0], v_y=p[1], v_dia=dia, v_drill=drill, v_net=net(b, netname))


def drop_vias(b, mask):
    keep = ~np.asarray(mask, bool)
    return b.replace(**{n: getattr(b, n)[keep] for n in _group('vias')})


def drop_pads(b, mask):
    keep = ~np.asarray(mask, bool)
    kw = {}
    for n in _group('pads'):
        v = getattr(b, n)
        kw[n] = tuple(x for x, k in zip(v, keep) if k) if isinstance(v, tuple) else v[keep]
    return b.replace(**kw)


def move_footprint(b, ref, x=None, y=None):
    i = b.ref_index(ref)
    fx, fy = b.fp_x.copy(), b.fp_y.copy()
    if x is not None:
        fx[i] = x
    if y is not None:
        fy[i] = y
    return b.replace(fp_x=fx, fp_y=fy)


def last_pad(b, ref, pin):
    """row of the pad the old loader saw for (ref, pin): the last one"""
    return int(b.pad_indices(ref, pin)[-1])


def shift_pad(b, ref, pin, dx=0.0, dy=0.0):
    r = last_pad(b, ref, pin)
    kw = {}
    for n, d in (('p_x', dx), ('p_bx0', dx), ('p_bx1', dx), ('p_y', dy), ('p_by0', dy), ('p_by1', dy)):
        a = getattr(b, n).copy()
        a[r] += d
        kw[n] = a
    return b.replace(**kw)


def set_pad_net(b, ref, pin, netname):
    r = last_pad(b, ref, pin)
    a = b.p_net.copy()
    a[r] = net(b, netname)
    return b.replace(p_net=a)


def add_footprint_like(b, new_ref, like_ref):
    """a footprint at the same place as `like_ref`, with its reference text (no pads)"""
    i = b.ref_index(like_ref)
    n = len(b.fp_idx)
    kw = {}
    for f in _group('footprints'):
        v = getattr(b, f)
        val = new_ref if f == 'fp_ref' else n if f == 'fp_idx' else v[i]
        kw[f] = _cat(v, [val], boardio.KIND[f])
    k = int(np.flatnonzero(b.r_fp == i)[0])
    for f in _group('reftext'):
        v = getattr(b, f)
        kw[f] = _cat(v, [n if f == 'r_fp' else v[k]], boardio.KIND[f])
    return b.replace(**kw)


def first_segment(b, netname):
    """(x0, y0, x1, y1) of the first segment of the net, in enumeration order, any layer"""
    i = int(np.flatnonzero(b.s_net == net(b, netname))[0])
    return (b.s_x0[i], b.s_y0[i], b.s_x1[i], b.s_y1[i])


def pad_center(b, ref, pin):
    r = last_pad(b, ref, pin)
    return (float(b.p_x[r]), float(b.p_y[r]))


def add_zone(b, netname, layer, rings, filled=True):
    """append a filled zone. `rings` is a list of (vertices (V,2), is_hole)"""
    xy = np.vstack([np.asarray(r, np.float64).reshape(-1, 2) for r, _ in rings])
    lens = [len(np.asarray(r).reshape(-1, 2)) for r, _ in rings]
    voff = np.concatenate([b.z_vert_off, b.z_vert_off[-1] + np.cumsum(lens)])
    return b.replace(z_layer=np.append(b.z_layer, 0 if layer == 'F' else 1).astype(np.int8),
                     z_net=np.append(b.z_net, net(b, netname)).astype(np.int32), z_filled=np.append(b.z_filled, filled),
                     z_xy=np.vstack([b.z_xy, xy]), z_vert_off=voff,
                     z_ring_off=np.append(b.z_ring_off, b.z_ring_off[-1] + len(rings)),
                     z_ring_hole=np.append(b.z_ring_hole, [int(h) for _, h in rings]).astype(np.int8))


def drop_segments(b, mask):
    """remove the segments where `mask` (over b.s_idx) is True"""
    keep = ~np.asarray(mask, bool)
    return b.replace(**{n: getattr(b, n)[keep] for n in _group('segments')})


def segments_at_pad(b, netname, ref, pin, reach=0.3):
    """bool over the segments: on `netname` and with an end within `reach` of the (ref, pin) pad's centre (any layer)"""
    c = pad_center(b, ref, pin)
    on = b.s_net == net(b, netname)
    d0, d1 = np.hypot(b.s_x0 - c[0], b.s_y0 - c[1]), np.hypot(b.s_x1 - c[0], b.s_y1 - c[1])
    return on & (np.minimum(d0, d1) <= reach)


def drop_zones(b, mask):
    """remove the zones where `mask` (over zones) is True, with their rings and vertices"""
    mask = np.asarray(mask, bool)
    keep_z = np.flatnonzero(~mask)
    rings, verts = [], []
    ring_off, vert_off, hole = [0], [0], []
    for z in keep_z:
        for j in range(b.z_ring_off[z], b.z_ring_off[z + 1]):
            v = b.z_xy[b.z_vert_off[j]:b.z_vert_off[j + 1]]
            verts.append(v)
            vert_off.append(vert_off[-1] + len(v))
            hole.append(int(b.z_ring_hole[j]))
        ring_off.append(len(hole))
    return b.replace(z_layer=b.z_layer[keep_z], z_net=b.z_net[keep_z], z_filled=b.z_filled[keep_z],
                     z_xy=np.vstack(verts) if verts else np.zeros((0, 2)), z_vert_off=np.array(vert_off, np.int64),
                     z_ring_off=np.array(ring_off, np.int64), z_ring_hole=np.array(hole, np.int8))


def set_pad_size(b, ref, pin, sx, sy):
    """resize the (ref, pin) pad about its centre; its bounding box follows its rotation"""
    r = last_pad(b, ref, pin)
    a = np.radians(b.p_rot[r])
    hx = (abs(np.cos(a)) * sx + abs(np.sin(a)) * sy) / 2
    hy = (abs(np.sin(a)) * sx + abs(np.cos(a)) * sy) / 2
    kw = {}
    for n, v in (('p_sx', sx), ('p_sy', sy), ('p_bx0', b.p_x[r] - hx), ('p_bx1', b.p_x[r] + hx), ('p_by0', b.p_y[r] - hy),
                 ('p_by1', b.p_y[r] + hy)):
        arr = getattr(b, n).copy()
        arr[r] = v
        kw[n] = arr
    return b.replace(**kw)
