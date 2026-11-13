"""Hand-built BoardArrays with known answers: no pcbnew, no files. Boards are described in Due mm."""
import types

import numpy as np

from pcbtools import boardio
from pcbtools.boards import v2


def cfg(**over):
    """the v2 config with some tables replaced (a plain namespace: rules read attributes only)"""
    d = {k: v for k, v in vars(v2).items() if k.isupper()}
    d.update(over)
    return types.SimpleNamespace(**d)


class Synth:
    def __init__(self, *nets, layers=2):
        self.nets = ('',) + tuple(nets)
        self.layers = layers
        self.fp, self.pad, self.seg, self.via, self.rt, self.silk, self.zone = [], [], [], [], [], [], []

    def n(self, name):
        return self.nets.index(name)

    def part(self, ref, x, y, box=None, rot=0.0, side=0, silk=True, h=0.8):
        """a footprint at (x, y); box = courtyard (x0, y0, x1, y1) or None; gets a designator text unless silk is None"""
        i = len(self.fp)
        self.fp.append((ref, x, y, rot, side, *(box if box else (np.nan,) * 4)))
        if silk is not None:
            self.rt.append((x, y, h, 0.8, 0.12, 0.0, 0, bool(silk), i))
        return self

    def p(self, ref, pin, x, y, net='', size=0.6, smd=True, mask=1, shape=1, sy=None, rot=0.0):
        """a pad: `size` square (or size x sy), `mask` the copper layers it reaches (bit0 F.Cu, bit1 B.Cu), `shape` as boardio
        (1 rect, 0 circle, 2 oval), `rot` degrees; the bounding box follows the rotation"""
        i = [f[0] for f in self.fp].index(ref)
        sy = size if sy is None else sy
        a = np.radians(rot)
        hx = (abs(np.cos(a)) * size + abs(np.sin(a)) * sy) / 2
        hy = (abs(np.sin(a)) * size + abs(np.cos(a)) * sy) / 2
        self.pad.append((i, pin, x, y, x - hx, y - hy, x + hx, y + hy, self.n(net) if net else 0, smd, mask, shape, size, sy, rot))
        return self

    def s(self, net, layer, x0, y0, x1, y1, w=0.2):
        self.seg.append((self.n(net) if net else 0, 0 if layer == 'F' else 1, x0, y0, x1, y1, w))
        return self

    def v(self, net, x, y):
        self.via.append((self.n(net) if net else 0, x, y))
        return self

    def z(self, net, layer, rings, filled=True):
        self.zone.append((self.n(net), 0 if layer == 'F' else 1, filled, rings))
        return self

    def text(self, t, x=0, y=0):
        self.silk.append((t, x, y, 1.0))
        return self

    def build(self):
        kw = dict(path='synthetic', copper_layers=self.layers, nets=self.nets)
        if self.seg:
            c = lambda k: [r[k] for r in self.seg]
            kw.update(s_idx=np.arange(len(self.seg)), s_net=c(0), s_layer=c(1), s_x0=c(2), s_y0=c(3), s_x1=c(4), s_y1=c(5), s_w=c(6))
        if self.via:
            kw.update(v_idx=np.arange(len(self.seg), len(self.seg) + len(self.via)), v_net=[r[0] for r in self.via],
                      v_x=[r[1] for r in self.via], v_y=[r[2] for r in self.via], v_dia=0.6, v_drill=0.3)
            kw['v_dia'] = [0.6] * len(self.via)
            kw['v_drill'] = [0.3] * len(self.via)
        if self.fp:
            c = lambda k: [r[k] for r in self.fp]
            kw.update(fp_idx=np.arange(len(self.fp)), fp_ref=c(0), fp_x=c(1), fp_y=c(2), fp_rot=c(3), fp_side=c(4), fp_cx0=c(5),
                      fp_cy0=c(6), fp_cx1=c(7), fp_cy1=c(8), fp_kind=['X'] * len(self.fp))
        if self.pad:
            c = lambda k: [r[k] for r in self.pad]
            n = len(self.pad)
            kw.update(p_fp=c(0), p_pin=c(1), p_x=c(2), p_y=c(3), p_bx0=c(4), p_by0=c(5), p_bx1=c(6), p_by1=c(7), p_net=c(8),
                      p_smd=c(9), p_rot=c(14), p_shape=c(11), p_sx=c(12), p_sy=c(13), p_layer_mask=c(10))
        if self.rt:
            c = lambda k: [r[k] for r in self.rt]
            kw.update(r_x=c(0), r_y=c(1), r_h=c(2), r_w=c(3), r_t=c(4), r_ang=c(5), r_layer=c(6), r_on_silk=c(7), r_fp=c(8))
        if self.silk:
            kw.update(t_text=[t[0] for t in self.silk], t_x=[t[1] for t in self.silk], t_y=[t[2] for t in self.silk], t_h=[t[3] for t in self.silk])
        if self.zone:
            roff, voff, hole, xy = [0], [0], [], []
            for _, _, _, rings in self.zone:
                for ring, is_hole in rings:
                    xy.extend(ring)
                    voff.append(voff[-1] + len(ring))
                    hole.append(int(is_hole))
                roff.append(len(hole))
            kw.update(z_net=[z[0] for z in self.zone], z_layer=[z[1] for z in self.zone], z_filled=[z[2] for z in self.zone],
                      z_xy=xy, z_ring_off=roff, z_vert_off=voff, z_ring_hole=hole)
        return boardio.BoardArrays(**kw)
