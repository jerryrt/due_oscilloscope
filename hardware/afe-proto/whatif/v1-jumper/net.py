#!/usr/bin/env python3
"""Version 1 jumper ratio measurement, general k.  Nodal truth model + the host's procedure + Monte Carlo (numpy only).
Adapted from kvm_02's v2 sense.py.  Version 1: ladder 8 x 270 ohm (taps 0.1875 .. 3.000 V), AWG window -1.35 .. +1.35 V (AW-1 reach about +-1.3 V
plus 50 mV), ADS1115 AIN0 = sense tap, AIN1 = VREF, AIN2 = the bottom-end reading, divider R7 (A to tap) and R8 (tap to B),
k = R8 / (R7 + R8), tap = (1 - k) B + k A, B tied to VREF by Rd, a jumper wire moves B to a LOW ladder tap (TAP2).

Nodes: 0 T0 (sense tap), 1 PIN (ADS1115 AIN0 with BAV99), 2 B, 3..7 TAP1..TAP5, 8 P2 (the AIN2 pin, behind Rm2 from B or from TAP2).
Datasheet figures, ADS1115 SBAS444E (hardware/afe-proto/models/ads1115/ads1115.pdf, section 5.5, read 2026-11-12): Zcm 6 Mohm at FSR +-4.096 V
(typ, no spread given), Zdiff 15 Mohm; offset +-3 LSB, offset channel match 3 LSB; gain channel match 0.05 % typ / 0.1 % max; noise 125 uVrms at
+-4.096 V (Table 6-1, <= 128 SPS); INL 1 LSB at +-2.048 V / 8 SPS only; abs max inputs GND - 0.3 V .. VDD + 0.3 V, 10 mA continuous."""
import os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results"); os.makedirs(RES, exist_ok=True)

LSB = 125e-6; NOISE = 125e-6; VC = 0.7; ZCM = 6e6; EPS_MAX = 0.001; EPS_TYP = 0.0005
OFF_LSB = 3.0; INL_LSB = 1.0
VREF = 3.0; REF_TOL = 0.001
RL = 270.0
VDD_MIN = 3.21     # +3V3A low corner, whatif/v1-basic/values.md section 4 (3.2095 V at the LM27762 limits)
AWG_LIM = 1.35
LEV = np.linspace(-AWG_LIM, AWG_LIM, 25)
NODE = dict(TAP1=3, TAP2=4, TAP3=5, TAP4=6, TAP5=7)

# the designs: R7 = Rt (A to tap), R8 = Rb (tap to B); k = Rb / (Rt + Rb)
BASE = dict(Rd=1e3, Rs=1.0, Rm1=0.0, Rm2=0.0, Il=0.0, chan="B")
def _d(rt, rb, wire, rm=0.0, **kw): return dict(BASE, Rt=rt, Rb=rb, wire=wire, Rm1=rm, Rm2=rm, **kw)
DESIGNS = {      # R7 = Rt, R8 = Rb; every value a Basic 0603 1 % (hardware/afe-proto/v2/jlc-basic.csv): 10k C25804, 20k C4184, 22k C31850, 30k C22984, 39k C23153, 47k C25819, 68k C23231, 82k C23254, 100k C25803, 150k C22807, 200k C25811; Rm: 7.5k C23234, 8.2k C25981, 15k C22809, 24k C23352
    "k1/2":  _d(47e3, 47e3, "TAP4"),
    "k1/3":  _d(47e3, 22e3, "TAP2"),
    "k1/4":  _d(30e3, 10e3, "TAP2"),
    "k1/5":  _d(39e3, 10e3, "TAP2"),
    "k1/2 matched": _d(47e3, 47e3, "TAP4", 24e3),
    "k1/3 matched": _d(47e3, 22e3, "TAP2", 15e3),
    "k1/4 matched": _d(30e3, 10e3, "TAP2", 7.5e3),
    "k1/5 matched": _d(39e3, 10e3, "TAP2", 8.2e3),
}
GRID = {"1/2": [(10e3, 10e3), (22e3, 22e3), (47e3, 47e3)], "1/3": [(20e3, 10e3), (47e3, 22e3), (100e3, 47e3)],
        "1/4": [(30e3, 10e3), (68e3, 22e3), (150e3, 47e3)], "1/5": [(39e3, 10e3), (82e3, 22e3), (200e3, 47e3)]}   # (R7, R8) per k
