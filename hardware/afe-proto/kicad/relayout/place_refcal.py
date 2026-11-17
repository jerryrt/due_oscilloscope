"""place_refcal.py [SEED] [ITERS] : simulated-annealing re-placement of the REFCAL/ADS block on the current base board (whatif/_scratch/base_final.kicad_pcb).
Cost: weighted half-perimeter wirelength (VREF x2; far loads excluded and the star hubs as points), hard penalties for courtyard overlap, the fence, label
overlap (labels above, 3.2 x 1.0 mm, 0.5 clear), LR-12 decoupling distance, LR-5 (10 mm from U401/C402 for sensitive pads). Translations and 180-degree flips only.
Prints the move list as ref:dx:dy:rot for apply_spec.py / quick.sh (rot is the new absolute rotation, so flips are recorded)."""
import sys, math, random, json
import numpy as np
from pcbtools import boardio
from pcbtools.boards import v1 as C
seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
ITERS = int(sys.argv[2]) if len(sys.argv) > 2 else 30000
random.seed(seed); np.random.seed(seed)
b = boardio.read_board('whatif/_scratch/base_final.kicad_pcb')
refs = list(b.fp_ref); ix = {r: i for i, r in enumerate(refs)}
FIX = {'J501', 'R503', 'R504', 'R506', 'R507', 'R508', 'R515', 'R516'}
MOV = [r for r in refs if C.BLOCK.get(r) == 'REFCAL' and not r.startswith(('J', 'MH')) and r not in FIX]
pos = {r: [float(b.fp_x[ix[r]]), float(b.fp_y[ix[r]])] for r in refs}
flip = {r: 0 for r in refs}
rel = {}
for r in refs:
    k = ix[r]
    if np.isnan(b.fp_cx0[k]): continue
    rel[r] = (float(b.fp_cx0[k] - b.fp_x[k]), float(b.fp_cy0[k] - b.fp_y[k]), float(b.fp_cx1[k] - b.fp_x[k]), float(b.fp_cy1[k] - b.fp_y[k]))
pads = {}
for j in range(len(b.p_fp)):
    r = refs[int(b.p_fp[j])]
    pads.setdefault(r, []).append((b.nets[int(b.p_net[j])], str(b.p_pin[j]), float(b.p_x[j] - b.fp_x[ix[r]]), float(b.p_y[j] - b.fp_y[ix[r]])))
def box(r):
    x0, y0, x1, y1 = rel[r]; px, py = pos[r]
    return (px - x1, py - y1, px - x0, py - y0) if flip[r] else (px + x0, py + y0, px + x1, py + y1)
def padpos(r, pin_or_idx):
    n, p, dx, dy = pads[r][pin_or_idx]; px, py = pos[r]
    return (px - dx, py - dy) if flip[r] else (px + dx, py + dy)
def label(r):
    x0, y0, x1, y1 = box(r); cx = (x0 + x1) / 2
    return (cx - 1.7, y1 + 0.2, cx + 1.7, y1 + 1.2)      # above (y up in Due mm): the part's far edge plus 0.2, 3.4 x 1.0
FENCE = (45.0, 4.2, 64.2, 39.3)
FAR = {('R307', '1'), ('R104', '2'), ('R204', '2'), ('R515', '1'), ('U301', '8'), ('C302', '1'), ('D201', '2'), ('D101', '2'), ('R108', '1')}
W = {'/VREF': 2.0, '/SDA1': 0.4, '/SCL1': 0.4, '/AREF': 0.4, '/GND': 0.0}
HUB = {'/+3V3A': (44.5, 17.0)}
nets = {}
for r, pl in pads.items():
    for i, (n, p, dx, dy) in enumerate(pl):
        if n and n != '/GND' and (r, p) not in FAR and 'nconnected' not in n: nets.setdefault(n, []).append((r, i))
movnets = {n: l for n, l in nets.items() if len(l) >= 2 and any(r in MOV for r, _ in l)}
by_part = {}
for n, l in movnets.items():
    for r, _ in l: by_part.setdefault(r, set()).add(n)
def hpwl(n):
    pts = [padpos(r, i) for r, i in movnets[n]]
    if n in HUB: pts.append(HUB[n])
    X = [p[0] for p in pts]; Y = [p[1] for p in pts]
    return W.get(n, 1.0) * ((max(X) - min(X)) + (max(Y) - min(Y)))
U401 = [(31.2, 7.5, 36.0, 12.2), (36.2, 8.4, 38.2, 11.2)]
SENS = ('/VREF', '/TAP', '/SNS', '/AREF')
def lr5(r):
    pen = 0.0
    for n, p, dx, dy in pads[r]:
        if not n.startswith(SENS): continue
        x, y = padpos(r, [q[1] for q in pads[r]].index(p))
        for (a, c, d, e) in U401:
            dist = math.hypot(max(a - x, 0, x - d), max(c - y, 0, y - e))
            if dist < 10.6: pen += 10.6 - dist
    return pen
