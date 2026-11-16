"""AFE-2 relayout, phase 1: placement of every block with a label zone above every part (owner convention 2026-11-15).

    python3 relayout_place.py DUMP.json OUT.json BLOCK [seed] [iters]       (in the PCB image; BLOCK = POWER REFCAL CH1 AWG)

Translation only: a part keeps its rotation. A block is a union of rectangles (REGIONS); a part's extent (courtyard plus the extent of its own
silk) must lie inside it, and so must the box of its label, 0.3 mm from the outline for the label (the outline is silk). The label is the
designator, horizontal, centred over the courtyard, 0.8 mm above its top (silkread's 0-0.6 mm gap to the text box, with the text
1.2 mm high here); its zone is the box grown by 0.3 mm. Hard rules, as depth of overlap (summed, scaled by 400, zero in a good placement):
  extent / extent 0.05 mm; zone / foreign extent; label / label 0.5 mm; label and extent inside the block (erosion by 0.3 / 0.2 mm);
  parts off the lanes kept free for the A0 / A1 traces through AWG; U401 and its flying capacitor 10 mm from every other block (LR-5).
Wirelength: half-perimeter per net with the net's weight (WEIGHT), the pads of fixed parts and of other blocks included as terminals;
decoupling capacitors are tied to their IC (TIES). CH2 is not placed here: its mock-up positions are read from CH2_PLACE.
"""
import json, math, os, random, sys
import numpy as np
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
FIXED = {'J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607', 'J101', 'J201', 'J301', 'MH601', 'MH602', 'U101'}
# the blocks, Due mm. A block is one contiguous union; REFCAL has no separate small box any more.
REGIONS = {
    'POWER': [(17.9, 4.6, 43.6, 26.0), (17.9, 26.0, 34.0, 37.0)],
    'REFCAL': [(44.2, 4.6, 58.4, 27.8), (44.2, 27.8, 62.0, 38.0), (44.2, 38.0, 57.4, 47.5), (34.6, 26.6, 44.2, 48.9)],
    'CH1': [(62.4, 33.0, 93.0, 50.0), (58.0, 38.6, 62.4, 50.0)],
    'CH2': [(69.0, 19.75, 93.0, 32.9)],
    'AWG': [(59.0, 4.55, 92.3, 18.4), (70.4, 18.4, 92.3, 19.25)],
}
LANES = [(65.3, 4.6, 66.8, 18.4), (67.9, 4.6, 69.3, 18.4)]      # A1 (x 66.04) and A0 (x 68.58) cross AWG to J602: no part stands in them
BLOCK_DIGIT = {'1': 'CH1', '2': 'CH2', '3': 'AWG', '4': 'POWER', '5': 'REFCAL'}
LAB_H, LAB_W, LAB_UP, ZONE, LAB_GAP, EXT_GAP = 1.3, 0.95, 0.8, 0.3, 0.5, 0.05
RES = 0.05
J501_TEXTS = {'ON': (2.62, -3.01, 1.4, 2.2), 'CAL': (-0.2, -3.46, 1.4, 3.1)}   # offset from J501's origin and the box of the vertical text
WEIGHT = {}
for n in ('CH1_IN', 'CH1_M1', 'CH1_M2', 'CH1_M3', 'CH1_N', 'CH1_NP'): WEIGHT['/' + n] = 9
for n in ('AWG_FB', 'AWG_BIN', 'AWG_OA', 'AWG_OB', 'AWG_BNC'): WEIGHT['/' + n] = 6
WEIGHT.update({'/AWG_VO': 3, '/AWG_VREF': 2})
for n in ('LM_C1N', 'LM_C1P', 'LM_CP', 'LM_FB3M', 'LM_FBN', 'LM_FBP', '/+5V_F', 'VNEG_G'): WEIGHT['/' + n.lstrip('/')] = 6
WEIGHT.update({'/VNEG': 3, '/VNEG_G': 4, '/GND': 0, '/+3V3A': 0.3, '/VREF': 0.6, '/A0': 1, '/A1': 1})
for n in ('TAP1', 'TAP2', 'TAP3', 'TAP4', 'TAP5', 'SNS_T0', 'SNS_B', 'SNS_B_N', 'ADS_TAP', 'ADS_B', 'TAP4_A'): WEIGHT['/' + n] = 2.5
TIES = [('C503', 'U502', 3), ('C502', 'U501', 3), ('C501', 'U501', 3), ('C305', 'U301', 2), ('C306', 'U301', 2), ('C303', 'U301', 2), ('C304', 'U301', 2),
        ('C401', 'U401', 3), ('C402', 'U401', 3), ('C403', 'U401', 3), ('C404', 'U401', 3), ('C405', 'U401', 2), ('C406', 'U401', 2), ('C409', 'U401', 4),
        ('C104', 'U101', 3), ('C105', 'U101', 3)]


