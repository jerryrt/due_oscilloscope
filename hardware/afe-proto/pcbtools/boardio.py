"""Board I/O: the only module that imports pcbnew (lazily, inside read_board), and the BoardArrays container.

    read_board(path) -> BoardArrays      loads the board once, copies it into numpy arrays, frees it
    to_due / from_due                    the one KiCad-mm <-> Due-mm transform
    save_npz / load_npz                  cache of a BoardArrays, readable without pcbnew
    read_board_retry(path)               read_board in a short child process, retried on a start-up segfault

Conventions (ARRAYS.md): Due mm, y up, origin at the Due's lower-left corner (x - 50, 150 - y); float64 rounded to
1e-6; angles in degrees counter-clockwise (a y flip leaves the visual sense unchanged, so KiCad's value is kept).
`s_idx`, `a_idx` and `v_idx` are the position of the item in board.GetTracks() (the whole enumeration, all classes
together), `fp_idx` the position in GetFootprints(): an editor can address an item from a mask on these arrays.
Layers: 0 = F.Cu, 1 = B.Cu, 2 = any inner copper layer.
"""
from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from functools import cached_property

import numpy as np

OX, OY = 50.0, 150.0        # KiCad board_x = OX + x, board_y = OY - y  (y up in Due mm)
ND = 6                      # decimals: 1e-6 mm

# (name, kind). kinds: f8 i4 i1 u1 i8 ? = numpy dtypes, S = tuple of str, xy = float64 (N,2)
_F = 'f8'
SPEC = {
    'outline': [('outline', 'xy')],
    'segments': [('s_idx', 'i4')] + [(n, _F) for n in ('s_x0', 's_y0', 's_x1', 's_y1', 's_w')] + [('s_layer', 'i1'), ('s_net', 'i4')],
    'arcs': [('a_idx', 'i4')] + [(n, _F) for n in ('a_x0', 'a_y0', 'a_xm', 'a_ym', 'a_x1', 'a_y1', 'a_w')] + [('a_layer', 'i1'), ('a_net', 'i4')],
    'vias': [('v_idx', 'i4')] + [(n, _F) for n in ('v_x', 'v_y', 'v_dia', 'v_drill')] + [('v_net', 'i4')],
    'footprints': [('fp_idx', 'i4'), ('fp_ref', 'S')] + [(n, _F) for n in ('fp_x', 'fp_y', 'fp_rot')] + [('fp_side', 'i1')]
                  + [(n, _F) for n in ('fp_cx0', 'fp_cy0', 'fp_cx1', 'fp_cy1')] + [('fp_kind', 'S')],
    'pads': [('p_fp', 'i4'), ('p_pin', 'S')] + [(n, _F) for n in ('p_x', 'p_y', 'p_bx0', 'p_by0', 'p_bx1', 'p_by1')]
            + [('p_net', 'i4'), ('p_smd', '?'), ('p_rot', _F), ('p_shape', 'i1'), ('p_sx', _F), ('p_sy', _F), ('p_layer_mask', 'u1')],
    'reftext': [(n, _F) for n in ('r_x', 'r_y', 'r_h', 'r_w', 'r_t', 'r_ang')] + [('r_layer', 'i1'), ('r_on_silk', '?'), ('r_fp', 'i4')],
    'silk': [('t_text', 'S')] + [(n, _F) for n in ('t_x', 't_y', 't_h')],
    'zones': [('z_layer', 'i1'), ('z_net', 'i4'), ('z_filled', '?')],
}
# zone geometry: z_xy (V,2), z_ring_off (nz+1) int64 zone -> ring, z_vert_off (nring+1) int64 ring -> vertex,
# z_ring_hole (nring) int8: 0 = outline ring, 1 = hole ring (a hole belongs to the nearest outline before it)
_ZGEO = [('z_xy', 'xy'), ('z_ring_off', 'off'), ('z_vert_off', 'off'), ('z_ring_hole', 'i1')]
PAD_SHAPES = {'circle': 0, 'rect': 1, 'oval': 2, 'roundrect': 3, 'other': 4}
R_LAYERS = {'F.SilkS': 0, 'B.SilkS': 1, 'F.Fab': 2, 'other': 3}


def _empty(kind):
    if kind == 'S':
        return ()
    if kind == 'xy':
        return np.zeros((0, 2), np.float64)
    if kind == 'off':
        return np.zeros(1, np.int64)
    return np.zeros(0, np.dtype(kind))


