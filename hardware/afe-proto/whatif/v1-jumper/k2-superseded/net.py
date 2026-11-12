#!/usr/bin/env python3
"""Version 1 jumper ratio measurement: the network, the host procedure and the Monte Carlo (numpy only).
Adapted from kvm_02's v2 sense.py (powercal), re-done for version 1: ladder 8 x 270 ohm (taps 0.1875 .. 3.000 V),
AWG window about -1.3 .. +1.3 V, k = 1/2, bottom end B tied to VREF through Rd, jumper wire B -> TAP5 (2.4375 V).

Nodes (truth, solved by nodal analysis per Monte Carlo draw, batched):
  A    AWG at the BNC (ideal source: what is sensed is the BNC voltage itself)
  T0   sense tap: A --Rt-- T0 --Rb-- B,  T0 --Rs-- PIN (ADS1115 AIN0, BAV99 clamp, Zcm 6 Mohm to 0.7 V)
  B    divider bottom end:  --Rd-- VREF (permanent);  jumper wire: B -- TAP5
  ladder: GND -(3 x 270 ||)- TAP1 -270- TAP2 -270- TAP3 -270- TAP4 -270- TAP5 -270- VREF
Datasheet figures: ADS1115 SBAS444E (hardware/afe-proto/models/ads1115/ads1115.pdf: Zcm 6 Mohm at FSR +-4.096 V typ only; offset
+-3 LSB (of +-2.048 V FSR; carried here as 3 x 125 uV, conservative, as v2 does); gain channel match 0.05 % typ / 0.1 % max;
noise 125 uVrms at FSR +-4.096 V, 8..128 SPS; INL 1 LSB at +-2.048 V; abs max inputs GND-0.3 .. VDD+0.3, 10 mA continuous)."""
import os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results"); os.makedirs(RES, exist_ok=True)

LSB = 125e-6; NOISE = 125e-6; VC = 0.7; ZCM = 6e6; EPS_MAX = 0.001; EPS_TYP = 0.0005
OFF_LSB = 3.0; INL_LSB = 1.0
VREF = 3.0; REF_TOL = 0.001          # REF3030E initial accuracy E grade (afe.md PA-2; SBVS032K 2.997 / 3 / 3.003 for the standard grade, here the E-grade figure the v2 work uses)
RL = 270.0
LADDER_NOM = dict(  # nominal taps (V) and the Thevenin of TAP5 and TAP2
    TAP1=0.1875, TAP2=0.75, TAP3=1.3125, TAP4=1.875, TAP5=2.4375)
VDD_MIN = 3.21     # +3V3A low corner: LM27762 VFB 1.182 V, R1/R2 = 175k/100k at -1 %/+1 %  (derived: 1.182 x (1 + 1.75 x 0.98) = 3.21)  (check)
AWG_LIM = 1.35     # AW-1 reach about +-1.3 V as built, plus 50 mV of tolerance
LEV = np.linspace(-AWG_LIM, AWG_LIM, 25)

DES = dict(Rt=100e3, Rb=100e3, Rd=1e3, Rs=1.0, Rm=0.0, Il=0.0)   # Rs: no separate series part (1 ohm = the track); Rm: series resistor on AIN1/AIN2 (Thevenin match), 0 = none

def solve_net(A, ref, rl3, rl5, Rt, Rb, Rd, Rs, Z, Il=0.0, wire=None, Vx=None, wire_r=1e-3):
    """Nodal solve. wire: None (off) | 'TAP5' | 'TAP4' | 'TAP2' | 'ladder54' (TAP4-TAP5) | 'fixed' (B to the source Vx)
    Node order: 0 T0, 1 PIN, 2 B, 3..7 TAP1..TAP5.  Returns dict of node voltages (n,) each.  A: scalar or (n,)."""
    n = Rt.shape[0]; N = 8
    G = np.zeros((n, N, N)); b = np.zeros((n, N))
    def res(i, j, r):
        g = 1.0 / r
        G[:, i, i] += g
        if j is not None:
            G[:, j, j] += g; G[:, i, j] -= g; G[:, j, i] -= g
    def src(i, r, v):   # resistor r from node i to a fixed source v
        g = 1.0 / r; G[:, i, i] += g; b[:, i] += g * v
    src(0, Rt, A); res(0, 2, Rb); res(0, 1, Rs); src(1, Z, VC); b[:, 1] -= Il
    src(2, Rd, ref)
    # ladder: 3 bottom resistors to ground in parallel
    for k in range(3): src(3, rl3[:, k], 0.0)
    res(3, 4, rl5[:, 0]); res(4, 5, rl5[:, 1]); res(5, 6, rl5[:, 2]); res(6, 7, rl5[:, 3]); src(7, rl5[:, 4], ref)
    if wire == "TAP5": res(2, 7, np.full(n, wire_r))
    elif wire == "TAP4": res(2, 6, np.full(n, wire_r))
    elif wire == "TAP2": res(2, 4, np.full(n, wire_r))
    elif wire == "ladder54": res(6, 7, np.full(n, wire_r))
    elif wire == "fixed": src(2, np.full(n, wire_r), Vx)
    elif wire == "tap5fixed": src(7, np.full(n, wire_r), Vx)
    V = np.linalg.solve(G, b[..., None])[..., 0]
    return dict(T0=V[:, 0], PIN=V[:, 1], B=V[:, 2], TAP1=V[:, 3], TAP2=V[:, 4], TAP3=V[:, 5], TAP4=V[:, 6], TAP5=V[:, 7], ref=ref)