DES = dict(DESIGNS["k1/2"])

def kof(d): return d["Rb"] / (d["Rt"] + d["Rb"])
def rth(d): return d["Rt"] * d["Rb"] / (d["Rt"] + d["Rb"])

def solve_net(A, ref, rl3, rl5, Rt, Rb, Rd, Rs, Z, Il=0.0, wire=None, Vx=None, wire_r=1e-3, Rm2=None, Z2=None, chan="B", inj=None):
    """Nodal solve.  wire: None | 'TAPn' (B to that tap) | 'ladderXY' (tap X to tap Y, B on its default) | 'fixed' (B to the source Vx) | 'tapNfixed' (tap N to Vx).
    A: scalar or (n,).  Returns the node voltages; the AIN2 pin is P2."""
    n = Rt.shape[0]; N = 10
    free_ref = ref is None
    G = np.zeros((n, N, N)); b = np.zeros((n, N))
    def res(i, j, r):
        g = 1.0 / r
        G[:, i, i] += g
        if j is not None:
            G[:, j, j] += g; G[:, i, j] -= g; G[:, j, i] -= g
    def src(i, r, v):
        g = 1.0 / r; G[:, i, i] += g; b[:, i] += g * v
    src(0, Rt, A); res(0, 2, Rb); res(0, 1, Rs); src(1, Z, VC); b[:, 1] -= Il
    if free_ref: res(2, 9, Rd)
    else: src(2, Rd, ref)
    for k in range(3): src(3, rl3[:, k], 0.0)
    res(3, 4, rl5[:, 0]); res(4, 5, rl5[:, 1]); res(5, 6, rl5[:, 2]); res(6, 7, rl5[:, 3])
    if free_ref: res(7, 9, rl5[:, 4])
    else: src(7, rl5[:, 4], ref)
    G[:, 9, 9] += 1e-9 if free_ref else 1.0
    w = lambda: np.full(n, wire_r)
    if wire in NODE: res(2, NODE[wire], w())
    elif wire and wire.startswith("ladder"): res(NODE["TAP" + wire[6]], NODE["TAP" + wire[7]], w())
    elif wire == "fixed": src(2, w(), Vx)
    elif wire and wire.endswith("fixed"): src(NODE["TAP" + wire[3]], w(), Vx)
    if Rm2 is not None:
        res(2 if chan == "B" else NODE[chan], 8, np.maximum(Rm2, 1.0)); src(8, Z2, VC)
    else:
        src(8, np.full(n, 1e15), VC)
    if inj is not None:
        for node, cur in inj.items(): b[:, node] -= cur      # current leaving the node (a clamp)
    V = np.linalg.solve(G, b[..., None])[..., 0]
    return dict(T0=V[:, 0], PIN=V[:, 1], B=V[:, 2], TAP1=V[:, 3], TAP2=V[:, 4], TAP3=V[:, 5], TAP4=V[:, 6], TAP5=V[:, 7], P2=V[:, 8], REF=V[:, 9], ref=ref)

def draw(n, seed=1, d=None, tol=0.01, zspread=0.25, eps=EPS_MAX, zcorr=0.0, inl_common=True, off_lsb=None):
    d = d or DES
    rng = np.random.default_rng(seed)
    U = lambda w, size=None: rng.uniform(-w, w, size)
    P = dict(Rt=d["Rt"] * (1 + U(tol, n)), Rb=d["Rb"] * (1 + U(tol, n)), Rd=d["Rd"] * (1 + U(tol, n)), Rs=d["Rs"] * (1 + U(tol, n)),
             Rm1=d["Rm1"] * (1 + U(tol, n)), Rm2=d["Rm2"] * (1 + U(tol, n)),
             rl3=RL * (1 + U(tol, (n, 3))), rl5=RL * (1 + U(tol, (n, 5))), ref=VREF * (1 + U(REF_TOL, n)))
    zc = U(zspread, (n, 1)); zi = U(zspread, (n, 4))
    P["Z"] = ZCM * (1 + zcorr * zc + (1 - zcorr) * zi)     # zcorr 1: one value common to the four channels; 0: independent per channel
    ol = OFF_LSB if off_lsb is None else off_lsb
    P["ge"] = 1 + U(eps / 2, (n, 4)); P["off"] = U(ol * LSB, (n, 4))
    P["inl"] = np.repeat(U(INL_LSB * LSB, (n, 1)), 4, 1) if inl_common else U(INL_LSB * LSB, (n, 4))
    P["rng"] = rng; P["n"] = n
    return P

