import sys, math
from PIL import Image, ImageDraw
from pcbtools import boardio
f, x0, y0, x1, y1, out = sys.argv[1], *map(float, sys.argv[2:6]), sys.argv[6]
hi = set(sys.argv[7].split(',')) if len(sys.argv) > 7 else set()
b = boardio.read_board(f); S = 28
im = Image.new('RGB', (int((x1 - x0) * S), int((y1 - y0) * S)), 'white'); d = ImageDraw.Draw(im)
P = lambda x, y: ((x - x0) * S, (y - y0) * S)
col = lambda n: (220, 30, 30) if n in hi else (60, 110, 190)
for k in range(len(b.s_idx)):
    n = b.nets[int(b.s_net[k])]; lay = int(b.s_layer[k])
    c = col(n) if lay == 0 else (150, 150, 150)
    d.line([P(b.s_x0[k], b.s_y0[k]), P(b.s_x1[k], b.s_y1[k])], fill=c, width=max(2, int(b.s_w[k] * S)))
for k in range(len(b.v_x)):
    px, py = P(b.v_x[k], b.v_y[k]); d.ellipse([px - 7, py - 7, px + 7, py + 7], outline=(0, 140, 0), width=2)
for j in range(len(b.p_fp)):
    px, py = P(b.p_x[j], b.p_y[j]); n = b.nets[int(b.p_net[j])]
    d.rectangle([px - 5, py - 5, px + 5, py + 5], fill=col(n) if n in hi else (30, 30, 30))
    d.text((px + 6, py - 5), b.fp_ref[int(b.p_fp[j])] + '.' + str(b.p_pin[j]) + ' ' + n, fill=(0, 0, 0))
im.save(out)
