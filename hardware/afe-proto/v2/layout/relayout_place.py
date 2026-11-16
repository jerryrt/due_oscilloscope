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
    'CH1': [(62.4, 33.0, 74.9, 50.0), (74.9, 33.0, 80.1, 47.1), (80.1, 33.0, 93.0, 50.0), (58.0, 38.6, 62.4, 50.0)],
    'CH2': [(69.0, 19.75, 93.0, 32.9)],
    'AWG': [(59.0, 6.2, 62.2, 18.4), (62.2, 4.55, 80.0, 18.4), (80.0, 6.2, 84.9, 18.4), (84.9, 4.55, 92.3, 18.4), (70.4, 18.4, 92.3, 19.25)],
}
# the Due's edge-row headers carry their designator on the inboard side, centred along the header (owner, bcbc1e3d): the blocks give up a strip there,
# as a notch only where the label stands. {ref: (centre x, centre y of the label)}; the header's courtyard is (x0, y0, x1, y1) in the dump
HEADER_LABEL_H = 0.5
LANES = [(65.3, 4.6, 66.8, 18.4), (67.9, 4.6, 69.3, 18.4)]      # A1 (x 66.04) and A0 (x 68.58) cross AWG to J602: no part stands in them
BLOCK_DIGIT = {'1': 'CH1', '2': 'CH2', '3': 'AWG', '4': 'POWER', '5': 'REFCAL'}
LAB_H, LAB_W, LAB_UP, ZONE, LAB_GAP, EXT_GAP = float(os.environ.get('RP_LABH', 1.3)), float(os.environ.get('RP_LABW', 0.95)), 0.8, float(os.environ.get('RP_ZONE', 0.3)), float(os.environ.get('RP_GAP', 0.5)), 0.05
RES = 0.05
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
DECOUP_MAX, RISO_MAX, INV_MAX = 3.0, 5.0, 5.0                      # LR-12, LR-4 (pad 1 of the series resistor to the output pin)
RISO = [('R108', 'U101', '7'), ('R208', 'U101', '1')]
KEEP_AT_INV = [('R108', 'U101'), ('R208', 'U101'), ('R303', 'U301'), ('R304', 'U301'), ('C301', 'U301'), ('R107', 'U101'), ('R207', 'U101')]   # feedback / gain / series-input parts: main's relative place, moved only as far as a label zone needs
SPAN_NETS = ('/A0', '/A1')


def _pad(P, ref, n):
    return [q for q in P[ref]['pads'] if q['n'] == n]


