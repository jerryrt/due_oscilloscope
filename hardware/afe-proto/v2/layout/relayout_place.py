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
    'POWER': [(17.9, 4.6, 34.5, 26.0), (34.5, 6.2, 39.2, 26.0), (39.2, 4.6, 43.6, 26.0), (17.9, 26.0, 34.0, 37.0)],
    'REFCAL': [(44.2, 4.6, 57.4, 27.8), (44.2, 27.8, 62.0, 38.0), (44.2, 38.0, 57.4, 47.1), (34.6, 26.6, 44.2, 48.9)],
    'CH1': [(62.4, 33.0, 74.9, 49.0), (74.9, 33.0, 80.1, 47.1), (80.1, 33.0, 92.25, 49.0), (58.0, 38.6, 62.4, 49.0)],
    'CH2': [(69.0, 19.75, 92.25, 32.9)],
    'AWG': [(59.0, 6.2, 62.2, 18.4), (62.2, 4.55, 80.0, 18.4), (80.0, 6.2, 84.9, 18.4), (84.9, 4.55, 92.25, 18.4), (70.4, 18.4, 92.25, 19.25), (59.0, 18.4, 65.0, 27.4)],
}
# the Due's edge-row headers carry their designator on the inboard side, centred along the header (owner, bcbc1e3d): the blocks give up a strip there,
# as a notch only where the label stands. {ref: (centre x, centre y of the label)}; the header's courtyard is (x0, y0, x1, y1) in the dump
HEADER_LABEL_H = 0.5
LANES = [(65.3, 4.6, 66.8, 18.4), (67.9, 4.6, 69.3, 18.4)]      # A1 (x 66.04) and A0 (x 68.58) cross AWG to J602: no part stands in them
BLOCK_DIGIT = {'1': 'CH1', '2': 'CH2', '3': 'AWG', '4': 'POWER', '5': 'REFCAL'}
LAB_H, LAB_W, LAB_UP, ZONE, LAB_GAP, EXT_GAP = float(os.environ.get('RP_LABH', 1.3)), float(os.environ.get('RP_LABW', 0.95)), 0.8, float(os.environ.get('RP_ZONE', 0.3)), float(os.environ.get('RP_GAP', 0.5)), 0.02
RES = 0.05
SOFT_W = 8.0
CLUSTER_FREE = {'C104', 'C105', 'R108', 'R107', 'R207', 'R208'}   # the U101 cluster's passives may stand vertical (owner, d5dafbf3 round)
J501_TEXTS = {'ON': (2.54, -2.81, 2.2, 1.4), 'CAL': (-2.54, -2.81, 3.1, 1.4)}   # horizontal, one under pin 3 and one under pin 1: centre offset from J501's origin and the box (text + 0.2 mm all round)
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


COS = (1.0, 0.0, -1.0, 0.0)
SIN = (0.0, 1.0, 0.0, -1.0)
ROTATABLE = ('R', 'C', 'BR')                          # two-pad passives turn in 90 degree steps; the label stays horizontal, centred above the turned courtyard


def rot_box(b, k):
    c, s_ = COS[k], SIN[k]
    pts = [(x * c - y * s_, x * s_ + y * c) for x in (b[0], b[2]) for y in (b[1], b[3])]
    return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))


def rotatable(ref):
    return ref.startswith(ROTATABLE)


LSHIFT = [(dx, dy) for dx in (0.0, -0.25, 0.25) for dy in (0.0, 0.25)]   # the label may sit up to 0.25 mm off centre and 0.25 mm higher (silkread allows 0.3 and 0.6)


import re
PAS = re.compile(r'(?:R|C|BR|L|FB)(\d)\d\d$')
ROW_LY = 1.85                    # a horizontal passive's label centre above its origin: one height for a whole row (align.py rule 2); gap to the courtyard 0.18-0.6


def orient(p, k):
    return round((p['rot'] + 90 * k) % 180.0) % 180