def _coerce(kind, v):
    if kind == 'S':
        return tuple(str(x) for x in v)
    if kind == 'xy':
        a = np.asarray(v, np.float64)
        return a.reshape(-1, 2)
    if kind == 'off':
        return np.asarray(v, np.int64).reshape(-1)
    return np.asarray(v, np.dtype(kind)).reshape(-1)


_ALL = [f for g in SPEC.values() for f in g] + _ZGEO
KIND = dict(_ALL)


def _post_init(self):
    for name, kind in _ALL:
        object.__setattr__(self, name, _coerce(kind, getattr(self, name)))
    object.__setattr__(self, 'nets', tuple(str(x) for x in self.nets))
    for g, fields in SPEC.items():
        if g == 'outline':
            continue
        ns = {len(getattr(self, n)) for n, _ in fields}
        if len(ns) != 1:
            raise ValueError(f'BoardArrays group {g}: fields differ in length: '
                             f'{ {n: len(getattr(self, n)) for n, _ in fields} }')
    nz, nring = len(self.z_layer), len(self.z_vert_off) - 1
    if len(self.z_ring_off) != nz + 1 and not (nz == 0 and len(self.z_ring_off) == 1):
        raise ValueError('z_ring_off must have one entry more than there are zones')
    if self.z_ring_off[-1] != nring or self.z_vert_off[-1] != len(self.z_xy):
        raise ValueError('zone offsets do not close over the ring / vertex arrays')
    if len(self.z_ring_hole) != nring:
        raise ValueError('z_ring_hole must have one flag per ring')
    if nring and self.z_ring_hole.min() < 0 or nring and self.z_ring_hole.max() > 1:
        raise ValueError('z_ring_hole flags are 0 (outline) or 1 (hole)')


def _make():
    fields = [('path', str, dataclasses.field(default='')), ('copper_layers', int, dataclasses.field(default=2)),
              ('nets', tuple, dataclasses.field(default=('',)))]
    for n, k in _ALL:
        fields.append((n, object, dataclasses.field(default_factory=(lambda k=k: _empty(k)))))
    return dataclasses.make_dataclass('BoardArrays', fields, frozen=True, eq=False, namespace={'__post_init__': _post_init,
                                      '__doc__': __doc__})


BoardArrays = _make()


# ----------------------------------------------------------------------------------------------- derived lookups
def _net_id(self, name):
    try:
        return self._net_map[name]
    except KeyError:
        raise KeyError(f'no net {name!r}') from None


def _ref_index(self, ref):
    try:
        return self._ref_map[ref]
    except KeyError:
        raise KeyError(f'no footprint {ref!r}') from None


def _pad_index(self, ref, pin):
    """first pad of (ref, pin) as an index into the pad arrays; pad_indices() gives every one"""
    ix = self.pad_indices(ref, pin)
    if not len(ix):
        raise KeyError(f'no pad {ref}.{pin}')
    return int(ix[0])


def _pad_indices(self, ref, pin):
    return np.flatnonzero((self.p_fp == self.ref_index(ref)) & (np.asarray(self.p_pin, dtype=object) == str(pin)))


def _layer_code(layer):
    if isinstance(layer, str):
        return {'F': 0, 'F.CU': 0, 'TOP': 0, 'B': 1, 'B.CU': 1, 'BOTTOM': 1}[layer.upper()]
    return int(layer)


def _seg_mask(self, net=None, layer=None):
    m = np.ones(len(self.s_idx), bool)
    if net is not None:
        m &= self.s_net == (self.net_id(net) if isinstance(net, str) else int(net))
    if layer is not None:
        m &= self.s_layer == _layer_code(layer)
    return m


def _pad_mask(self, net=None):
    m = np.ones(len(self.p_fp), bool)
    if net is not None:
        m &= self.p_net == (self.net_id(net) if isinstance(net, str) else int(net))
    return m


BoardArrays.net_id = _net_id
BoardArrays.ref_index = _ref_index
BoardArrays.pad_index = _pad_index
BoardArrays.pad_indices = _pad_indices
BoardArrays.seg_mask = _seg_mask
BoardArrays.pad_mask = _pad_mask
BoardArrays._net_map = cached_property(lambda self: {n: i for i, n in reversed(list(enumerate(self.nets)))})
BoardArrays._ref_map = cached_property(lambda self: {r: i for i, r in enumerate(self.fp_ref)})
BoardArrays._net_map.__set_name__(BoardArrays, '_net_map')
BoardArrays._ref_map.__set_name__(BoardArrays, '_ref_map')
BoardArrays.from_arrays = classmethod(lambda cls, **kw: cls(**kw))
BoardArrays.replace = lambda self, **kw: dataclasses.replace(self, **kw)


