"""Stray-capacitance estimate between chosen nets of the routed board: a 3-D finite-difference Laplace solve.

    python3.14 -I cap.py [board.kicad_pcb]

Method (every number it prints is a result of this solve and nothing else; all are *(check)* against VT-19's extraction):
  - a window around the pair under study, 0.1 mm cells in x and y; z: the bottom ground plane at z = 0 (Dirichlet 0),
    1.6 mm of FR4 (er 4.5 *(check)*, JLC's 1.6 mm 2-layer stack-up is not given in jlcpcb.md), the top copper at
    z = 1.6 mm, then air up to 8 mm where a grounded lid closes the box (the shield above is the Due's, 8.5 mm up);
  - the four side faces are Neumann (the box is cut out of a larger board: the result is a slight over-estimate for
    nets near the window edge, so the window is padded 4 mm beyond the nets);
  - top-layer copper of each net is a conductor at z = 1.6 (pads, tracks as capsules); every net not under study is
    held at 0 V, which is the usual ground-capacitance reading and it ignores that other high-impedance nodes float;
  - part bodies (SOIC plastic, 0603 ceramics) and solder mask are not modelled;
  - one scenario has the top GND pour present (every cell farther than POUR_CLEAR from non-GND copper is GND), the
    other has none (all other copper is as routed: tracks and pads only), and the larger of the two is the bound;
  - the mutual capacitance C_ij is the charge on conductor j with conductor i at 1 V and everything else at 0 V.
Resolution 0.1 mm for 0.2 mm tracks is coarse: the figure is good to a factor of about 1.5 and no better *(check)*.
"""
import math
import os
import sys

import numpy as np

sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew as pcb  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
H = 0.1                  # mm cell (main() may change it)
ER = 4.5
T_BOARD, T_AIR = 1.6, 4.0
POUR_CLEAR = 0.3
E0 = 8.854e-12           # F/m


def mm(v):
    return pcb.ToMM(v)


def copper(board, nets):
    """{net: [('rect', x0, y0, x1, y1) | ('seg', xa, ya, xb, yb, w)]} on F.Cu, board coordinates (y down)"""
    out = {n: [] for n in nets}
    out['__other__'] = []
    for f in board.GetFootprints():
        for p in f.Pads():
            if not p.IsOnLayer(pcb.F_Cu):
                continue
            n = str(p.GetNetname())
            b = p.GetBoundingBox()
            item = ('rect', mm(b.GetLeft()), mm(b.GetTop()), mm(b.GetRight()), mm(b.GetBottom()))
            out[n if n in out else '__other__'].append(item) if n != '/GND' else out.setdefault('/GND', []).append(item)
    for t in board.GetTracks():
        if t.GetClass() == 'PCB_VIA':
            continue
        if t.GetLayer() != pcb.F_Cu:
            continue
        n = str(t.GetNetname())
        item = ('seg', mm(t.GetStart().x), mm(t.GetStart().y), mm(t.GetEnd().x), mm(t.GetEnd().y), mm(t.GetWidth()))
        out[n if n in out else '__other__'].append(item) if n != '/GND' else out.setdefault('/GND', []).append(item)
    return out


def raster(items, x0, y0, nx, ny):
    m = np.zeros((ny, nx), bool)
    xs = x0 + (np.arange(nx) + 0.5) * H
    ys = y0 + (np.arange(ny) + 0.5) * H
    X, Y = np.meshgrid(xs, ys)
    for it in items:
        if it[0] == 'rect':
            m |= (X >= it[1]) & (X <= it[3]) & (Y >= it[2]) & (Y <= it[4])
        else:
            _, ax, ay, bx, by, w = it
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            t = np.clip(((X - ax) * dx + (Y - ay) * dy) / L2, 0, 1) if L2 > 0 else 0 * X
            d2 = (X - (ax + t * dx)) ** 2 + (Y - (ay + t * dy)) ** 2
            m |= d2 <= (w / 2) ** 2
    return m


