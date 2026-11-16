"""AWG block, rows first: U301 fixed where it is (label above), every other part in a row of horizontal passives (rows y_a, y_b, y_c, and a column west of the A1 lane),
chosen by a depth-first search over discrete slots; every hard row and the lanes are checked exactly (relayout_place's own functions)."""
import sys, math, json, random, itertools
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import numpy as np, relayout_place as RP
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
D0, P0 = RP.load(R + 'dump_all.json')
U = (76.56, 9.71)                                              # U301 stays where it is
POCKET = ('C303', 'C304', 'R305', 'TP301')
PARTS = ['C306', 'C305', 'R304', 'R303', 'C301', 'R306', 'R307', 'R308', 'R309', 'R301', 'R302', 'TP301', 'C303', 'C304', 'R305']
ROWS = [7.235, 12.185, 16.15]
POCKET_X, POCKET_ROWS = 62.3, [8.1, 11.6, 15.1]
def ov(a, b, g): return min(a[2], b[2]) - max(a[0], b[0]) + g > 1e-6 and min(a[3], b[3]) - max(a[1], b[1]) + g > 1e-6
reg = RP.REGIONS['AWG']; mext, mlab = RP.Mask(reg, 0.2), RP.Mask(reg, 0.4)
lanes = RP.LANES
BELOW = ('R304', 'R303', 'C301')
def pg(ref, k=0, ls=0):
    gg = RP.part_geom(P0[ref], k, ls)
    if ref in BELOW:
        c = gg['cy']; cx = (c[0] + c[2]) / 2 + RP.LSHIFT[ls][0]; w = RP.LAB_W * len(ref); top = c[1] - 0.2
        lab = (cx - w / 2, top - RP.LAB_H, cx + w / 2, top)
        gg = dict(gg); gg['lab'] = lab; gg['zone'] = (lab[0] - 0.05, lab[1] - 0.05, lab[2] + 0.05, lab[3] + 0.05)
    return gg
g = RP.part_geom(P0['U301']); ux, uy = U
U_ext = (g['ext'][0]+ux, g['ext'][1]+uy, g['ext'][2]+ux, g['ext'][3]+uy)
U_lab = (g['lab'][0]+ux, g['lab'][1]+uy, g['lab'][2]+ux, g['lab'][3]+uy); U_zone = (g['zone'][0]+ux, g['zone'][1]+uy, g['zone'][2]+ux, g['zone'][3]+uy)
fixed_ext = [U_ext]; fixed_zone = [U_zone]; fixed_lab = [U_lab]
# fixed header labels / names near the block
nb = RP.name_box('AWG', P0, {r: RP.part_geom(p) for r, p in P0.items()}, None); fixed_lab.append(nb)
for r in ('J602', 'J603'):
    c = RP.header_label(P0[r]); w, h = RP.LAB_W * 4, RP.LAB_H
    fixed_lab.append((c[0] - w / 2, c[1] - h / 2, c[0] + w / 2, c[1] + h / 2))
for r in ('J301', 'J605', 'MH601'):
    c = P0[r]['cy']; fixed_ext.append(tuple(c))
fixed_ext += [(P0[r]['silk'] or P0[r]['cy']) for r in ('J602', 'J603')]
HARD = [h for h in RP.hard_constraints(P0) if any(r in PARTS for r in h['refs'])]
def orient0(ref): return [k for k in range(4) if RP.orient(P0[ref], k) == 0]
def cand(ref):
    out = []
    spec = ref
    for k in (range(4) if ref in BELOW else orient0(ref)):
        for ls in (0, 2, 4):
            gg = pg(ref, k, ls)
            rows = ROWS if ref not in POCKET else list(np.arange(6.4, 27.2, 0.05))
            if ref in BELOW: rows = [round(v, 3) for v in np.arange(4.8, 17.6, 0.05)]
            xs = (np.arange(59.5, 92.2, 0.05) if ref not in POCKET else ([62.2] if ref == 'TP301' else [62.3]))
            if ref in BELOW: xs = np.arange(70.0, 84.5, 0.05)
            for y in rows:
                for x in xs:
                    x = round(float(x), 2); y = round(float(y), 3)
                    e = (gg['ext'][0]+x, gg['ext'][1]+y, gg['ext'][2]+x, gg['ext'][3]+y)
                    z = (gg['zone'][0]+x, gg['zone'][1]+y, gg['zone'][2]+x, gg['zone'][3]+y)
                    lb = (gg['lab'][0]+x, gg['lab'][1]+y, gg['lab'][2]+x, gg['lab'][3]+y)
                    if mext.bad(e) > 0 or mlab.bad(lb) > 0: continue
                    if any(ov(e, f, 0.02) for f in fixed_ext) or any(ov(z, f, 0) for f in fixed_ext) or any(ov(e, f, 0) for f in fixed_zone) or any(ov(lb, f, 0.5) for f in fixed_lab): continue
                    if any(ov(e, l, 0) or ov(z, l, 0) for l in lanes): continue
                    out.append((ref, k, ls, x, y, e, z, lb))
    return out
