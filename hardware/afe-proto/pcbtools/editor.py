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

    def set_ref_pose(self, ref, x, y, angle):
        """move and rotate the designator text only (position in Due mm, angle in degrees); layer, size and visibility stay"""
        r = self._fp(ref).Reference()
        r.SetPosition(self._pt(x, y))
        r.SetTextAngleDegrees(float(angle))

    def add_text(self, text, x, y, h=1.0, layer='F.SilkS', t=0.15):
        tx = self.pcb.PCB_TEXT(self.b)
        tx.SetText(str(text))
        tx.SetLayer(self.b.GetLayerID(layer))
        tx.SetPosition(self._pt(x, y))
        tx.SetTextSize(self.pcb.VECTOR2I(self.pcb.FromMM(float(h)), self.pcb.FromMM(float(h))))
        tx.SetTextThickness(self.pcb.FromMM(float(t)))
        if layer.startswith('B.'):
            tx.SetMirrored(True)                          # read from the back
        self.b.Add(tx)
        self._give(tx)

    def add_box(self, rect, layer='F.SilkS', filled=True, t=0.15):
        """a rectangle in Due mm (x0, y0, x1, y1), filled or outlined, on a graphic layer (the S/N box)"""
        s = self.pcb.PCB_SHAPE(self.b)
        s.SetShape(self.pcb.SHAPE_T_RECT)
        s.SetLayer(self.b.GetLayerID(layer))
        x0, y0, x1, y1 = rect
        s.SetStart(self._pt(x0, y1))
        s.SetEnd(self._pt(x1, y0))
        s.SetFilled(bool(filled))
        s.SetWidth(self.pcb.FromMM(float(t)))
        self.b.Add(s)
        self._give(s)

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
        """vias at (x, y), Due mm. NB: KiCad gives a via that lands on a pad the PAD's net when the board is saved and read
        back, whatever net was asked for: place vias off other nets' pads."""
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

    def pour(self, net='GND', layer='B', rect=None, clearance=0.25):
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
        z.SetMinThickness(self.pcb.FromMM(0.2))
        z.SetPadConnection(self.pcb.ZONE_CONNECTION_FULL)     # solid to pads: small fine-pitch GND pads starve on spokes
        z.SetThermalReliefGap(self.pcb.FromMM(0.25))
        z.SetThermalReliefSpokeWidth(self.pcb.FromMM(0.3))
        z.SetIslandRemovalMode(self.pcb.ISLAND_REMOVAL_MODE_ALWAYS)
        for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            z.AppendCorner(self._pt(px, py), -1)
        self.b.Add(z)
        self._give(z)
        self.fill_zones()
        return z

    def set_outline(self, rect, width=0.1):
        """Edge.Cuts replaced by the rectangle `rect` = (x0, y0, x1, y1) in Due mm: every Edge.Cuts drawing is removed and four
        segments added"""
        for d in [d for d in self.b.GetDrawings() if d.GetLayer() == self.pcb.Edge_Cuts]:
            self.b.RemoveNative(d)
        x0, y0, x1, y1 = rect
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        for a_, b_ in zip(pts, pts[1:] + pts[:1]):
            s = self.pcb.PCB_SHAPE(self.b)
            s.SetShape(self.pcb.SHAPE_T_SEGMENT)
            s.SetStart(self._pt(*a_))
            s.SetEnd(self._pt(*b_))
            s.SetLayer(self.pcb.Edge_Cuts)
            s.SetWidth(self.pcb.FromMM(float(width)))
            self.b.Add(s)
            self._give(s)

    def keepout(self, rect, name='keepout', tracks=True, vias=True, pour=True, layers='all'):
        """a rule area over `rect` = (x0, y0, x1, y1) in Due mm on every copper layer (layers='all') or on 'F' or 'B' only: no tracks,
        no vias, no copper pour (each switchable); pads and footprints are allowed. KiCad's DRC reports anything inside it as a
        keepout violation, and a router that reads the board (Specctra export) keeps out of it"""
        z = self.pcb.ZONE(self.b)
        z.SetIsRuleArea(True)
        if layers == 'all':
            ls = self.pcb.LSET.AllCuMask()
        else:
            ls = self.pcb.LSET()
            ls.AddLayer(self._layer(layers))
        z.SetLayerSet(ls)
        z.SetDoNotAllowTracks(bool(tracks))
        z.SetDoNotAllowVias(bool(vias))
        z.SetDoNotAllowZoneFills(bool(pour))
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        z.SetZoneName(name)
        x0, y0, x1, y1 = rect
        for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            z.AppendCorner(self._pt(px, py), -1)
        self.b.Add(z)
        self._give(z)
        return z

    def pad_xy(self, ref, pin):
        """centre of pad `pin` of `ref` in Due mm (the last pad of that number, as boardio reads it)"""
        hit = [p for p in self._fp(ref).Pads() if p.GetNumber() == str(pin)]
        if not hit:
            raise KeyError(f'{ref}.{pin}: no such pad')
        c = hit[-1].GetPosition()
        x, y = boardio.to_due(self.pcb.ToMM(c.x), self.pcb.ToMM(c.y))
        return float(x), float(y)

    def stub_via(self, net, ref, pin, dx, dy, w=0.3, dia=0.6, drill=0.3, layer='F'):
        """a stub from the centre of pad (ref, pin) to the point (dx, dy) away from it, and a via at its end: what the old
        router gave every GND pad so the plane on the other layer could take it. The point is the caller's: nothing here
        searches for free copper."""
        x, y = self.pad_xy(ref, pin)
        self.add_tracks(net, layer, [x], [y], [x + dx], [y + dy], w)
        self.add_vias(net, [x + dx], [y + dy], dia, drill)
        return x + dx, y + dy

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