def part_geom(p, k=0, ls=0):
    """rel boxes of a part about its origin, turned by k * 90 degrees: ext (courtyard + own silk), cy, lab (label ink box), zone"""
    x, y = p['x'], p['y']
    cy = p['cy']; ext = list(cy)
    if p['silk']:
        ext = list(box_u(ext, p['silk']))
    r = lambda b: rot_box((b[0] - x, b[1] - y, b[2] - x, b[3] - y), k)
    cyr, extr = r(cy), r(ext)
    if p['ref'] == 'J501':                      # its function texts "ON" and "CAL" go with it, below the courtyard (J501_TEXTS)
        for (ox, oy, tw, th) in J501_TEXTS.values():
            extr = box_u(extr, (ox - tw / 2, oy - th / 2, ox + tw / 2, oy + th / 2))
    n = len(p['ref']); w = LAB_W * n
    cx = (cyr[0] + cyr[2]) / 2
    ly = max(cyr[3] + LAB_UP, (extr[3] + 0.3 + LAB_H / 2) if p['silk'] else 0)
    if PAS.fullmatch(p['ref']) and orient(p, k) == 0:
        ly = min(max(ROW_LY, cyr[3] + 0.5), cyr[3] + 1.1); ls = ls - (ls % 2) if ls < 10 else ls                    # no extra height for a row part
    if ls >= 10:                                                  # beside (silkread 2b): ls 10 east, 11 west of the courtyard, centred in y, 0.3 mm off it
        ly = (cyr[1] + cyr[3]) / 2
        cx = cyr[2] + 0.3 + w / 2 if ls == 10 else cyr[0] - 0.3 - w / 2
    else:
        cx += LSHIFT[ls][0]; ly += LSHIFT[ls][1]
    lab = (cx - w / 2, ly - LAB_H / 2, cx + w / 2, ly + LAB_H / 2)
    return dict(ext=extr, cy=cyr, lab=lab, zone=(lab[0] - ZONE, lab[1] - ZONE, lab[2] + ZONE, lab[3] + ZONE), ly=ly, gap=lab[1] + 0.1 - cyr[3])


def u101_label_east(P, cur=None, ref='U101', k=0):
    """U101's designator horizontal beside its pin-free east end: text west edge 0.3 mm from the courtyard, centred in y on it. Returns (label box, zone box, centre)"""
    x, y = (cur or {}).get(ref, (P[ref]['x'], P[ref]['y']))
    c0 = P[ref]['cy']
    if k:
        r_ = rot_box((c0[0] - P[ref]['x'], c0[1] - P[ref]['y'], c0[2] - P[ref]['x'], c0[3] - P[ref]['y']), k); c0 = (r_[0] + P[ref]['x'], r_[1] + P[ref]['y'], r_[2] + P[ref]['x'], r_[3] + P[ref]['y'])
    c = (c0[0] + x - P[ref]['x'], c0[1] + y - P[ref]['y'], c0[2] + x - P[ref]['x'], c0[3] + y - P[ref]['y']); w = LAB_W * 4
    cx = c[2] + 0.3 + w / 2; cy = (c[1] + c[3]) / 2
    lab = (cx - w / 2, cy - LAB_H / 2, cx + w / 2, cy + LAB_H / 2)
    return lab, (lab[0] - ZONE, lab[1] - ZONE, lab[2] + ZONE, lab[3] + ZONE), (cx, cy)


def seg_dist_rect(rects, pt):
    best = 1e9
    for r in rects:
        dx = max(r[0] - pt[0], 0, pt[0] - r[2]); dy = max(r[1] - pt[1], 0, pt[1] - r[3]); best = min(best, math.hypot(dx, dy))
    return best



ICS = ['U101', 'U301', 'U501', 'U502', 'U401']       # the op-amps, the reference and converter, the rail generator: LR-4's ICs
NOSUP = ('BR', 'TP', 'J', 'MH', 'U')


def header_label(p):
    """centre of the designator of an edge header (owner, bcbc1e3d): a header along x, horizontal, centred along it, below it in the upper half of the board and above it
    in the lower half; J605, along y, above its top end"""
    c = p['cy']; cx = (c[0] + c[2]) / 2
    if (c[2] - c[0]) >= (c[3] - c[1]):
        return (cx, c[1] - LAB_UP) if (c[1] + c[3]) / 2 > 27.67 else (cx, c[3] + LAB_UP)
    return (cx, c[3] + LAB_UP)


DECOUP = [('C104', 'U101', '8'), ('C105', 'U101', '8'), ('C305', 'U301', '8'), ('C306', 'U301', '4'), ('C502', 'U501', '1'), ('C501', 'U501', '2'), ('C503', 'U502', '8')]
DECOUP_MAX, RISO_MAX, INV_MAX = 2.8, 5.0, 5.0                      # LR-12, LR-4 (pad 1 of the series resistor to the output pin)
RISO = [('R108', 'U101', '7'), ('R208', 'U101', '1')]
KEEP_AT_INV = []   # feedback / gain / series-input parts: main's relative place, moved only as far as a label zone needs
SPAN_NETS = ('/A0', '/A1')


def _pad(P, ref, n):
    return [q for q in P[ref]['pads'] if q['n'] == n]