def hard_constraints(P):
    """LR rules a placement can hold: LR-12 decoupling (pad to pin <= 3 mm), LR-4 isolation resistor at its output pin (<= 5 mm), and the A0 / A1 nets' span no larger than main's"""
    out = []
    def pair(a, b, pa, pb, lim, name):
        def fn(pos_of):
            A, B = pos_of(a), pos_of(b)
            d = min(math.hypot(A[0] + p[0] - B[0] - q[0], A[1] + p[1] - B[1] - q[1]) for p in pa for q in pb)
            return max(0.0, d - (lim - 0.01))
        out.append(dict(refs=(a, b), fn=fn, name=name))
    for cap, ic, pin in DECOUP:
        net = _pad(P, ic, pin)[0]['net']; ip = _pad(P, ic, pin)[0]['c']
        ks = [q for q in P[cap]['pads'] if q['net'] == net] or P[cap]['pads'][:1]
        pair(cap, ic, [(q['c'][0] - P[cap]['x'], q['c'][1] - P[cap]['y']) for q in ks], [(ip[0] - P[ic]['x'], ip[1] - P[ic]['y'])], DECOUP_MAX, f'LR-12 {cap}>{ic}.{pin}')
    for r, ic, pin in RISO:
        q = _pad(P, r, '1')[0]['c']; ip = _pad(P, ic, pin)[0]['c']
        pair(r, ic, [(q[0] - P[r]['x'], q[1] - P[r]['y'])], [(ip[0] - P[ic]['x'], ip[1] - P[ic]['y'])], RISO_MAX, f'LR-4 {r}>{ic}.{pin}')
    for net in SPAN_NETS:
        pins = [(r, q['c'][0] - p['x'], q['c'][1] - p['y']) for r, p in P.items() for q in p['pads'] if q['net'] == net]
        xs = [P[r]['x'] + dx for r, dx, dy in pins]; ys = [P[r]['y'] + dy for r, dx, dy in pins]
        span0 = (max(xs) - min(xs)) + (max(ys) - min(ys))
        def fn(pos_of, pins=pins, span0=span0):
            xs = [pos_of(r)[0] + dx for r, dx, dy in pins]; ys = [pos_of(r)[1] + dy for r, dx, dy in pins]
            return max(0.0, (max(xs) - min(xs)) + (max(ys) - min(ys)) - (span0 - 0.01))
        out.append(dict(refs=tuple(r for r, _, _ in pins if r not in FIXED), fn=fn, name=f'{net} span <= main {span0:.1f}'))
    # LR-4 INV_MAX (the follower output nodes and the AWG inverting node: <= 5 mm of track, so their pads span at most that), LR-2 flow, LR-7, the 5 V feed
    def span(net, cap, name):
        pins = [(r, q['c'][0] - p['x'], q['c'][1] - p['y']) for r, p in P.items() for q in p['pads'] if q['net'] == net]
        xs0 = [P[r]['x'] + dx for r, dx, dy in pins]; ys0 = [P[r]['y'] + dy for r, dx, dy in pins]
        def fn(pos_of, pins=pins, cap=cap):
            xs = [pos_of(r)[0] + dx for r, dx, dy in pins]; ys = [pos_of(r)[1] + dy for r, dx, dy in pins]
            return max(0.0, (max(xs) - min(xs)) + (max(ys) - min(ys)) - (cap - 0.01))
        out.append(dict(refs=tuple(r for r, _, _ in pins if r not in FIXED), fn=fn, name=name))
    for net in ('/CH1_OUT', '/CH2_OUT'):
        span(net, 4.7, f'LR-4 {net} pad span <= 4.7 (INV_MAX {INV_MAX} of track)')
    for prot, rnp, riso, bnc_x, adc_x in (('R101', 'R107', 'R108', 102.0, 66.04), ('R201', 'R207', 'R208', 102.0, 68.58)):
        ux = P['U101']['x']
        def fn(pos_of, prot=prot, rnp=rnp, riso=riso, bnc_x=bnc_x, adc_x=adc_x, ux=ux):
            xs = [bnc_x, pos_of(prot)[0], pos_of(rnp)[0], ux, pos_of(riso)[0], adc_x]
            return sum(max(0.0, b + 0.02 - a) for a, b in zip(xs, xs[1:]))
        out.append(dict(refs=(prot, rnp, riso), fn=fn, name=f'LR-2 flow x falls BNC > {prot} > {rnp} > U101 > {riso} > ADC pad'))
    jx, jy = P['J301']['x'], P['J301']['y']
    for r in ('R301', 'R302'):
        out.append(dict(refs=(r,), fn=lambda pos_of, r=r: max(0.0, math.hypot(pos_of(r)[0] - jx, pos_of(r)[1] - jy) - 15.99), name=f'LR-7 {r} within 16 mm of J301'))
    d0 = _pad(P, 'J603', '5')[0]['c']; q0 = _pad(P, 'R306', '1')[0]['c']; off = (q0[0] - P['R306']['x'], q0[1] - P['R306']['y'])
    out.append(dict(refs=('R306',), fn=lambda pos_of: max(0.0, abs(pos_of('R306')[0] + off[0] - d0[0]) + abs(pos_of('R306')[1] + off[1] - d0[1]) - 11.49), name='LR-7 DAC0 pad span <= 12'))
    f5 = _pad(P, 'J601', '5')[0]['c']
    out.append(dict(refs=('U401',), fn=lambda pos_of: max(0.0, math.hypot(pos_of('U401')[0] - f5[0], pos_of('U401')[1] - f5[1]) - 14.99), name='LR-2 U401 within 15 mm of the 5 V pad'))
    def gap5(pos_of):
        g = 1e9
        A = [(r, dx, dy) for r, p in P.items() for q in p['pads'] if q['net'] in ('/CH1_N', '/CH1_NP', '/CH1_IN') and q['c'][0] < 91.0 for dx, dy in [(q['c'][0] - p['x'], q['c'][1] - p['y'])]]
        B = [(r, dx, dy) for r, p in P.items() for q in p['pads'] if q['net'] in ('/CH2_N', '/CH2_NP', '/CH2_IN') and q['c'][0] < 91.0 for dx, dy in [(q['c'][0] - p['x'], q['c'][1] - p['y'])]]
        for a in A:
            pa = pos_of(a[0])
            for b in B:
                pb = pos_of(b[0]); g = min(g, math.hypot(pa[0] + a[1] - pb[0] - b[1], pa[1] + a[2] - pb[1] - b[2]))
        return max(0.0, 5.02 - g)
    refs5 = tuple(r for r, p in P.items() if r not in FIXED and any(q['net'] in ('/CH1_N', '/CH1_NP', '/CH1_IN', '/CH2_N', '/CH2_NP', '/CH2_IN') for q in p['pads']))
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