# ----------------------------------------------------------------------------------------------- the transform
def to_due(x, y):
    """KiCad mm -> Due mm (arrays or scalars). The only place the transform is written."""
    return np.asarray(x, np.float64) - OX, OY - np.asarray(y, np.float64)


def from_due(x, y):
    """Due mm -> KiCad mm; the inverse of to_due"""
    return np.asarray(x, np.float64) + OX, OY - np.asarray(y, np.float64)


def _r(a):
    return np.round(np.asarray(a, np.float64), ND) + 0.0      # + 0.0 turns -0.0 into 0.0


# ----------------------------------------------------------------------------------------------- npz cache
def save_npz(b, path):
    d = {'__path': np.array(b.path), '__copper_layers': np.array(b.copper_layers), '__nets': np.array(b.nets, dtype=str)}
    for n, k in _ALL:
        v = getattr(b, n)
        d[n] = np.array(v, dtype=str) if k == 'S' else v
    np.savez_compressed(path, **d)


def load_npz(path):
    with np.load(path, allow_pickle=False) as z:
        kw = dict(path=str(z['__path']), copper_layers=int(z['__copper_layers']), nets=tuple(z['__nets'].tolist()))
        for n, k in _ALL:
            kw[n] = tuple(z[n].tolist()) if k == 'S' else z[n]
    return BoardArrays(**kw)


# ----------------------------------------------------------------------------------------------- pcbnew side
def _layer(pcb, lay, name_map=None):
    if lay == pcb.F_Cu:
        return 0
    if lay == pcb.B_Cu:
        return 1
    return 2


def read_board(path):
    """Load `path` with pcbnew once, copy everything into BoardArrays, delete the board, return."""
    import gc
    import pcbnew as pcb
    assert pcb.pcbIUScale.IU_PER_MM == 1e6
    b = pcb.LoadBoard(str(path))
    if b is None:
        raise IOError(f'pcbnew cannot load {path}')
    try:
        out = _extract(pcb, b, str(path))
    finally:
        del b
        gc.collect()
    return out