def hard_constraints(P):
    """LR rules a placement can hold. Every fn(pos_of, off) returns the excess in mm (0 = met); off(ref, (dx, dy)) turns a pad offset by the part's rotation.
    LR-12 decoupling (pad to pin <= 3 mm), LR-4 isolation resistor at its output pin (<= 5 mm), LR-4 INV_MAX (the follower output nodes' pads span <= 4.7 mm,
    of 5 mm of track), the A0 / A1 nets' span no larger than main's, LR-2 flow, LR-7, the 5 V feed, the channels' divider pads 5 mm apart."""
    out = []
    def rel(ref, c):
        return (c[0] - P[ref]['x'], c[1] - P[ref]['y'])
    def pair(a, b, pa, pb, lim, name):
        def fn(pos_of, off):
            A, B = pos_of(a), pos_of(b)
            d = 1e9
            for p in pa:
                po = off(a, p)
                for q in pb:
                    qo = off(b, q)
                    d = min(d, math.hypot(A[0] + po[0] - B[0] - qo[0], A[1] + po[1] - B[1] - qo[1]))
            return max(0.0, d - (lim - 0.01))
        out.append(dict(refs=(a, b), fn=fn, name=name))
    for cap, ic, pin in DECOUP:
        net = _pad(P, ic, pin)[0]['net']; ip = _pad(P, ic, pin)[0]['c']
        ks = [q for q in P[cap]['pads'] if q['net'] == net] or P[cap]['pads'][:1]
        pair(cap, ic, [rel(cap, q['c']) for q in ks], [rel(ic, ip)], DECOUP_MAX, f'LR-12 {cap}>{ic}.{pin}')
    for r, ic, pin in RISO:
        q = _pad(P, r, '1')[0]['c']; ip = _pad(P, ic, pin)[0]['c']
        pair(r, ic, [rel(r, q)], [rel(ic, ip)], RISO_MAX, f'LR-4 {r}>{ic}.{pin}')
    def span_fn(net, cap, name, main_cap=False):
        pins = [(r, rel(r, q['c'])) for r, p in P.items() for q in p['pads'] if q['net'] == net]
        if main_cap:
            xs0 = [P[r]['x'] + d[0] for r, d in pins]; ys0 = [P[r]['y'] + d[1] for r, d in pins]
            cap = (max(xs0) - min(xs0)) + (max(ys0) - min(ys0))
        def fn(pos_of, off, pins=pins, cap=cap):
            pts = [(pos_of(r)[0] + off(r, d)[0], pos_of(r)[1] + off(r, d)[1]) for r, d in pins]
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            return max(0.0, (max(xs) - min(xs)) + (max(ys) - min(ys)) - (cap - 0.01))
        out.append(dict(refs=tuple(r for r, _ in pins if r not in FIXED), fn=fn, name=name % cap if '%' in name else name))
    for net in SPAN_NETS:
        span_fn(net, 0, '%s span <= main %%.1f' % net, True)
    def mst_fn(net, name):
        pins = [(r, rel(r, q['c'])) for r, p in P.items() for q in p['pads'] if q['net'] == net]
        def tree(pts):
            n = len(pts); inT = {0}; tot = 0.0
            while len(inT) < n:
                d, j = min((abs(pts[i][0] - pts[j][0]) + abs(pts[i][1] - pts[j][1]), j) for i in inT for j in range(n) if j not in inT)
                tot += d; inT.add(j)
            return tot
        cap = tree([(P[r]['x'] + d[0], P[r]['y'] + d[1]) for r, d in pins])               # main's own tree, which the checker measured as 4.9 mm of track
        def fn(pos_of, off, pins=pins, cap=cap):
            return max(0.0, tree([(pos_of(r)[0] + off(r, d)[0], pos_of(r)[1] + off(r, d)[1]) for r, d in pins]) - (cap - 0.01))
        out.append(dict(refs=tuple(r for r, _ in pins if r not in FIXED), fn=fn, name=name % cap))
    mst_fn('/AWG_FB', 'LR-4 /AWG_FB pad tree <= main %.2f')
    for net in ('/CH1_OUT', '/CH2_OUT'):
        span_fn(net, 5.0, f'LR-4 {net} pad span <= 5.0 (INV_MAX {INV_MAX} of track; three pins: Steiner length = half-perimeter)')
    for prot, rnp, riso, bnc_x, adc_x in (('R101', 'R107', 'R108', 102.0, 66.04), ('R201', 'R207', 'R208', 102.0, 68.58)):
        ux = P['U101']['x']
        def f1(pos_of, off, a=prot, b=rnp, bnc_x=bnc_x):
            return max(0.0, pos_of(b)[0] + 0.02 - pos_of(a)[0]) + max(0.0, pos_of(a)[0] + 0.02 - bnc_x)
        def f2(pos_of, off, rnp=rnp, ux=ux):
            return max(0.0, ux + 0.02 - pos_of(rnp)[0])
        def f3(pos_of, off, riso=riso, ux=ux, adc_x=adc_x):
            return max(0.0, pos_of(riso)[0] + 0.02 - ux) + max(0.0, adc_x + 0.02 - pos_of(riso)[0])
        out.append(dict(refs=(prot, rnp), fn=f1, name=f'LR-2 flow x: BNC > {prot} > {rnp}'))
        out.append(dict(refs=(rnp,), fn=f2, name=f'LR-2 flow x: {rnp} > U101'))
        out.append(dict(refs=(riso,), fn=f3, name=f'LR-2 flow x: U101 > {riso} > ADC pad'))
    jx, jy = P['J301']['x'], P['J301']['y']
    for r in ('R301', 'R302'):
        out.append(dict(refs=(r,), fn=lambda pos_of, off, r=r: max(0.0, math.hypot(pos_of(r)[0] - jx, pos_of(r)[1] - jy) - 15.99), name=f'LR-7 {r} within 16 mm of J301'))
    d0 = _pad(P, 'J603', '5')[0]['c']; o306 = rel('R306', _pad(P, 'R306', '1')[0]['c'])
    def dac(pos_of, off):
        o = off('R306', o306); p = pos_of('R306')
        return max(0.0, abs(p[0] + o[0] - d0[0]) + abs(p[1] + o[1] - d0[1]) - 11.99)
    out.append(dict(refs=('R306',), fn=dac, name='LR-7 DAC0 pad span <= 12'))
    f5 = _pad(P, 'J601', '5')[0]['c']
    out.append(dict(refs=('U401',), fn=lambda pos_of, off: max(0.0, math.hypot(pos_of('U401')[0] - f5[0], pos_of('U401')[1] - f5[1]) - 14.99), name='LR-2 U401 within 15 mm of the 5 V pad'))
    A = [(r, rel(r, q['c'])) for r, p in P.items() for q in p['pads'] if q['net'] in ('/CH1_N', '/CH1_NP', '/CH1_IN') and q['c'][0] < 91.0]
    B = [(r, rel(r, q['c'])) for r, p in P.items() for q in p['pads'] if q['net'] in ('/CH2_N', '/CH2_NP', '/CH2_IN') and q['c'][0] < 91.0]
    def gap5(pos_of, off):
        g = 1e9
        for a in A:
            pa = pos_of(a[0]); oa = off(a[0], a[1])
            for b in B:
                pb = pos_of(b[0]); ob = off(b[0], b[1])
                g = min(g, math.hypot(pa[0] + oa[0] - pb[0] - ob[0], pa[1] + oa[1] - pb[1] - ob[1]))
        return max(0.0, 5.02 - g)
    refs5 = tuple(sorted({r for r, _ in A} | {r for r, _ in B}))
    out.append(dict(refs=refs5, fn=gap5, name="LR-2 the channels' divider pads >= 5 mm apart"))
    return out


