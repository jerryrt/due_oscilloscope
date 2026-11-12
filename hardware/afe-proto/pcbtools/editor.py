"""editor.py: the one write path for a .kicad_pcb.

    with edit(path) as e:                       # loads once, saves on a clean exit, frees in one place
        e.move('R303', 80.0, 6.9, 180)
        e.add_tracks('AWG_OUT', 'F', x0, y0, x1, y1, 0.25)
        e.remove_tracks(arrays.s_idx[mask])     # indices from BoardArrays: positions in board.GetTracks()

Coordinates are Due mm (x right, y up), converted by boardio.to_due/from_due (the one transform). Item indices
(`s_idx`, `a_idx`, `v_idx`, `fp_idx`) are the positions the reader recorded; they stay valid for the whole edit() because
the editor takes its snapshot of the enumeration on entry and additions only append.

Lifetime. The editor holds the board, the snapshot, every removed item and every other board it copied from until the
`with` block ends, then drops the Python references and the board in one place. Every item added to the board is handed
over (`thisown = False`): the board owns it from `Add`, and a second free by the Python wrapper corrupts the heap. A removed
item is taken off the board with RemoveNative (plain Remove makes Python own it and corrupts the module state). Nothing is kept at module level. A block that raises writes nothing.
"""
from __future__ import annotations

import contextlib
import gc

import numpy as np

from . import boardio

_LAYERS = {0: 'F.Cu', 1: 'B.Cu', 'F': 'F.Cu', 'B': 'B.Cu', 'F.Cu': 'F.Cu', 'B.Cu': 'B.Cu'}


def _pcb():
    import pcbnew
    return pcbnew


