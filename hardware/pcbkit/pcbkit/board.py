"""Board I/O: the only module that imports pcbnew (lazily, inside read_board), and the BoardArrays container.

    read_board(path, cfg) -> BoardArrays        loads the board once, copies it into numpy arrays, frees it
    to_frame / from_frame                       the one KiCad-mm <-> board-frame-mm transform, from FRAME = (OX, OY)
    save_npz / load_npz                         cache of a BoardArrays, readable without pcbnew
    read_board_retry(path, cfg)                 read_board in a short child process, retried on a start-up segfault

The frame is the configuration's FRAME = (OX, OY): board_x = OX + x, board_y = OY - y, so x is KiCad's x less OX and y points up.
FRAME is a project name and is REQUIRED: a read with no configuration, or one without FRAME, raises ValueError naming FRAME. A project that
wants KiCad's own origin passes `KICAD_FRAME` = (0.0, 0.0) explicitly (x as KiCad has it, y flipped to point up: board_y = 0 - y).

Conventions (ARRAYS.md): frame mm, y up; float64 rounded to
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

from .config import declare

declare('board', ['FRAME'])
KICAD_FRAME = (0.0, 0.0)    # KiCad's own origin: board_x = OX + x, board_y = OY - y with OX = OY = 0, so y points up. Never a default: FRAME is required
ND = 6                      # decimals: 1e-6 mm

# (name, kind). kinds: f8 i4 i1 u1 i8 ? = numpy dtypes, S = tuple of str, xy = float64 (N,2)
_F = 'f8'
SPEC = {
    'outline': [('outline', 'xy')],
    'segments': [('s_idx', 'i4')] + [(n, _F) for n in ('s_x0', 's_y0', 's_x1', 's_y1', 's_w')] + [('s_layer', 'i1'), ('s_net', 'i4')],
    'arcs': [('a_idx', 'i4')] + [(n, _F) for n in ('a_x0', 'a_y0', 'a_xm', 'a_ym', 'a_x1', 'a_y1', 'a_w')] + [('a_layer', 'i1'), ('a_net', 'i4')],
    'vias': [('v_idx', 'i4')] + [(n, _F) for n in ('v_x', 'v_y', 'v_dia', 'v_drill')] + [('v_net', 'i4')],
    'footprints': [('fp_idx', 'i4'), ('fp_ref', 'S')] + [(n, _F) for n in ('fp_x', 'fp_y', 'fp_rot')] + [('fp_side', 'i1')]
                  + [(n, _F) for n in ('fp_cx0', 'fp_cy0', 'fp_cx1', 'fp_cy1')] + [('fp_kind', 'S')]
                  + [(n, _F) for n in ('fp_fab_x0', 'fp_fab_y0', 'fp_fab_x1', 'fp_fab_y1')],
    'fpsilk': [('fs_fp', 'i4')] + [(n, _F) for n in ('fs_x0', 'fs_y0', 'fs_x1', 'fs_y1')] + [('fs_kind', 'S')],
    'gsilk': [(n, _F) for n in ('g_x0', 'g_y0', 'g_x1', 'g_y1')] + [('g_kind', 'S')],
    'pads': [('p_fp', 'i4'), ('p_pin', 'S')] + [(n, _F) for n in ('p_x', 'p_y', 'p_bx0', 'p_by0', 'p_bx1', 'p_by1')]
            + [('p_net', 'i4'), ('p_smd', '?'), ('p_rot', _F), ('p_shape', 'i1'), ('p_sx', _F), ('p_sy', _F), ('p_layer_mask', 'u1')],
    'reftext': [(n, _F) for n in ('r_x', 'r_y', 'r_h', 'r_w', 'r_t', 'r_ang')] + [('r_layer', 'i1'), ('r_on_silk', '?'), ('r_fp', 'i4'),
                                                                                     ('r_hide', '?'), ('r_just', 'S')],
    'silk': [('t_text', 'S')] + [(n, _F) for n in ('t_x', 't_y', 't_h')]
            + [(n, _F) for n in ('t_ang', 't_stroke', 't_x0', 't_y0', 't_x1', 't_y1')] + [('t_hide', '?'), ('t_layer', 'i1'), ('t_just', 'S')],
    'zones': [('z_layer', 'i1'), ('z_net', 'i4'), ('z_filled', '?'), ('z_keepout', '?')],
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

# Fields added after the first release of the arrays. A board built by hand, or an npz cache written before them, leaves them
# EMPTY (length 0), which means "not read": the group-length check lets them be empty, and a consumer that needs one checks len().
_ADDED = frozenset({'fp_fab_x0', 'fp_fab_y0', 'fp_fab_x1', 'fp_fab_y1', 'r_hide', 'r_just', 't_ang', 't_stroke', 't_x0', 't_y0', 't_x1', 't_y1',
                    't_hide', 't_layer', 't_just'})
# every name added after the first release, groups of their own included: a project that must keep its recorded array set (the AFE's
# cached fixtures hold the first one) filters _ALL, KIND and SPEC by it
LATER_FIELDS = frozenset(_ADDED) | {n for g in ('fpsilk', 'gsilk') for n, _ in SPEC[g]}


def _post_init(self):
    if len(self.z_keepout) == 0 and len(self.z_layer):          # a cache or a hand-built board from before z_keepout: no zone is a rule area
        object.__setattr__(self, 'z_keepout', np.zeros(len(self.z_layer), bool))
    for name, kind in _ALL:
        object.__setattr__(self, name, _coerce(kind, getattr(self, name)))
    object.__setattr__(self, 'nets', tuple(str(x) for x in self.nets))
    object.__setattr__(self, 'read_fields', frozenset(self.read_fields))
    for g, fields in SPEC.items():
        if g == 'outline':
            continue
        ns = {len(getattr(self, n)) for n, _ in fields if not (n in _ADDED and len(getattr(self, n)) == 0)}
        if len(ns) > 1:
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
              ('nets', tuple, dataclasses.field(default=('',))),
              ('read_fields', frozenset, dataclasses.field(default=frozenset()))]      # which LATER_FIELDS a read filled (see require)
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


# ----------------------------------------------------------------------------------------------- fields that may not have been read
class FieldNotRead(LookupError):
    """a consumer asked for an array the board's reader did not fill"""


