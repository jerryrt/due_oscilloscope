"""In-memory placement repair for a cluster, D30-label aware. In the image, cwd hand/:
    python3 fastlayout.py BASE.kicad_pcb START.json OUT.json SECONDS SEED [PITCH_ROWS]
BASE: the board (outlines drawn, fixed copper). START.json {ref: [x, y, rot]}. Parts in START are movable; everything else is fixed, labels of fixed parts too.
Hard constraints, counted as violations: courtyards of any two parts overlap, a courtyard in an A1/A0 lane or outside the region, LR-12 (cap pad to IC pin <= 3.0), LR-2
(R501 R506 U501 U502 >= 10 mm from U401 / C409), LR-5, and a label: every moved part needs a place for its designator ABOVE it (rule 1: centred to 0.3, gap 0 to 0.6)
clear of every courtyard, pad, silk line and other label (0.5 mm), except the parts the board already lets carry a beside label. Moves: shift, turn by 90 degrees, swap two parts
of one footprint. Random descent with plateau moves; writes the best state."""
import sys, json, random, math, re, time, os
sys.path.append('/usr/lib/python3/dist-packages'); sys.path.insert(0, '/work/hardware/afe-proto')
import pcbnew
from pcbtools import silkread
base, start, out, secs, seed = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), int(sys.argv[5])
random.seed(seed)
mm = pcbnew.ToMM
b = pcbnew.LoadBoard(base)
REG = tuple(float(v) for v in os.environ.get('REGBOX', '45.8,4.9,64.7,27.5').split(','))
AWGBOX = tuple(float(v) for v in os.environ.get('AWGBOX', '69.5,4.6,92.0,19.2').split(','))
AWGW = ('TP301', 'C303', 'C304', 'R305', 'R307')
LANES = [(65.3, 4.6, 66.8, 18.4), (67.9, 4.6, 69.3, 18.4)]
BESIDE_OK = set(eval(re.search(r'BESIDE = (\{.*?\})\n', open('/work/hardware/afe-proto/tests/pcbtools/test_silkread.py').read(), re.S).group(1))['v2/layout/integrated/afe-v2-integrated.kicad_pcb'])
BESIDE_OK |= set(eval(re.search(r'EAST_END = (\{.*?\})\n', open('/work/hardware/afe-proto/tests/pcbtools/test_silkread.py').read(), re.S).group(1))['v2/layout/integrated/afe-v2-integrated.kicad_pcb'])
def X(v): return mm(v) - 50.0
def Y(v): return 150.0 - mm(v)
class Part: pass
P = {}
for f in b.GetFootprints():
    p = Part(); p.ref = f.GetReference(); p.x, p.y, p.rot = X(f.GetPosition().x), Y(f.GetPosition().y), round(f.GetOrientationDegrees()) % 360
    c = f.GetCourtyard(pcbnew.F_CrtYd).BBox(); p.court = (X(c.GetX()), Y(c.GetBottom()), X(c.GetRight()), Y(c.GetY()))
    p.pads = []
    for q in f.Pads():
        bb = q.GetBoundingBox(); p.pads.append((q.GetNumber(), q.GetNetname(), (X(bb.GetX()), Y(bb.GetBottom()), X(bb.GetRight()), Y(bb.GetY())), (X(q.GetPosition().x), Y(q.GetPosition().y))))
    r = f.Reference(); p.lab = (X(r.GetPosition().x), Y(r.GetPosition().y), mm(r.GetTextWidth()), mm(r.GetTextHeight()), r.GetTextAngleDegrees())
    P[p.ref] = p
silk = silkread.read_silk(open(base).read())
S = json.load(open(start))
MOV = sorted(S)
def rect_rot(rc, k, ox, oy):                     # rotate a rect about (ox, oy) by k * 90 degrees ccw (y up)
    x0, y0, x1, y1 = rc[0] - ox, rc[1] - oy, rc[2] - ox, rc[3] - oy
    for _ in range(k % 4):
        x0, y0, x1, y1 = -y1, x0, -y0, x1
    return (x0, y0, x1, y1)
def pt_rot(pt, k, ox, oy):
    x, y = pt[0] - ox, pt[1] - oy
    for _ in range(k % 4): x, y = -y, x
    return (x, y)