DEC = {'C502': ('U502', '8'), 'C501': ('U501', '1')}
def ov(a, c, m):
    return max(0.0, min(a[2] + m, c[2]) - max(a[0] - m, c[0])) * 1.0 if (min(a[2] + m, c[2]) > max(a[0] - m, c[0]) and min(a[3] + m, c[3]) > max(a[1] - m, c[1])) else 0.0
def inter(a, c, m):
    dx = min(a[2] + m, c[2]) - max(a[0] - m, c[0]); dy = min(a[3] + m, c[3]) - max(a[1] - m, c[1])
    return (dx * dy if dx > 0 and dy > 0 else 0.0)
others = [r for r in rel if r not in MOV and not r.startswith('MH') and r not in ('J601', 'J603')]
def part_pen(r):
    bx = box(r); pen = 0.0
    for o in list(MOV) + others:
        if o == r: continue
        pen += inter(bx, box(o), 0.2) * 8
    lb = label(r)
    for o in list(MOV) + others:
        if o == r: continue
        pen += inter(lb, box(o), 0.3) * 6
        if o in MOV: pen += inter(lb, label(o), 0.4) * 6      # a label against another movable label
    # the part against other parts' labels
    for o in MOV:
        if o != r: pen += inter(bx, label(o), 0.3) * 6
    pen += 40 * (max(0, FENCE[0] - bx[0]) + max(0, bx[2] - FENCE[2]) + max(0, FENCE[1] - bx[1]) + max(0, bx[3] - FENCE[3]))
    pen += 40 * (max(0, FENCE[0] - lb[0]) + max(0, lb[2] - FENCE[2]) + max(0, lb[3] - FENCE[3]))
    pen += 12 * lr5(r)
    if r in DEC:
        ic, pin = DEC[r]; ipos = padpos(ic, [q[1] for q in pads[ic]].index(pin))
        cp = min(((padpos(r, i)) for i in range(len(pads[r])) if pads[r][i][0] != '/GND'), key=lambda q: 0)
        d = math.hypot(cp[0] - ipos[0], cp[1] - ipos[1]); pen += 30 * max(0, d - 2.3)
    return pen
def total():
    return sum(hpwl(n) for n in movnets) + sum(part_pen(r) for r in MOV)
def local(r):
    return sum(hpwl(n) for n in by_part.get(r, ())) + part_pen(r) * 2      # a part's own penalty counted against the rest too, twice for symmetry
start = {r: (list(pos[r]), flip[r]) for r in MOV}
cost0 = total(); print('start cost %.1f' % cost0, 'movable', len(MOV), flush=True)
T0, T1 = 3.0, 0.02
cur = cost0
best = (cur, {r: (list(pos[r]), flip[r]) for r in MOV})
for it in range(ITERS):
    T = T0 * (T1 / T0) ** (it / ITERS)
    r = random.choice(MOV); old = (list(pos[r]), flip[r]); l0 = local(r)
    if random.random() < 0.12: flip[r] ^= 1
    else:
        s = 0.25 + 2.5 * (1 - it / ITERS)
        pos[r][0] += random.gauss(0, s); pos[r][1] += random.gauss(0, s)
    l1 = local(r)
    if l1 <= l0 or random.random() < math.exp(-(l1 - l0) / T):
        cur += (l1 - l0) / 1.0
    else:
        pos[r], flip[r] = old
    if it % 3000 == 0:
        cur = total(); print('iter', it, 'cost %.1f' % cur, flush=True)
        if cur < best[0]: best = (cur, {q: (list(pos[q]), flip[q]) for q in MOV})
cur = total()
if cur < best[0]: best = (cur, {q: (list(pos[q]), flip[q]) for q in MOV})
for q, (p, f) in best[1].items(): pos[q] = [round(p[0] / 0.05) * 0.05, round(p[1] / 0.05) * 0.05]; flip[q] = f
print('final cost %.1f (hpwl %.1f, pen %.1f)' % (total(), sum(hpwl(n) for n in movnets), sum(part_pen(r) for r in MOV)))
R0 = json.load(open('whatif/_scratch/rotov_keep2.json')); R1 = json.load(open('whatif/_scratch/rot.json'))
spec = []
for r in MOV:
    dx = pos[r][0] - float(b.fp_x[ix[r]]); dy = pos[r][1] - float(b.fp_y[ix[r]])
    base = R0.get(r, R1.get(r, float(b.fp_rot[ix[r]]) if hasattr(b, 'fp_rot') else 0.0))
    rot = (int(round(base)) + 180) % 360 if flip[r] else '-'
    if abs(dx) > 1e-6 or abs(dy) > 1e-6 or flip[r]: spec.append('%s:%.2f:%.2f:%s' % (r, dx, dy, rot))
print('SPEC', ';'.join(spec))
for r in MOV: print('  ', r, pos[r], 'flip' if flip[r] else '', 'LR5 %.2f' % lr5(r))