def require(b, *fields):
    """Raise FieldNotRead, naming the field, unless every named field was filled by the read that made `b` (b.read_fields). Fields
    of the first release are always there; the LATER_FIELDS are there only for a board read by pcbkit.board.read_board (or an npz
    cache of one). Every pcbkit consumer of a later field calls this first: an empty array is "not read", never "no rows"."""
    for f in fields:
        if f not in KIND:
            raise ValueError(f'unknown board field {f!r}')
        if f in LATER_FIELDS and f not in b.read_fields:
            raise FieldNotRead(f'board field {f!r} was not read: this board did not come from pcbkit.board.read_board (read it with '
                               f'pcbkit.board.read_board(path, cfg), not a binding that keeps the first release\'s arrays)')


def fab_boxes(b):
    """(n, 4) the F.Fab body box of every footprint, x0, y0, x1, y1, NaN for one with none"""
    require(b, 'fp_fab_x0', 'fp_fab_y0', 'fp_fab_x1', 'fp_fab_y1')
    return np.column_stack([b.fp_fab_x0, b.fp_fab_y0, b.fp_fab_x1, b.fp_fab_y1]) if len(b.fp_fab_x0) else np.zeros((0, 4))


def footprint_silk(b):
    """(owner rows, (m, 4) boxes, kinds) of the F.SilkS graphics of the footprints"""
    require(b, 'fs_fp', 'fs_x0', 'fs_y0', 'fs_x1', 'fs_y1', 'fs_kind')
    return b.fs_fp, np.column_stack([b.fs_x0, b.fs_y0, b.fs_x1, b.fs_y1]) if len(b.fs_fp) else np.zeros((0, 4)), b.fs_kind


