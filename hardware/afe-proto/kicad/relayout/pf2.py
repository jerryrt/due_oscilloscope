"""PathFinder (negotiated congestion) router for the scratch board, one layer (F.Cu), 0.1 mm grid. Run in the PCB image:

    python3 pf.py BOARD.kicad_pcb OUT_SPEC.py [ITER] [SECONDS]

Fixed copper = every track and via already on BOARD (hi-Z, outputs, AWG_FB, A0/A1, GND stubs and vias, hand trunks). Nets still open
are routed; LR-6 (+3V3A, VNEG) and LR-8 (VREF) groups are separate pseudo nets that may touch only their star / source pads.
Rules honoured as hard blocks: clearance 0.2 (cells within 0.42 of other copper), hi-Z tracks 0.9, edge 0.65, the far-edge band,
LR-5 (sensitive nets 10 mm from U401 / C409), LR-9 (SDA/SCL out of the analog courtyards). Writes ROUTES in Due mm."""
import sys, math, heapq, time, json, os
sys.path.insert(0, 'whatif/_scratch')
import numpy as np
from pcbtools import boardio
from pcbtools.boards import v1 as C
import route_lib as RL

BOARD, OUT = sys.argv[1], sys.argv[2]
ITER = int(sys.argv[3]) if len(sys.argv) > 3 else 25
SECS = float(sys.argv[4]) if len(sys.argv) > 4 else 900
RES = 0.1
X0, Y0, X1, Y1 = RL.X0 - 0.3, RL.Y0 - 0.3, RL.X1 + 0.3, RL.Y1 + 0.3
NX, NY = int(round((X1 - X0) / RES)), int(round((Y1 - Y0) / RES))
INFL = 0.355     # centre to centre 0.4 (0.2 track + 0.2 clearance) must pass: the disk radius is INFL + 0.035
INFL_PAD = 0.26      # centre line of a 0.2 track to a pad edge
INFL_HIZ = float(os.environ.get('INFL_HIZ', '0.9'))
HIZ = set(C.HIZ)
SENS = tuple(C.SENSITIVE)
DIGITAL = tuple(C.DIGITAL)
STAR = {n: ['%s.%s' % k for k in C.STAR[n]] for n in C.STAR}
GROUPS = {}
VREF_SRC = ['%s.%s' % tuple(k) for k in C.VREF_SOURCE]
ANALOG_COURT = C.ANALOG_REFS

b = boardio.read_board(BOARD)


def cell(x, y): return int(round((x - X0) / RES)), int(round((y - Y0) / RES))
def xy(i, j): return X0 + i * RES, Y0 + j * RES


def rect_mask(x0, y0, x1, y1, m):
    i0, j0 = cell(x0 - m, y0 - m); i1, j1 = cell(x1 + m, y1 + m)
    i0, j0 = max(i0, 0), max(j0, 0); i1, j1 = min(i1, NX - 1), min(j1, NY - 1)
    return i0, j0, i1, j1


def stamp_rect(g, x0, y0, x1, y1, m, val=True):
    i0, j0, i1, j1 = rect_mask(x0, y0, x1, y1, m)
    if i0 <= i1 and j0 <= j1:
        ii, jj = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1), indexing='ij')
        gx_, gy_ = X0 + ii * RES, Y0 + jj * RES
        dx = np.maximum(np.maximum(x0 - gx_, gx_ - x1), 0); dy = np.maximum(np.maximum(y0 - gy_, gy_ - y1), 0)
        g[i0:i1 + 1, j0:j1 + 1] |= np.hypot(dx, dy) <= m


_DISK = {}
def disk(m):
    k = round(m, 3)
    if k not in _DISK:
        r = int(math.ceil((m + RES * 0.35) / RES))
        ii, jj = np.meshgrid(np.arange(-r, r + 1), np.arange(-r, r + 1), indexing='ij')
        sel = np.hypot(ii, jj) * RES <= m + RES * 0.35
        _DISK[k] = np.stack([ii[sel], jj[sel]], 1)
    return _DISK[k]