def keep_list(P):
    return [(r, ic, (P[r]['x'] - P[ic]['x'], P[r]['y'] - P[ic]['y'])) for r, ic in KEEP_AT_INV]


def name_box(blk, P, G, cur=None):
    """the block's name, in the top-left-most free place of the block (rows from the top, then from the left): its box (1.05 mm a character + 0.2, 1.3 high)"""
    word = NAMES[blk]
    w, h = 1.05 * len(word) + 0.2, 1.3
    m = Mask(REGIONS[blk], 0.4)
    fx = []
    for r in FIXED:
        g = G[r]; x, y = (cur or {}).get(r, (P[r]['x'], P[r]['y'])); fx.append((g['ext'][0] + x, g['ext'][1] + y, g['ext'][2] + x, g['ext'][3] + y))
    fx = np.array(fx)
    r0 = REGIONS[blk]
    x0, y1 = min(r[0] for r in r0), max(r[3] for r in r0)
    best = None
    for y in np.arange(y1 - h, min(r[1] for r in r0), -0.1):
        for x in np.arange(x0, max(r[2] for r in r0), 0.1):
            b = (x, y, x + w, y + h)
            if m.bad(b) > 0 or depth(b, fx, 0.5) > 0:
                continue
            sc = (x - x0) + (y1 - (y + h))                    # nearest the block's top-left corner
            if best is None or sc < best[0]:
                best = (sc, b)
    if best:
        return tuple(round(float(v), 2) for v in best[1])
    raise RuntimeError('no place for the name of ' + blk)


NAMES = {'POWER': 'POWER', 'REFCAL': 'REF / CAL', 'CH1': 'CH1', 'CH2': 'CH2', 'AWG': 'AWG'}


