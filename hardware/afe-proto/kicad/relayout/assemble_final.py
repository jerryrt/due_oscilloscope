import os, shutil, re, uuid, subprocess, sys
import numpy as np
from pcbtools import boardio, silkread
from pcbtools.boards import v1 as C
src = 'whatif/_scratch/relaid'; dst = 'whatif/_scratch/final'
os.makedirs(dst, exist_ok=True)
for f in os.listdir(src): shutil.copy(os.path.join(src, f), dst)
P = os.path.join(dst, 'afe-proto.kicad_pcb')
r = subprocess.run([sys.executable, '-m', 'pcbtools.pinlabels', P, '--config', 'v1', '--write'], capture_output=True, text=True)
print('pinlabels', r.returncode, (r.stdout + r.stderr).strip()[-300:])
b = boardio.read_board(P)
refs = list(b.fp_ref)
def U(name): return str(uuid.uuid5(uuid.UUID(C.NS), 'final-' + name))
X = lambda x: x + 50.0
Y = lambda y: 150.0 - y
def text(t, x, y, h, layer='F.SilkS', th=0.15, key=None):
    return (f'\t(gr_text "{t}"\n\t\t(at {X(x):.6g} {Y(y):.6g} 0)\n\t\t(layer "{layer}")\n\t\t(uuid "{U(key or t + layer)}")\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size {h} {h})\n\t\t\t\t(thickness {th})\n\t\t\t)\n\t\t)\n\t)\n')
def rect(x0, y0, x1, y1, key):
    return (f'\t(gr_rect\n\t\t(start {X(x0):.6g} {Y(y0):.6g})\n\t\t(end {X(x1):.6g} {Y(y1):.6g})\n\t\t(stroke\n\t\t\t(width 0.15)\n\t\t\t(type default)\n\t\t)\n\t\t(fill yes)\n\t\t(layer "F.SilkS")\n\t\t(uuid "{U(key)}")\n\t)\n')
def line(a, c, key):
    return (f'\t(gr_line\n\t\t(start {X(a[0]):.6g} {Y(a[1]):.6g})\n\t\t(end {X(c[0]):.6g} {Y(c[1]):.6g})\n\t\t(stroke\n\t\t\t(width 0.15)\n\t\t\t(type default)\n\t\t)\n\t\t(layer "F.SilkS")\n\t\t(uuid "{U(key)}")\n\t)\n')
I = C.IDENT
out = ''
out += text(C.NAME, I['name'][0], I['name'][1], I['name'][2], th=0.3, key='name')
out += text(C.ID_LINE, I['line'][0], I['line'][1], I['line'][2], th=0.2, key='line')
out += text(C.SN_LABEL, I['sn_label'][0], I['sn_label'][1], I['sn_label'][2], key='snl')
out += rect(*I['sn_box'], key='snbox')
out += text(C.JLC_ORDER_TEXT, I['jlc'][0], I['jlc'][1], I['jlc'][2], layer='B.SilkS', key='jlc')
# obstacles for the block titles: courtyards, pads, designators, other silk text
shown = {}
for j in range(len(b.r_fp)):
    i = int(b.r_fp[j])
    if int(b.r_layer[j]) == boardio.R_LAYERS['F.SilkS']:
        shown[i] = silkread.text_box(refs[i], b.r_x[j], b.r_y[j], b.r_w[j], b.r_h[j], b.r_ang[j])
obst = []
for i in range(len(refs)):
    if np.isnan(b.fp_cx0[i]): continue
    obst.append((float(b.fp_cx0[i]), float(b.fp_cy0[i]), float(b.fp_cx1[i]), float(b.fp_cy1[i])))
    if i in shown: obst.append(tuple(float(v) for v in shown[i]))
for k in range(len(b.t_text)):
    obst.append(tuple(float(v) for v in silkread.text_box(b.t_text[k], b.t_x[k], b.t_y[k], b.t_h[k], b.t_h[k], 0.0)) if False else (b.t_x[k] - 0.6, b.t_y[k] - 0.6, b.t_x[k] + 0.6 + 0.9 * len(b.t_text[k]) * (0 if b.t_text[k] in () else 1) / 1.0 * 0.0, b.t_y[k] + 0.6))
for j in range(len(b.p_fp)):
    obst.append((float(b.p_bx0[j]), float(b.p_by0[j]), float(b.p_bx1[j]), float(b.p_by1[j])))
O = np.array(obst)
def free_spot(word, fence_rects, h=1.0, M=0.5, south=False):
    w = len(word) * 0.9 * h
    best = None
    for (x0, y0, x1, y1) in fence_rects:
        for cx in np.arange(x0 + w / 2 + 0.3, x1 - w / 2 - 0.3, 0.1):
            for cy in np.arange(y0 + h / 2 + 0.3, y1 - h / 2 - 0.3, 0.1):
                bx = (cx - w / 2 - M, cy - h / 2 - M, cx + w / 2 + M, cy + h / 2 + M)
                if ((O[:, 0] < bx[2]) & (O[:, 2] > bx[0]) & (O[:, 1] < bx[3]) & (O[:, 3] > bx[1])).any(): continue
                # prefer the spot nearest the fence's north-west corner
                score = (cx - x0) + ((cy - y0) if south else (y1 - cy))
                if best is None or score < best[0]: best = (score, round(float(cx), 2), round(float(cy), 2))
    return best
for word, blk in (('POWER', 'POWER'), ('REF/CAL', 'REFCAL'), ('CH1', 'SCOPE'), ('CH2', 'SCOPE'), ('AWG', 'AWG')):
    rects = C.FENCES[blk][:1] if word == 'CH1' else (C.FENCES[blk][1:2] if word == 'CH2' else C.FENCES[blk][:1])
    so = word in ('AWG', 'REF/CAL')
    sp = free_spot(word, rects, south=so) or free_spot(word, rects, M=0.3, south=so) or free_spot(word, C.FENCES[blk], M=0.3, south=so)
    print('title', word, sp)
    if sp:
        out += text(word, sp[1], sp[2], 1.0, key='title' + word)
        x0_, y0_ = sp[1] - len(word) * 0.45 - 0.5, sp[2] - 1.0
        O = np.vstack([O, [sp[1] - len(word) * 0.45 - 0.3, sp[2] - 0.8, sp[1] + len(word) * 0.45 + 0.3, sp[2] + 0.8]])
# the ratio jumper's ON mark, at the same offsets from J501 as on the main board
j = b.ref_index('J501'); jx, jy = float(b.fp_x[j]), float(b.fp_y[j])
out += text('ON', jx + 0.76, jy - 4.756921 + (12.6 - 12.6), 1.0, key='ON')
out += line((jx + 0.76, jy - 3.6), (jx + 3.16, jy - 3.6), 'on1') + line((jx + 0.76, jy - 3.15), (jx + 0.76, jy - 3.6), 'on2') + line((jx + 3.16, jy - 3.6), (jx + 3.16, jy - 3.35), 'on3')
txt = open(P).read()
i = txt.rindex(')')
open(P, 'w').write(txt[:i] + out + txt[i:])
print('written', P)
