"""place designators (1.0 mm) and block words on F.SilkS: greedy, bounded, avoids pads, vias, other text, courtyards where it can"""
import sys, math, numpy as np
from pcbtools import boardio
from pcbtools.editor import edit
SRC, OUT = sys.argv[1], sys.argv[2]
b = boardio.read_board(SRC)
mine = [r for r in b.fp_ref if len(r) >= 4 and r[1:2] in '12' and r[0] in 'RCDUT' and (r[0] != 'T' or r.startswith('TP')) or r in ('J101', 'J201')]
mine = [r for r in b.fp_ref if (''.join(c for c in r if c.isdigit())[:1] in '12' and len(''.join(c for c in r if c.isdigit())) >= 3)]
H = 1.0
def tbox(text, x, y):
    w = 0.95 * len(text) + 0.3; return (x - w / 2, y - 0.65, x + w / 2, y + 0.65)
obst = []                       # (x0,y0,x1,y1, hard)
for j in range(len(b.p_x)):
    if b.p_x[j] < 60 or b.p_x[j] > 120: continue
    obst.append((b.p_bx0[j]-.25, b.p_by0[j]-.25, b.p_bx1[j]+.25, b.p_by1[j]+.25))
for x, y, d in zip(b.v_x, b.v_y, b.v_dia): obst.append((x-d/2-.25, y-d/2-.25, x+d/2+.25, y+d/2+.25))
court = {r: (b.fp_cx0[i], b.fp_cy0[i], b.fp_cx1[i], b.fp_cy1[i]) for i, r in enumerate(b.fp_ref)}
for i, r in enumerate(b.fp_ref):          # footprint's own silk is inside its courtyard: treat other parts' courtyards as soft
    pass
def hit(a, c): return a[0] < c[2] and c[0] < a[2] and a[1] < c[3] and c[1] < a[3]
placed = []                      # text boxes
fixed = []
# block words first (fixed spots, checked later)
words = {'CH1': (86.0, 48.6), 'CH2': (86.0, 20.4)}
for w, (x, y) in words.items():
    placed.append(tbox(w, x, y))
res = {}
manual = {'J101': (105.2, 42.0), 'J201': (105.2, 26.3), 'R109': (62.8, 37.1), 'R110': (66.04, 32.9)}
for r, (x, y) in manual.items(): res[r] = (0, x, y); placed.append(tbox(r, x, y))
O = np.array(obst); CT = np.array([court[o] for o in court if not math.isnan(court[o][0]) and 60 < court[o][0] < 120 and o not in mine])
CTn = {o: court[o] for o in court if not math.isnan(court[o][0]) and 60 < court[o][0] < 120}
order = [r for r in sorted(mine, key=lambda r: -((court[r][2]-court[r][0])*(court[r][3]-court[r][1]) if not math.isnan(court[r][0]) else 0)) if r not in manual]
gx, gy = np.meshgrid(np.arange(-7, 7.01, 0.25), np.arange(-5, 5.01, 0.25)); gx = gx.ravel(); gy = gy.ravel()
def hits(B, boxes):      # B: (n,4) candidate boxes; boxes (m,4) -> (n,) any hit / count
    if len(boxes) == 0: return np.zeros(len(B), int)
    h = (B[:, None, 0] < boxes[None, :, 2]) & (boxes[None, :, 0] < B[:, None, 2]) & (B[:, None, 1] < boxes[None, :, 3]) & (boxes[None, :, 1] < B[:, None, 3])
    return h.sum(1)
def cand(r):
    cx0, cy0, cx1, cy1 = court[r]; ccx, ccy = (cx0+cx1)/2, (cy0+cy1)/2
    tw = 0.95*len(r)+0.3
    X = ccx + gx; Y = ccy + gy
    B = np.column_stack([X-tw/2, Y-0.65, X+tw/2, Y+0.65])
    ok = (B[:,0] >= 64.0) & (B[:,2] <= 92.0) & (B[:,1] >= 19.2) & (B[:,3] <= 50.2)
    ok &= hits(B, O) == 0
    if r != 'U101': ok &= hits(B, np.array([court[r]])) == 0
    return X, Y, B, ok
free = {r: int(cand(r)[3].sum()) for r in order}
order = ['U101'] + sorted([r for r in order if r != 'U101'], key=lambda r: free[r])
print('free spots', {r: free[r] for r in order[:8]})
for r in order:
    cx0, cy0, cx1, cy1 = court[r]; ccx, ccy = (cx0+cx1)/2, (cy0+cy1)/2
    tw = 0.95*len(r)+0.3
    X = ccx + gx; Y = ccy + gy
    B = np.column_stack([X-tw/2, Y-0.65, X+tw/2, Y+0.65])
    ok = (B[:,0] >= 64.0) & (B[:,2] <= 92.0) & (B[:,1] >= 19.2) & (B[:,3] <= 50.2)
    ok &= hits(B, O) == 0
    ok &= hits(B, np.array(placed)) == 0
    if r != 'U101': ok &= hits(B, np.array([court[r]])) == 0
    other = np.array([v for o, v in CTn.items() if o != r])
    soft = hits(B, other)
    # the part's own courtyard: the text must not sit on its own pads (already excluded) 
    d = np.hypot(gx, gy*1.6)
    sc = np.where(ok, d + soft*1.2, np.inf)
    i = int(np.argmin(sc))
    if not np.isfinite(sc[i]): print('NO SPOT', r); continue
    res[r] = (float(sc[i]), float(X[i]), float(Y[i])); placed.append(tuple(B[i]))
print({r: (round(v[1],2), round(v[2],2), v[0]) for r, v in res.items()})
with edit(SRC, OUT) as e:
    for r, (sc, x, y) in res.items(): e.set_ref(r, x, y, h=H)
    for w, (x, y) in words.items(): e.add_text(w, x, y, h=H)