class Editor:
    def __init__(self, board, pcb):
        self.b = board
        self.pcb = pcb
        self._tracks = list(board.GetTracks())          # snapshot: index -> item, valid for the whole edit
        self._fps = list(board.GetFootprints())
        self._removed = []                               # kept alive until the block ends
        self._bases = {}                                 # path -> board, kept alive until the block ends
        self._added = []

    # ------------------------------------------------------------------ helpers
    def _pt(self, x, y):
        kx, ky = boardio.from_due(x, y)
        return self.pcb.VECTOR2I(self.pcb.FromMM(float(kx)), self.pcb.FromMM(float(ky)))

    def _give(self, item):
        """hand a new item to the board: after board.Add() the board owns it, so the Python wrapper must not free it again
        (a double free corrupts the heap and shows up later as a SwigPyObject where a BOARD should be)"""
        item.thisown = False
        self._added.append(item)
        return item

    def _fp(self, ref):
        f = self.b.FindFootprintByReference(ref)
        if f is None:
            raise KeyError(f'no footprint {ref}')
        return f

    def _net(self, name):
        for cand in (name, '/' + name):
            n = self.b.FindNet(cand)
            if n is not None:
                return n
        raise KeyError(f'no net {name}')

    def _layer(self, layer):
        try:
            return self.b.GetLayerID(_LAYERS[layer])
        except KeyError:
            return self.b.GetLayerID(layer)

    # ------------------------------------------------------------------ parts and text
    def move(self, ref, x, y, rot=None, side=None):
        """centre (Due mm), rotation in degrees, side 0 = F / 1 = B (flip only when it differs)"""
        f = self._fp(ref)
        f.SetPosition(self._pt(x, y))
        if rot is not None:
            f.SetOrientationDegrees(float(rot))
        if side is not None and int(side) != int(f.GetLayer() == self.pcb.B_Cu):
            f.Flip(f.GetPosition(), False)

    def set_ref(self, ref, x, y, h=1.0, w=None, t=0.15, on_silk=True):
        """the designator text: absolute position (Due mm), height h, width w (default h), stroke t, F.SilkS or F.Fab"""
        r = self._fp(ref).Reference()
        r.SetLayer(self.pcb.F_SilkS if on_silk else self.pcb.F_Fab)
        r.SetVisible(True)
        r.SetTextSize(self.pcb.VECTOR2I(self.pcb.FromMM(float(h if w is None else w)), self.pcb.FromMM(float(h))))
        r.SetTextThickness(self.pcb.FromMM(float(t)))
        r.SetPosition(self._pt(x, y))
        r.SetTextAngleDegrees(0)

    def add_text(self, text, x, y, h=1.0, layer='F.SilkS', t=0.15):
        tx = self.pcb.PCB_TEXT(self.b)
        tx.SetText(str(text))
        tx.SetLayer(self.b.GetLayerID(layer))
        tx.SetPosition(self._pt(x, y))
        tx.SetTextSize(self.pcb.VECTOR2I(self.pcb.FromMM(float(h)), self.pcb.FromMM(float(h))))
        tx.SetTextThickness(self.pcb.FromMM(float(t)))
        self.b.Add(tx)
        self._give(tx)

    def remove_footprint(self, ref):
        """take a footprint off the board (kept alive until the block ends)"""
        f = self._fp(ref)
        self.b.RemoveNative(f)
        self._removed.append(f)

    def add_footprint_from(self, base_path, ref):
        """copy footprint `ref` (position, rotation, pads, nets by name) from another board file"""
        base = self._bases.get(base_path)
        if base is None:
            base = self._bases[base_path] = self.pcb.LoadBoard(str(base_path))
        src = base.FindFootprintByReference(ref)
        if src is None:
            raise KeyError(f'{ref} is not on {base_path}')
        d = src.Duplicate(False)
        self.b.Add(d)
        return self._give(d)

    # ------------------------------------------------------------------ copper
    def add_tracks(self, net, layer, x0, y0, x1, y1, w):
        """segments from (x0, y0) to (x1, y1), Due mm; scalars or arrays (broadcast), one net and one layer per call"""
        x0, y0, x1, y1, w = np.broadcast_arrays(*(np.atleast_1d(np.asarray(v, np.float64)) for v in (x0, y0, x1, y1, w)))
        n, lay = self._net(net), self._layer(layer)
        for i in range(x0.size):
            t = self.pcb.PCB_TRACK(self.b)
            t.SetStart(self._pt(x0[i], y0[i]))
            t.SetEnd(self._pt(x1[i], y1[i]))
            t.SetWidth(self.pcb.FromMM(float(w[i])))
            t.SetLayer(lay)
            t.SetNet(n)
            self.b.Add(t)
            self._give(t)

    def add_vias(self, net, x, y, dia=0.6, drill=0.3):
        x, y, dia, drill = np.broadcast_arrays(*(np.atleast_1d(np.asarray(v, np.float64)) for v in (x, y, dia, drill)))
        n = self._net(net)
        for i in range(x.size):
            v = self.pcb.PCB_VIA(self.b)
            v.SetPosition(self._pt(x[i], y[i]))
            v.SetWidth(self.pcb.FromMM(float(dia[i])))
            v.SetDrill(self.pcb.FromMM(float(drill[i])))
            v.SetViaType(self.pcb.VIATYPE_THROUGH)
            v.SetNet(n)
            self.b.Add(v)
            self._give(v)

    def _remove(self, idx):
        for i in np.unique(np.asarray(idx, np.int64)):
            item = self._tracks[int(i)]
            self.b.RemoveNative(item)           # not Remove(): that hands the item to Python, which then frees it without a destructor
            self._removed.append(item)

    def remove_tracks(self, idx):
        """remove the tracks / arcs at these positions of the reader's enumeration (s_idx, a_idx)"""
        self._remove(idx)

    def remove_vias(self, idx):
        """remove the vias at these positions (v_idx)"""
        self._remove(idx)

    # ------------------------------------------------------------------ zones
    def fill_zones(self):
        self.pcb.ZONE_FILLER(self.b).Fill(self.b.Zones())

    def pour(self, net='GND', layer='B', rect=None, clearance=0.2):
        """a copper pour on `layer` for `net`, filled. `rect` = (x0, y0, x1, y1) in Due mm; default: the board outline's
        bounding box. An existing zone of that net and layer is reused (only refilled)."""
        lay = self._layer(layer)
        for z in self.b.Zones():
            if z.GetLayer() == lay and z.GetNetname().lstrip('/') == net:
                self.fill_zones()
                return z
        if rect is None:
            bb = self.b.GetBoardEdgesBoundingBox()
            x0, y1 = boardio.to_due(self.pcb.ToMM(bb.GetLeft()), self.pcb.ToMM(bb.GetTop()))
            x1, y0 = boardio.to_due(self.pcb.ToMM(bb.GetRight()), self.pcb.ToMM(bb.GetBottom()))
        else:
            x0, y0, x1, y1 = rect
        z = self.pcb.ZONE(self.b)
        z.SetLayer(lay)
        z.SetNet(self._net(net))
        z.SetLocalClearance(self.pcb.FromMM(float(clearance)))
        for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            z.AppendCorner(self._pt(px, py), -1)
        self.b.Add(z)
        self._give(z)
        self.fill_zones()
        return z

    def _release(self):
        """drop everything in the order that keeps pcbnew's objects valid: removed and added items first, board last"""
        self._removed.clear()
        self._added.clear()
        self._tracks = []
        self._fps = []
        self._bases.clear()
        self.b = None


@contextlib.contextmanager
def edit(path, out=None):
    """load `path` once, yield an Editor, save to `out` (default: in place) on a clean exit, free in one place."""
    pcb = _pcb()
    b = pcb.LoadBoard(str(path))
    if b is None:
        raise IOError(f'pcbnew cannot load {path}')
    e = Editor(b, pcb)
    try:
        yield e
        pcb.SaveBoard(str(out or path), b)
    finally:
        e._release()
        del e, b
        gc.collect()