def solve(cond, eps, nz_board, fixed1):
    """cond: bool (nz, ny, nx) of conductor cells (at the top-copper layer only), eps per cell, drive: fixed1 subset
    of cond at 1 V, the rest of cond at 0 V.  Matrix-free CG on the Laplacian with face-averaged permittivity."""
    nz, ny, nx = eps.shape
    V = np.zeros(eps.shape)
    fixed = cond.copy()
    fixed[0, :, :] = True        # ground plane
    fixed[-1, :, :] = True       # lid
    V[fixed1] = 1.0
    free = ~fixed
    # face conductances (harmonic mean of the two cells' permittivity, in units where hx = hy = hz = H)
    def face(a, b):
        return 2 * a * b / (a + b)
    cx = face(eps[:, :, :-1], eps[:, :, 1:])
    cy = face(eps[:, :-1, :], eps[:, 1:, :])
    cz = face(eps[:-1, :, :], eps[1:, :, :])

    def A(v):
        r = np.zeros_like(v)
        d = v[:, :, 1:] - v[:, :, :-1]
        fl = cx * d
        r[:, :, :-1] += fl
        r[:, :, 1:] -= fl
        d = v[:, 1:, :] - v[:, :-1, :]
        fl = cy * d
        r[:, :-1, :] += fl
        r[:, 1:, :] -= fl
        d = v[1:, :, :] - v[:-1, :, :]
        fl = cz * d
        r[:-1, :, :] += fl
        r[1:, :, :] -= fl
        return r
    diag = np.zeros(eps.shape)
    diag[:, :, :-1] += cx; diag[:, :, 1:] += cx
    diag[:, :-1, :] += cy; diag[:, 1:, :] += cy
    diag[:-1, :, :] += cz; diag[1:, :, :] += cz
    b = -A(V)                       # residual with the fixed values in place
    b[~free] = 0
    x = np.zeros(eps.shape)
    r = b.copy()
    Minv = np.where(free, 1.0 / np.maximum(diag, 1e-12), 0.0)
    z = Minv * r
    p = z.copy()
    rz = (r * z).sum()
    nb = math.sqrt((b * b).sum()) or 1.0
    for it in range(4000):
        Ap = A(p)
        Ap[~free] = 0
        a = rz / (p * Ap).sum()
        x += a * p
        r -= a * Ap
        if math.sqrt((r * r).sum()) < 1e-6 * nb:
            break
        z = Minv * r
        rz2 = (r * z).sum()
        p = z + (rz2 / rz) * p
        rz = rz2
    V = V + x
    return V, A(V)


def selftest():
    """the solver against a case with an exact answer: full-width parallel plates, uniform and with two dielectrics in
    series, C = e0 A / sum(d_i / er_i).  Returns the worst relative error."""
    worst = 0.0
    for layers in ((12, 1.0), (6, 4.5)), ((8, 4.5), (4, 1.0)), ((10, 2.0),):
        nzc = sum(n for n, _ in layers)
        nz, ny, nx = nzc + 2, 20, 20
        eps = np.ones((nz, ny, nx))
        z = 1
        d_over_er = 0.0
        for n, er in layers:
            eps[z - 1 + 0: z + n] = np.maximum(eps[z - 1: z + n], 0)   # cells between planes
            eps[z - 1: z - 1 + n] = er
            d_over_er += n * H / er
            z += n
        # planes at k = 1 (0 V, fixed) and k = nzc + 1 (1 V); eps of the layer cells k..k+n-1 sit between the planes
        eps[:] = 1.0
        k = 1
        for n, er in layers:
            eps[k: k + n] = er
            k += n
        eps[nzc + 1] = layers[-1][1]
        cond = np.zeros(eps.shape, bool)
        cond[1] = True
        cond[nzc + 1] = True
        fixed1 = np.zeros_like(cond); fixed1[nzc + 1] = True
        V, A = solve(cond, eps, 0, fixed1)
        # the lid and the ground at k = 0 / nz - 1 are Dirichlet too but are shielded by the planes (no flux between)
        q = A[1].sum()
        # flux into the bottom plane from the layer above only: the cell below (k = 0) is ground at the same 0 V
        c_fd = q * H * 1e-3 * E0 * 1e12
        c_ex = E0 * (nx * H * 1e-3) * (ny * H * 1e-3) / (d_over_er * 1e-3) * 1e12
        err = abs(c_fd - c_ex) / c_ex
        worst = max(worst, err)
        print(f'selftest plates {layers}: FD {c_fd * 1e3:.3f} fF, exact {c_ex * 1e3:.3f} fF, error {err * 100:.3f} %')
    return worst


def _hj(u, er):
    """Hammerstad and Jensen (1980) single microstrip, no lid: effective permittivity and characteristic impedance"""
    a = 1 + math.log((u ** 4 + (u / 52) ** 2) / (u ** 4 + 0.432)) / 49 + math.log(1 + (u / 18.1) ** 3) / 18.7
    b = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
    ee = (er + 1) / 2 + (er - 1) / 2 * (1 + 10 / u) ** (-a * b)
    F = 6 + (2 * math.pi - 6) * math.exp(-(30.666 / u) ** 0.7528)
    z0 = 376.73 / (2 * math.pi * math.sqrt(ee)) * math.log(F / u + math.sqrt(1 + (2 / u) ** 2))
    return ee, z0