def run(dump, out, blk, seed=1, iters=100000, pos0=None, fixed_pos=None):
    D, P = load(dump)
    G = {r: part_geom(p) for r, p in P.items()}
    mine = [r for r in P if block_of(r) == blk and r not in FIXED]
    main = {r: (P[r]['x'], P[r]['y']) for r in P}
    cur = dict(main)
    if fixed_pos: cur.update({k: tuple(v) for k, v in fixed_pos.items()})
    fx_ext = []
    for r in FIXED:
        g = G[r]; x, y = cur[r]
        fx_ext.append((g['ext'][0] + x, g['ext'][1] + y, g['ext'][2] + x, g['ext'][3] + y))
    u = G['U101']; ux, uy = cur['U101']
    fx_lab = [(u['lab'][0] + ux, u['lab'][1] + uy, u['lab'][2] + ux, u['lab'][3] + uy)]
    for r in FIXED:                                  # the labels of the fixed parts: the headers' by the owner's rule, U101's above it, the rest where they are
        if r.startswith(('J1', 'J2', 'J3')) or r == 'U101': continue
        p = P[r]; w, h = LAB_W * len(r), LAB_H
        if r in ('J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607'):
            tx, ty = header_label(p)
        else:
            tx, ty = p['tx'], p['ty']
            if abs((p['tang'] % 180) - 90) < 1: w, h = h, w
        fx_lab.append((tx - w / 2, ty - h / 2, tx + w / 2, ty + h / 2))
    nb = name_box(blk, P, G, cur); fx_lab.append(nb)                 # the block's name is placed before the parts
    fx_ext, fx_lab = np.array(fx_ext), np.array(fx_lab)
    lanes = np.array(LANES) if blk == 'AWG' else np.zeros((0, 4))
    mext, mlab = Mask(REGIONS[blk], 0.2), Mask(REGIONS[blk], 0.4)
    others = [r for b, rs in REGIONS.items() if b != blk for r in rs]
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
    HARD, KEEP = hard_constraints(P), keep_list(P)
    HARD = [h for h in HARD if any(r in idx for r in h['refs'])]
    KEEP = [k for k in KEEP if k[0] in idx]
    consof = {i: [k for k, h in enumerate(HARD) if mine[i] in h['refs']] for i in range(len(mine))}
    n = len(mine)
    ext0 = np.array([G[r]['ext'] for r in mine]); lab0 = np.array([G[r]['lab'] for r in mine]); zon0 = np.array([G[r]['zone'] for r in mine])
    cy0 = np.array([G[r]['cy'] for r in mine])
    st = np.zeros((n, 2))
    rnd = random.Random(seed)
    rb = [min(r[0] for r in REGIONS[blk]), min(r[1] for r in REGIONS[blk]), max(r[2] for r in REGIONS[blk]), max(r[3] for r in REGIONS[blk])]
    for i, r in enumerate(mine):
        st[i] = (rnd.uniform(rb[0] + 2, rb[2] - 2), rnd.uniform(rb[1] + 2, rb[3] - 2))
    clusters = {}                                         # IC in the block -> the indices of the parts that go with it; start each at main's relative layout
    for ic in {k[1] for k in KEEP} | {h['refs'][1] for h in HARD if len(h['refs']) > 1 and h['refs'][1] in idx}:
        mem = sorted({idx[k[0]] for k in KEEP if k[1] == ic and k[0] in idx} | {idx[h['refs'][0]] for h in HARD if len(h['refs']) > 1 and h['refs'][1] == ic and h['refs'][0] in idx})
        if ic in idx:
            clusters[idx[ic]] = mem
            for j in mem: st[j] = st[idx[ic]] + np.array(main[mine[j]]) - np.array(main[ic])
        else:
            for j in mem: st[j] = main[mine[j]]
    keep10 = [r for r in ('U401', 'C409') if r in idx] if blk == 'POWER' else []
    pos_of = lambda ref: st[idx[ref]] if ref in idx else np.array(cur[ref])

    def hp(k):
        w, mv, term = netl[k]
        xs = [st[i][0] + dx for i, dx, dy in mv] + [t[0] for t in term]; ys = [st[i][1] + dy for i, dx, dy in mv] + [t[1] for t in term]
        return w * ((max(xs) - min(xs)) + (max(ys) - min(ys)))

    def sup(k):
        return HARD[k]['fn'](pos_of)

    def keepc(i):
        t = 0.0
        for r, ic, off in KEEP:
            if idx[r] == i or (ic in idx and idx[ic] == i):
                pa = pos_of(r); pb = pos_of(ic)
                t += 8.0 * math.hypot(pa[0] - pb[0] - off[0], pa[1] - pb[1] - off[1])
        return t

    def own(i, pos):
        sh = np.array([pos[0], pos[1], pos[0], pos[1]])
        e = ext0[i] + sh; lb = lab0[i] + sh; z = zon0[i] + sh
        v = mext.bad(e) + mlab.bad(lb)
        v += depth(e, fx_ext, EXT_GAP) + depth(z, fx_ext, 0) + depth(lb, fx_lab, LAB_GAP) + depth(e, fx_lab, 0.3) + depth(e, lanes, 0.0)
        for r in keep10:
            if r == mine[i]:
                v += max(0.0, 12.6 - seg_dist_rect(others, (pos[0] + (cy0[i][0] + cy0[i][2]) / 2, pos[1] + (cy0[i][1] + cy0[i][3]) / 2))) * 3
        return v + sum(sup(k) for k in consof[i]) + 0 * keepc(i)

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

    def total(i, pos):
        return own(i, pos) + pairs(i, pos)

    def full():
        wl = sum(hp(k) for k in range(len(netl))) + sum(tie(i, st[i]) for i in range(n)) / 2 + sum(keepc(i) for i in range(n)) / 2
        v = sum(own(i, st[i]) - sum(sup(k) for k in consof[i]) for i in range(n)) + 0.5 * sum(pairs(i, st[i]) for i in range(n)) + sum(sup(k) for k in range(len(HARD)))
        return wl + 400 * v, wl, v
    E, wl, v = full()
    best = (E, st.copy())
    T0 = 25.0
    for it in range(iters):
        T = T0 * (1 - it / iters) ** 2 + 0.02
        sc = 0.15 + 3.0 * T / T0
        if clusters and rnd.random() < 0.06:               # move an IC with its support parts
            ic = rnd.choice(list(clusters)); mem = [ic] + clusters[ic]
            sh = np.array([round(rnd.gauss(0, sc * 2) * 100) / 100, round(rnd.gauss(0, sc * 2) * 100) / 100])
            old = st[mem].copy(); st[mem] += sh
            E2, _, _ = full()
            if E2 <= E or rnd.random() < math.exp(-(E2 - E) / T):
                E = E2
                if E < best[0] - 1e-9: best = (E, st.copy())
            else:
                st[mem] = old
            continue
        i = rnd.randrange(n)
        old = st[i].copy()
        if rnd.random() < 0.03:
            new = np.array([rnd.uniform(rb[0], rb[2]), rnd.uniform(rb[1], rb[3])])
        else:
            new = np.array([round((old[0] + rnd.gauss(0, sc)) * 100) / 100, round((old[1] + rnd.gauss(0, sc)) * 100) / 100])
        o_t = total(i, old); o_w = sum(hp(k) for k in of[i]); o_ti = tie(i, old) + keepc(i)
        st[i] = new
        n_t = total(i, new); n_w = sum(hp(k) for k in of[i]); n_ti = tie(i, new) + keepc(i)
        d = (n_w - o_w) + (n_ti - o_ti) + 400 * (n_t - o_t)
        if d <= 0 or rnd.random() < math.exp(-d / T):
            E += d
            if E < best[0] - 1e-9: best = (E, st.copy())
        else:
            st[i] = old
    st[:] = best[1]
    E, wl, v = full()
    if v > 0.01 or os.environ.get('RP_DEBUG'):
        for k, h in enumerate(HARD):
            print('  hard', h['name'], 'excess %.3f' % sup(k))
        print('  total terms: own-sup %.3f pairs %.3f sup %.3f' % (sum(own(i, st[i]) - sum(sup(k) for k in consof[i]) for i in range(n)), 0.5 * sum(pairs(i, st[i]) for i in range(n)), sum(sup(k) for k in range(len(HARD)))))
        for i in range(n):
            sh = np.array([st[i][0], st[i][1], st[i][0], st[i][1]])
            e = ext0[i] + sh; lb = lab0[i] + sh
            parts_ = dict(region=mext.bad(e) + mlab.bad(lb), fixed=depth(e, fx_ext, EXT_GAP) + depth(zon0[i] + sh, fx_ext, 0) + depth(lb, fx_lab, LAB_GAP) + depth(e, fx_lab, 0.3), pairs=pairs(i, st[i]))
            if sum(parts_.values()) > 1e-6: print('  ', mine[i], {k: round(x, 2) for k, x in parts_.items()})
    moves = []
    for r, ic, off in KEEP:
        pa, pb = pos_of(r), pos_of(ic)
        moves.append(dict(part=r, ic=ic, main_cc=round(math.hypot(*off), 2), new_cc=round(math.hypot(pa[0] - pb[0], pa[1] - pb[1]), 2), shift=round(math.hypot(pa[0] - pb[0] - off[0], pa[1] - pb[1] - off[1]), 2)))
    res = {r: [round(float(st[idx[r]][0]), 2), round(float(st[idx[r]][1]), 2)] for r in mine}
    json.dump(dict(blk=blk, seed=seed, wl=wl, viol=v, st=res, name=list(nb), keep_moves=moves), open(out, 'w'))
    print(blk, 'seed', seed, 'wl %.1f viol %.4f' % (wl, v), 'parts', n, 'hard', len(HARD), 'keep', len(KEEP))
    return res


if __name__ == '__main__':
    a = sys.argv
    fp = None
    if os.path.exists(os.path.join(os.path.dirname(a[1]), 'place.json')):
        fp = json.load(open(os.path.join(os.path.dirname(a[1]), 'place.json')))['st']      # CH2's mock-up positions
    for extra in a[6:]:                                              # positions of the other blocks from an earlier round
        fp = dict(fp or {}); fp.update(json.load(open(extra))['st'])
    run(a[1], a[2], a[3], int(a[4]) if len(a) > 4 else 1, int(a[5]) if len(a) > 5 else 100000, fixed_pos=fp)
