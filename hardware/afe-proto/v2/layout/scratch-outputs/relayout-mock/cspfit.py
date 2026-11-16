"""CSP fit of the free CH parts around one fixed template translation.  BLK, VAR, XL, YB in the environment (or argv: json list of picks).
Backtracking with forward checking over numpy domains; first complete assignment wins."""
import sys, os, math, json, time, random
sys.argv = [sys.argv[0], 'csp']
import scan_tmpl2 as T
T.kof = lambda r, rot: int(round((rot - round(T.P0[r]['rot'])) / 90.0)) % 4
R = T.R
np, RP, P0, PN = T.np, T.RP, T.P0, T.PN
BLK = T.BLK
OVm, vbad, mext, mlab = T.OVm, T.vbad, T.mext, T.mlab
pl_above, pl_any = T.pl_above, T.pl_any
HN, HO, HNP = float(os.environ.get('HN', 8)), float(os.environ.get('HO', 10)), float(os.environ.get('HNP', 12))
CAPB = int(os.environ.get('CAPB', 12))
HZ = {'CH1': ('/CH1_N', '/CH1_M1', '/CH1_M2', '/CH1_M3', '/CH1_NP'), 'CH2': ('/CH2_N', '/CH2_M1', '/CH2_M2', '/CH2_M3', '/CH2_NP')}[BLK]
def lim(net): return HN if net.endswith('_N') else (HNP if net.endswith('_NP') else HO)
def box(p, g, x, y, key): b = g[key]; return (b[0] + x, b[1] + y, b[2] + x, b[3] + y)
BESIDE_FIX = T.BESIDE_FIX

def fixed_obstacles(tmpl):
    """{ref: dict(cy, ext, lab, bes)} for every part that is not a free CH part"""
    ob = {}
    for r, p in PN.items():
        if r in T.PART and r not in tmpl: continue
        if r in tmpl:
            x, y, rot, ls = tmpl[r]; k = T.kof(r, rot); g = RP.part_geom(P0[r], k, ls)
            ob[r] = dict(cy=box(0, g, x, y, 'cy'), ext=box(0, g, x, y, 'ext'), lab=box(0, g, x, y, 'lab'), bes=True); continue
        g = RP.part_geom(p); x, y = p['x'], p['y']
        d = dict(cy=box(0, g, x, y, 'cy'), ext=box(0, g, x, y, 'ext'), lab=None, bes=r in BESIDE_FIX)
        if r in ('J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607'):
            c = RP.header_label(p); w, h = RP.LAB_W * 4, RP.LAB_H; d['lab'] = (c[0] - w / 2, c[1] - h / 2, c[0] + w / 2, c[1] + h / 2)
        elif r in ('U101', 'U301', 'U401'):
            d['lab'] = RP.u101_label_east(PN, None, r)[0]
        elif not (r.startswith('MH') or r in ('J101', 'J201', 'J301')):
            w, h = RP.LAB_W * len(r), RP.LAB_H
            if abs((p['tang'] % 180) - 90) < 1: w, h = h, w
            d['lab'] = (p['tx'] - w / 2, p['ty'] - h / 2, p['tx'] + w / 2, p['ty'] + h / 2)
        ob[r] = d
    ob['_blockname'] = dict(cy=(35.5, 45.2, 44.2, 46.9), ext=(35.5, 45.2, 44.2, 46.9), lab=None, bes=False)
    import re, subprocess
    txt = subprocess.run(['git', 'show', 'HEAD:hardware/afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pcb'], capture_output=True, text=True, cwd='/work').stdout if False else open('/work/hardware/afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pcb').read()
    n = 0
    for m in re.finditer(r'\n\t\(gr_line\n\t\t\(start ([\d.-]+) ([\d.-]+)\)\n\t\t\(end ([\d.-]+) ([\d.-]+)\)(?:\n\t\t.*)*?\n\t\t\(layer "F.SilkS"\)', txt):
        x0, y0, x1, y1 = float(m.group(1)) - 50, 150 - float(m.group(2)), float(m.group(3)) - 50, 150 - float(m.group(4))
        bxx = (min(x0, x1) - 0.075, min(y0, y1) - 0.075, max(x0, x1) + 0.075, max(y0, y1) + 0.075)
        if bxx[2] < 55 or bxx[0] > 95 or bxx[3] < 17 or bxx[1] > 50: continue
        ob['_line%d' % n] = dict(cy=None, ext=bxx, lab=None, bes=False); n += 1
    for m in re.finditer(r'\n\t\(gr_text "([^"]+)"\n\t\t\(at ([\d.-]+) ([\d.-]+)', txt):
        t, x, y = m.group(1), float(m.group(2)) - 50, 150 - float(m.group(3))
        if t in ('CH1', 'CH2') or True:
            w = len(t) * 0.95 * 1.0; h = 1.2
            if 55 < x < 95 and 17 < y < 50: ob['_text_' + t + str(n)] = dict(cy=None, ext=None, lab=(x - w / 2, y - h / 2, x + w / 2, y + h / 2), bes=False); n += 1
    return ob