def read(pin, ch, P, navg=64, noise=NOISE):
    vv = np.clip(pin, 0, 4.096)
    return (P["ge"][:, ch] * pin + P["off"][:, ch] + P["inl"][:, ch] * 4 * vv * (4.096 - vv) / 4.096 ** 2
            + P["rng"].normal(0, noise / np.sqrt(navg), P["n"]))

def unload(x, Rser, Zn=ZCM):
    return VC + (x - VC) * (Zn + Rser) / Zn

def host_T_from_AB(A, kk, B, d, Zn=ZCM):
    Rtot = d["Rt"] + d["Rb"]; gt, gb, gz = 1 / (Rtot * (1 - kk)), 1 / (Rtot * kk), 1 / (Zn + d["Rs"])
    return (A * gt + B * gb + VC * gz) / (gt + gb + gz)

def host_T_off(A, kk, refh, d, Zn=ZCM):
    Rtot = d["Rt"] + d["Rb"]; gt, gb, gd, gz = 1 / (Rtot * (1 - kk)), 1 / (Rtot * kk), 1 / d["Rd"], 1 / (Zn + d["Rs"])
    a11, a12, b1 = gt + gb + gz, -gb, A * gt + VC * gz
    a21, a22, b2 = -gb, gb + gd, refh * gd
    det = a11 * a22 - a12 * a21
    return (b1 * a22 - a12 * b2) / det