def box_u(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])) if a else tuple(b)


def depth(a, B, g):
    """sum over rows of B of the penetration depth of box a into it with gap g"""
    dx = np.minimum(a[2], B[:, 2]) - np.maximum(a[0], B[:, 0]) + g
    dy = np.minimum(a[3], B[:, 3]) - np.maximum(a[1], B[:, 1]) + g
    return float(np.where((dx > 0) & (dy > 0), np.minimum(dx, dy), 0.0).sum())


class Mask:
    def __init__(self, rects, inset):
        self.x0, self.y0 = 15.0, -6.0
        nx, ny = int(105 / RES), int(66 / RES)
        m = np.zeros((nx, ny), bool)
        for r in rects:
            m[int(round((r[0] - self.x0) / RES)):int(round((r[2] - self.x0) / RES)), int(round((r[1] - self.y0) / RES)):int(round((r[3] - self.y0) / RES))] = True
        e = ndimage.distance_transform_edt(np.pad(m, 1)) [1:-1, 1:-1]
        good = e * RES >= inset - 1e-9
        bad = (~good).astype(np.int64)
        self.S = np.zeros((nx + 1, ny + 1), np.int64)
        self.S[1:, 1:] = bad.cumsum(0).cumsum(1)
        self.nx, self.ny = nx, ny

    def bad(self, b):
        i0 = max(int(math.floor((b[0] - self.x0) / RES + 1e-6)), 0); i1 = min(int(math.ceil((b[2] - self.x0) / RES - 1e-6)), self.nx)
        j0 = max(int(math.floor((b[1] - self.y0) / RES + 1e-6)), 0); j1 = min(int(math.ceil((b[3] - self.y0) / RES - 1e-6)), self.ny)
        if i1 <= i0 or j1 <= j0:
            return 1e3
        n = self.S[i1, j1] - self.S[i0, j1] - self.S[i1, j0] + self.S[i0, j0]
        out = (max(0, -(b[0] - self.x0)) + max(0, (b[2] - self.x0) - self.nx * RES) + max(0, -(b[1] - self.y0)) + max(0, (b[3] - self.y0) - self.ny * RES))
        return float(n) * RES * RES * 4 + out * 10


def load(dump):
    D = json.load(open(dump))
    P = {p['ref']: p for p in D['parts']}
    return D, P


def block_of(ref):
    return BLOCK_DIGIT[ref[-3]] if ref not in FIXED else None


def part_geom(p):
    """rel boxes of a part about its origin: ext (courtyard + own silk), cyr, lab (label ink box), zone"""
    x, y = p['x'], p['y']
    cy = p['cy']; ext = list(cy)
    if p['silk']:
        ext = list(box_u(ext, p['silk']))
    r = lambda b: (b[0] - x, b[1] - y, b[2] - x, b[3] - y)
    cyr, extr = r(cy), r(ext)
    if p['ref'] == 'J501':                      # its function texts "ON" and "CAL" go with it, below the courtyard (J501_TEXTS)
        for (ox, oy, tw, th) in J501_TEXTS.values():
            extr = box_u(extr, (ox - tw / 2, oy - th / 2, ox + tw / 2, oy + th / 2))
    n = len(p['ref']); w = LAB_W * n
    cx = (cyr[0] + cyr[2]) / 2
    ly = max(cyr[3] + LAB_UP, (extr[3] + 0.3 + LAB_H / 2) if p['silk'] else 0)
    lab = (cx - w / 2, ly - LAB_H / 2, cx + w / 2, ly + LAB_H / 2)
    return dict(ext=extr, cy=cyr, lab=lab, zone=(lab[0] - ZONE, lab[1] - ZONE, lab[2] + ZONE, lab[3] + ZONE), ly=ly, gap=lab[1] + 0.1 - cyr[3])


def seg_dist_rect(rects, pt):
    best = 1e9
    for r in rects:
        dx = max(r[0] - pt[0], 0, pt[0] - r[2]); dy = max(r[1] - pt[1], 0, pt[1] - r[3]); best = min(best, math.hypot(dx, dy))
    return best