def stamp_cells(g, cells, m):
    c = np.asarray(cells, int).reshape(-1, 2)
    off = disk(m)
    idx = (c[:, None, :] + off[None, :, :]).reshape(-1, 2)
    ok = (idx[:, 0] >= 0) & (idx[:, 0] < NX) & (idx[:, 1] >= 0) & (idx[:, 1] < NY)
    idx = idx[ok]
    g[idx[:, 0], idx[:, 1]] = True


def stamp_seg(g, ax, ay, bx, by, m):
    n = max(2, int(math.hypot(bx - ax, by - ay) / (RES / 2)) + 1)
    pts = [cell(ax + (bx - ax) * t, ay + (by - ay) * t) for t in np.linspace(0, 1, n)]
    stamp_cells(g, sorted(set(pts)), m)


# ------------------------------------------------------------------------------------------------ read the board
pads = []          # dict(ref, pin, net, bb)
for j_ in range(len(b.p_fp)):
    pads.append(dict(ref=b.fp_ref[int(b.p_fp[j_])], pin=str(b.p_pin[j_]), net=b.nets[int(b.p_net[j_])], bb=(float(b.p_bx0[j_]), float(b.p_by0[j_]), float(b.p_bx1[j_]), float(b.p_by1[j_])), th=False))
key = {(p['ref'], p['pin']): p for p in pads}
tracks = []        # (net, ax, ay, bx, by, w)
vias = []          # (net, x, y, d)
for k_ in range(len(b.s_idx)):
    if int(b.s_layer[k_]) == 0:
        tracks.append((b.nets[int(b.s_net[k_])], float(b.s_x0[k_]), float(b.s_y0[k_]), float(b.s_x1[k_]), float(b.s_y1[k_]), float(b.s_w[k_])))
for k_ in range(len(b.v_x)):
    vias.append((b.nets[int(b.v_net[k_])], float(b.v_x[k_]), float(b.v_y[k_]), float(b.v_drill[k_]) + 0.3))

names = sorted({p['net'] for p in pads if p['net']} | {t[0] for t in tracks})
nid = {n: i for i, n in enumerate(names)}

# ------------------------------------------------------------------------------------------------ fixed obstacles per net
net_mask = {n: np.zeros((NX, NY), bool) for n in names}
for p in pads:
    if p['net']:
        stamp_rect(net_mask[p['net']], *p['bb'], INFL_PAD)
for n, ax, ay, bx, by, w in tracks:
    stamp_seg(net_mask[n], ax, ay, bx, by, INFL_HIZ if n in HIZ else INFL)
for n, x, y, d in vias:
    stamp_seg(net_mask[n], x, y, x, y, d / 2 + INFL - 0.1)
for p in pads:                                           # an unconnected pad (no net) is an obstacle for everybody
    if not p['net']:
        for n in names:
            pass
static = np.zeros((NX, NY), bool)
for p in pads:
    if not p['net']:
        stamp_rect(static, *p['bb'], INFL_PAD)
# board edge, far-edge band
ex0, ey0, ex1, ey1 = RL.X0 + 0.25, RL.Y0 + 0.25, RL.X1 - 0.25, RL.Y1 - 0.25
i, j = np.meshgrid(np.arange(NX), np.arange(NY), indexing='ij')
gx, gy = X0 + i * RES, Y0 + j * RES
static |= (gx < ex0) | (gx > ex1) | (gy < ey0) | (gy > ey1)
total = np.zeros((NX, NY), np.int16)
for n in names:
    total += net_mask[n]

# fixed copper connectivity: which pads are already joined
parent = {}
def find(a):
    while parent.setdefault(a, a) != a:
        parent[a] = parent[parent[a]]; a = parent[a]
    return a