cur0 = {r: (P[r].x, P[r].y, P[r].rot) for r in MOV}      # what the board has
def geom(r, st):
    p = P[r]; x, y, rot = st; k = ((rot - p.rot) // 90) % 4
    c = rect_rot(p.court, k, p.x, p.y); court = (c[0] + x, c[1] + y, c[2] + x, c[3] + y)
    pads = []
    for num, net, bb, ctr in p.pads:
        q = rect_rot(bb, k, p.x, p.y); cc = pt_rot(ctr, k, p.x, p.y)
        pads.append((num, net, (q[0] + x, q[1] + y, q[2] + x, q[3] + y), (cc[0] + x, cc[1] + y)))
    return court, pads
G = {r: geom(r, S[r]) for r in MOV}
for r, p in P.items():
    if r not in G: G[r] = (p.court, [(n, nt, bb, ct) for n, nt, bb, ct in p.pads])
mx0 = min(G[r][0][0] for r in MOV) - 4.0; my0 = min(G[r][0][1] for r in MOV) - 4.0; mx1 = max(G[r][0][2] for r in MOV) + 4.0; my1 = max(G[r][0][3] for r in MOV) + 4.0
RELAB = {r for r, p in P.items() if r not in MOV and not r.startswith(('MH', 'J101', 'J201', 'J301', 'U401', 'U101')) and p.court[0] >= mx0 and p.court[2] <= mx1 and p.court[1] >= my0 and p.court[3] <= my1}
RELAB |= {'J602'}
LABSET = sorted(set(MOV) | RELAB, key=lambda r: (r not in BESIDE_OK, r))
print('labels solved for', len(LABSET), 'parts (', len(RELAB), 'neighbours)', sorted(RELAB), flush=True)
FIXLAB = {r: (lambda bx: (bx[0] - 0.0, bx[1] - 0.1, bx[2], bx[3] + 0.1))(silkread.text_box(r, p.lab[0], p.lab[1], p.lab[2] * 0.95 / 0.9, p.lab[3], p.lab[4])) for r, p in P.items() if r not in LABSET and not r.startswith('MH')}
def ov(a, c, m=0.0): return min(a[2], c[2]) - max(a[0], c[0]) > m and min(a[3], c[3]) - max(a[1], c[1]) > m
GEN = [ct for r in ('U401', 'C409') for _, _, _, ct in P[r].pads]
SENSP = ('/A0', '/A1', '/VREF', '/TAP', '/SNS', '/AWG_BNC', '/ADS_', '/CH1_N', '/CH2_N')
LASTLAB = {}
def viol(st, moved=None):
    global cur_st
    LASTLAB.clear()
    cur_st = st
    v = 0; det = []
    refs = list(MOV)
    for r in refs:
        c = G[r][0]
        rg = AWGBOX if r in AWGW else REG
        if not (c[0] >= rg[0] and c[1] >= rg[1] and c[2] <= rg[2] and c[3] <= rg[3]): v += 1; det.append('region ' + r)
        for l in LANES:
            if ov(c, l): v += 1; det.append('lane ' + r)
        for o, (c2, _) in G.items():
            if o != r and (o not in MOV or o > r) and ov(c, c2): v += 1; det.append('court %s/%s' % (r, o))
    for r in MOV:                                   # LR-11: the origin lies in its own block's outline and in no other's
        x, y = cur_st[r][0], cur_st[r][1]
        inr = (45.5 <= x <= 65.0 and 4.6 <= y <= 27.8); ina = (69.5 <= x <= 92.25 and 4.55 <= y <= 19.25)
        if (r in AWGW and not ina) or (r not in AWGW and not inr): v += 2; det.append('outline ' + r)
    for cap, ic, pin in (('C502', 'U501', '1'), ('C501', 'U501', '2'), ('C503', 'U502', '8')):
        tgt = [ct for n, nt, bb, ct in G[ic][1] if n == pin][0]; tn = [nt for n, nt, bb, ct in G[ic][1] if n == pin][0]
        ks = [ct for n, nt, bb, ct in G[cap][1] if nt == tn] or [G[cap][1][0][3]]
        if min(math.hypot(k[0] - tgt[0], k[1] - tgt[1]) for k in ks) > 3.0: v += 3; det.append('LR-12 ' + cap)
    for r in ('R501', 'R506', 'U501', 'U502'):
        for n, nt, bb, ct in G[r][1]:
            if min(math.hypot(ct[0] - g[0], ct[1] - g[1]) for g in GEN) < 10.0: v += 3; det.append('LR-2 ' + r); break
    for r in MOV:
        for n, nt, bb, ct in G[r][1]:
            if nt.startswith(SENSP) and min(math.hypot(ct[0] - g[0], ct[1] - g[1]) for g in GEN) < 10.0: v += 3; det.append('LR-5 ' + r); break
    # labels
    allpads = [bb for r, (c, ps) in G.items() for _, _, bb, _ in ps]
    allc = [c for r, (c, ps) in G.items()]
    placed = {}
    for r in LABSET:
        c = G[r][0]; w = len(r) * 0.95; h = 1.2; cx, cy = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2; ok = False
        cs = [(cx + dx, c[3] + g + 0.5) for g in (0.3, 0.0, 0.5, 0.15, 0.45) for dx in (0.0, -0.15, 0.15, -0.3, 0.3)]
        if r in BESIDE_OK:                          # a part the board labels beside keeps its label beside (rules 2a, 2b): never above
            cs = [((c[2] + g + w / 2) if sd > 0 else (c[0] - g - w / 2), cy + dy) for sd in (1, -1) for g in (0.3, 0.0, 0.5) for dy in (0.0, 0.15, -0.15, 0.3, -0.3)]
        for (x, y) in cs:
            bx = (x - w / 2, y - h / 2, x + w / 2, y + h / 2)
            if any(ov(bx, cc) for cc in allc) or any(ov(bx, pp) for pp in allpads): continue
            if any(silkread._on_shape(bx, sh) for sh in silk): continue
            if any(silkread._gap(bx, o) < 0.55 for o in list(FIXLAB.values()) + list(placed.values())): continue
            placed[r] = bx; LASTLAB[r] = (x, y); ok = True; break
        if not ok: v += 1; det.append('label ' + r)
    return v, det
def apply(st, r, new):
    old = st[r]; st[r] = new; G[r] = geom(r, new); return old
cur = {r: list(v) for r, v in S.items()}
best, det = viol(cur)
print('start violations', best, det, flush=True)
DISP_W = float(os.environ.get('DISP_W', '1.0'))
REF = json.load(open(os.environ['REFJSON'])) if os.environ.get('REFJSON') else S
def disp(st): return sum(abs(st[r][0] - REF[r][0]) + abs(st[r][1] - REF[r][1]) + (0.5 if st[r][2] != REF[r][2] else 0.0) for r in MOV)
bd = disp(cur)
t0 = time.time(); n = 0
disp0 = {r: S[r][:2] for r in MOV}
while time.time() - t0 < secs:
    n += 1
    r = random.choice(MOV); mv = random.choice(['shift', 'shift', 'shift', 'turn', 'swap', 'jump'] if r in AWGW else ['shift', 'shift', 'shift', 'turn', 'swap'])
    old = list(cur[r]); old2 = None
    if mv == 'shift':
        dx, dy = random.choice([(0.05, 0), (-0.05, 0), (0, 0.05), (0, -0.05), (0.1, 0), (-0.1, 0), (0, 0.1), (0, -0.1), (0.25, 0), (-0.25, 0), (0, 0.25), (0, -0.25), (0.5, 0), (-0.5, 0), (0, 0.5), (0, -0.5), (1, 0), (-1, 0), (0, 1), (0, -1), (2, 0), (-2, 0), (0, 2), (0, -2)])
        new = [old[0] + dx, old[1] + dy, old[2]]
    elif mv == 'turn':
        new = [old[0], old[1], (old[2] + random.choice([90, 180, 270])) % 360]
    elif mv == 'jump':
        rg = AWGBOX; new = [round(random.uniform(rg[0] + 1, rg[2] - 1), 1), round(random.uniform(rg[1] + 1, rg[3] - 1), 1), old[2]]
    else:
        same = [o for o in MOV if o != r and o[0] == r[0] and o[0] in 'RC' and ((o in AWGW) == (r in AWGW)) and P[o].court[2] - P[o].court[0] == P[r].court[2] - P[r].court[0]]
        if not same: continue
        o = random.choice(same); old2 = list(cur[o]); new = [old2[0], old2[1], old2[2]]; new2 = [old[0], old[1], old[2]]
    apply(cur, r, new)
    if old2 is not None: apply(cur, o, new2)
    v, d = viol(cur); dd = disp(cur)
    if v < best or (v == best and dd <= bd + float(os.environ.get('DISP_TOL', '0.0' if os.environ.get('REFJSON') else '0.02'))):
        best, det, bd = v, d, dd
    else:
        apply(cur, r, old)
        if old2 is not None: apply(cur, o, old2)
    if n % 4000 == 0: print('n', n, 'best', best, det, 'disp', round(bd, 1), round(time.time() - t0), flush=True)
print('done', n, 'moves; violations', best, det, 'displacement', round(bd, 1), flush=True)
json.dump({r: [round(v[0], 3), round(v[1], 3), v[2]] for r, v in cur.items()}, open(out, 'w'))
viol(cur)
json.dump({r: [round(v[0], 3), round(v[1], 3)] for r, v in LASTLAB.items()}, open(out.replace('.json', '_labels.json'), 'w'))