def stack(ob, skip=()):
    ks = [k for k in ob if k not in skip]
    cy = np.array([ob[k]['cy'] for k in ks if ob[k]['cy'] is not None]); ext = np.array([ob[k]['ext'] for k in ks if ob[k]['ext'] is not None])
    lab = np.array([ob[k]['lab'] for k in ks if ob[k]['lab'] is not None]).reshape(-1, 4)
    bcy = np.array([ob[k]['cy'] for k in ks if ob[k]['bes']]).reshape(-1, 4)
    blab = np.array([ob[k]['lab'] for k in ks if ob[k]['bes'] and ob[k]['lab'] is not None]).reshape(-1, 4)
    return cy, ext, lab, bcy, blab

def padxy(r, k, x, y, n):
    p = P0[r]; cs, sn = RP.COS[k], RP.SIN[k]
    q = [q for q in p['pads'] if q['n'] == n][0]; o = (q['c'][0] - p['x'], q['c'][1] - p['y']); o = (o[0] * cs - o[1] * sn, o[0] * sn + o[1] * cs)
    return x + o[0], y + o[1]

OTHERPADS = []
def load_other():
    f = os.environ.get('OTHERFILE')
    st = json.load(open(f))['st'] if f else {}; ob_ = 'CH2' if BLK == 'CH1' else 'CH1'; nets = (('/CH2_N', '/CH2_NP', '/CH2_IN') if BLK == 'CH1' else ('/CH1_N', '/CH1_NP', '/CH1_IN'))
    for rr, v in st.items():
        if rr not in P0 or RP.block_of(rr) != ob_: continue
        k = int(round((v[2] - round(P0[rr]['rot'])) / 90.0)) % 4
        for q in P0[rr]['pads']:
            if q['net'] in nets:
                xy = padxy(rr, k, v[0], v[1], q['n'])
                if xy[0] < 91.0: OTHERPADS.append(xy)
    for w in P0['U101']['pads']:
        if w['net'] in nets and w['c'][0] < 91.0: OTHERPADS.append(tuple(w['c']))