def draw(n, seed=1, d=DES, tol=0.01, zspread=0.25, eps=EPS_MAX, zcorr=0.0, inl_common=True):
    rng = np.random.default_rng(seed)
    U = lambda w, size=None: rng.uniform(-w, w, size)
    P = dict(Rt=d["Rt"] * (1 + U(tol, n)), Rb=d["Rb"] * (1 + U(tol, n)), Rd=d["Rd"] * (1 + U(tol, n)), Rs=d["Rs"] * (1 + U(tol, n)),
             Rm=d["Rm"] * (1 + U(tol, n)),
             rl3=RL * (1 + U(tol, (n, 3))), rl5=RL * (1 + U(tol, (n, 5))), ref=VREF * (1 + U(REF_TOL, n)))
    # input impedance per channel: independent +-zspread (conservative: the datasheet gives one typ value and no spread) or fully correlated (zcorr = 1)
    zc = U(zspread, (n, 1)); zi = U(zspread, (n, 4))
    P["Z"] = ZCM * (1 + zcorr * zc + (1 - zcorr) * zi)
    P["ge"] = 1 + U(eps / 2, (n, 4)); P["off"] = U(OFF_LSB * LSB, (n, 4)); P["inl"] = (np.repeat(U(INL_LSB * LSB, (n, 1)), 4, 1) if inl_common else U(INL_LSB * LSB, (n, 4)))
    P["rng"] = rng; P["n"] = n
    return P

def chan_pin(v, ch, P, d):
    """voltage at the ADS1115 pin of channel ch for a source voltage v behind the channel's series resistance (Thevenin source 0 ohm
    for the reference / ladder taps, Rm if matched): pin = VC + (v - VC) Z/(Z + Rm).  AIN0 (the sense tap) is solved in the network."""
    Rm = P["Rm"]
    return VC + (v - VC) * P["Z"][:, ch] / (P["Z"][:, ch] + Rm)

def read(pin, ch, P, navg=64, noise=NOISE):
    vv = np.clip(pin, 0, 4.096)
    return (P["ge"][:, ch] * pin + P["off"][:, ch] + P["inl"][:, ch] * 4 * vv * (4.096 - vv) / 4.096 ** 2
            + P["rng"].normal(0, noise / np.sqrt(navg), P["n"]))

def unload(x, Rser, Zn=ZCM):
    """the host undoes the NOMINAL input loading of a channel behind series resistance Rser (it knows Zcm typ only)"""
    return VC + (x - VC) * (Zn + Rser) / Zn

# ----------------------------------------------------------------------------------------------------------- the host's model
def host_T_from_AB(A, kk, B, d, Zn=ZCM):
    """wire on, B known: T0 = (A gt + B gb + VC gz)/(gt+gb+gz), loaded by the sense pin's (Zn + Rs) to VC"""
    Rtot = d["Rt"] + d["Rb"]; gt, gb, gz = 1 / (Rtot * (1 - kk)), 1 / (Rtot * kk), 1 / (Zn + d["Rs"])
    return (A * gt + B * gb + VC * gz) / (gt + gb + gz)

def host_T_off(A, kk, refh, d, Zn=ZCM):
    """wire off, B from the default tie (nominal Rd): KCL at B and T0"""
    Rtot = d["Rt"] + d["Rb"]; gt, gb, gd, gz = 1 / (Rtot * (1 - kk)), 1 / (Rtot * kk), 1 / d["Rd"], 1 / (Zn + d["Rs"])
    a11, a12, b1 = gt + gb + gz, -gb, A * gt + VC * gz
    a21, a22, b2 = -gb, gb + gd, refh * gd
    det = a11 * a22 - a12 * a21
    return (b1 * a22 - a12 * b2) / det