def board_silk_graphics(b):
    """((m, 4) boxes, kinds) of the board-level F.SilkS shapes"""
    require(b, 'g_x0', 'g_y0', 'g_x1', 'g_y1', 'g_kind')
    return (np.column_stack([b.g_x0, b.g_y0, b.g_x1, b.g_y1]) if len(b.g_kind) else np.zeros((0, 4))), b.g_kind


def text_boxes(b):
    """(n, 4) the rendered box of every board-level silk text"""
    require(b, 't_x0', 't_y0', 't_x1', 't_y1')
    return np.column_stack([b.t_x0, b.t_y0, b.t_x1, b.t_y1]) if len(b.t_text) else np.zeros((0, 4))


# ----------------------------------------------------------------------------------------------- the transform
def frame_of(cfg):
    """the (OX, OY) a configuration names: a 2-sequence is the frame itself; otherwise `cfg.FRAME` or `cfg['FRAME']`. No configuration
    (None) or one without FRAME raises ValueError naming FRAME: there is no default frame (KICAD_FRAME is for a project to pass)."""
    if cfg is None:
        fr = None
    elif isinstance(cfg, (tuple, list)) and len(cfg) == 2:
        fr = cfg
    elif isinstance(cfg, dict):
        fr = cfg.get('FRAME')
    else:
        fr = getattr(cfg, 'FRAME', None)
    if fr is None:
        raise ValueError('no FRAME = (OX, OY) in the configuration: board.read_board does not guess the project\'s coordinate frame '
                         '(pass pcbkit.board.KICAD_FRAME for KiCad\'s own axes)')
    ox, oy = fr
    return float(ox), float(oy)


def to_frame(x, y, frame):
    """KiCad mm -> frame mm (arrays or scalars). The only place the transform is written."""
    return np.asarray(x, np.float64) - frame[0], frame[1] - np.asarray(y, np.float64)


def from_frame(x, y, frame):
    """frame mm -> KiCad mm; the inverse of to_frame"""
    return np.asarray(x, np.float64) + frame[0], frame[1] - np.asarray(y, np.float64)


def _r(a):
    return np.round(np.asarray(a, np.float64), ND) + 0.0      # + 0.0 turns -0.0 into 0.0


# ----------------------------------------------------------------------------------------------- npz cache
def save_npz(b, path):
    d = {'__path': np.array(b.path), '__copper_layers': np.array(b.copper_layers), '__nets': np.array(b.nets, dtype=str),
         '__read_fields': np.array(sorted(b.read_fields), dtype=str)}
    for n, k in _ALL:
        v = getattr(b, n)
        d[n] = np.array(v, dtype=str) if k == 'S' else v
    np.savez_compressed(path, **d)


def load_npz(path):
    with np.load(path, allow_pickle=False) as z:
        kw = dict(path=str(z['__path']), copper_layers=int(z['__copper_layers']), nets=tuple(z['__nets'].tolist()),
                  read_fields=frozenset(z['__read_fields'].tolist()) if '__read_fields' in z.files else frozenset())
        for n, k in _ALL:
            if n not in z.files:             # additive fields: an older cache lacks them (z_keepout -> all False, by _post_init)
                continue
            kw[n] = tuple(z[n].tolist()) if k == 'S' else z[n]
    return BoardArrays(**kw)


# ----------------------------------------------------------------------------------------------- pcbnew side
def _layer(pcb, lay, name_map=None):
    if lay == pcb.F_Cu:
        return 0
    if lay == pcb.B_Cu:
        return 1
    return 2


_JUST = {}