def _extract(pcb, b, path):
    U = 1e-6
    # nets: index = net code; codes must be 0..n-1 (checked)
    byc = b.GetNetInfo().NetsByNetcode()
    codes = sorted(byc.keys())
    if codes != list(range(len(codes))) or str(byc[0].GetNetname()) != '':
        raise ValueError('net codes are not contiguous from 0 with an empty net 0')
    nets = tuple(str(byc[c].GetNetname()) for c in codes)

    # tracks
    S, A, V = [], [], []
    for i, t in enumerate(b.GetTracks()):
        c = t.GetClass()
        if c == 'PCB_VIA':
            p = t.GetPosition()
            V.append((i, p.x, p.y, t.GetWidth(pcb.F_Cu), t.GetDrillValue(), t.GetNetCode()))
        elif c == 'PCB_ARC':
            s, m, e = t.GetStart(), t.GetMid(), t.GetEnd()
            A.append((i, s.x, s.y, m.x, m.y, e.x, e.y, t.GetWidth(), _layer(pcb, t.GetLayer()), t.GetNetCode()))
        elif c == 'PCB_TRACK':
            s, e = t.GetStart(), t.GetEnd()
            S.append((i, s.x, s.y, e.x, e.y, t.GetWidth(), _layer(pcb, t.GetLayer()), t.GetNetCode()))
        else:
            raise ValueError(f'unknown track class {c}')
    S, A, V = (np.array(x, np.float64).reshape(len(x), -1) if x else x for x in (S, A, V))
    kw = {}
    if len(S):
        x0, y0 = to_due(S[:, 1] * U, S[:, 2] * U)
        x1, y1 = to_due(S[:, 3] * U, S[:, 4] * U)
        kw.update(s_idx=S[:, 0], s_x0=_r(x0), s_y0=_r(y0), s_x1=_r(x1), s_y1=_r(y1), s_w=_r(S[:, 5] * U), s_layer=S[:, 6], s_net=S[:, 7])
    if len(A):
        x0, y0 = to_due(A[:, 1] * U, A[:, 2] * U)
        xm, ym = to_due(A[:, 3] * U, A[:, 4] * U)
        x1, y1 = to_due(A[:, 5] * U, A[:, 6] * U)
        kw.update(a_idx=A[:, 0], a_x0=_r(x0), a_y0=_r(y0), a_xm=_r(xm), a_ym=_r(ym), a_x1=_r(x1), a_y1=_r(y1),
                  a_w=_r(A[:, 7] * U), a_layer=A[:, 8], a_net=A[:, 9])
    if len(V):
        x, y = to_due(V[:, 1] * U, V[:, 2] * U)
        kw.update(v_idx=V[:, 0], v_x=_r(x), v_y=_r(y), v_dia=_r(V[:, 3] * U), v_drill=_r(V[:, 4] * U), v_net=V[:, 5])

    # footprints, pads, reference text
    FP, PD, RT = [], [], []
    shape_map = {pcb.PAD_SHAPE_CIRCLE: 0, pcb.PAD_SHAPE_RECTANGLE: 1, pcb.PAD_SHAPE_OVAL: 2, pcb.PAD_SHAPE_ROUNDRECT: 3}
    for i, f in enumerate(b.GetFootprints()):
        side = 0 if f.GetLayer() == pcb.F_Cu else 1
        f.BuildCourtyardCaches()
        cy = f.GetCourtyard(pcb.F_CrtYd if side == 0 else pcb.B_CrtYd)
        if cy.OutlineCount():
            bb = cy.BBox()
            box = (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom())
        else:
            box = (np.nan,) * 4
        p = f.GetPosition()
        FP.append((str(f.GetReference()), p.x, p.y, f.GetOrientationDegrees(), side) + box + (str(f.GetFPID().GetLibItemName()),))
        for pd in f.Pads():
            q, bb, sz = pd.GetPosition(), pd.GetBoundingBox(), pd.GetSize(pcb.F_Cu)
            mask = (1 if pd.IsOnLayer(pcb.F_Cu) else 0) | (2 if pd.IsOnLayer(pcb.B_Cu) else 0)
            PD.append((i, str(pd.GetNumber()), q.x, q.y, bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom(), pd.GetNetCode(),
                       pd.GetAttribute() == pcb.PAD_ATTRIB_SMD, pd.GetOrientationDegrees(), shape_map.get(pd.GetShape(), 4),
                       sz.x, sz.y, mask))
        r = f.Reference()
        rl = r.GetLayer()
        lay = 0 if rl == pcb.F_SilkS else 1 if rl == pcb.B_SilkS else 2 if rl == pcb.F_Fab else 3
        rp = r.GetPosition()
        RT.append((rp.x, rp.y, r.GetTextHeight(), r.GetTextWidth(), r.GetTextThickness(), r.GetTextAngleDegrees(), lay,
                   rl == pcb.F_SilkS and r.IsVisible(), i))
    if FP:
        c = lambda k: np.array([row[k] for row in FP], np.float64)
        x, y = to_due(c(1) * U, c(2) * U)
        cx0, cy1 = to_due(c(5) * U, c(6) * U)      # KiCad left/top  -> Due left/top (top has the larger y)
        cx1, cy0 = to_due(c(7) * U, c(8) * U)
        kw.update(fp_idx=np.arange(len(FP)), fp_ref=[row[0] for row in FP], fp_x=_r(x), fp_y=_r(y), fp_rot=_r(c(3)),
                  fp_side=c(4), fp_cx0=_r(cx0), fp_cy0=_r(cy0), fp_cx1=_r(cx1), fp_cy1=_r(cy1), fp_kind=[row[9] for row in FP])
    if PD:
        c = lambda k: np.array([row[k] for row in PD], np.float64)
        x, y = to_due(c(2) * U, c(3) * U)
        bx0, by1 = to_due(c(4) * U, c(5) * U)
        bx1, by0 = to_due(c(6) * U, c(7) * U)
        kw.update(p_fp=c(0), p_pin=[row[1] for row in PD], p_x=_r(x), p_y=_r(y), p_bx0=_r(bx0), p_by0=_r(by0), p_bx1=_r(bx1),
                  p_by1=_r(by1), p_net=c(8), p_smd=c(9), p_rot=_r(c(10)), p_shape=c(11), p_sx=_r(c(12) * U), p_sy=_r(c(13) * U),
                  p_layer_mask=c(14))
    if RT:
        c = lambda k: np.array([row[k] for row in RT], np.float64)
        x, y = to_due(c(0) * U, c(1) * U)
        kw.update(r_x=_r(x), r_y=_r(y), r_h=_r(c(2) * U), r_w=_r(c(3) * U), r_t=_r(c(4) * U), r_ang=_r(c(5)), r_layer=c(6),
                  r_on_silk=c(7), r_fp=c(8))

    # board-level silk text
    T = [(str(d.GetText()), d.GetPosition().x, d.GetPosition().y, d.GetTextHeight()) for d in b.Drawings()
         if d.GetClass() == 'PCB_TEXT' and d.GetLayer() == pcb.F_SilkS]
    if T:
        x, y = to_due(np.array([t[1] for t in T]) * U, np.array([t[2] for t in T]) * U)
        kw.update(t_text=[t[0] for t in T], t_x=_r(x), t_y=_r(y), t_h=_r(np.array([t[3] for t in T]) * U))

    # zones: filled outlines and their holes, as rings
    zl, zn, zf, xy, roff, voff, rhole = [], [], [], [], [0], [0], []
    for z in b.Zones():
        lay = z.GetLayer()
        zl.append(_layer(pcb, lay)); zn.append(z.GetNetCode()); zf.append(bool(z.IsFilled()))
        if z.IsFilled():
            ps = z.GetFilledPolysList(lay)
            for k in range(ps.OutlineCount()):
                rings = [(0, ps.Outline(k))] + [(1, ps.Hole(k, h)) for h in range(ps.HoleCount(k))]
                for hole, ch in rings:
                    pts = [(ch.CPoint(j).x, ch.CPoint(j).y) for j in range(ch.PointCount())]
                    xy.extend(pts)
                    voff.append(voff[-1] + len(pts))
                    rhole.append(hole)
        roff.append(len(voff) - 1)
    if zl:
        a = np.array(xy, np.float64).reshape(-1, 2) * U
        x, y = to_due(a[:, 0], a[:, 1])
        kw.update(z_layer=zl, z_net=zn, z_filled=zf, z_xy=np.column_stack([_r(x), _r(y)]), z_ring_off=roff, z_vert_off=voff, z_ring_hole=rhole)

    # outline: the Edge.Cuts polygon(s), concatenated outer rings (a single ring on these boards)
    ps = pcb.SHAPE_POLY_SET()
    ring = []
    if b.GetBoardPolygonOutlines(ps, False) and ps.OutlineCount():
        ch = ps.Outline(0)
        ring = [(ch.CPoint(j).x * U, ch.CPoint(j).y * U) for j in range(ch.PointCount())]
    if ring:
        a = np.array(ring)
        x, y = to_due(a[:, 0], a[:, 1])
        kw['outline'] = np.column_stack([_r(x), _r(y)])
    return BoardArrays(path=path, copper_layers=b.GetCopperLayerCount(), nets=nets, **kw)