def union(a, c): parent[find(a)] = find(c)
for n, ax, ay, bx, by, w in tracks:
    for k, p in key.items():
        if p['net'] != n: continue
        x0, y0, x1, y1 = p['bb']
        for (qx, qy) in ((ax, ay), (bx, by)):
            if x0 - w / 2 - 0.02 <= qx <= x1 + w / 2 + 0.02 and y0 - w / 2 - 0.02 <= qy <= y1 + w / 2 + 0.02:
                union(('pad',) + k, ('t', n, round(ax, 3), round(ay, 3), round(bx, 3), round(by, 3)))
    for m, a2, c2, d2, e2, w2 in tracks:
        if m != n: continue
        for q in ((ax, ay), (bx, by)):
            if abs(q[0] - a2) + abs(q[1] - c2) < 0.02 or abs(q[0] - d2) + abs(q[1] - e2) < 0.02:
                union(('t', n, round(ax, 3), round(ay, 3), round(bx, 3), round(by, 3)), ('t', m, round(a2, 3), round(c2, 3), round(d2, 3), round(e2, 3)))
    for m, vx, vy, vd in vias:
        if m == n and (math.hypot(ax - vx, ay - vy) < 0.05 or math.hypot(bx - vx, by - vy) < 0.05):
            union(('t', n, round(ax, 3), round(ay, 3), round(bx, 3), round(by, 3)), ('v', m, vx, vy))

# ------------------------------------------------------------------------------------------------ nets and terminals
jobs = []          # dict(name, own (net whose fixed mask is the job's own), comps: list of list of pad keys, goals alt)
def comps_of(padkeys):
    c = {}
    for k in padkeys:
        c.setdefault(find(('pad',) + k), []).append(k)
    return list(c.values())

bynet = {}
for p in pads:
    if p['net'] and p['net'] != '/GND':
        bynet.setdefault(p['net'], []).append((p['ref'], p['pin']))
for n, ks in bynet.items():
    if n in STAR or n == '/VREF':
        continue
    comps = comps_of(ks)
    if len(comps) > 1:
        jobs.append(dict(name=n, own=n, comps=comps, star=None))
for rail in C.STAR:
    ingroup = set().union(*C.GROUPS[rail].values())
    GROUPS[rail] = {g: ['%s.%s' % (r, p['pin']) for r in sorted(refs) for p in pads if p['ref'] == r and p['net'] == rail] for g, refs in C.GROUPS[rail].items()}
for n, groups in GROUPS.items():
    stars = [tuple(s.split('.')) for s in STAR[n]]
    hubk = [(p['ref'], p['pin']) for p in pads if p['net'] == n and p['ref'] not in set().union(*C.GROUPS[n].values())]
    jobs.append(dict(name=n + '#star', own=n, comps=[[k] for k in sorted(hubk, key=lambda k: k not in stars)], star=None))
    for gname, gp in groups.items():
        ks = [tuple(s.split('.')) for s in gp if tuple(s.split('.')) in key and key[tuple(s.split('.'))]['net'] == n]
        if not ks: continue
        jobs.append(dict(name=n + '#' + gname, own=n, comps=[ks], star=stars))
vsrc = [tuple(s.split('.')) for s in VREF_SRC]
jobs.append(dict(name='/VREF#src', own='/VREF', comps=[[k] for k in vsrc], star=None))
used = set(vsrc)
for gi, gp in enumerate(C.VREF_BRANCHES):
    ks = [tuple(k) for k in gp if tuple(k) in key and key[tuple(k)]['net'] == '/VREF']
    if gi == 4 and ('R515', '1') in key: ks.append(('R515', '1'))
    used |= set(ks)
    if ks:
        jobs.append(dict(name='/VREF#%d' % gi, own='/VREF', comps=[ks], star=vsrc))
for k in sorted(p_ for p_ in key if key[p_]['net'] == '/VREF' and p_ not in used):
    jobs.append(dict(name='/VREF#x%s%s' % k, own='/VREF', comps=[[k]], star=vsrc))
print('jobs', len(jobs), [j['name'] for j in jobs])

