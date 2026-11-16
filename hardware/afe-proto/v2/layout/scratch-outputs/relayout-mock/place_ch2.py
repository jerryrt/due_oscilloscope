"""Simulated-annealing placement of CH2 with label zones (translation only; rotations stay). Writes ch2_place.json.
python3 place_ch2.py [seed] [iters]"""
import os, sys, json, math, random
os.chdir(os.path.dirname(os.path.abspath(__file__)))
P = {p['ref']: p for p in json.load(open('parts_cur.json'))}
D = json.load(open('pads_cur.json'))
MOVE = ['R201','R202','R203','R204','R205','R206','R207','R208','C201','C202','C203','D201','TP201']
REGION = [(69.0, 19.75, 93.0, 32.9)]        # CH2 outline now; extension rects are appended by the caller
EXT = json.loads(sys.argv[3]) if len(sys.argv) > 3 else []
REGION += [tuple(r) for r in EXT]
INSET = 0.3     # courtyards and labels stay this far inside the block outline (silk line)
LABEL_GAP = 0.5
ZONE = 0.3      # label sits this far above its own courtyard
LH = 1.2
def Lw(ref): return 0.95 * len(ref)
def cyd(p):
    c = p['cy']; return (c[0]-50, 150-c[3], c[2]-50, 150-c[1])
def ink(p):
    c = p['ink']; return (c[0]-50, 150-c[3], c[2]-50, 150-c[1])
def pos(p): return (p['x']-50, 150-p['y'])
REL = {}   # courtyard relative to the part position
for r in MOVE:
    p = P[r]; c = cyd(p); x, y = pos(p); REL[r] = (c[0]-x, c[1]-y, c[2]-x, c[3]-y)
PADS = {}
for q in D['pads']:
    PADS.setdefault(q['ref'], []).append(q)
def padrel(r):
    x, y = pos(P[r]); return [(q['net'], q['c'][0]-x, q['c'][1]-y) for q in PADS[r]]
PR = {r: padrel(r) for r in MOVE}
# fixed obstacles
FIX_CY = [cyd(p) for r, p in P.items() if r not in MOVE]
NEWLB = {}
for r_ in ('BR501', 'BR504'):
    c_ = cyd(P[r_]); w_ = Lw(r_); cx_ = (c_[0]+c_[2])/2; ly_ = c_[3] + 0.8
    NEWLB[r_] = (cx_-w_/2, ly_-0.5, cx_+w_/2, ly_+0.5)
FIX_LB = [NEWLB.get(r, None) or ink(p) for r, p in P.items() if r not in MOVE and p['tvis']]
DEL_NETS = {'/CH2_IN','/CH2_N','/CH2_M1','/CH2_M2','/CH2_M3','/CH2_NP','/CH2_OUT','/A0','/VREF_P','/GND'}
FIX_VIA = [(t['c'][0], t['c'][1], t['d']/2) for t in D['trk'] if t['k']=='via' and t['net'] not in DEL_NETS]
FIX_TRK = [(t['a'], t['b'], t['w']/2) for t in D['trk'] if t['k']=='seg' and t['net'] not in DEL_NETS]
def ov(a, b, g=0.0):
    """penetration depth of rectangles a,b with gap g (0 when clear)"""
    dx = min(a[2], b[2]) - max(a[0], b[0]) + g
    dy = min(a[3], b[3]) - max(a[1], b[1]) + g
    return min(dx, dy) if dx > 0 and dy > 0 else 0.0
def inside(r, rects, inset):
    best = 1e9
    for g in rects:
        d = max(g[0]+inset-r[0], g[1]+inset-r[1], r[2]-(g[2]-inset), r[3]-(g[3]-inset), 0)
        best = min(best, d)
    # a box straddling the seam between the main rectangle and a flush extension (the old west edge is removed there)
    m = REGION[0]
    for g in REGION[1:]:
        if abs(g[2]-m[0]) < 1e-9 or abs(g[0]-m[2]) < 1e-9:
            lo, hi = max(g[1], m[1]), min(g[3], m[3])
            x0, x1 = min(g[0], m[0]), max(g[2], m[2])
            d = max(x0+inset-r[0], r[2]-(x1-inset), lo+inset-r[1], r[3]-(hi-inset), 0)
            best = min(best, d)
    return best
def seg_rect(a, b, w, r, g):
    x0, y0, x1, y1 = r[0]-g-w, r[1]-g-w, r[2]+g+w, r[3]+g+w
    # Liang-Barsky
    t0, t1 = 0.0, 1.0
    dx, dy = b[0]-a[0], b[1]-a[1]
    for p_, q_ in ((-dx, a[0]-x0), (dx, x1-a[0]), (-dy, a[1]-y0), (dy, y1-a[1])):
        if p_ == 0:
            if q_ < 0: return False
        else:
            t = q_/p_
            if p_ < 0:
                if t > t1: return False
                t0 = max(t0, t)
            else:
                if t < t0: return False
                t1 = min(t1, t)
    return t0 <= t1