def run(n=20000, seed=1, d=None, eps=EPS_MAX, tol=0.01, zspread=0.25, zcorr=1.0, levels_ratio=(-1.3, 0.0, 1.3), navg=64, nav_ratio=64,
        host_Z=ZCM, iters=12, offs=True, leak_sign=+1, inl_common=True, hd=None, measure_k=True, sweep="J", off_lsb=None, ref_tol=None):
    d = d or DES; hd = hd or d
    P = draw(n, seed, d, tol, zspread, eps, zcorr, inl_common, off_lsb)
    if not offs: P["off"] = P["off"] * 0
    Rt, Rb, Rd, Rs, Z = P["Rt"], P["Rb"], P["Rd"], P["Rs"], P["Z"]
    Il = d["Il"] * leak_sign
    wire, chan = d["wire"], d["chan"]
    def readings(A, w, navg_):
        nd = solve_net(A, P["ref"], P["rl3"], P["rl5"], Rt, Rb, Rd, Rs, Z[:, 0], Il, w, None, Rm2=P["Rm2"], Z2=Z[:, 2], chan=chan)
        xs = dict(T=read(nd["PIN"], 0, P, navg_),
                  REF=read(VC + (P["ref"] - VC) * Z[:, 1] / (Z[:, 1] + P["Rm1"]), 1, P, navg_),
                  B=read(nd["P2"], 2, P, navg_))
        return nd, xs
    def unload_T(x): return VC + (x - VC) * (host_Z + hd["Rs"]) / host_Z
    def host_volts(xs):
        r = VREF / unload(xs["REF"], hd["Rm1"], host_Z)
        return unload_T(xs["T"]) * r, unload(xs["B"], hd["Rm2"], host_Z) * r
    Rtot = hd["Rt"] + hd["Rb"]; kn = hd["Rb"] / Rtot
    ks = []
    for LR in levels_ratio:
        _, xd = readings(LR, None, nav_ratio); _, xj = readings(LR, wire, nav_ratio)
        Td, Bd = host_volts(xd); Tj, Bj = host_volts(xj)
        A = np.full(n, float(LR)); kh = np.full(n, kn)
        if chan == "B":      # B is read in both states, on one channel
            f = lambda AA, kk: np.stack([host_T_from_AB(AA, kk, Bd, hd, host_Z) - Td, host_T_from_AB(AA, kk, Bj, hd, host_Z) - Tj])
        else:                # B is read only with the wire on; the wire-off B comes from the default tie (nominal Rd)
            f = lambda AA, kk: np.stack([host_T_off(AA, kk, VREF, hd, host_Z) - Td, host_T_from_AB(AA, kk, Bj, hd, host_Z) - Tj])
        for _ in range(iters):
            F = f(A, kh); dd = 1e-6
            dA = (f(A + dd, kh) - F) / dd; dk = (f(A, kh + dd) - F) / dd
            det = dA[0] * dk[1] - dk[0] * dA[1]
            A = A - (F[0] * dk[1] - dk[0] * F[1]) / det
            kh = kh - (dA[0] * F[1] - F[0] * dA[1]) / det
        ks.append(kh)
    kh = np.mean(ks, axis=0)
    if not measure_k: kh = np.full(n, kn)
    ktrue = Rb / (Rt + Rb)
    err, t0s, pins, bs = [], [], [], []
    for L in LEV:
        w = wire if sweep == "J" else None
        nd, xs = readings(L, w, navg)
        T0h, Bh = host_volts(xs)
        gt, gb, gz = 1 / (Rtot * (1 - kh)), 1 / (Rtot * kh), 1 / (host_Z + hd["Rs"])
        if sweep == "J" or chan == "B":
            est = (T0h * (gt + gb + gz) - Bh * gb - VC * gz) / gt
        else:
            gd = 1 / hd["Rd"]; Bo = (gb * T0h + gd * VREF) / (gb + gd)
            est = (T0h * (gt + gb + gz) - Bo * gb - VC * gz) / gt
        err.append(est - L * VREF / P["ref"])
        t0s.append(nd["T0"]); pins.append(nd["PIN"]); bs.append(nd["B"])
    err = np.array(err)
    Am = np.stack([np.ones_like(LEV), LEV], 1)
    coef = np.linalg.lstsq(Am, err, rcond=None)[0]
    return dict(err=err, off=coef[0], gain=coef[1], k=kh, ktrue=ktrue, t0=np.array(t0s), pin=np.array(pins), B=np.array(bs))

def summ(r, q=99.9):
    return dict(gain_pct=float(np.nanpercentile(np.abs(r["gain"]), q) * 100), off_mV=float(np.nanpercentile(np.abs(r["off"]), q) * 1e3),
                err_mV=float(np.nanpercentile(np.abs(r["err"]).max(0), q) * 1e3),
                k_err_pct=float(np.nanpercentile(np.abs(r["k"] / r["ktrue"] - 1), q) * 100),
                t0_min=float(r["t0"].min()), t0_max=float(r["t0"].max()), pin_min=float(r["pin"].min()), pin_max=float(r["pin"].max()),
                B_min=float(r["B"].min()), B_max=float(r["B"].max()))