# per-job static mask: other nets' fixed copper (own net's removed), star pads of the same family are neutral
FENCE_RECTS = [r for blk_ in ('REFCAL', 'AWG', 'SCOPE') for r in C.OUTLINE[blk_]]
BOTTOM_OK_BLOCKS = {'POWER', 'EDGE'}
def bottom_ok(job):
    refs = {k_[0] for comp in job['comps'] for k_ in comp} | {k_[0] for k_ in (job['star'] or [])}
    nm = job['own']
    return all(C.BLOCK.get(r_) in BOTTOM_OK_BLOCKS for r_ in refs) and not (nm in HIZ or nm.startswith(SENS)) and not nm.startswith(DIGITAL) and os.environ.get('NOBOTTOM') is None
def job_block(job):
    blk = (total - net_mask[job['own']].astype(np.int16)) > 0
    blk |= static
    nm = job['own']
    for comp in job['comps']:
        for k in comp:
            for c in pad_cells(k):
                blk[c] = False
    for k in (job['star'] or []):
        if k in key:
            for c in pad_cells(k):
                blk[c] = False
    if nm in SENS or nm.startswith(SENS):
        for ref in C.GEN:
            for p in pads:
                if p['ref'] == ref:
                    x0, y0, x1, y1 = p['bb']
                    cxm, cym = (x0 + x1) / 2, (y0 + y1) / 2
                    blk |= np.hypot(gx - cxm, gy - cym) < 10.0
    if nm.startswith(DIGITAL):
        own_refs = {k_[0] for comp in job['comps'] for k_ in comp}
        for k_ in range(len(b.fp_ref)):
            r_ = b.fp_ref[k_]
            if r_ in C.ANALOG_REFS and r_ not in own_refs and not np.isnan(b.fp_cx0[k_]):
                blk |= (gx >= b.fp_cx0[k_]) & (gx <= b.fp_cx1[k_]) & (gy >= b.fp_cy0[k_]) & (gy <= b.fp_cy1[k_])
    bot = static_bot.copy() if bottom_ok(job) else np.ones((NX, NY), bool)
    return np.stack([blk, bot])


static_bot = static.copy()
for (fx0, fy0, fx1, fy1) in FENCE_RECTS:
    static_bot |= (gx >= fx0 - 0.4) & (gx <= fx1 + 0.4) & (gy >= fy0 - 0.4) & (gy <= fy1 + 0.4)
for k_ in range(len(b.fp_ref)):              # LR-1: no bottom copper under an analog part (courtyard + ZONE_PAD 0.3 + half the track)
    if b.fp_ref[k_] in C.ANALOG_REFS and not np.isnan(b.fp_cx0[k_]):
        static_bot |= (gx >= b.fp_cx0[k_] - 0.45) & (gx <= b.fp_cx1[k_] + 0.45) & (gy >= b.fp_cy0[k_] - 0.45) & (gy <= b.fp_cy1[k_] + 0.45)
for n_, x_, y_, d_ in vias:
    stamp_seg(static_bot, x_, y_, x_, y_, d_ / 2 + INFL - 0.1)
from scipy import ndimage as _ndi
VIA_OK = _ndi.distance_transform_edt(~((total > 0) | static)) * RES >= 0.56
occ = np.zeros((2, NX, NY), np.int16)         # dynamic: other jobs' routed copper, per layer
hist = np.zeros((2, NX, NY), np.float32)
routed = {}                                # job name -> (cells array, polylines)
OWNMASK = {}


def pad_cells(k):
    x0, y0, x1, y1 = key[k]['bb']
    i0, j0 = cell(x0, y0); i1, j1 = cell(x1, y1)
    return [(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1) if x0 - 1e-6 <= X0 + i * RES <= x1 + 1e-6 and y0 - 1e-6 <= Y0 + j * RES <= y1 + 1e-6]


DIRS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]