def _just(pcb, t):
    """horizontal justification of a text as 'left' | 'center' | 'right'"""
    if not _JUST:
        _JUST.update({pcb.GR_TEXT_H_ALIGN_LEFT: 'left', pcb.GR_TEXT_H_ALIGN_CENTER: 'center', pcb.GR_TEXT_H_ALIGN_RIGHT: 'right'})
    return _JUST.get(t.GetHorizJustify(), 'center')


_SHAPE_KINDS = {}


def _init_kinds(pcb):
    _SHAPE_KINDS.update({pcb.SHAPE_T_SEGMENT: 'segment', pcb.SHAPE_T_RECT: 'rect', pcb.SHAPE_T_ARC: 'arc', pcb.SHAPE_T_CIRCLE: 'circle',
                         pcb.SHAPE_T_POLY: 'poly'})


def read_board(path, cfg):
    """Load `path` with pcbnew once, copy everything into BoardArrays in the configuration's frame, delete the board, return."""
    frame = frame_of(cfg)
    import gc
    import pcbnew as pcb
    assert pcb.pcbIUScale.IU_PER_MM == 1e6
    _init_kinds(pcb)
    b = pcb.LoadBoard(str(path))
    if b is None:
        raise IOError(f'pcbnew cannot load {path}')
    try:
        out = _extract(pcb, b, str(path), frame)
    finally:
        del b
        gc.collect()
    return out


