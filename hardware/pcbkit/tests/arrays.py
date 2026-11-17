"""Boards built from numbers, for the rule tests: no pcbnew, no file. Layer codes 0 = F.Cu, 1 = B.Cu."""
import numpy as np

from pcbkit import board as B


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


class Arr:
    def __init__(self, *nets, layers=2):
        self.nets = ('',) + tuple(nets)
        self.layers = layers
        self.seg, self.via, self.zone, self.fp, self.pad = [], [], [], [], []
        self.fab, self.lab, self.txt = {}, [], []

    def n(self, name):
        return self.nets.index(name)

    def s(self, net, layer, x0, y0, x1, y1, w=0.2):
        self.seg.append((x0, y0, x1, y1, w, layer, self.n(net)))
        return self

    def v(self, net, x, y, dia=0.6, drill=0.3):
        self.via.append((x, y, dia, drill, self.n(net)))
        return self

    def z(self, net, layer, rings, filled=True, keepout=False):
        """rings: list of (hole, [(x, y), ...])"""
        self.zone.append((layer, self.n(net), filled, keepout, rings))
        return self

    def part(self, ref, x, y, court=None):
        self.fp.append((ref, x, y, court if court else (np.nan,) * 4))
        return self

    def p(self, ref, pin, x, y, net, smd=True, size=0.8):
        k = [f[0] for f in self.fp].index(ref)
        h = size / 2
        self.pad.append((k, pin, x, y, x - h, y - h, x + h, y + h, self.n(net), smd, size))
        return self

    def body(self, ref, x0, y0, x1, y1):
        """the F.Fab body box of a part"""
        self.fab[ref] = (x0, y0, x1, y1)
        return self

    def label(self, ref, x, y, ang=0.0, h=1.0, silk=True, layer=0):
        """the reference text of a part (layer 0 = F.SilkS, 2 = F.Fab); `silk` False is a hidden one"""
        self.lab.append((ref, x, y, h, ang, layer, silk))
        return self

    def text(self, label, x0, y0, x1, y1):
        """a board-level silk text with its rendered box"""
        self.txt.append((label, x0, y0, x1, y1))
        return self

    def build(self):
        S, V, F, P = self.seg, self.via, self.fp, self.pad
        kw = dict(nets=self.nets, copper_layers=self.layers)
        if S:
            a = np.array(S, float)
            kw.update(s_idx=range(len(S)), s_x0=a[:, 0], s_y0=a[:, 1], s_x1=a[:, 2], s_y1=a[:, 3], s_w=a[:, 4], s_layer=a[:, 5], s_net=a[:, 6])
        if V:
            a = np.array(V, float)
            kw.update(v_idx=range(len(V)), v_x=a[:, 0], v_y=a[:, 1], v_dia=a[:, 2], v_drill=a[:, 3], v_net=a[:, 4])
        if F:
            kw.update(fp_idx=range(len(F)), fp_ref=[f[0] for f in F], fp_x=[f[1] for f in F], fp_y=[f[2] for f in F], fp_rot=[0] * len(F),
                      fp_side=[0] * len(F), fp_cx0=[f[3][0] for f in F], fp_cy0=[f[3][1] for f in F], fp_cx1=[f[3][2] for f in F],
                      fp_cy1=[f[3][3] for f in F], fp_kind=['K'] * len(F))
        if P:
            kw.update(p_fp=[q[0] for q in P], p_pin=[q[1] for q in P], p_x=[q[2] for q in P], p_y=[q[3] for q in P], p_bx0=[q[4] for q in P],
                      p_by0=[q[5] for q in P], p_bx1=[q[6] for q in P], p_by1=[q[7] for q in P], p_net=[q[8] for q in P], p_smd=[q[9] for q in P],
                      p_rot=[0] * len(P), p_shape=[1] * len(P), p_sx=[q[10] for q in P], p_sy=[q[10] for q in P], p_layer_mask=[1] * len(P))
        if F:
            nan = (np.nan,) * 4
            fb = [self.fab.get(f[0], nan) for f in F]
            kw.update(fp_fab_x0=[q[0] for q in fb], fp_fab_y0=[q[1] for q in fb], fp_fab_x1=[q[2] for q in fb], fp_fab_y1=[q[3] for q in fb])
        if self.lab:
            idx = {f[0]: i for i, f in enumerate(F)}
            R = self.lab
            kw.update(r_x=[q[1] for q in R], r_y=[q[2] for q in R], r_h=[q[3] for q in R], r_w=[q[3] for q in R], r_t=[0.15] * len(R),
                      r_ang=[q[4] for q in R], r_layer=[q[5] for q in R], r_on_silk=[q[6] and q[5] == 0 for q in R], r_fp=[idx[q[0]] for q in R],
                      r_hide=[not q[6] for q in R], r_just=['center'] * len(R))
        if self.txt:
            T = self.txt
            kw.update(t_text=[q[0] for q in T], t_x=[(q[1] + q[3]) / 2 for q in T], t_y=[(q[2] + q[4]) / 2 for q in T], t_h=[1.0] * len(T),
                      t_ang=[0.0] * len(T), t_stroke=[0.15] * len(T), t_x0=[q[1] for q in T], t_y0=[q[2] for q in T], t_x1=[q[3] for q in T],
                      t_y1=[q[4] for q in T], t_hide=[False] * len(T), t_layer=[0] * len(T), t_just=['center'] * len(T))
        kw['read_fields'] = B.LATER_FIELDS
        if self.zone:
            xy, roff, voff, rhole = [], [0], [0], []
            for _, _, _, _, rings in self.zone:
                for hole, pts in rings:
                    xy.extend(pts)
                    voff.append(voff[-1] + len(pts))
                    rhole.append(1 if hole else 0)
                roff.append(len(voff) - 1)
            kw.update(z_layer=[z[0] for z in self.zone], z_net=[z[1] for z in self.zone], z_filled=[z[2] for z in self.zone],
                      z_keepout=[z[3] for z in self.zone], z_xy=np.array(xy, float), z_ring_off=roff, z_vert_off=voff, z_ring_hole=rhole)
        return B.BoardArrays.from_arrays(**kw)