VIA_COST = float(os.environ.get('VIA_COST', '8'))
BOT_COST = float(os.environ.get('BOT_COST', '3'))
def astar(starts, goals, blk, pres, win):
    """starts, goals: sets of (l,i,j) cells; returns the path list or None. win = (i0, j0, i1, j1)"""
    i0, j0, i1, j1 = win
    gi0 = min(g[1] for g in goals); gi1 = max(g[1] for g in goals); gj0 = min(g[2] for g in goals); gj1 = max(g[2] for g in goals)
    def h(i, j):
        dx = max(gi0 - i, 0, i - gi1); dy = max(gj0 - j, 0, j - gj1)
        return (max(dx, dy) + 0.414 * min(dx, dy))
    pq = []; best = {}; prev = {}
    for s_ in starts:
        best[s_] = 0.0
        heapq.heappush(pq, (h(s_[1], s_[2]), 0.0, s_))
    while pq:
        f, g0, c = heapq.heappop(pq)
        if g0 > best.get(c, 1e18) + 1e-9:
            continue
        if c in goals:
            path = [c]
            while c in prev:
                c = prev[c]; path.append(c)
            return path[::-1]
        cl, ci, cj = c
        for di, dj, w in DIRS:
            ni, nj = ci + di, cj + dj
            if ni < i0 or ni > i1 or nj < j0 or nj > j1:
                continue
            nb = (cl, ni, nj)
            if blk[cl, ni, nj] and nb not in goals:
                continue
            cost = w * ((1.0 + hist[cl, ni, nj]) * (BOT_COST if cl else 1.0)) + (pres * w if occ[cl, ni, nj] else 0.0)
            ng = g0 + cost
            if ng < best.get(nb, 1e18) - 1e-9:
                best[nb] = ng; prev[nb] = c
                heapq.heappush(pq, (ng + h(ni, nj), ng, nb))
        ol = 1 - cl                                              # a via: both layers free here and around (via pad radius)
        if not blk[0, ci, cj] and not blk[1, ci, cj] and VIA_OK[ci, cj]:
            nb = (ol, ci, cj)
            ng = g0 + VIA_COST + (pres * 2 if occ[ol, ci, cj] else 0.0)
            if ng < best.get(nb, 1e18) - 1e-9:
                best[nb] = ng; prev[nb] = c
                heapq.heappush(pq, (ng + h(ci, cj), ng, nb))
    return None


def cover(path):
    """cells within INFL of the path centre line, per layer (the copper this route denies to others); a via covers both"""
    g = np.zeros((2, NX, NY), bool)
    for l_ in (0, 1):
        cl = [(i, j) for (l, i, j) in path if l == l_]
        if cl:
            stamp_cells(g[l_], cl, INFL)
    nv_ = [(i, j) for a, c in zip(path, path[1:]) if a[0] != c[0] for (l, i, j) in (a,)]
    for (i, j) in nv_:
        for l_ in (0, 1):
            stamp_cells(g[l_], [(i, j)], 0.65)
    return g


def pad_cells3(k):
    return [(0, i, j) for (i, j) in pad_cells(k)]


def route_job(job, pres):
    blk = job_block(job)
    comps = job['comps']
    star = job['star']
    cells = set(); paths = []
    comp_cells = [set(c for k in comp for c in pad_cells3(k)) for comp in comps]
    if star:
        goalsets = [set(c for s in star if s in key for c in pad_cells3(s))]
        tree = comp_cells[0]
        targets = goalsets[0]
        remaining = []
        order = [(tree, targets)]
    else:
        order = None
    ok = True
    if star:
        steps = [(comp_cells[0], goalsets[0])]
    else:
        tree = set(comp_cells[0]); rest = comp_cells[1:]
        steps = []
    allc = []
    def run(starts, goals):
        pts = [c for c in starts] + [c for c in goals]
        bi0 = min(p[1] for p in pts); bi1 = max(p[1] for p in pts); bj0 = min(p[2] for p in pts); bj1 = max(p[2] for p in pts)
        for grow in (60, 150, 400):
            win = (max(bi0 - grow, 0), max(bj0 - grow, 0), min(bi1 + grow, NX - 1), min(bj1 + grow, NY - 1))
            p = astar(starts, goals, blk, pres, win)
            if p:
                return p
        return None
    res = []
    if star:
        p = run(comp_cells[0], goalsets[0])
        if p is None:
            return None
        res.append(p)
        # the other pads of the group join the group's own copper
        tree = set(comp_cells[0]) | set(p)
        for c in comp_cells[1:]:
            pass
        extra = [set(c for k in [kk] for c in pad_cells3(kk)) for comp in comps for kk in comp][1:]
        for c in extra:
            p2 = run(tree, c)
            if p2 is None:
                return None
            res.append(p2); tree |= set(p2) | c
    else:
        tree = set(comp_cells[0])
        rest = comp_cells[1:]
        while rest:
            goals = set().union(*rest)
            p = run(tree, goals)
            if p is None:
                return None
            end = p[-1]
            k = [i for i, c in enumerate(rest) if end in c][0]
            tree |= set(p) | rest[k]
            rest.pop(k)
            res.append(p)
    return res