LAST_ATTEMPTS = {'n': 0}        # attempts the last read_board_retry used (1 = first try); anything above 1 is a finding to report


def read_board_retry(path, tries=3, timeout=120):
    """read_board in a short child process (pcbnew segfaults intermittently at start-up), via an .npz in a scratch dir.
    Retries on a signal death up to `tries` times; raises RuntimeError with the child's stderr otherwise."""
    import tempfile
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.abspath(path)          # the child runs in `here`: a path relative to the caller's cwd would not be found there
    last = ''
    for attempt in range(tries):
        with tempfile.TemporaryDirectory(dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.scratch')
                                         if os.path.isdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.scratch')) else None) as d:
            out = os.path.join(d, 'b.npz')
            p = subprocess.run([sys.executable, '-m', 'pcbtools.boardio', str(path), out], cwd=here, capture_output=True,
                               text=True, timeout=timeout)
            if p.returncode == 0:
                LAST_ATTEMPTS['n'] = attempt + 1
                if attempt:
                    print(f'read_board_retry: attempt {attempt + 1} of {tries} succeeded after {attempt} signal death(s) '
                          '(pcbnew start-up segfault): a finding, not a cost', file=sys.stderr)
                return load_npz(out)
            last = f'rc={p.returncode}\n{p.stderr[-2000:]}'
            if p.returncode >= 0:      # a real error, not a signal death: do not retry
                break
    raise RuntimeError(f'read_board failed after {attempt + 1} attempt(s): {last}')


if __name__ == '__main__':       # python -m pcbtools.boardio BOARD.kicad_pcb OUT.npz
    save_npz(read_board(sys.argv[1]), sys.argv[2])