def _extract(pcb, b, path, frame):
    U = 1e-6
    to_f = lambda x, y: to_frame(x, y, frame)      # the arrays are in the frame
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
        x0, y0 = to_f(S[:, 1] * U, S[:, 2] * U)
        x1, y1 = to_f(S[:, 3] * U, S[:, 4] * U)
        kw.update(s_idx=S[:, 0], s_x0=_r(x0), s_y0=_r(y0), s_x1=_r(x1), s_y1=_r(y1), s_w=_r(S[:, 5] * U), s_layer=S[:, 6], s_net=S[:, 7])
    if len(A):
        x0, y0 = to_f(A[:, 1] * U, A[:, 2] * U)
        xm, ym = to_f(A[:, 3] * U, A[:, 4] * U)
        x1, y1 = to_f(A[:, 5] * U, A[:, 6] * U)
        kw.update(a_idx=A[:, 0], a_x0=_r(x0), a_y0=_r(y0), a_xm=_r(xm), a_ym=_r(ym), a_x1=_r(x1), a_y1=_r(y1),
                  a_w=_r(A[:, 7] * U), a_layer=A[:, 8], a_net=A[:, 9])
    if len(V):
        x, y = to_f(V[:, 1] * U, V[:, 2] * U)
        kw.update(v_idx=V[:, 0], v_x=_r(x), v_y=_r(y), v_dia=_r(V[:, 3] * U), v_drill=_r(V[:, 4] * U), v_net=V[:, 5])

    # footprints, pads, reference text
    FP, PD, RT, FS = [], [], [], []
    BOX = lambda bb: (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom())      # KiCad nm, y down
    fab_box = []
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
        fab = pcb.BOX2I()                              # the body: every F.Fab SHAPE (text on that layer is a label, not the part: it is not printed)
        for g in f.GraphicalItems():
            lay_ = g.GetLayer()
            if lay_ == pcb.F_Fab and g.GetClass() == 'PCB_SHAPE':
                fab.Merge(g.GetBoundingBox())
            elif lay_ == pcb.F_SilkS:
                FS.append((i, _SHAPE_KINDS.get(g.GetShape(), 'other') if g.GetClass() == 'PCB_SHAPE' else 'text') + BOX(g.GetBoundingBox()))
        fab_box.append(BOX(fab) if fab.GetWidth() or fab.GetHeight() else (np.nan,) * 4)
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
                   rl == pcb.F_SilkS and r.IsVisible(), i, not r.IsVisible(), _just(pcb, r)))
    if FP:
        c = lambda k: np.array([row[k] for row in FP], np.float64)
        x, y = to_f(c(1) * U, c(2) * U)
        cx0, cy1 = to_f(c(5) * U, c(6) * U)      # KiCad left/top  -> frame left/top (top has the larger y)
        cx1, cy0 = to_f(c(7) * U, c(8) * U)
        kw.update(fp_idx=np.arange(len(FP)), fp_ref=[row[0] for row in FP], fp_x=_r(x), fp_y=_r(y), fp_rot=_r(c(3)),
                  fp_side=c(4), fp_cx0=_r(cx0), fp_cy0=_r(cy0), fp_cx1=_r(cx1), fp_cy1=_r(cy1), fp_kind=[row[9] for row in FP])
        fb = np.array(fab_box, np.float64) * U
        fx0, fy1 = to_f(fb[:, 0], fb[:, 1])
        fx1, fy0 = to_f(fb[:, 2], fb[:, 3])
        kw.update(fp_fab_x0=_r(fx0), fp_fab_y0=_r(fy0), fp_fab_x1=_r(fx1), fp_fab_y1=_r(fy1))
    if PD:
        c = lambda k: np.array([row[k] for row in PD], np.float64)
        x, y = to_f(c(2) * U, c(3) * U)
        bx0, by1 = to_f(c(4) * U, c(5) * U)
        bx1, by0 = to_f(c(6) * U, c(7) * U)
        kw.update(p_fp=c(0), p_pin=[row[1] for row in PD], p_x=_r(x), p_y=_r(y), p_bx0=_r(bx0), p_by0=_r(by0), p_bx1=_r(bx1),
                  p_by1=_r(by1), p_net=c(8), p_smd=c(9), p_rot=_r(c(10)), p_shape=c(11), p_sx=_r(c(12) * U), p_sy=_r(c(13) * U),
                  p_layer_mask=c(14))
    if RT:
        c = lambda k: np.array([row[k] for row in RT], np.float64)
        x, y = to_f(c(0) * U, c(1) * U)
        kw.update(r_x=_r(x), r_y=_r(y), r_h=_r(c(2) * U), r_w=_r(c(3) * U), r_t=_r(c(4) * U), r_ang=_r(c(5)), r_layer=c(6),
                  r_on_silk=c(7), r_fp=c(8), r_hide=c(9), r_just=[row[10] for row in RT])

    if FS:
        a = np.array([row[2:] for row in FS], np.float64) * U
        x0, y1 = to_f(a[:, 0], a[:, 1])
        x1, y0 = to_f(a[:, 2], a[:, 3])
        kw.update(fs_fp=[row[0] for row in FS], fs_x0=_r(x0), fs_y0=_r(y0), fs_x1=_r(x1), fs_y1=_r(y1), fs_kind=[row[1] for row in FS])

    # board-level silk text: position, height, angle, stroke, justification, hide flag, layer and the rendered box
    T = [(str(d.GetText()), d.GetPosition().x, d.GetPosition().y, d.GetTextHeight(), d.GetTextAngleDegrees(), d.GetTextThickness(),
          not d.IsVisible(), _just(pcb, d)) + BOX(d.GetBoundingBox())
         for d in b.Drawings() if d.GetClass() == 'PCB_TEXT' and d.GetLayer() == pcb.F_SilkS]
    if T:
        x, y = to_f(np.array([t[1] for t in T]) * U, np.array([t[2] for t in T]) * U)
        a = np.array([t[8:] for t in T], np.float64) * U
        x0, y1 = to_f(a[:, 0], a[:, 1])
        x1, y0 = to_f(a[:, 2], a[:, 3])
        kw.update(t_text=[t[0] for t in T], t_x=_r(x), t_y=_r(y), t_h=_r(np.array([t[3] for t in T]) * U), t_ang=_r([t[4] for t in T]),
                  t_stroke=_r(np.array([t[5] for t in T]) * U), t_hide=[t[6] for t in T], t_layer=[0] * len(T), t_just=[t[7] for t in T],
                  t_x0=_r(x0), t_y0=_r(y0), t_x1=_r(x1), t_y1=_r(y1))

    # board-level silk graphics (gr_line, gr_rect, gr_poly, gr_arc, gr_circle): bounding box with the stroke, as pcbnew gives it
    G = [({'segment': 'line'}.get(_SHAPE_KINDS.get(d.GetShape(), 'other'), _SHAPE_KINDS.get(d.GetShape(), 'other')),) + BOX(d.GetBoundingBox())
         for d in b.Drawings() if d.GetClass() == 'PCB_SHAPE' and d.GetLayer() == pcb.F_SilkS]
    if G:
        a = np.array([g[1:] for g in G], np.float64) * U
        x0, y1 = to_f(a[:, 0], a[:, 1])
        x1, y0 = to_f(a[:, 2], a[:, 3])
        kw.update(g_x0=_r(x0), g_y0=_r(y0), g_x1=_r(x1), g_y1=_r(y1), g_kind=[g[0] for g in G])

    # zones: filled outlines and their holes, as rings
    zl, zn, zf, zk, xy, roff, voff, rhole = [], [], [], [], [], [0], [0], []
    for z in b.Zones():
        lay = z.GetLayer()
        zl.append(_layer(pcb, lay)); zn.append(z.GetNetCode()); zf.append(bool(z.IsFilled())); zk.append(bool(z.GetIsRuleArea()))
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
        x, y = to_f(a[:, 0], a[:, 1])
        kw.update(z_layer=zl, z_net=zn, z_filled=zf, z_keepout=zk, z_xy=np.column_stack([_r(x), _r(y)]), z_ring_off=roff, z_vert_off=voff, z_ring_hole=rhole)

    # outline: the Edge.Cuts polygon(s), concatenated outer rings (a single ring on these boards)
    ps = pcb.SHAPE_POLY_SET()
    ring = []
    if b.GetBoardPolygonOutlines(ps, False) and ps.OutlineCount():
        ch = ps.Outline(0)
        ring = [(ch.CPoint(j).x * U, ch.CPoint(j).y * U) for j in range(ch.PointCount())]
    if ring:
        a = np.array(ring)
        x, y = to_f(a[:, 0], a[:, 1])
        kw['outline'] = np.column_stack([_r(x), _r(y)])
    return BoardArrays(path=path, copper_layers=b.GetCopperLayerCount(), nets=nets, read_fields=frozenset(LATER_FIELDS), **kw)