def run(dump, out, blk, seed=1, iters=100000, mine=None, frozen=None, regions=None, cluster_of=None, soft=None, fixed_pos=None, init=None):
    """Place `mine` (default: the block's movable parts not in `frozen`) inside the union of REGIONS[b] for b in `regions` (default [blk]).
    frozen: {ref: [x, y, rot]} parts already placed (anchors, other blocks): obstacles, and terminals of the nets. cluster_of: the IC whose cluster this is
    (moves of the IC take the other parts with it). soft: {ref: (ic, (dx, dy))} parts pulled toward the IC's position + that offset (main's relative place)."""
    D, P = load(dump)
    regions = regions or [blk]
    G0 = {r: part_geom(p, 0) for r, p in P.items()}
    frozen = {k: list(v) for k, v in (frozen or {}).items()}
    mine = mine or [r for r in P if block_of(r) == blk and r not in FIXED and r not in frozen]
    main = {r: (P[r]['x'], P[r]['y']) for r in P}
    cur = dict(main); crot = {r: 0 for r in P}
    for r, v in frozen.items():
        cur[r] = (v[0], v[1]); crot[r] = int(round((v[2] - P[r]['rot']) / 90.0)) % 4
    reg = [rc for b in regions for rc in REGIONS[b]]
    n = len(mine); idx = {r: i for i, r in enumerate(mine)}
    can_rot = [rotatable(r) for r in mine]
    GEO = [[part_geom(P[r], k) for k in range(4)] if can_rot[i] else [part_geom(P[r], 0)] * 4 for i, r in enumerate(mine)]
    rk = [0] * n; ls = [0] * n
    is_pas = [bool(PAS.fullmatch(r)) for r in mine]
    anchor_mode = bool(soft)                                   # a cluster: parts may stand turned; the rest of a block is horizontal
    allowed_k = [([k for k in range(4) if orient(P[r], k) == 0] if (is_pas[i] and not anchor_mode and r not in CLUSTER_FREE) else (list(range(4)) if can_rot[i] else [0])) or [0] for i, r in enumerate(mine)]
    for i in range(n): rk[i] = allowed_k[i][0]
    def arr(key): return np.array([GEO[i][rk[i]][key] for i in range(n)])
    ext0, lab0, zon0, cy0 = arr('ext'), arr('lab'), arr('zone'), arr('cy')
    can_rot = [len(a) > 1 for a in allowed_k]
    def setrot(i, k, l_=None):
        rk[i] = k
        if l_ is not None: ls[i] = l_
        for a_, key in ((ext0, 'ext'), (cy0, 'cy')): a_[i] = GEO[i][k][key]
        sh = LSHIFT[ls[i]]
        for a_, key in ((lab0, 'lab'), (zon0, 'zone')):
            b_ = GEO[i][k][key]; a_[i] = (b_[0] + sh[0], b_[1] + sh[1], b_[2] + sh[0], b_[3] + sh[1])
    def rotk(ref): return rk[idx[ref]] if ref in idx else crot.get(ref, 0)
    def off(ref, v):
        k = rotk(ref); c, s_ = COS[k], SIN[k]
        return (v[0] * c - v[1] * s_, v[0] * s_ + v[1] * c)
    # fixed obstacles: the fixed parts, the frozen ones (extent, label, zone), the header labels, the names of the blocks
    fx_ext, fx_lab, fx_zone = [], [], []
    for r in FIXED:
        g = G0[r]; x, y = cur[r]
        fx_ext.append((g['ext'][0] + x, g['ext'][1] + y, g['ext'][2] + x, g['ext'][3] + y))
    ul, uz, _ = u101_label_east(P, cur)
    fx_lab.append(ul); fx_zone.append(uz)
    for r in frozen:
        if r in FIXED: continue
        g = part_geom(P[r], crot[r], frozen[r][3] if len(frozen[r]) > 3 else 0); x, y = cur[r]
        fx_ext.append((g['ext'][0] + x, g['ext'][1] + y, g['ext'][2] + x, g['ext'][3] + y))
        fx_lab.append((g['lab'][0] + x, g['lab'][1] + y, g['lab'][2] + x, g['lab'][3] + y)); fx_zone.append((g['zone'][0] + x, g['zone'][1] + y, g['zone'][2] + x, g['zone'][3] + y))
    for r in FIXED:
        if r.startswith(('J1', 'J2', 'J3')) or r == 'U101': continue
        p = P[r]; w, h = LAB_W * len(r), LAB_H
        if r in ('J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607'):
            tx, ty = header_label(p)
        else:
            tx, ty = p['tx'], p['ty']
            if abs((p['tang'] % 180) - 90) < 1: w, h = h, w
        fx_lab.append((tx - w / 2, ty - h / 2, tx + w / 2, ty + h / 2))
    for b in regions:
        fx_lab.append(name_box(b, P, G0, cur))
    fx_ext, fx_lab, fx_zone = np.array(fx_ext), np.array(fx_lab), np.array(fx_zone).reshape(-1, 4)
    lanes = np.array(LANES) if 'AWG' in regions else np.zeros((0, 4))
    mext, mlab = Mask(reg, 0.2), Mask(reg, 0.4)
    others = [rc for b, rs in REGIONS.items() if b not in regions for rc in rs]
    # nets
    nets = {}
    for r, p in P.items():
        for q in p['pads']:
            nets.setdefault(q['net'], []).append((r, q['c'][0] - p['x'], q['c'][1] - p['y']))
    netl = []
    for nname, pins in nets.items():
        w = WEIGHT.get(nname, 1.0)
        if w <= 0 or len(pins) < 2 or nname.startswith('/unconnected') or not any(r in idx for r, _, _ in pins):
            continue
        mv = [(idx[r], (dx, dy)) for r, dx, dy in pins if r in idx]
        term = []
        for r, dx, dy in pins:
            if r not in idx:
                k = crot.get(r, 0); c, s_ = COS[k], SIN[k]
                term.append((cur[r][0] + dx * c - dy * s_, cur[r][1] + dx * s_ + dy * c))
        netl.append((w, mv, term))
    of = {i: [k for k, (_, mv, _) in enumerate(netl) if any(m[0] == i for m in mv)] for i in range(n)}
    ties = [(idx[a], b, 4 * w) for a, b, w in TIES if a in idx and (b in idx or b in cur)]
    known = set(mine) | set(frozen) | FIXED | {r for r in P if block_of(r) not in regions}
    HARD = [h for h in hard_constraints(P) if any(r in idx for r in h['refs']) and all(r in known or block_of(r) not in regions for r in h['refs'])]
    consof = {i: [k for k, h in enumerate(HARD) if mine[i] in h['refs']] for i in range(n)}
    soft = {r: v for r, v in (soft or {}).items() if r in idx}
    st = np.zeros((n, 2))
    rnd = random.Random(seed)
    rb = [min(r[0] for r in reg), min(r[1] for r in reg), max(r[2] for r in reg), max(r[3] for r in reg)]
    for i, r in enumerate(mine):
        if r in soft and soft[r][0] not in idx:
            ic, o = soft[r]; st[i] = (cur[ic][0] + o[0], cur[ic][1] + o[1])
        else:
            st[i] = (rnd.uniform(rb[0] + 2, rb[2] - 2), rnd.uniform(rb[1] + 2, rb[3] - 2))
    clusters = {}
    if cluster_of and cluster_of in idx:
        clusters[idx[cluster_of]] = [idx[r] for r in mine if r != cluster_of]
        for j in clusters[idx[cluster_of]]:
            if mine[j] in soft: st[j] = st[idx[cluster_of]] + np.array(soft[mine[j]][1])
    keep10 = [r for r in ('U401', 'C409') if r in idx]
    pos_of = lambda ref: st[idx[ref]] if ref in idx else np.array(cur[ref])

    # ---- D31: rows, columns and pin lines (align.py). A passive's y snaps to a row (the y of another passive of the block and orientation, or a base row),
    # or to a pad line of a part that is not a passive (y, or x, of a pad centre within 5 mm); the rule is held by construction, not repaired afterwards.
    blkd = {r: int(PAS.fullmatch(r).group(1)) for r in P if PAS.fullmatch(r)}
    FZ = [(cur[r][0], cur[r][1], orient(P[r], crot[r]), blkd[r]) for r in frozen if r in blkd and r not in FIXED]
    FZa = np.array(FZ, float).reshape(-1, 4)
    SP = []
    for r, p in P.items():
        if r in blkd or r in idx: continue
        k = crot.get(r, 0); c, s_ = COS[k], SIN[k]
        for q in p['pads']:
            dx, dy = q['c'][0] - p['x'], q['c'][1] - p['y']
            SP.append((cur[r][0] + dx * c - dy * s_, cur[r][1] + dx * s_ + dy * c))
    SPa = np.array(SP, float).reshape(-1, 2)
    MP = [(r, [(q['c'][0] - P[r]['x'], q['c'][1] - P[r]['y']) for q in P[r]['pads']]) for r in mine if r not in blkd]
    mpi = [i for i in range(n) if is_pas[i]]
    base_rows = {}
    for b in regions:
        ylo = min(rc[1] for rc in REGIONS[b]); yhi = max(rc[3] for rc in REGIONS[b])
        base_rows[b] = [ylo + 1.2 + 3.55 * j for j in range(int((yhi - ylo) / 3.55))]
    def rows_of(i): return base_rows[BLOCK_DIGIT[mine[i][-3]]] if BLOCK_DIGIT[mine[i][-3]] in base_rows else [P[mine[i]]['y']]
    modes_ok = [([1, 2] if cluster_of else [0, 1, 2]) if is_pas[i] else [0] for i in range(n)]
    mode = [m[0] for m in modes_ok]
    def pad_xy():
        pts = []
        for r, offs in MP:
            p0 = st[idx[r]]
            for o in offs:
                oo = off(r, o); pts.append((p0[0] + oo[0], p0[1] + oo[1]))
        return np.vstack([SPa, np.array(pts, float).reshape(-1, 2)]) if pts else SPa
    def snap(i, x, y):
        if not is_pas[i]: return x, y
        m = mode[i]
        if m == 0:
            oi = orient(P[mine[i]], rk[i]); bi = blkd[mine[i]]
            ys = list(rows_of(i))
            ys += [st[j][1] for j in mpi if j != i and blkd[mine[j]] == bi and orient(P[mine[j]], rk[j]) == oi]
            ys += [fy for fx, fy, fo, fb in FZ if fb == bi and fo == oi]
            return x, min(ys, key=lambda v: abs(v - y))
        PA = pad_xy()
        near = PA[np.hypot(PA[:, 0] - x, PA[:, 1] - y) <= 5.0]
        if not len(near): return x, y
        if m == 1: return x, float(near[np.argmin(np.abs(near[:, 1] - y)), 1])
        return float(near[np.argmin(np.abs(near[:, 0] - x)), 0]), y
    def align_total():
        if not mpi: return 0.0
        X = np.array([st[i][0] for i in mpi]); Y = np.array([st[i][1] for i in mpi])
        O = np.array([orient(P[mine[i]], rk[i]) for i in mpi]); B = np.array([blkd[mine[i]] for i in mpi])
        ax = np.concatenate([X, FZa[:, 0]]); ay = np.concatenate([Y, FZa[:, 1]]); ao = np.concatenate([O, FZa[:, 2]]); ab = np.concatenate([B, FZa[:, 3]])
        dx = X[:, None] - ax[None, :]; dy = Y[:, None] - ay[None, :]
        dist = np.hypot(dx, dy)
        same = (B[:, None] == ab[None, :]) & (O[:, None] == ao[None, :]) & (dist <= 8.0)
        same[np.arange(len(mpi)), np.arange(len(mpi))] = False
        ok = (same & ((np.abs(dy) <= 0.05) | (np.abs(dx) <= 0.05))).any(1)
        PA = pad_xy()
        if len(PA):
            ddx = X[:, None] - PA[None, :, 0]; ddy = Y[:, None] - PA[None, :, 1]
            ok |= ((np.hypot(ddx, ddy) <= 4.0) & ((np.abs(ddx) <= 0.05) | (np.abs(ddy) <= 0.05))).any(1)
        return float((~ok).sum())

    def hp(k):
        w, mv, term = netl[k]
        pts = [(st[i][0] + off(mine[i], d)[0], st[i][1] + off(mine[i], d)[1]) for i, d in mv] + term
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        return w * ((max(xs) - min(xs)) + (max(ys) - min(ys)))

    def sup(k): return HARD[k]['fn'](pos_of, off)

    def softc(i):
        t = 0.0
        for r, (ic, o) in soft.items():
            if idx[r] == i or (ic in idx and idx[ic] == i):
                pa = pos_of(r); pb = pos_of(ic)
                t += SOFT_W * math.hypot(pa[0] - pb[0] - o[0], pa[1] - pb[1] - o[1])
        return t

    def own(i, pos):
        sh = np.array([pos[0], pos[1], pos[0], pos[1]])
        e = ext0[i] + sh; lb = lab0[i] + sh; z = zon0[i] + sh
        v = mext.bad(e) + mlab.bad(lb)
        v += depth(e, fx_ext, EXT_GAP) + depth(z, fx_ext, 0) + depth(lb, fx_lab, LAB_GAP) + depth(e, fx_lab, 0.3) + depth(e, fx_zone, 0) + depth(e, lanes, 0.0) + depth(z, lanes, 0.0)
        for r in keep10:
            if r == mine[i]:
                v += max(0.0, 12.6 - seg_dist_rect(others, (pos[0] + (cy0[i][0] + cy0[i][2]) / 2, pos[1] + (cy0[i][1] + cy0[i][3]) / 2))) * 3
        return v + sum(sup(k) for k in consof[i])

    def pairs(i, pos):
        o = [j for j in range(n) if j != i]
        if not o: return 0.0
        sh = np.array([pos[0], pos[1], pos[0], pos[1]])
        e = ext0[i] + sh; lb = lab0[i] + sh; z = zon0[i] + sh
        s2 = np.concatenate([st[o], st[o]], axis=1)
        E = ext0[o] + s2; L = lab0[o] + s2; Z = zon0[o] + s2
        return depth(e, E, EXT_GAP) + depth(z, E, 0) + depth(lb, L, LAB_GAP) + depth(e, Z, 0)

    def tie(i, pos):
        t = 0.0
        for a, b, w in ties:
            if a == i: pb = st[idx[b]] if b in idx else cur[b]
            elif b in idx and idx[b] == i: pb = st[a]
            else: continue
            t += w * math.hypot(pos[0] - pb[0], pos[1] - pb[1])
        return t

    def total(i, pos): return own(i, pos) + pairs(i, pos)

    def full():
        wl = sum(hp(k) for k in range(len(netl))) + sum(tie(i, st[i]) for i in range(n)) / 2 + sum(softc(i) for i in range(n)) / 2
        v = sum(own(i, st[i]) - sum(sup(k) for k in consof[i]) for i in range(n)) + 0.5 * sum(pairs(i, st[i]) for i in range(n)) + sum(sup(k) for k in range(len(HARD)))
        v += align_total()
        return wl + 400 * v, wl, v
    for r_, (x_, y_, k_, l_) in (init or {}).items():
        if r_ in idx:
            i_ = idx[r_]; setrot(i_, k_, l_); st[i_] = (x_, y_)
    for i in range(n):
        if not any(mine[i] == r_ for r_ in (init or {})): st[i] = snap(i, st[i][0], st[i][1])
    E, wl, v = full()
    best = (E, st.copy(), list(rk), list(ls))
    rot_ids = [i for i in range(n) if can_rot[i]]
    passes = ((25.0, 3.0, 0.15, iters), (0.8, 0.4, 0.04, max(iters // 3, 20000)))
    if os.environ.get('RP_POLISH'): passes = ((1.5, 0.6, 0.05, iters),)
    for T0, sf, sc0, nit in passes:
        st[:] = best[1]
        for i_, k_ in enumerate(best[2]): setrot(i_, k_, best[3][i_])
        E, _, _ = full()
        for it in range(nit):
            T = T0 * (1 - it / nit) ** 2 + 0.02
            sc = sc0 + sf * T / T0
            u_ = rnd.random()
            if clusters and u_ < 0.06:
                ic = next(iter(clusters)); mem = [ic] + clusters[ic]
                sh = np.array([round(rnd.gauss(0, sc * 2) * 100) / 100, round(rnd.gauss(0, sc * 2) * 100) / 100])
                old = st[mem].copy(); st[mem] += sh
                E2, _, _ = full()
                if E2 <= E or rnd.random() < math.exp(-(E2 - E) / T):
                    E = E2
                    if E < best[0] - 1e-9: best = (E, st.copy(), list(rk), list(ls))
                else: st[mem] = old
                continue
            i = rnd.randrange(n)
            old = st[i].copy(); oldk = rk[i]; oldl = ls[i]; oldm = mode[i]
            newk = oldk; newl = oldl
            if rnd.random() < 0.12: newl = rnd.randrange(len(LSHIFT))
            if len(allowed_k[i]) > 1 and rnd.random() < 0.12: newk = rnd.choice(allowed_k[i])
            if len(modes_ok[i]) > 1 and rnd.random() < 0.08: mode[i] = rnd.choice(modes_ok[i])
            if rnd.random() < 0.03: new = np.array([rnd.uniform(rb[0], rb[2]), rnd.uniform(rb[1], rb[3])])
            else: new = np.array([round((old[0] + rnd.gauss(0, sc)) * 100) / 100, round((old[1] + rnd.gauss(0, sc)) * 100) / 100])
            o_t = total(i, old); o_w = sum(hp(k) for k in of[i]); o_ti = tie(i, old) + softc(i); o_a = align_total()
            if newk != oldk or newl != oldl: setrot(i, newk, newl)
            new = np.array(snap(i, new[0], new[1]))
            st[i] = new
            n_t = total(i, new); n_w = sum(hp(k) for k in of[i]); n_ti = tie(i, new) + softc(i); n_a = align_total()
            d = (n_w - o_w) + (n_ti - o_ti) + 400 * (n_t - o_t) + 400 * (n_a - o_a)
            if d <= 0 or rnd.random() < math.exp(-d / T):
                E += d
                if E < best[0] - 1e-9: best = (E, st.copy(), list(rk), list(ls))
            else:
                st[i] = old; mode[i] = oldm
                if newk != oldk or newl != oldl: setrot(i, oldk, oldl)

    st[:] = best[1]
    for i, k in enumerate(best[2]): setrot(i, k, best[3][i])
    E, wl, v = full()
    if v > 0.01 or os.environ.get('RP_DEBUG'):
        for k, h in enumerate(HARD):
            if sup(k) > 1e-6: print('  hard', h['name'], 'excess %.3f' % sup(k))
        for i in range(n):
            sh = np.array([st[i][0], st[i][1], st[i][0], st[i][1]])
            e = ext0[i] + sh; lb = lab0[i] + sh; z = zon0[i] + sh
            parts_ = dict(region=mext.bad(e) + mlab.bad(lb), fixed=depth(e, fx_ext, EXT_GAP) + depth(z, fx_ext, 0) + depth(lb, fx_lab, LAB_GAP) + depth(e, fx_lab, 0.3) + depth(e, fx_zone, 0), lanes=depth(e, lanes, 0) + depth(z, lanes, 0), pairs=pairs(i, st[i]))
            if sum(parts_.values()) > 1e-6: print('  ', mine[i], {k: round(x, 2) for k, x in parts_.items()})
    print('  align leftovers:', int(align_total()))
    res = {r: [round(float(st[idx[r]][0]), 2), round(float(st[idx[r]][1]), 2), ((round(P[r]['rot']) + 90 * rk[idx[r]] + 180) % 360) - 180, ls[idx[r]]] for r in mine}
    json.dump(dict(blk=blk, seed=seed, wl=wl, viol=v, st=res), open(out, 'w'))
    print(blk, 'seed', seed, 'wl %.1f viol %.4f' % (wl, v), 'parts', n, 'hard', len(HARD), 'soft', len(soft))
    return res, v