def run(dump, out, blk, seed=1, iters=100000, pos0=None, fixed_pos=None):
    D, P = load(dump)
    G = {r: part_geom(p) for r, p in P.items()}
    mine = [r for r in P if block_of(r) == blk and r not in FIXED]
    cur = {r: (P[r]['x'], P[r]['y']) for r in P}
    if fixed_pos: cur.update({k: tuple(v) for k, v in fixed_pos.items()})
    # fixed obstacles: extents of fixed parts (U101 and its label too) and the vias that remain
    fx_ext, fx_zone = [], []
    for r in FIXED:
        g = G[r]; x, y = cur[r]
        fx_ext.append((g['ext'][0] + x, g['ext'][1] + y, g['ext'][2] + x, g['ext'][3] + y))
    u = G['U101']; ux, uy = cur['U101']
    fx_lab = [(u['lab'][0] + ux, u['lab'][1] + uy, u['lab'][2] + ux, u['lab'][3] + uy)]
    for r in FIXED:                                  # the labels of the fixed parts stay where they are (the headers' cannot be placed by the rule)
        if r in ('J601', 'J602', 'J605', 'U101') or r.startswith('J1') or r.startswith('J2') or r.startswith('J3'): continue
        p = P[r]; w, h = LAB_W * len(r), LAB_H
        if abs((p['tang'] % 180) - 90) < 1: w, h = h, w
        fx_lab.append((p['tx'] - w / 2, p['ty'] - h / 2, p['tx'] + w / 2, p['ty'] + h / 2))
    fx_ext, fx_lab = np.array(fx_ext), np.array(fx_lab)
    lanes = np.array(LANES) if blk == 'AWG' else np.zeros((0, 4))
    mext, mlab = Mask(REGIONS[blk], 0.2), Mask(REGIONS[blk], 0.4)
    others = [r for b, rs in REGIONS.items() if b != blk for r in rs]
    # nets
    nets = {}
    for r, p in P.items():
        for q in p['pads']:
            nets.setdefault(q['net'], []).append((r, q['c'][0] - p['x'], q['c'][1] - p['y']))
    idx = {r: i for i, r in enumerate(mine)}
    netl = []
    for n, pins in nets.items():
        w = WEIGHT.get(n, 1.0)
        if w <= 0 or len(pins) < 2 or n.startswith('/unconnected') or not any(r in idx for r, _, _ in pins):
            continue
        mv = [(idx[r], dx, dy) for r, dx, dy in pins if r in idx]
        term = [(cur[r][0] + dx, cur[r][1] + dy) for r, dx, dy in pins if r not in idx]
        netl.append((w, mv, term))
    of = {i: [k for k, (_, mv, _) in enumerate(netl) if any(m[0] == i for m in mv)] for i in range(len(mine))}
    ties = [(idx[a], b, 4 * w) for a, b, w in TIES if a in idx and (b in idx or b in cur)]
    n = len(mine)
    ext0 = np.array([G[r]['ext'] for r in mine]); lab0 = np.array([G[r]['lab'] for r in mine]); zon0 = np.array([G[r]['zone'] for r in mine])
    cy0 = np.array([G[r]['cy'] for r in mine])
    st = np.zeros((n, 2))
    rnd = random.Random(seed)
    rb = [min(r[0] for r in REGIONS[blk]), min(r[1] for r in REGIONS[blk]), max(r[2] for r in REGIONS[blk]), max(r[3] for r in REGIONS[blk])]
    for i, r in enumerate(mine):
        st[i] = pos0[r] if pos0 and r in pos0 else (rnd.uniform(rb[0] + 2, rb[2] - 2), rnd.uniform(rb[1] + 2, rb[3] - 2))
    keep10 = [r for r in ('U401', 'C409', 'C403') if r in idx] if blk == 'POWER' else []

    def hp(k):
        w, mv, term = netl[k]
        xs = [st[i][0] + dx for i, dx, dy in mv] + [t[0] for t in term]; ys = [st[i][1] + dy for i, dx, dy in mv] + [t[1] for t in term]
        return w * ((max(xs) - min(xs)) + (max(ys) - min(ys)))

    def own(i, pos):
        e = ext0[i] + np.array([pos[0], pos[1], pos[0], pos[1]]); lb = lab0[i] + np.array([pos[0], pos[1], pos[0], pos[1]]); z = zon0[i] + np.array([pos[0], pos[1], pos[0], pos[1]])
        v = mext.bad(e) + mlab.bad(lb)
        v += depth(e, fx_ext, EXT_GAP) + depth(z, fx_ext, 0) + depth(lb, fx_lab, LAB_GAP) + depth(e, fx_lab, 0.3) + depth(e, lanes, 0.0)
        for r in keep10:
            if r == mine[i]:
                v += max(0.0, 12.6 - min(seg_dist_rect(rs, (pos[0] + (cy0[i][0] + cy0[i][2]) / 2, pos[1] + (cy0[i][1] + cy0[i][3]) / 2)) for rs in [[q for q in others]])) * 3
        return v

    def pairs(i, pos):
        o = [j for j in range(n) if j != i]
        if not o: return 0.0
        e = ext0[i] + np.array([pos[0], pos[1], pos[0], pos[1]]); lb = lab0[i] + np.array([pos[0], pos[1], pos[0], pos[1]]); z = zon0[i] + np.array([pos[0], pos[1], pos[0], pos[1]])
        sh = np.concatenate([st[o], st[o]], axis=1)
        E = ext0[o] + sh; L = lab0[o] + sh; Z = zon0[o] + sh
        return depth(e, E, EXT_GAP) + depth(z, E, 0) + depth(lb, L, LAB_GAP) + sum(depth(Z[k:k + 1][0], e[None, :], 0) for k in range(0))

    def tie(i, pos):
        t = 0.0
        for a, b, w in ties:
            if a == i:
                pb = st[idx[b]] if b in idx else cur[b]
            elif b in idx and idx[b] == i:
                pb = st[a]; 
            else:
                continue
            t += w * math.hypot(pos[0] - pb[0], pos[1] - pb[1])
        return t

    def zpairs(i, pos):
        """zone of i against the extents of the others, and the zones of the others against i's extent"""
        o = [j for j in range(n) if j != i]
        if not o: return 0.0
        sh = np.concatenate([st[o], st[o]], axis=1)
        e = ext0[i] + np.array([pos[0], pos[1], pos[0], pos[1]])
        return depth(e, zon0[o] + sh, 0)

    def total(i, pos):
        return own(i, pos) + pairs(i, pos) + zpairs(i, pos)

    def energy():
        wl = sum(hp(k) for k in range(len(netl)))
        v = sum(own(i, st[i]) for i in range(n)) + 0.5 * sum(pairs(i, st[i]) + zpairs(i, st[i]) for i in range(n))
        return wl + sum(tie(i, st[i]) for i in range(n)) * 1.0, v
    wl, v = energy()
    E = wl + 400 * v
    best = (E, st.copy(), wl, v)
    T0 = 25.0
    for it in range(iters):
        T = T0 * (1 - it / iters) ** 2 + 0.02
        i = rnd.randrange(n)
        old = st[i].copy()
        sc = 0.15 + 3.0 * T / T0
        if rnd.random() < 0.03:
            new = np.array([rnd.uniform(rb[0], rb[2]), rnd.uniform(rb[1], rb[3])])
        else:
            new = np.array([round((old[0] + rnd.gauss(0, sc)) * 20) / 20, round((old[1] + rnd.gauss(0, sc)) * 20) / 20])
        o_t = total(i, old) ; o_w = sum(hp(k) for k in of[i]); o_ti = tie(i, old)
        st[i] = new
        n_t = total(i, new); n_w = sum(hp(k) for k in of[i]); n_ti = tie(i, new)
        d = (n_w - o_w) + (n_ti - o_ti) + 400 * (n_t - o_t)
        if d <= 0 or rnd.random() < math.exp(-d / T):
            E += d
            if E < best[0] - 1e-9:
                best = (E, st.copy(), 0, 0)
        else:
            st[i] = old
    st[:] = best[1]
    wl, v = energy()
    res = {r: [round(float(st[idx[r]][0]), 2), round(float(st[idx[r]][1]), 2)] for r in mine}
    json.dump(dict(blk=blk, seed=seed, wl=wl, viol=v, st=res), open(out, 'w'))
    print(blk, 'seed', seed, 'wl %.1f viol %.4f' % (wl, v), 'parts', n)
    return res


if __name__ == '__main__':
    a = sys.argv
    fp = None
    if os.path.exists(os.path.join(os.path.dirname(a[1]), 'place.json')):
        fp = json.load(open(os.path.join(os.path.dirname(a[1]), 'place.json')))['st']      # CH2's mock-up positions
    for extra in a[6:]:                                              # positions of the other blocks from an earlier round
        fp = dict(fp or {}); fp.update(json.load(open(extra))['st'])
    run(a[1], a[2], a[3], int(a[4]) if len(a) > 4 else 1, int(a[5]) if len(a) > 5 else 100000, fixed_pos=fp)