LAST_ATTEMPTS = {'n': 0}        # attempts the last read_board_retry used (1 = first try); anything above 1 is a finding to report


def read_board_retry(path, cfg, tries=3, timeout=120):
    """read_board in a short child process (pcbnew segfaults intermittently at start-up), via an .npz in a scratch dir.
    Retries on a signal death up to `tries` times; raises RuntimeError with the child's stderr otherwise."""
    import tempfile
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # the directory that holds the pcbkit package
    ox, oy = frame_of(cfg)
    path = os.path.abspath(path)          # the child runs in `here`: a path relative to the caller's cwd would not be found there
    last = ''
    for attempt in range(tries):
        with tempfile.TemporaryDirectory(dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.scratch')
                                         if os.path.isdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.scratch')) else None) as d:
            out = os.path.join(d, 'b.npz')
            p = subprocess.run([sys.executable, '-m', 'pcbkit.board', str(path), out, repr(ox), repr(oy)], cwd=here, capture_output=True,
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


if __name__ == '__main__':       # python -m pcbkit.board BOARD.kicad_pcb OUT.npz [OX OY]
    if len(sys.argv) < 5:
        sys.exit('usage: python -m pcbkit.board BOARD.kicad_pcb OUT.npz OX OY (the frame is required)')
    save_npz(read_board(sys.argv[1], (float(sys.argv[3]), float(sys.argv[4]))), sys.argv[2])