def polylines(path):
    """[(layer, [(x, y)...])] runs and [(x, y)] vias of a (l, i, j) path"""
    runs = []; vs = []; cur = [path[0]]
    for a, c in zip(path, path[1:]):
        if a[0] != c[0]:
            runs.append(cur); vs.append(xy(a[1], a[2])); cur = [c]
        else:
            cur.append(c)
    runs.append(cur)
    out = []
    for r in runs:
        pts = [xy(c[1], c[2]) for c in r]
        o = [pts[0]]
        for a, c, d in zip(pts, pts[1:], pts[2:]):
            if abs((c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (d[0] - c[0])) > 1e-9:
                o.append(c)
        o.append(pts[-1])
        out.append((r[0][0], [(round(x, 3), round(y, 3)) for x, y in o]))
    return out, [(round(x, 3), round(y, 3)) for x, y in vs]


t0 = time.time()
paths_of = {}
cov_of = {}
pres = 0.5
order = sorted(jobs, key=lambda j: -len(j['comps'][0]))
for it in range(ITER):
    conflicts = 0
    failed = []
    for job in order:
        nm = job['name']
        if nm in cov_of:
            occ -= cov_of[nm]
        r = route_job(job, pres)
        if r is None:
            failed.append(nm); cov_of.pop(nm, None); paths_of.pop(nm, None)
            continue
        cv = np.zeros((2, NX, NY), bool)
        for p in r:
            cv |= cover(p)
        cvi = cv.astype(np.int16)
        pcs = np.array([c for p in r for c in p])
        hit = np.zeros((2, NX, NY), bool)
        hit[pcs[:, 0], pcs[:, 1], pcs[:, 2]] = occ[pcs[:, 0], pcs[:, 1], pcs[:, 2]] > 0
        if hit.any():
            conflicts += 1
            hist[hit] += 1.0
        occ += cvi
        cov_of[nm] = cvi; paths_of[nm] = r
    # conflicts among current routes
    bad = []
    for nm in paths_of:
        others = occ - cov_of[nm]
        pc = np.array([c for p in paths_of[nm] for c in p])
        if (others[pc[:, 0], pc[:, 1], pc[:, 2]] > 0).any():
            bad.append(nm)
    if it == 0 and os.environ.get('DIAG'):
        for nm in failed:
            job = [j for j in jobs if j['name'] == nm][0]
            blk = job_block(job)
            for comp in job['comps']:
                for k in comp:
                    pc = pad_cells(k)
                    ring = []
                    for (ci, cj) in pc[:1]:
                        pass
                    x0, y0, x1, y1 = key[k]['bb']
                    i0, j0 = cell(x0 - 1.5, y0 - 1.5); i1, j1 = cell(x1 + 1.5, y1 + 1.5)
                    sub = blk[i0:i1 + 1, j0:j1 + 1]
                    # who blocks around: nets whose mask covers cells right next to the pad
                    near = [n for n in names if n != job['own'] and net_mask[n][i0:i1 + 1, j0:j1 + 1].any()]
                    seen = set(pc); st = list(pc)
                    while st and len(seen) < 400000:
                        a, c = st.pop()
                        for di, dj, _w in DIRS:
                            q = (a + di, c + dj)
                            if 0 <= q[0] < NX and 0 <= q[1] < NY and q not in seen and not blk[q]:
                                seen.add(q); st.append(q)
                    xs = [xy(*q)[0] for q in seen]; ys = [xy(*q)[1] for q in seen]
                    if k == ('U502', '4'):
                        x0_, y0_, x1_, y1_ = key[k]['bb']; qi, qj = cell((x0_ + x1_) / 2, y1_ + 0.1)
                        qi2, qj2 = cell((x0_ + x1_) / 2, y0_ - 0.1)
                        for (a_, c_) in ((qi, qj), (qi, qj2)):
                            print('PROBE cell', xy(a_, c_), 'static', bool(static[a_, c_]), 'covered by', [n for n in names if net_mask[n][a_, c_]], 'own', job['own'])
                    print('FLOOD', nm, k, len(seen), 'x', round(min(xs), 1), round(max(xs), 1), 'y', round(min(ys), 1), round(max(ys), 1))
                    print('DIAG', nm, k, 'pad cells', len(pc), 'blocked pad cells', sum(1 for c in pc if blk[c]), 'free cells in 1.5mm box', int((~sub).sum()), 'nets near', near[:8])
    if it == 0 and os.environ.get('DUMP'):
        from PIL import Image
        nm, bx0, by0, bx1, by1 = os.environ['DUMP'].split(',')
        job = [j for j in jobs if j['name'] == nm][0]
        blk = job_block(job)
        i0, j0 = cell(float(bx0), float(by0)); i1, j1 = cell(float(bx1), float(by1))
        sub = blk[i0:i1, j0:j1]
        im = Image.new('RGB', (i1 - i0, j1 - j0))
        px = im.load()
        for a in range(i1 - i0):
            for c in range(j1 - j0):
                px[a, (j1 - j0 - 1) - c] = (180, 60, 60) if sub[a, c] else (30, 90, 60)
        for p in pads:
            x0, y0, x1, y1 = p['bb']
            for a in range(max(cell(x0, y0)[0], i0), min(cell(x1, y1)[0], i1)):
                for c in range(max(cell(x0, y0)[1], j0), min(cell(x1, y1)[1], j1)):
                    px[a - i0, (j1 - j0 - 1) - (c - j0)] = (230, 200, 60)
        im = im.resize(((i1 - i0) * 6, (j1 - j0) * 6), Image.NEAREST)
        im.save('dump.png'); print('dumped')
    print('iter %d: %.0fs  routed %d/%d  failed %s  conflicting %d' % (it, time.time() - t0, len(paths_of), len(jobs), failed, len(bad)), flush=True)
    if not failed and not bad:
        break
    if time.time() - t0 > SECS:
        break
    pres = min(pres * 1.8, 300)
    order = sorted(jobs, key=lambda j: (j['name'] not in bad and j['name'] not in failed, -len(j['comps'][0])))

pairs = []
for a in paths_of:
    pc = np.array([c for p in paths_of[a] for c in p])
    for c in paths_of:
        if c != a:
            n = int((cov_of[c][pc[:, 0], pc[:, 1], pc[:, 2]] > 0).sum())
            if n:
                pairs.append((a, c, n, tuple(np.round(xy(*pc[(cov_of[c][pc[:, 0], pc[:, 1], pc[:, 2]] > 0).argmax()][1:]), 1))))
pairs.sort(key=lambda t: -t[2])
print('PAIRS', pairs[:40])
B = RL.Board(BOARD)
segs = []; vsl = []
nb_hop = 0
for nm, rs in paths_of.items():
    net = [j for j in jobs if j['name'] == nm][0]['own']
    for p in rs:
        runs, vv = polylines(p)
        for l_, pl in runs:
            for a_, c_ in zip(pl, pl[1:]):
                segs.append((net, l_, a_, c_, 0.2, nm))
        for (x_, y_) in vv:
            vsl.append((net, x_, y_, nm)); nb_hop += 1
print('vias', len(vsl))
B.add(segs, vsl)
B.save(OUT)
print('wrote', OUT, len(segs), 'segments; failed', [j['name'] for j in jobs if j['name'] not in paths_of], 'conflicting', bad, 'CONFLICTS', len(bad) + len([j for j in jobs if j['name'] not in paths_of]))