load_other()
GROUP = ('/CH1_N', '/CH1_NP', '/CH1_IN') if BLK == 'CH1' else ('/CH2_N', '/CH2_NP', '/CH2_IN')
def domain(r, tmpl, ob, O, windows, relax=()):
    cy_, ext_, lab_, bcy_, blab_ = O
    p = P0[r]; ks = range(4) if r.startswith(RP.ROTATABLE) else [0]
    # fixed pads per hi-Z net (template parts and U101)
    fixed = {}
    for rr, (x, y, rot, ls) in tmpl.items():
        k = T.kof(rr, rot)
        for q in P0[rr]['pads']:
            if q['net'] in HZ: fixed.setdefault(q['net'], []).append(padxy(rr, k, x, y, q['n']))
    for q in P0['U101']['pads']:
        if q['net'] in HZ: fixed.setdefault(q['net'], []).append((q['c'][0], q['c'][1]))
    out = {k_: [] for k_ in ('k', 'ls', 'x', 'y', 'cy', 'z', 'lab', 'ext')}
    for (cx, cyy, rad, step) in windows:
        xs = np.round(np.arange(cx - rad, cx + rad + 1e-9, step), 3); ys = np.round(np.arange(cyy - rad, cyy + rad + 1e-9, step), 3)
        X, Y = np.meshgrid(xs, ys); X = X.ravel(); Y = Y.ravel()
        for k in ks:
            for ls in (0, 2, 4, 10, 11):
                gg = RP.part_geom(p, k, ls)
                def bx(b): return np.stack([X + b[0], Y + b[1], X + b[2], Y + b[3]], 1)
                E = bx(gg['ext']); CYB = bx(gg['cy']); LB = bx(gg['lab'])
                ZB = bx((gg['lab'][0] - 0.06, gg['lab'][1] - 0.06, gg['lab'][2] + 0.06, gg['lab'][3] + 0.06)) if ls >= 10 else bx(gg['zone'])
                LBC = np.stack([(LB[:, 0] + LB[:, 2]) / 2 - 0.01, (LB[:, 1] + LB[:, 3]) / 2 - 0.01, (LB[:, 0] + LB[:, 2]) / 2 + 0.01, (LB[:, 1] + LB[:, 3]) / 2 + 0.01], 1)
                ok = (vbad(mext, E) <= 0) & (vbad(mlab, LBC) <= 0)
                # unary rules from the fixed pads: half-perimeter, ties, flow
                for q in p['pads']:
                    if q['net'] in HZ:
                        cs, sn = RP.COS[k], RP.SIN[k]; o = (q['c'][0] - p['x'], q['c'][1] - p['y']); o = (o[0] * cs - o[1] * sn, o[0] * sn + o[1] * cs)
                        px, py = X + o[0], Y + o[1]; fx = [f[0] for f in fixed.get(q['net'], [])]; fy = [f[1] for f in fixed.get(q['net'], [])]
                        if fx:
                            ok &= (np.maximum(px, max(fx)) - np.minimum(px, min(fx)) + np.maximum(py, max(fy)) - np.minimum(py, min(fy))) <= lim(q['net']) + 1e-9
                if OTHERPADS:
                    for q in p['pads']:
                        if q['net'] in GROUP:
                            cs, sn = RP.COS[k], RP.SIN[k]; o = (q['c'][0] - p['x'], q['c'][1] - p['y']); o = (o[0] * cs - o[1] * sn, o[0] * sn + o[1] * cs)
                            px, py = X + o[0], Y + o[1]
                            for (ox, oy) in OTHERPADS: ok &= (px >= 91.0) | (np.hypot(px - ox, py - oy) >= 5.0)
                if 'tie' not in relax:
                    for ref, pin, ic, ipin, L in (('C104', '1', 'U101', '8', 2.8), ('C105', '1', 'U101', '8', 2.8), ('R108', '1', 'U101', '7', 5.0), ('R208', '1', 'U101', '1', 5.0)):
                        if r == ref:
                            cs, sn = RP.COS[k], RP.SIN[k]; q = [q for q in p['pads'] if q['n'] == pin][0]; o = (q['c'][0] - p['x'], q['c'][1] - p['y']); o = (o[0] * cs - o[1] * sn, o[0] * sn + o[1] * cs)
                            u = [w for w in P0[ic]['pads'] if w['n'] == ipin][0]['c']
                            ok &= np.hypot(X + o[0] - u[0], Y + o[1] - u[1]) <= L
                if 'flow' not in relax:
                    ux = P0['U101']['x']
                    if r in ('R101', 'R201'):
                        rr = 'R107' if r == 'R101' else 'R207'; ok &= X > tmpl[rr][0] + 0.01
                    if r in ('R108', 'R208'): ok &= X < ux - 0.01
                    if r in ('R107', 'R207'): ok &= X > ux + 0.01
                idx = np.flatnonzero(ok)
                for c0 in range(0, len(idx), 4000):
                    ii = idx[c0:c0 + 4000]
                    bad = OVm(CYB[ii], cy_, 0.0).any(1) | OVm(ZB[ii], cy_, 0).any(1)
                    if 'lab' not in relax:
                        bad |= OVm(LB[ii], lab_, 0.5).any(1) | OVm(CYB[ii], lab_, 0).any(1)
                        bad |= OVm(LB[ii] + np.array([-0.3, -0.3, 0.3, 0.3]), ext_, 0).any(1)
                        bad |= pl_any(LB[ii], bcy_).any(1)
                        if len(blab_): bad |= pl_above(blab_, CYB[ii]).any(0)
                        if ls >= 10: bad |= pl_above(LB[ii], cy_).any(1) | pl_any(lab_, CYB[ii]).any(0)
                    jj = ii[~bad]
                    for key, arr in (('cy', CYB), ('z', ZB), ('lab', LB), ('ext', E)): out[key].append(arr[jj])
                    out['x'].append(X[jj]); out['y'].append(Y[jj]); out['k'].append(np.full(len(jj), k)); out['ls'].append(np.full(len(jj), ls))
    D = {k_: (np.concatenate(v) if v else np.zeros((0, 4)) if k_ in ('cy', 'z', 'lab', 'ext') else np.zeros(0)) for k_, v in out.items()}
    if len(D['x']):                       # dedupe
        key = np.round(np.stack([D['x'], D['y'], D['k'], D['ls']], 1), 3); _, u = np.unique(key, axis=0, return_index=True)
        D = {k_: v[u] for k_, v in D.items()}
    return D