def selftest_microstrip(w=1.6, h_sub=1.6, s=0.8, er=4.5):
    """The solver against a published geometry: a single microstrip (Hammerstad and Jensen) and a pair of coupled lines
    (Garg and Bahl 1979, from memory: *(check)* against the paper).  Two long strips w wide, s apart, on the board's
    stack; the capacitance per unit length from the solve against the formula.  The lid 4 mm up and the Neumann sides
    are the solver's own, so the formula's open-space answer is approached, not met; the error is reported."""
    global H
    H0 = H
    H = 0.1
    nzb = int(round(h_sub / H)); nza = int(round(T_AIR / H)); nz = nzb + 1 + nza + 1
    pad = 6.0
    nx = int(round((2 * w + s + 2 * pad) / H)); ny = 40
    eps = np.ones((nz, ny, nx)); eps[:nzb + 1] = er; eps[nzb] = (er + 1) / 2
    x0 = pad
    m1 = np.zeros((ny, nx), bool); m2 = np.zeros((ny, nx), bool)
    xs = (np.arange(nx) + 0.5) * H
    m1[:, (xs >= x0) & (xs < x0 + w)] = True
    m2[:, (xs >= x0 + w + s) & (xs < x0 + 2 * w + s)] = True
    out = {}
    cond = np.zeros((nz, ny, nx), bool); cond[nzb] = m1 | m2
    f1 = np.zeros_like(cond); f1[nzb] = m1
    V, res = solve(cond, eps, nzb, f1)
    out['c21'] = res[nzb][m2].sum() * H * 1e-3 * E0 * 1e12 / (ny * H * 1e-3)            # mutual, pF / m
    cond1 = np.zeros((nz, ny, nx), bool); cond1[nzb] = m1
    V, res = solve(cond1, eps, nzb, f1)                                                  # the single line alone
    out['c11'] = abs(res[nzb][m1].sum()) * H * 1e-3 * E0 * 1e12 / (ny * H * 1e-3)
    # the self capacitance seen from conductor 1 with conductor 2 grounded = C_ground + C_mutual
    ee, z0 = _hj(w / h_sub, er)
    c_single = math.sqrt(ee) / (299792458 * z0) * 1e12                                   # pF / m
    # Garg and Bahl even / odd mode
    e0 = E0 * 1e12
    u = w / h_sub; g = s / h_sub
    cp = e0 * er * u
    cf = 0.5 * (c_single - cp)
    A = math.exp(-0.1 * math.exp(2.33 - 2.53 * u))
    cfp = cf / (1 + A / g * math.tanh(8 * g))
    ce = cp + cf + cfp

    def K(k):
        a_, b_ = 1.0, math.sqrt(1 - k * k)
        for _ in range(30):
            a_, b_ = (a_ + b_) / 2, math.sqrt(a_ * b_)
        return math.pi / (2 * a_)
    k = g / (g + 2 * u); kp = math.sqrt(1 - k * k)
    cga = e0 * K(kp) / K(k)
    cgd = e0 * er / math.pi * math.log(1 / math.tanh(math.pi * g / 4)) + 0.65 * cf * (0.02 * math.sqrt(er) / g + 1 - 1 / er ** 2)
    co = cp + cf + cga + cgd
    c12 = (co - ce) / 2
    print(f'microstrip w/h = {u:.2f}, er {er}: single line  FD {out["c11"]:.1f} pF/m, Hammerstad-Jensen {c_single:.1f} pF/m ({out["c11"] / c_single * 100 - 100:+.1f} %)')
    print(f'coupled, gap s/h = {g:.2f}: mutual FD {out["c21"]:.2f} pF/m, Garg-Bahl (even {ce:.1f}, odd {co:.1f}) {c12:.2f} pF/m '
          f'({out["c21"] / c12 * 100 - 100:+.1f} %)')
    H = H0
    return abs(out['c11'] / c_single - 1), abs(out['c21'] / c12 - 1)


def pair_caps(board, nets, window, pour):
    cu = copper(board, nets)
    x0, y0, x1, y1 = window
    nx, ny = int(round((x1 - x0) / H)), int(round((y1 - y0) / H))
    nzb = int(round(T_BOARD / H)); nza = int(round(T_AIR / H))
    nz = nzb + 1 + nza + 1
    eps = np.ones((nz, ny, nx)); eps[:nzb + 1] = ER
    eps[nzb] = (ER + 1) / 2
    masks = {n: raster(cu[n], x0, y0, nx, ny) for n in nets}
    other = raster(cu['__other__'], x0, y0, nx, ny)
    gnd = raster(cu.get('/GND', []), x0, y0, nx, ny)
    if pour:
        occupied = other.copy()
        for m in masks.values():
            occupied |= m
        k = int(round(POUR_CLEAR / H))
        occ = occupied.copy()
        for dy in range(-k, k + 1):
            for dx in range(-k, k + 1):
                if dx * dx + dy * dy <= k * k:
                    occ |= np.roll(np.roll(occupied, dy, 0), dx, 1)
        gnd |= ~occ
    res = {}
    for i in nets:
        cond = np.zeros((nz, ny, nx), bool)
        cond[nzb] = gnd
        for n in nets:
            cond[nzb] |= masks[n]
        cond[nzb] |= other                      # other nets: 0 V
        fixed1 = np.zeros_like(cond); fixed1[nzb] = masks[i]
        V, res_ = solve(cond, eps, nzb, fixed1)
        for j in nets:
            if j == i:
                continue
            q = res_[nzb][masks[j]].sum()       # net flux into conductor j, in H * er-units
            res[(i, j)] = q * H * 1e-3 * E0 * 1e12      # C = eps0 * H[m] * sum of the link terms, in pF
    return res