def run(n=20000, seed=1, d=DES, eps=EPS_MAX, tol=0.01, zspread=0.25, zcorr=0.0, levels_ratio=(-1.3,), sweep="J", navg=64, nav_ratio=64,
        host_Z=ZCM, iters=10, offs=True, leak_sign=+1, inl_common=True, hd=None, measure_k=True, ref_tol=None):
    """Monte Carlo of the whole procedure: ratio from wire-off/on readings at levels_ratio, then the sweep.  Returns summary arrays."""
    hd = hd or d
    P = draw(n, seed, d, tol, zspread, eps, zcorr, inl_common)
    if not offs: P["off"] = P["off"] * 0
    Rt, Rb, Rd, Rs, Z = P["Rt"], P["Rb"], P["Rd"], P["Rs"], P["Z"]
    Il = d["Il"] * leak_sign
    Rm = d["Rm"]; Rmh = hd["Rm"]
    def readings(A, wire, navg_):
        nd = solve_net(A, P["ref"], P["rl3"], P["rl5"], Rt, Rb, Rd, Rs, Z[:, 0], Il, wire)
        xs = dict(
            T=read(nd["PIN"], 0, P, navg_),
            REF=read(chan_pin(P["ref"], 1, P, d), 1, P, navg_),
            TAP5=read(chan_pin(nd["TAP5"], 2, P, d), 2, P, navg_))
        return nd, xs
    # helper functions that keep the host honest: T0 is recovered from the pin, B from AIN2, both through the reference reading
    def unload_T(x, d_, Zn):      # pin -> node T0 behind Rs (the host divides out Rs / Zn)
        return VC + (x - VC) * (Zn + d_["Rs"]) / Zn
    def host_volts(xs):
        r = VREF / unload(xs["REF"], Rmh, host_Z)       # scale: V = r x (unloaded reading)
        T0 = unload_T(xs["T"], hd, host_Z)
        B = unload(xs["TAP5"], Rmh, host_Z)
        # the ratio to the reference is taken about zero volts (V = 3.0 x reading / reference reading), as the project's other ADS1115 reads
        return T0 * r, B * r
    Rtot = hd["Rt"] + hd["Rb"]; kn = hd["Rb"] / Rtot
    ks = []
    for LR in levels_ratio:
        _, xd = readings(LR, None, nav_ratio); _, xj = readings(LR, "TAP5", nav_ratio)
        Td, _ = host_volts(xd); Tj, Bj = host_volts(xj)
        refh_d = VREF            # the scale is already 3.0 V
        A = np.full(n, float(LR)); kh = np.full(n, kn)
        for _ in range(iters):
            f = lambda AA, kk: np.stack([host_T_off(AA, kk, refh_d, hd, host_Z) - Td, host_T_from_AB(AA, kk, Bj, hd, host_Z) - Tj])
            F = f(A, kh); dd = 1e-6
            dA = (f(A + dd, kh) - F) / dd; dk = (f(A, kh + dd) - F) / dd
            det = dA[0] * dk[1] - dk[0] * dA[1]
            A = A - (F[0] * dk[1] - dk[0] * F[1]) / det
            kh = kh - (dA[0] * F[1] - F[0] * dA[1]) / det
        ks.append(kh)
    kh = np.mean(ks, axis=0)
    if not measure_k: kh = np.full(n, kn)
    ktrue = Rb / (Rt + Rb)
    # sweep
    err, t0s, pins, bs = [], [], [], []
    for L in LEV:
        nd, xs = readings(L, "TAP5" if sweep == "J" else None, navg)
        T0h, Bh = host_volts(xs)
        gt, gb, gz = 1 / (Rtot * (1 - kh)), 1 / (Rtot * kh), 1 / (host_Z + hd["Rs"])
        if sweep == "J":
            est = (T0h * (gt + gb + gz) - Bh * gb - VC * gz) / gt
        else:
            gd = 1 / hd["Rd"]
            Bo = (gb * T0h + gd * VREF) / (gb + gd)
            est = (T0h * (gt + gb + gz) - Bo * gb - VC * gz) / gt
        err.append(est - L * VREF / P["ref"])   # the reference's own accuracy is PA-2's share, not the sense's
        t0s.append(nd["T0"]); pins.append(nd["PIN"]); bs.append(nd["B"])
    err = np.array(err)
    Am = np.stack([np.ones_like(LEV), LEV], 1)
    coef = np.linalg.lstsq(Am, err, rcond=None)[0]
    return dict(err=err, off=coef[0], gain=coef[1], k=kh, ktrue=ktrue, t0=np.array(t0s), pin=np.array(pins), B=np.array(bs))

def summ(r, q=99.9):
    return dict(gain_pct=float(np.nanpercentile(np.abs(r["gain"]), q) * 100), off_mV=float(np.nanpercentile(np.abs(r["off"]), q) * 1e3),
                err_mV=float(np.nanpercentile(np.abs(r["err"]).max(0), q) * 1e3),
                k_err_pct=float(np.nanpercentile(np.abs(r["k"] / r["ktrue"] - 1), q) * 100),
                t0_min=float(r["t0"].min()), t0_max=float(r["t0"].max()), pin_min=float(r["pin"].min()), pin_max=float(r["pin"].max()))