# ------------------------------------------------------------------------------------------------------------------------------
# Structure S3 (kvm_02's v2 design): T0 on ADS1115 AIN2 through Rs, B on AIN3 through Rm, read as a DIFFERENTIAL pair AIN2 - AIN3 (T - B) and B alone
# single-ended on AIN3; A = B + (T - B)/k, k = d(T - B)/dB between the wire positions; the reference scale rebuilt from B with the wire off
# (KCL at B: REF = B - Rd (T - B)/Rb), so no other input's gain enters.  ADS1115 differential pairs allowed: AIN0-1, AIN0-3, AIN1-3, AIN2-3 (SBAS444E).
def run_s3(n=20000, seed=1, d=None, eps=EPS_MAX, tol=0.01, zspread=0.25, zcorr=1.0, ratio_level=0.0, lev=None, navg=64, host_Z=ZCM, iters=12,
           offs=True, inl_common=False, off_lsb=None, hd=None, Il=0.0):
    d = d or DES; hd = hd or d
    lev = LEV if lev is None else lev
    P = draw(n, seed, d, tol, zspread, eps, zcorr, inl_common, off_lsb)
    if not offs: P["off"] = P["off"] * 0
    Rt, Rb, Rd, Rs, Z = P["Rt"], P["Rb"], P["Rd"], P["Rs"], P["Z"]
    wire = d["wire"]
    rm = hd["Rm2"]
    def meas(A, w):
        nd = solve_net(A, P["ref"], P["rl3"], P["rl5"], Rt, Rb, Rd, Rs, Z[:, 1], Il, w, None, Rm2=P["Rm2"], Z2=Z[:, 2], chan="B")
        Dv = nd["PIN"] - nd["P2"]
        rB = read(nd["P2"], 2, P, navg)
        rD = P["ge"][:, 3] * Dv + P["off"][:, 3] + P["inl"][:, 3] * 4 * np.clip(nd["B"], 0, 4.096) * (4.096 - np.clip(nd["B"], 0, 4.096)) / 4.096 ** 2 + P["rng"].normal(0, NOISE / np.sqrt(navg), n)
        return nd, rB, rD
    uB = lambda r: VC + (r - VC) * (host_Z + rm) / host_Z
    Rtot = hd["Rt"] + hd["Rb"]; kn = hd["Rb"] / Rtot
    def host_T(AA, kk, Bm):
        gt, gb, gz = 1 / (Rtot * (1 - kk)), 1 / (Rtot * kk), 1 / (host_Z + hd["Rs"])
        T0 = (AA * gt + Bm * gb + VC * gz) / (gt + gb + gz)
        return VC + (T0 - VC) * host_Z / (host_Z + hd["Rs"])
    bp = lambda Bv: VC + (Bv - VC) * host_Z / (host_Z + rm)
    _, rBD, rVD = meas(ratio_level, None); _, rBJ, rVJ = meas(ratio_level, wire)
    rBD, rBJ = uB(rBD), uB(rBJ)
    REFr = rBD - hd["Rd"] * rVD / hd["Rb"]
    sc = VREF / REFr
    A = np.full(n, float(ratio_level)); kh = np.full(n, kn)
    f = lambda AA, kk: np.stack([host_T(AA, kk, rBD * sc) - (rVD * sc + bp(rBD * sc)), host_T(AA, kk, rBJ * sc) - (rVJ * sc + bp(rBJ * sc))])
    for _ in range(iters):
        F = f(A, kh); dd = 1e-6
        dA = (f(A + dd, kh) - F) / dd; dk = (f(A, kh + dd) - F) / dd
        det = dA[0] * dk[1] - dk[0] * dA[1]
        A = A - (F[0] * dk[1] - dk[0] * F[1]) / det
        kh = kh - (dA[0] * F[1] - F[0] * dA[1]) / det
    outs = [meas(L, wire) for L in lev]
    V = np.array([o[2] for o in outs]); Bv = np.array([uB(o[1]) for o in outs])
    err = []
    for i, L in enumerate(lev):
        gt, gb, gz = 1 / (Rtot * (1 - kh)), 1 / (Rtot * kh), 1 / (host_Z + hd["Rs"])
        pinT = V[i] * sc + bp(Bv[i] * sc)
        T0h = VC + (pinT - VC) * (host_Z + hd["Rs"]) / host_Z
        est = (T0h * (gt + gb + gz) - Bv[i] * sc * gb - VC * gz) / gt
        err.append(est - L * VREF / P["ref"])
    err = np.array(err); Am = np.stack([np.ones_like(lev), lev], 1); coef = np.linalg.lstsq(Am, err, rcond=None)[0]
    return dict(err=err, off=coef[0], gain=coef[1], k=kh, ktrue=Rb / (Rt + Rb), t0=np.array([o[0]["T0"] for o in outs]), pin=np.array([o[0]["PIN"] for o in outs]),
                pin2=np.array([o[0]["P2"] for o in outs]), B=np.array([o[0]["B"] for o in outs]))