def self_cap(board, net, pad=3.0, h=0.1):
    """capacitance of one net's top copper (pads and tracks, the part packages not modelled) to everything else, which is
    held at 0 V: the figure AN-1's table is read against (the inverting node, pF)"""
    global H
    H0 = H
    H = h
    cu = copper(board, (net,))
    items = cu[net]
    xs = [v for it in items for v in ((it[1], it[3]) if it[0] == 'rect' else (it[1], it[3]))]
    ys = [v for it in items for v in ((it[2], it[4]) if it[0] == 'rect' else (it[2], it[4]))]
    x0, y0, x1, y1 = min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad
    nx, ny = int(round((x1 - x0) / H)), int(round((y1 - y0) / H))
    nzb = int(round(T_BOARD / H)); nza = int(round(T_AIR / H)); nz = nzb + 1 + nza + 1
    eps = np.ones((nz, ny, nx)); eps[:nzb + 1] = ER; eps[nzb] = (ER + 1) / 2
    m = raster(items, x0, y0, nx, ny)
    other = raster(cu['__other__'], x0, y0, nx, ny)
    gnd = raster(cu.get('/GND', []), x0, y0, nx, ny)
    res = {}
    for pour in (False, True):
        g = gnd | other
        if pour:
            occ = m | other
            k = int(round(POUR_CLEAR / H))
            occ2 = occ.copy()
            for dy in range(-k, k + 1):
                for dx in range(-k, k + 1):
                    if dx * dx + dy * dy <= k * k:
                        occ2 |= np.roll(np.roll(occ, dy, 0), dx, 1)
            g = g | ~occ2
        cond = np.zeros((nz, ny, nx), bool); cond[nzb] = m | g
        f1 = np.zeros_like(cond); f1[nzb] = m
        V, r_ = solve(cond, eps, nzb, f1)
        res[pour] = abs(r_[nzb][m].sum()) * H * 1e-3 * E0 * 1e12
    H = H0
    return res


def main(path=os.path.join(HERE, 'afe-v2.kicad_pcb')):
    board = pcb.LoadBoard(path)
    global H
    out = {}
    for label, nets, pad in (('N-N', ('/CH1_N', '/CH2_N'), 3.0), ('NP-NP (+IN pads)', ('/CH1_NP', '/CH2_NP'), 3.0)):
        pts = []
        for f in board.GetFootprints():
            for p in f.Pads():
                if str(p.GetNetname()) in nets:
                    pts.append((mm(p.GetPosition().x), mm(p.GetPosition().y)))
        for t in board.GetTracks():
            if t.GetClass() != 'PCB_VIA' and str(t.GetNetname()) in nets:
                pts += [(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))]
        w = (min(p[0] for p in pts) - pad, min(p[1] for p in pts) - pad, max(p[0] for p in pts) + pad,
             max(p[1] for p in pts) + pad)
        H = 0.1 if label.startswith('NP') else 0.2
        for pour in (False, True):
            r = pair_caps(board, list(nets), w, pour)
            v = r[(nets[0], nets[1])]
            out[(label, pour)] = v
            print(f'{label:20s} pour={pour!s:5s} window {w[2]-w[0]:.0f}x{w[3]-w[1]:.0f} mm  C = {v * 1e3:.2f} fF '
                  f'(reverse {r[(nets[1], nets[0])] * 1e3:.2f} fF)', flush=True)
    for net in ('/AWG_FB',):
        r = self_cap(board, net)
        print(f'{net} self capacitance to everything else (tracks and pads, no package): no pour {r[False]:.3f} pF, '
              f'with the top pour (kept 0.3 mm off) {r[True]:.3f} pF', flush=True)
        out[(net, 'self')] = r
    return out


if __name__ == '__main__':
    if sys.argv[1:2] == ['selftest']:
        e1 = selftest()
        e2 = selftest_microstrip()
        sys.exit(0 if e1 < 0.08 else 1)
    main(*sys.argv[1:2])