def pad_abs(ref, k, x, y, n):
    c, s_ = RP.COS[k], RP.SIN[k]
    q = [q for q in P0[ref]['pads'] if q['n'] == n][0]
    o = (q['c'][0] - P0[ref]['x'], q['c'][1] - P0[ref]['y']); o = (o[0]*c - o[1]*s_, o[0]*s_ + o[1]*c)
    return (x + o[0], y + o[1])
pinU = {n: [q['c'] for q in P0['U301']['pads'] if q['n'] == n][0] for n in '12345678'}
# U301's pads in the board are at U (76.56, 9.71); the dump is main's: shift
dxU, dyU = U[0] - P0['U301']['x'], U[1] - P0['U301']['y']
pinU = {n: (c[0] + dxU, c[1] + dyU) for n, c in pinU.items()}
def ok_local(c):
    ref, k, ls, x, y = c[:5]
    if ref == 'C305':
        return math.hypot(*(np.array(pad_abs(ref, k, x, y, '1')) - np.array(pinU['8']))) <= 2.79
    if ref == 'C306':
        return math.hypot(*(np.array(pad_abs(ref, k, x, y, '1')) - np.array(pinU['4']))) <= 2.79
    if ref in ('R301', 'R302'):
        return math.hypot(x - 102.0, y - 8.89) <= 15.99
    if ref == 'R306':
        d0 = [q['c'] for q in P0['J603']['pads'] if q['n'] == '5'][0]; p = pad_abs(ref, k, x, y, '1')
        return abs(p[0] - d0[0]) + abs(p[1] - d0[1]) <= 11.49
    return True
TARGET = {'C306': (81.9, 7.235), 'R301': (89.7, 7.235), 'R306': (83.8, 12.185), 'R302': (89.7, 12.185), 'C305': (71.5, 12.185),
          'R307': (72.9, 16.15), 'R308': (85.8, 16.15), 'R309': (90.1, 16.15)}
TOL = float(sys.argv[3]) if len(sys.argv) > 3 else 1.2
TOLX = {'R306': 1.8}
C = {r: [c for c in cand(r) if ok_local(c) and (r in POCKET or r in BELOW or (abs(c[3] - TARGET[r][0]) <= TOLX.get(r, TOL) and abs(c[4] - TARGET[r][1]) < 0.06))] for r in PARTS}
print({r: len(v) for r, v in C.items()}, flush=True)
def comp(a, b):
    return not (ov(a[5], b[5], 0.02) or ov(a[6], b[5], 0) or ov(b[6], a[5], 0) or ov(a[7], b[7], 0.5))
def ac3(sets):
    ch = True
    while ch:
        ch = False
        for a in sets:
            keep = []
            for ca in sets[a]:
                if all(any(comp(ca, cb) for cb in sets[b]) for b in sets if b != a):
                    keep.append(ca)
            if len(keep) != len(sets[a]):
                sets[a] = keep; ch = True; print('AC', a, len(keep), flush=True)
            if not keep: return False
    return True
_first = ['C306', 'C305', 'R301', 'R306', 'R302', 'R307', 'R309', 'R308']
FB = ['R304', 'R303', 'C301']
def fbpad(c):
    n = {'R304': '1', 'R303': '2', 'C301': '2'}[c[0]]
    return pad_abs(c[0], c[1], c[3], c[4], n)
dd = lambda p, q: abs(p[0] - q[0]) + abs(p[1] - q[1])
p2, p6 = pinU['2'], pinU['6']
FBL = {r: [(c, fbpad(c)) for c in C[r]] for r in FB}
FBL = {r: [(c, p) for c, p in v if min(dd(p, p2), dd(p, p6)) <= 5.0] for r, v in FBL.items()}
print('min d', {r: sorted((round(min(dd(p, p2), dd(p, p6)), 2), c[3], c[4]) for c, p in v)[:2] for r, v in FBL.items()}); print('FB cands', {r: len(v) for r, v in FBL.items()}, flush=True)
def mst(pts):
    n = len(pts); inT = {0}; L = 0
    while len(inT) < n:
        d, j = min((dd(pts[i], pts[j]), j) for i in inT for j in range(n) if j not in inT); L += d; inT.add(j)
    return L
LIM = float(sys.argv[5]) if len(sys.argv) > 5 else 12.58
base = dd(p2, p6)
def arr(L, i): return np.array([c[i] for c, p in L])
def OV(A, B, g):   # A: (n,4) arrays, B: (m,4): matrix of ov
    return ((np.minimum(A[:, None, 2], B[None, :, 2]) - np.maximum(A[:, None, 0], B[None, :, 0]) + g) > 1e-6) & ((np.minimum(A[:, None, 3], B[None, :, 3]) - np.maximum(A[:, None, 1], B[None, :, 1]) + g) > 1e-6)
def geo(L):
    return [np.array([c[i] for c, p in L]) for i in (5, 6, 7)]