def OV2(A, B, g): return ((np.minimum(A[:, None, 2], B[None, :, 2]) - np.maximum(A[:, None, 0], B[None, :, 0]) + g) > 1e-6) & ((np.minimum(A[:, None, 3], B[None, :, 3]) - np.maximum(A[:, None, 1], B[None, :, 1]) + g) > 1e-6)
def conflict(c, D):
    """boolean over D: candidate c (dict of boxes) conflicts with each domain entry"""
    A = lambda b: np.array([b])
    cy1, z1, l1 = A(c['cy']), A(c['z']), A(c['lab'])
    bad = OV2(cy1, D['cy'], 0.0)[0] | OV2(z1, D['cy'], 0)[0] | OV2(cy1, D['z'], 0)[0] | OV2(l1, D['lab'], 0.5)[0] | OV2(cy1, D['lab'], 0)[0] | OV2(l1, D['cy'], 0)[0]
    b1 = c['ls'] >= 10; b2 = D['ls'] >= 10
    if b1: bad |= pl_any(D['lab'], cy1).any(1) | pl_above(l1, D['cy']).any(0)
    bad |= b2 & (pl_any(l1, D['cy']).any(0) | pl_above(D['lab'], cy1).any(1))
    return bad

def solve(tmpl, relax=(), skip=(), tl=60.0, seed=1, verbose=False):
    ob = fixed_obstacles(tmpl); O = stack(ob, skip)
    free = [r for r in T.PART if r not in tmpl]
    # windows: around the fixed pads each part must stay near, else the region
    xs = [q for rc in RP.REGIONS[BLK] for q in (rc[0], rc[2])]; ys = [q for rc in RP.REGIONS[BLK] for q in (rc[1], rc[3])]
    reg = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(max(xs) - min(xs), max(ys) - min(ys)) / 2, 0.5)
    anchors = {}
    for r in free:
        a = []
        for q in P0[r]['pads']:
            if q['net'] in HZ:
                for rr, (x, y, rot, ls) in tmpl.items():
                    for w in P0[rr]['pads']:
                        if w['net'] == q['net']: a.append(padxy(rr, T.kof(rr, rot), x, y, w['n']))
                for w in P0['U101']['pads']:
                    if w['net'] == q['net']: a.append(tuple(w['c']))
        if r in ('C104', 'C105', 'R108', 'R208'):
            u = [w for w in P0['U101']['pads'] if w['n'] == {'C104': '8', 'C105': '8', 'R108': '7', 'R208': '1'}[r]][0]['c']; a = [tuple(u)]
        anchors[r] = a
    doms = {}
    for r in free:
        wins = []
        if anchors[r]:
            ax = sum(a[0] for a in anchors[r]) / len(anchors[r]); ay = sum(a[1] for a in anchors[r]) / len(anchors[r])
            wins.append((ax, ay, 7.0, 0.25))
        else: wins.append(reg)
        doms[r] = domain(r, tmpl, ob, O, wins, relax)
        if verbose: print(r, 'domain', len(doms[r]['x']), flush=True)
        if not len(doms[r]['x']): return None, ('empty domain', r, {k: len(v['x']) for k, v in doms.items()})
    t0 = time.time(); rng = random.Random(seed); nodes = [0]
    def sub(D, mask): return {k: v[mask] for k, v in D.items()}
    def search(doms, chosen, nbes):
        if time.time() - t0 > tl: return 'timeout'
        if not doms: return chosen
        r = min(doms, key=lambda q: len(doms[q]['x']))
        D = doms[r]; n = len(D['x'])
        score = (D['ls'] >= 10) * 1000.0
        if anchors[r]:
            ax = sum(a[0] for a in anchors[r]) / len(anchors[r]); ay = sum(a[1] for a in anchors[r]) / len(anchors[r])
            score = score + np.hypot(D['x'] - ax, D['y'] - ay)
        order = np.argsort(score + np.array([rng.random() * 0.3 for _ in range(n)]) if n < 200000 else score)
        tries = 0
        for i in order:
            c = dict(cy=D['cy'][i], z=D['z'][i], lab=D['lab'][i], ls=int(D['ls'][i]))
            nb = nbes + (1 if c['ls'] >= 10 else 0)
            rest = {q: doms[q] for q in doms if q != r}; new = {}; dead = False
            for q, Dq in rest.items():
                m = ~conflict(c, Dq)
                if nb >= CAPB - 6: m &= Dq['ls'] < 10 if CAPB - 6 <= nb else m
                if not m.any(): dead = True; break
                new[q] = sub(Dq, m)
            nodes[0] += 1
            if dead:
                tries += 1
                if tries > 400: return None
                continue
            res = search(new, chosen + [(r, int(D['k'][i]), int(D['ls'][i]), float(D['x'][i]), float(D['y'][i]))], nb)
            if res == 'timeout': return res
            if res: return res
            tries += 1
            if tries > 400: return None
        return None
    res = search(doms, [], 0)
    return (res if res not in (None, 'timeout') else None), ('timeout' if res == 'timeout' else 'no fit', nodes[0], {k: len(v['x']) for k, v in doms.items()})

def to_placement(tmpl, chosen):
    st = {r: [x, y, rot, ls] for r, (x, y, rot, ls) in tmpl.items()}
    for r, k, ls, x, y in chosen: st[r] = [x, y, ((round(P0[r]['rot']) + 90 * k + 180) % 360) - 180, ls]
    return st

if __name__ == '__main__':
    picks = json.load(open(R + 'picks_%s.json' % BLK))
    only = os.environ.get('ONLY')
    for var, xl, yb, base in picks:
        if only and var != only: continue
        t = T.template(var, xl, yb) if hasattr(T, 'template') else None
        res, info = solve(t, tl=float(os.environ.get('TL', 60)), verbose=False)
        print(var, round(xl, 2), round(yb, 2), 'NPbase', round(base, 2), '->', 'FIT' if res else info, flush=True)
        if res:
            json.dump(dict(st=to_placement(t, res), var=var, xl=xl, yb=yb), open(R + 'csp_%s_%s_%s.json' % (BLK, var, str(round(xl, 2))), 'w')); print('FOUND', flush=True); break