def geom(st):
    cy, lb = {}, {}
    for r in MOVE:
        x, y = st[r]; c = REL[r]
        k = (x+c[0], y+c[1], x+c[2], y+c[3]); cy[r] = k
        w = Lw(r); cx = (k[0]+k[2])/2; ly = k[3] + 0.8
        lb[r] = (cx-w/2, ly-LH/2, cx+w/2, ly+LH/2)
    return cy, lb
W = {'/CH2_IN': 8, '/CH2_M1': 8, '/CH2_N': 10, '/CH2_M2': 8, '/CH2_M3': 6, '/CH2_NP': 10, '/CH2_OUT': 2, '/A0': 1.0, '/VREF_P': 0.5}
TERM = {'/CH2_IN': [(92.2, 27.82)], '/A0': [(68.58, 24.0)], '/VREF_P': [(69.0, 24.5)]}
for q in D['pads']:
    if q['ref'] == 'U101' and q['net'] in ('/CH2_NP', '/CH2_OUT'):
        TERM.setdefault(q['net'], []).append(tuple(q['c']))
def cost(st):
    cy, lb = geom(st)
    nets = {}
    for r in MOVE:
        for n, dx, dy in PR[r]:
            if n in W: nets.setdefault(n, []).append((st[r][0]+dx, st[r][1]+dy))
    wl = 0
    for n, pts in nets.items():
        pts = pts + TERM.get(n, [])
        if len(pts) > 1:
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            wl += W[n]*((max(xs)-min(xs)) + (max(ys)-min(ys)))
    v = 0.0
    for r in MOVE:
        v += inside(cy[r], REGION, INSET) + inside(lb[r], REGION, INSET)
        for f in FIX_CY:
            v += ov(cy[r], f, 0.1)            # courtyard to courtyard
            v += ov(lb[r], f, ZONE)           # label zone clear of foreign courtyards
        for f in FIX_LB:
            v += ov(lb[r], f, LABEL_GAP) + ov(cy[r], f, 0.3)
        for (vx, vy, vr) in FIX_VIA:
            b = (vx-vr, vy-vr, vx+vr, vy+vr)
            v += ov(cy[r], b, 0.2) + ov(lb[r], b, 0.3)
        for a, b, w in FIX_TRK:
            if seg_rect(a, b, w, cy[r], 0.15): wl += 6.0
    for i, r in enumerate(MOVE):
        for s in MOVE[i+1:]:
            v += ov(cy[r], cy[s], 0.1) + ov(lb[r], lb[s], LABEL_GAP) + ov(lb[r], cy[s], ZONE) + ov(lb[s], cy[r], ZONE)
    return wl, v
def energy(st):
    wl, v = cost(st); return wl + 400*v, wl, v
def run(seed, iters):
    rnd = random.Random(seed)
    slots = [(90.5,20.85),(90.5,24.15),(90.5,27.45),(86.2,20.85),(86.2,24.15),(81.9,20.85),(81.9,24.15),(77.6,20.85),(77.6,24.15),(72.4,20.85),(72.4,24.15),(72.4,27.45),(77.6,28.4)]
    rnd.shuffle(slots)
    st = {r: slots[i] for i, r in enumerate(MOVE)}
    e, wl, v = energy(st)
    best = (e, dict(st), wl, v)
    T0 = 6.0
    for it in range(iters):
        T = T0*(1-it/iters)**2 + 0.02
        r = rnd.choice(MOVE)
        sc = 0.15 + 1.0*T/T0
        if rnd.random() < 0.05:                                    # swap two parts
            r2 = rnd.choice(MOVE); a_, b_ = st[r], st[r2]; st[r], st[r2] = b_, a_
            e2, wl2, v2 = energy(st)
            if e2 <= e or rnd.random() < math.exp((e-e2)/T):
                e, wl, v = e2, wl2, v2
                if (v < 1e-9 and e < best[0]) or (best[3] > 1e-9 and e < best[0]): best = (e, dict(st), wl, v)
            else: st[r], st[r2] = a_, b_
            continue
        nx = round((st[r][0] + rnd.gauss(0, sc))*20)/20; ny = round((st[r][1] + rnd.gauss(0, sc))*20)/20
        old = st[r]; st[r] = (nx, ny)
        e2, wl2, v2 = energy(st)
        if e2 <= e or rnd.random() < math.exp((e-e2)/T):
            e, wl, v = e2, wl2, v2
            if v < 1e-9 and e < best[0] or (best[3] > 1e-9 and e < best[0]):
                best = (e, dict(st), wl, v)
        else:
            st[r] = old
    return best
if __name__ == '__main__':
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    iters = int(sys.argv[2]) if len(sys.argv) > 2 else 30000
    b = run(seed, iters)
    print('seed', seed, 'E', round(b[0], 2), 'wl', round(b[2], 2), 'viol', round(b[3], 4))
    json.dump(dict(seed=seed, e=b[0], wl=b[2], viol=b[3], st=b[1]), open('ch2_place_%d.json' % seed, 'w'))