FBL['R304'] = [(c, p) for c, p in FBL['R304'] if min(dd(p, p2), dd(p, p6)) <= 4.4]
FBL['R303'] = [(c, p) for c, p in FBL['R303'] if min(dd(p, p2), dd(p, p6)) <= 4.4]
print('FB cands', {r: len(v) for r, v in FBL.items()}, flush=True)
def compat(LA, LB):
    ea, za, la = geo(LA); eb, zb, lb = geo(LB)
    return ~(OV(ea, eb, 0.02) | OV(za, eb, 0) | OV(ea, zb, 0) | OV(la, lb, 0.5))
M_ab = compat(FBL['R304'], FBL['R303']); M_ac = compat(FBL['R304'], FBL['C301']); M_bc = compat(FBL['R303'], FBL['C301'])
PA = np.array([p for c, p in FBL['R304']]); PB = np.array([p for c, p in FBL['R303']]); PC = np.array([p for c, p in FBL['C301']])
P2 = np.array(p2); P6 = np.array(p6)
triples = []
for i in range(len(PA)):
    js = np.nonzero(M_ab[i])[0]
    if not len(js): continue
    ks = np.nonzero(M_ac[i])[0]
    if not len(ks): continue
    # MST of 5 points: enumerate via simple Prim in numpy would be heavy: use bound then exact
    da = min(dd(PA[i], p2), dd(PA[i], p6))
    for j in js:
        db = min(dd(PB[j], p2), dd(PB[j], p6), dd(PB[j], PA[i]))
        if base + da + db > LIM: continue
        kk = ks[M_bc[j][ks]]
        if not len(kk): continue
        pts = np.array([p2, p6, PA[i], PB[j]])
        dc = np.abs(PC[kk][:, None, :] - pts[None, :, :]).sum(2).min(1)
        for k2 in kk[base + da + db + dc <= LIM + 1e-9]:
            t = mst([p2, p6, tuple(PA[i]), tuple(PB[j]), tuple(PC[k2])])
            if t <= LIM + 1e-9: triples.append((t, FBL['R304'][i][0], FBL['R303'][j][0], FBL['C301'][k2][0]))
triples.sort(key=lambda t: t[0]); print('triples', len(triples), [round(t[0], 2) for t in triples[:5]], flush=True)
import pickle; pickle.dump(triples[:2000], open(R + 'below_triples.pkl', 'wb'))
def mates_ok(ch):
    pas = [c for c in ch if RP.PAS.fullmatch(c[0])]; bad = 0
    for a in pas:
        if not any(b is not a and abs(a[4] - b[4]) <= 0.05 and math.hypot(a[3]-b[3], a[4]-b[4]) <= 8 for b in pas) and not any(b is not a and abs(a[3] - b[3]) <= 0.05 and math.hypot(a[3]-b[3], a[4]-b[4]) <= 8 for b in pas):
            bad += 1
    return bad
def hard_ok(ch):
    pos = {c[0]: c for c in ch}
    pos_of = lambda ref: np.array((pos[ref][3], pos[ref][4])) if ref in pos else np.array((P0[ref]['x'], P0[ref]['y']))
    def off(ref, v):
        k = pos[ref][1] if ref in pos else 0; c, s_ = RP.COS[k], RP.SIN[k]
        return (v[0]*c - v[1]*s_, v[0]*s_ + v[1]*c)
    def pos2(ref):
        if ref == 'U301': return np.array(U)
        return pos_of(ref)
    return [h['name'] for h in HARD if 'AWG_FB' not in h['name'] and h['fn'](pos2, off) > 1e-6 and all(r in pos or r in ('U301', 'J603', 'J301', 'J601') or r in P0 and r not in PARTS for r in h['refs'])]
def greedy(tr, seed):
    r = random.Random(seed)
    ch = [tr[1], tr[2], tr[3]]
    for ref in ['TP301', 'R305', 'C303', 'C304'] + _first:
        cs = [c for c in C[ref] if all(comp(c, p) for p in ch)]
        if not cs: return None, ref
        if ref in POCKET: cs.sort(key=lambda c: (c[4], c[2], r.random()))
        else: cs.sort(key=lambda c: abs(c[3] - TARGET[ref][0]) + r.random() * 0.6)
        ch.append(cs[0])
    return ch, None
cnt = 0
for ti, tr in enumerate(triples[:int(sys.argv[2]) if len(sys.argv) > 2 else 300]):
    for sd in range(6):
        ch, miss = greedy(tr, sd)
        if ch is None: break
        m, h = mates_ok(ch), hard_ok(ch)
        if not h:
            print('triple', ti, round(tr[0], 2), 'seed', sd, 'mates bad', m, flush=True)
            if m <= 1:
                print('FOUND', [(c[0], c[1], c[2], c[3], c[4]) for c in ch], flush=True)
                json.dump({c[0]: [c[3], c[4], ((round(P0[c[0]]['rot']) + 90 * c[1] + 180) % 360) - 180, c[2]] for c in ch}, open(R + 'awg_below_result.json', 'w')); sys.exit(0)
print('none', flush=True)
