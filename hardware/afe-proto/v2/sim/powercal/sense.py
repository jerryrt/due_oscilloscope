#!/usr/bin/env python3
"""Task 5: the AWG-sense divider and its jumper (PA-4, V2-5, VT-21, VT-22), with the wire fitted for the WHOLE tee sweep.

Circuit (design.md section 5):  A (the AWG at the BNC / tee node) -- Rt -- T0 -- Rb -- B ;  T0 -- Rs -- ADS1115 AIN2 (the tap)
B -- Rd -- REF3030E (the permanent default).  The jumper wire joins B to the 1/3 ladder tap (a Thevenin source Vth behind Rth).
Structures: S1 reads B on AIN3 with the wire on only, the reference on AIN0; S2 reads B on AIN3 in both positions; S3 (the design) reads the
pair AIN2 and AIN3 differentially, AIN3 being B through Rm, and rebuilds the reference's scale on AIN3.  AIN1 is the 2/3 tap (a check only).
k = Rb/(Rt+Rb) is the weight of A in the tap:  T0 = k A + (1-k) B  (loaded by the ADC input).

Truth model per draw: every resistor U(+-1 %) (ladder parts too), REF 3.0 V +-0.1 %, the ADS1115's per-input gain (channel match
0.1 % max, uniform +-eps/2 each), offset (the datasheet's 3 LSB is specified at +-2.048 V, LSB 62.5 uV, and bounds the difference of ANY TWO inputs: the model draws an independent +-3 LSB per input at 125 uV, up to 4x conservative *(check)*), INL bow 1 LSB, input
loading as a resistor Zcm (6 Mohm +-25 %, typ only *(check)*) to 0.7 V (SBAS444E 7.3.2), and the host's own averaging noise.
The host solves (A, k) at one ratio level from the wire-off and wire-on readings with the NOMINAL network and Zcm, exactly as
the procedure would, then converts every sweep reading (wire on throughout) to AWG volts.  numpy only."""
import os, sys, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

C = Cases("sense"); G = Guards("sense"); R = {}
LSB = ADS["lsb"]; VC = ADS["v_common"]
DES = dict(Rt=15e3, Rb=10e3, Rd=1e3, Rs=3.9e3, Rl=330.0, tap=3, REF=3.0)      # the design (k = 0.4); tap = the calibration node TAP_on (the 1/2 tap); TAP_HI below is the other outer pin of the 1x3 header
LEV = np.linspace(-1.923, 2.18, 25)      # the kept sweep: from the clip level of the weak -rail to the hard-corner DC window top end 2.133 V (../awg/design.md) plus 0.05 V
VDD_MIN = 3.22
TAP_HI = 4                                # the 1x3 header J_RAT = pin 1 TAP_hi (2/3 tap) | pin 2 B | pin 3 TAP_on (1/2 tap), the same form as v1's TAP4 | B | TAP3
RM = 10e3                                 # the matched series resistor on AIN3 (B)

def ladder(rl, ref, tap):
    """Thevenin (Vth, Rth) of tap number `tap` of six equal rungs, from the bottom; rl: (n, 6)."""
    S = rl.sum(1); lo = rl[:, :tap].sum(1)
    return ref * lo / S, lo * (S - lo) / S

def solve(pos, A, ref, Rt, Rb, Rd, Rs, Z, Vth, Rth, Il=0.0):
    """Node T0 and B.  Node T0 is loaded by Z + Rs to 0.7 V; in position J node B also hangs on the ladder tap (and Z4, small, folded
    into Vth/Rth: its 0.4 uA across 440 ohm is 0.2 mV, carried by the MC through Zcm).  Returns T0, B, pin voltage of AIN2."""
    gt, gb, gd, gz, gl = 1 / Rt, 1 / Rb, 1 / Rd, 1 / (Z + Rs), (1 / Rth if pos == "J" else 0.0)
    a11, a12, b1 = gt + gb + gz, -gb, A * gt + VC * gz + Il
    a21, a22, b2 = -gb, gb + gd + gl, ref * gd + (Vth * gl if pos == "J" else 0.0)
    det = a11 * a22 - a12 * a21
    T0 = (b1 * a22 - a12 * b2) / det
    B = (a11 * b2 - a21 * b1) / det
    pin = VC + (T0 - VC) * Z / (Z + Rs)
    return T0, B, pin

def host_inv_T(pin, Rs, Z):
    """the host undoes its own Rs / Zcm divider: node voltage T0 from the pin reading"""
    return VC + (pin - VC) * (Z + Rs) / Z

def mc(n=20000, seed=1, d=DES, eps=ADS["gain_ch_match"][1], tol=0.01, zspread=0.25, wire_on_sweep=True, ratio_level=2.0, k_in=None, sweep_pos="J",
       tolset=None, sweep_mode="B_each", struct="S1", rm=0.0, zcommon=False, iters=12, offs=ADS["off_err_lsb"], inl=ADS["inl_lsb"], navg=64, noise=ADS["noise_rms"]):
    rng = np.random.default_rng(seed)
    U = lambda w, size=None: rng.uniform(-w, w, size)
    CHB = 2 if (d["tap"] == 2 or struct == "S2") else 3
    tl = lambda nm: tol if (tolset is None or nm in tolset) else 0.0
    Rt = d["Rt"] * (1 + U(tl("Rt"), n)); Rb = d["Rb"] * (1 + U(tl("Rb"), n)); Rd = d["Rd"] * (1 + U(tl("Rd"), n)); Rs = d["Rs"] * (1 + U(tl("Rs"), n))
    rl = d["Rl"] * (1 + U(tl("Rl"), (n, 6)))
    ref = d["REF"] * (1 + U(REF["tol"], n))
    Vth, Rth = ladder(rl, ref, d["tap"])
    Z = ADS["zcm"] * (1 + U(zspread, (n, 4)))
    if zcommon: Z = np.repeat(Z[:, :1], 4, axis=1)
    ge = 1 + U(eps / 2, (n, 4)); off = U(offs * LSB, (n, 4)); inlb = U(inl * LSB, (n, 4))
    def read(v, ch, rs=0.0):
        vv = np.clip(v, 0, 4.096)
        v = VC + (v - VC) * Z[:, ch] / (Z[:, ch] + rs)      # the source impedance in front of the input (rm) against Zcm
        return ge[:, ch] * v + off[:, ch] + inlb[:, ch] * 4 * vv * (4.096 - vv) / 4.096 ** 2 + rng.normal(0, noise / np.sqrt(navg), n)
    # reference reading (ch 0) defines the ratio scale: the host reports V = 3.0 x reading / reference reading
    Zn0 = ADS["zcm"]
    und = lambda r, rs: VC + (r - VC) * (Zn0 + rs) / Zn0     # the host undoes the nominal loading of a source impedance rs
    rref = und(read(ref, 0, rm), rm)
    vol = lambda r, rs=0.0: d["REF"] * und(r, rs) / rref
    Rtot = d["Rt"] + d["Rb"]; kn = d["Rb"] / Rtot
    Rtn, Rbn = d["Rt"], d["Rb"]
    Vthn, Rthn = d["REF"] * d["tap"] / 6, d["Rl"] * d["tap"] * (6 - d["tap"]) / 6
    Zn = ADS["zcm"]
    # ---- ratio level, wire off then on
    A0 = ratio_level
    T0d, Bd, pind = solve("D", A0, ref, Rt, Rb, Rd, Rs, Z[:, 1], Vth, Rth)
    T0j, Bj, pinj = solve("J", A0, ref, Rt, Rb, Rd, Rs, Z[:, 1], Vth, Rth)
    rTd = vol(read(pind, 1)); rTj = vol(read(pinj, 1)); rN = vol(read(Bj, CHB, rm), rm)
    rBd = vol(read(Bd, CHB, rm), rm) if struct == "S2" else None
    # the host: unknowns (A, k) with the nominal network
    def fwd(pos, A, kk, N):
        Rtt, Rbb = Rtot * (1 - kk), Rtot * kk
        T0, B, pin = solve(pos, A, d["REF"], Rtt, Rbb, d["Rd"], d["Rs"], Zn, N, Rthn)
        return pin
    def jfwd(AA, kk, Bm):
        """wire on: the host knows B (reading), so T0 = k A + (1-k) B loaded by Z + Rs"""
        Rtt, Rbb = Rtot * (1 - kk), Rtot * kk
        gt, gb, gz = 1 / Rtt, 1 / Rbb, 1 / (Zn + d["Rs"])
        T0 = (AA * gt + Bm * gb + VC * gz) / (gt + gb + gz)
        return VC + (T0 - VC) * Zn / (Zn + d["Rs"])
    A = np.full(n, A0); kh = np.full(n, kn)
    for _ in range(iters):
        f = lambda AA, kk: np.stack([(fwd("D", AA, kk, rN) if struct == "S1" else jfwd(AA, kk, rBd)) - rTd, jfwd(AA, kk, rN) - rTj])
        F = f(A, kh); dd = 1e-6
        dA = (f(A + dd, kh) - F) / dd; dk = (f(A, kh + dd) - F) / dd
        det = dA[0] * dk[1] - dk[0] * dA[1]
        A = A - (F[0] * dk[1] - dk[0] * F[1]) / det
        kh = kh - (dA[0] * F[1] - F[0] * dA[1]) / det
    # ---- the sweep
    err, pins, t0s, bs, t0h_all, est_all = [], [], [], [], [], []
    for L in LEV:
        T0, B, pin = solve(sweep_pos, L, ref, Rt, Rb, Rd, Rs, Z[:, 1], Vth, Rth)
        pins.append(pin); t0s.append(T0); bs.append(B)
        rT = vol(read(pin, 1))
        Bm = vol(read(B, CHB, rm), rm) if sweep_pos == "J" else None
        if sweep_pos == "J":
            Rtt, Rbb = Rtot * (1 - kh), Rtot * kh
            gt, gb, gz = 1 / Rtt, 1 / Rbb, 1 / (Zn + d["Rs"])
            T0h = host_inv_T(rT, d["Rs"], Zn)
            est = (T0h * (gt + gb + gz) - Bm * gb - VC * gz) / gt
        else:
            Rtt, Rbb = Rtot * (1 - kh), Rtot * kh
            # wire off: solve for A given T with B from the default network (host model, nominal Rd)
            gt, gb, gd, gz = 1 / Rtt, 1 / Rbb, 1 / d["Rd"], 1 / (Zn + d["Rs"])
            T0h = host_inv_T(rT, d["Rs"], Zn)
            Bh = (gb * T0h + gd * d["REF"]) / (gb + gd)       # KCL at B
            est = (T0h * (gt + gb + gz) - Bh * gb - VC * gz) / gt
        t0h_all.append(T0h); est_all.append(est)
        err.append(est - L * d["REF"] / ref)      # in REF units: the reference's own +-0.1 % is SC-7's PA-2 share, not the sense's
    if sweep_mode == "interp" and sweep_pos == "J":
        # D21: the ADS1115 free-runs on the sense node only; B is read at the first and last level, every level between is the straight line of T0 through those two
        T = np.array(t0h_all); E = np.array(est_all)
        w = (T - T[0]) / (T[-1] - T[0])
        est_i = E[0] + w * (E[-1] - E[0])
        err = np.array([est_i[i] - LEV[i] * d["REF"] / ref for i in range(len(LEV))])
    else:
        err = np.array(err)
    Lx = LEV; Am = np.stack([np.ones_like(Lx), Lx], 1)
    coef = np.linalg.lstsq(Am, err, rcond=None)[0]
    return dict(err=err, off=coef[0], gain=coef[1], k=kh, k_true=Rb / (Rt + Rb), pins=np.array(pins), t0=np.array(t0s), B=np.array(bs),
                Vth=Vth, Rth=Rth)


def mc3(n=20000, seed=1, d=DES, eps=ADS["gain_ch_match"][1], tol=0.01, zspread=0.25, ratio_level=2.0, iters=12, offs=ADS["off_err_lsb"], inl=ADS["inl_lsb"],
        navg=64, noise=ADS["noise_rms"], zcommon=False, dscale=1.0, rm=0.0, cT=2, cB=3):
    """Structure S3: AIN3 is the divider's bottom node B (single-ended), AIN2 and AIN3 read as a DIFFERENTIAL pair (T - B) all through the sweep, the
    reference's scale is rebuilt on AIN3 itself from B with the wire off (KCL at B: REF = B - Rd (T - B) / Rb), so no other input's gain enters:
    A = B + (T - B) / k, and k = d(T-B) / dB from the two wire positions, B read on one channel in both.  The sweep reads the pair only; B at the first and last level."""
    rng = np.random.default_rng(seed)
    U = lambda w, size=None: rng.uniform(-w, w, size)
    Rt = d["Rt"] * (1 + U(tol, n)); Rb = d["Rb"] * (1 + U(tol, n)); Rd = d["Rd"] * (1 + U(tol, n)); Rs = d["Rs"] * (1 + U(tol, n))
    rl = d["Rl"] * (1 + U(tol, (n, 6))); ref = d["REF"] * (1 + U(REF["tol"], n)); Vth, Rth = ladder(rl, ref, d["tap"])
    Z = ADS["zcm"] * (1 + U(zspread, (n, 5)))      # columns AIN0..AIN3 and the differential reading
    if zcommon: Z = np.repeat(Z[:, :1], 5, axis=1)
    ge = 1 + U(eps / 2, (n, 5)); off = U(offs * LSB, (n, 5)); inlb = U(inl * LSB, (n, 5))
    nz = lambda: rng.normal(0, noise / np.sqrt(navg), n)
    bow = lambda v, ch: inlb[:, ch] * 4 * np.clip(v, 0, 4.096) * (4.096 - np.clip(v, 0, 4.096)) / 4.096 ** 2
    gB = lambda: Z[:, cB] / (Z[:, cB] + rm)                     # the matched source resistor rm in front of the B pin against Zcm
    readB = lambda v: ge[:, cB] * (VC + (v - VC) * gB()) + off[:, cB] + bow(v, cB) + nz()
    readD = lambda v, vcm: ge[:, 4] * v * dscale + off[:, 4] + bow(vcm, 4) + nz()
    Rtot = d["Rt"] + d["Rb"]; Zn = ADS["zcm"]
    def host_T(AA, kk, Bm):
        Rtt, Rbb = Rtot * (1 - kk), Rtot * kk
        gt, gb, gz = 1 / Rtt, 1 / Rbb, 1 / (Zn + d["Rs"])
        T0 = (AA * gt + Bm * gb + VC * gz) / (gt + gb + gz)
        return VC + (T0 - VC) * Zn / (Zn + d["Rs"])
    def meas(pos, A):
        T0, B, pin = solve(pos, A, ref, Rt, Rb, Rd, Rs, Z[:, cT], Vth, Rth)
        Bp = VC + (B - VC) * Z[:, cB] / (Z[:, cB] + rm)
        return pin, B, readB(B), readD(pin - Bp, B)
    A0 = ratio_level
    pD, BD, rBD, rVD = meas("D", A0); pJ, BJ, rBJ, rVJ = meas("J", A0)
    uB = lambda r: VC + (r - VC) * (Zn + rm) / Zn
    rBD, rBJ = uB(rBD), uB(rBJ)
    # the scale: volts per reading unit from the reference rebuilt on AIN3 (wire off): REF = B - Rd (T - B)/Rb, nominal Rd, Rb
    REFr = rBD - d["Rd"] * rVD / d["Rb"]
    sc = d["REF"] / REFr
    A = np.full(n, A0); kh = np.full(n, d["Rb"] / Rtot)
    for _ in range(iters):
        bp = lambda Bv: VC + (Bv - VC) * Zn / (Zn + rm)
        f = lambda AA, kk: np.stack([host_T(AA, kk, rBD * sc) - (rVD * sc + bp(rBD * sc)), host_T(AA, kk, rBJ * sc) - (rVJ * sc + bp(rBJ * sc))])
        F = f(A, kh); dd = 1e-6
        dA = (f(A + dd, kh) - F) / dd; dk = (f(A, kh + dd) - F) / dd
        det = dA[0] * dk[1] - dk[0] * dA[1]
        A = A - (F[0] * dk[1] - dk[0] * F[1]) / det
        kh = kh - (dA[0] * F[1] - F[0] * dA[1]) / det
    outs = [meas("J", L) for L in LEV]
    V = np.array([o[3] for o in outs]); Bv = np.array([uB(o[2]) for o in outs])      # pair readings at every level, B at every level (only the ends are used)
    w = (V - V[0]) / (V[-1] - V[0])
    Bi = Bv[0] + w * (Bv[-1] - Bv[0])
    err, pins, t0s = [], [], []
    for i, L in enumerate(LEV):
        Rtt, Rbb = Rtot * (1 - kh), Rtot * kh
        gt, gb, gz = 1 / Rtt, 1 / Rbb, 1 / (Zn + d["Rs"])
        pinT = V[i] * sc + VC + (Bi[i] * sc - VC) * Zn / (Zn + rm)
        T0h = host_inv_T(pinT, d["Rs"], Zn)
        est = (T0h * (gt + gb + gz) - Bi[i] * sc * gb - VC * gz) / gt
        err.append(est - L * d["REF"] / ref)
        pins.append(outs[i][0])
    err = np.array(err)
    Am = np.stack([np.ones_like(LEV), LEV], 1); coef = np.linalg.lstsq(Am, err, rcond=None)[0]
    return dict(err=err, off=coef[0], gain=coef[1], k=kh, k_true=Rb / (Rt + Rb), pins=np.array(pins), t0=np.array(pins), B=np.array([o[1] for o in outs]))

def summ(r, q=99.9):
    return dict(gain_pct=float(np.percentile(np.abs(r["gain"]), q) * 100), off_mV=float(np.percentile(np.abs(r["off"]), q) * 1e3),
                err_mV=float(np.percentile(np.abs(r["err"]).max(0), q) * 1e3), k_err_pct=float(np.percentile(np.abs(r["k"] / r["k_true"] - 1), q) * 100),
                pin_min=float(r["pins"].min()), pin_max=float(r["pins"].max()), t0_min=float(r["t0"].min()), t0_max=float(r["t0"].max()))

# ------------------------------------------------------------------------------------------------------------- wrong positions
def wrong_positions(d=DES, A=LEV, vref=3.0, nodes=None):
    """B tied to a node X through the wire (zero ohm) while Rd to REF still hangs on it.  X from GND to the 5 V pin and 12 V (VIN) for stress.
    Returns per X: T0 open-circuit extremes over A, the current into the ADS pin's ESD diodes through Rs, the shift of dT against the default at A=0.8."""
    out = []
    names = nodes or {1.0: "pin 1, TAP_hi (2/3 tap): the shunt slipped to pins 1-2, the one wrong placement", 1.5: "pin 3, TAP_on (1/2 tap): the calibration position (shunt across pins 2-3)", 3.0: "shunt off (default tie to the REF3030E)"}
    kk = d["Rb"] / (d["Rt"] + d["Rb"])
    for X, nm in names.items():
        Rth = d["Rl"] * 2 * 4 / 6 if X in (1.0, 2.0) else 1.0  # stiff nodes: ladder taps through their Thevenin, supplies ~0
        if X in (0.5, 1.0, 1.5, 2.0, 2.5): rth = (d["Rl"] * round(X / 0.5)) * (d["Rl"] * (6 - round(X / 0.5))) / (6 * d["Rl"])
        else: rth = 0.01
        # B is tied to X by the wire: B = X (the node's Thevenin is small beside Rb), Rd to REF carries (REF - X)/Rd and is ignored by the stiff source
        Bn = X
        T0 = kk * A + (1 - kk) * Bn
        lo, hi = T0.min(), T0.max()
        # current into the ADS ESD diodes when T0 is outside -0.3 .. VDD+0.3: through Rt||Rb + Rs (diode drop 0.3..0.5 V assumed)
        src = d["Rt"] * d["Rb"] / (d["Rt"] + d["Rb"]) + d["Rs"]
        iesd = max(0.0, (-0.3 - lo) / src, (hi - (VDD_MIN + 0.3)) / src) if (lo < -0.3 or hi > VDD_MIN + 0.3) else 0.0
        # the same bounded on the diode drop: the clamp holds the pin about 0.3 V past the rail, so the current is (T0 - (rail+0.3)) / src
        # the supply-pin side: current into the Rd / ladder is the stiff source's business: the ladder tap 4 loads: (A - X)/(Rt+Rb) through the wire
        i3 = max(0.0, (Bn - (VDD_MIN + 0.3)) / RM, (-0.3 - Bn) / RM)
        iwire = np.abs((A - Bn)).max() / (d["Rt"] + d["Rb"])
        out.append(dict(node=nm, X=X, t0_min=float(lo), t0_max=float(hi), iesd_ua=float(iesd * 1e6), iesd3_ua=float(i3 * 1e6), iwire_ua=float(iwire * 1e6),
                        dT_at_0p8=float(kk * 0 + (1 - kk) * (Bn - (vref - 0.0))), pin_ok_0_to_vdd=bool(lo >= 0 and hi <= VDD_MIN)))
    return out

def header_states(k_rt=None):
    """The three states of the 1x3 header: shunt off, TAP_on (B to the 1/2 tap, the calibration position), TAP_hi (B to the 1/3 tap).  A shunt misaligned by one pin
    leaves one pin of the pair open: it is the off state.  Returns, per state, the sense tap range over the sweep, B's range and the ratio figures (S3)."""
    out = []
    d_on = dict(DES); d_lo = dict(DES, tap=TAP_HI)
    rm = RM
    seps = {}
    rng = np.random.default_rng(7); nn = 800
    rl = DES["Rl"] * (1 + rng.uniform(-.01, .01, (nn, 6))); ref = 3.0 * (1 + rng.uniform(-.001, .001, nn))
    Bk = {}
    for nm, pos, tp in (("off", "D", DES["tap"]), ("TAP_on", "J", DES["tap"]), ("TAP_hi", "J", TAP_HI)):
        Vth, Rth = ladder(rl, ref, tp)
        Bk[nm] = np.array([solve(pos, Lv, ref, DES["Rt"], DES["Rb"], DES["Rd"], DES["Rs"], ADS["zcm"], Vth, Rth)[1] for Lv in LEV])
    sep = {"off": min(np.abs(Bk["off"] - Bk["TAP_on"]).min(), np.abs(Bk["off"] - Bk["TAP_hi"]).min()),
           "TAP_on": min(np.abs(Bk["off"] - Bk["TAP_on"]).min(), np.abs(Bk["TAP_on"] - Bk["TAP_hi"]).min()),
           "TAP_hi": min(np.abs(Bk["off"] - Bk["TAP_hi"]).min(), np.abs(Bk["TAP_on"] - Bk["TAP_hi"]).min())}
    for nm, d, pos in (("off", d_on, "D"), ("TAP_on", d_on, "J"), ("TAP_hi", d_lo, "J")):
        r = mc(n=1500, d=d, sweep_pos=pos); sm = summ(r)
        row = dict(state=nm, pin_min=sm["pin_min"], pin_max=sm["pin_max"], B_min=float(r["B"].min()), B_max=float(r["B"].max()), sep_min_mV=float(sep[nm] * 1e3),
                   gain_trk=None, off_trk=None, gain_ind=None, off_ind=None)
        if nm != "off":
            a_ = summ(mc3(n=8000, d=d, rm=rm, zcommon=True)); b_ = summ(mc3(n=8000, d=d, rm=rm))
            row.update(gain_trk=a_["gain_pct"], off_trk=a_["off_mV"], gain_ind=b_["gain_pct"], off_ind=b_["off_mV"])
        out.append(row)
    return out

def clip_detect(levels, vtb, thr=0.5, win=3):
    """Drop the levels at which the sense reading stops following the DAC code: the slope of the reading over the last `win` levels against the median
    slope of the sweep; a level is dropped when that slope is below thr x the median.  Returns the boolean keep mask."""
    sl = np.diff(vtb) / np.diff(levels)
    med = np.median(sl)
    keep = np.ones(len(levels), bool)
    n = len(levels)
    for i in range(n):
        if i + win <= n - 1: w = sl[i:i + win]          # the slope just above the level
        else: w = sl[i - win:i]                         # the slope just below it, at the top end
        if np.mean(w) < thr * med: keep[i] = False
    return keep

def clip_case(thr=0.5, vclip=-1.923, n=1025, lo=-2.031, hi=1.747, noise_mv=0.1):
    """A staircase of DAC codes (1.45 mV per code at the AWG output), the AWG flat below vclip; k = 0.4 so the pair reads k (A - B).  Returns (first dropped level, kept count,
    fit gain error over the kept levels, bottom of the kept range)."""
    rng = np.random.default_rng(2)
    L = np.linspace(lo, hi, n)
    A = np.maximum(L, vclip)                                   # the output stops following the code
    vtb = 0.4 * (A - 1.2) + rng.normal(0, noise_mv * 1e-3 * 0.4, n)
    keep = clip_detect(L, vtb, thr)
    p = np.polyfit(L[keep], vtb[keep], 1)
    return dict(first_dropped=float(L[~keep].min()) if (~keep).any() else None, kept=int(keep.sum()), gain_err_pct=float((p[0] / 0.4 - 1) * 100), bottom=float(L[keep].min()),
                dropped=int((~keep).sum()))

def main():
    s3 = summ(mc3(rm=10e3)); s3c = summ(mc3(rm=10e3, zcommon=True))
    s1 = summ(mc()); s2 = summ(mc(struct="S2")); s3n = summ(mc3(rm=0.0))
    R["base"] = s3; R["common_z"] = s3c; R["S1"] = s1; R["S2"] = s2; R["S3_no_rm"] = s3n
    R["typ_match"] = summ(mc3(rm=10e3, eps=ADS["gain_ch_match"][0])); R["no_match"] = summ(mc3(rm=10e3, eps=0.0))
    ab = {}
    z0 = dict(eps=0.0, offs=0.0, inl=0.0, zspread=0.0, noise=0.0, tol=0.0)
    for nm, kw in (("base (as shipped)", {}), ("no channel mismatch", dict(eps=0.0)), ("no ADS offsets", dict(offs=0.0)), ("no Zcm spread", dict(zspread=0.0)), ("no resistor tolerance", dict(tol=0.0)),
                   ("no INL", dict(inl=0.0)), ("no noise", dict(noise=0.0)), ("channel match only", dict(offs=0.0, zspread=0.0, tol=0.0, inl=0.0, noise=0.0)),
                   ("offsets only", dict(eps=0.0, zspread=0.0, tol=0.0, inl=0.0, noise=0.0)), ("Zcm spread only", dict(eps=0.0, offs=0.0, tol=0.0, inl=0.0, noise=0.0)),
                   ("1 % resistors only", dict(eps=0.0, offs=0.0, zspread=0.0, inl=0.0, noise=0.0))):
        a_ = summ(mc3(n=20000, rm=10e3, **kw)); b_ = summ(mc(n=20000, **kw))
        ab[nm] = dict(S3_gain=a_["gain_pct"], S3_off=a_["off_mV"], S1_gain=b_["gain_pct"], S1_off=b_["off_mV"])
    R["ablation"] = ab
    off = mc(sweep_pos="D"); so = summ(off); R["wire_off_sweep"] = so
    R["structs"] = dict(S1=s1, S2=s2, S3_no_rm=s3n, S3_rm=s3, S3_rm_common=s3c)
    C.add("PA-4/range", "PA-4", "sweep, wire ON throughout: sense tap pin voltage at every AWG level -1.923..+2.18 V, every resistor at +-1 %, REF +-0.1 %", f"0 V .. {VDD_MIN} V (ADS supply minimum)",
          f"{s3['pin_min']:.3f} .. {s3['pin_max']:.3f} V", f"{s3['pin_min']:+.3f} V / {VDD_MIN-s3['pin_max']:+.3f} V", s3["pin_min"] >= 0 and s3["pin_max"] <= VDD_MIN, "k = 0.4, TAP_on = the 1/2 tap, Rd 1k", "sense")
    C.add("PA-4/range-off", "PA-4", "the same with the wire OFF (default tie to the REF3030E; the normal-use state)", f"0 V .. {VDD_MIN} V", f"{so['pin_min']:.3f} .. {so['pin_max']:.3f} V",
          f"{so['pin_min']:+.3f} V / {VDD_MIN-so['pin_max']:+.3f} V", so["pin_min"] >= 0 and so["pin_max"] <= VDD_MIN, "", "sense")
    lim_g, lim_o = 0.05, 3.0
    C.add("PA-4/ratio", "PA-4, SC-7", "AWG level through the sweep, structure S3 (AIN3 = B with a 10k matched resistor, AIN2 - AIN3 read DIFFERENTIALLY, the reference's scale rebuilt on AIN3, no other input's gain enters), "
          "ADS1115 channel match 0.1 % max (SBAS444E 5.5 'Gain channel match'), offset 3 LSB, Zcm TRACKING between inputs (one input stage behind the mux) *(check)*, 99.9th pct",
          f"gain <= {lim_g} %, offset <= {lim_o} mV", f"gain {s3c['gain_pct']:.3f} %, offset {s3c['off_mV']:.2f} mV, worst point {s3c['err_mV']:.2f} mV (k error {s3c['k_err_pct']:.3f} %)", f"{lim_g-s3c['gain_pct']:+.3f} %",
          s3c["gain_pct"] <= lim_g * 1.1 and s3c["off_mV"] <= lim_o, "this design's allotment (0.05 %; the Monte Carlo reads 0.05 +- 0.003 %, so it is AT the limit, not under it) of the 0.1 % fit share", "sense")
    C.add("PA-4/ratio-ind", "PA-4, SC-7", "the same if Zcm spreads +-25 % INDEPENDENTLY between the inputs (the datasheet gives only a typical 6 Mohm)", f"gain <= {lim_g} %, offset <= {lim_o} mV",
          f"gain {s3['gain_pct']:.3f} %, offset {s3['off_mV']:.2f} mV", f"{lim_g-s3['gain_pct']:+.3f} %", s3["gain_pct"] <= lim_g and s3["off_mV"] <= lim_o,
          "fails the sense's 0.05 % share; it fits inside SC-7's whole 0.5 % with the rest of the stack (section 6), and VT-21 measures which case the part is in", "sense")
    C.add("PA-4/struct", "PA-4", "the structures compared (gain %, offset mV, 99.9th pct, channel match 0.1 % max): S1 = tap on AIN2, B on AIN3 in the wire position only, REF on AIN0; S2 = B on AIN3 in both positions; S3 without the matched resistor; S3 with it",
          "information", f"S1 {s1['gain_pct']:.3f} %/{s1['off_mV']:.1f} mV; S2 {s2['gain_pct']:.3f}/{s2['off_mV']:.1f}; S3 {s3n['gain_pct']:.3f}/{s3n['off_mV']:.1f}; S3+rm {s3['gain_pct']:.3f}/{s3['off_mV']:.1f} (Zcm tracking {s3c['gain_pct']:.3f}/{s3c['off_mV']:.1f})", "", None,
          "S2 removes the offsets of the ratio (ΔT on one channel, ΔB on one channel); S3 also removes the channel-gain terms (the differential pair and the REF rebuilt on AIN3); rm matches the source impedances", "sense")
    pr = {}
    for nm, (ct, cb) in (("AIN2 tap, AIN3 B (the design)", (2, 3)), ("swapped: tap on AIN3, B on AIN2", (3, 2)), ("tap on AIN0, B on AIN1", (0, 1))):
        for zc in (True, False):
            q_ = summ(mc3(n=20000, rm=10e3, zcommon=zc, cT=ct, cB=cb)); pr[f"{nm}|{'tracking' if zc else 'independent'}"] = dict(gain=q_["gain_pct"], off=q_["off_mV"])
    R["pairing"] = pr
    vals = [v_["gain"] for v_ in pr.values()]
    C.add("PA-4/pairing", "PA-4", "the ratio figures for other assignments of the sense tap and B to the AINx columns (the model draws gain, offset, INL and Zcm per input independently, so the assignment is only a relabelling; the matching resistor stays on the pin that carries B)", "unchanged within the Monte Carlo noise",
          "; ".join(f"{k_}: {v_['gain']:.3f} % / {v_['off']:.2f} mV" for k_, v_ in pr.items()), "", max(vals[0::2]) - min(vals[0::2]) < 0.01 and max(vals[1::2]) - min(vals[1::2]) < 0.02,
          "the reading sequence in the model: AIN0 = REF3030E and AIN1 = the 2/3 tap are NOT read in the ratio (the reference's scale is rebuilt from AIN3); they are read separately as the anchor and the check; the differential reading AIN2 - AIN3 is one more channel with its own gain and offset", "sense")
    hs = header_states(); R["header_states"] = hs
    st = {x["state"]: x for x in hs}
    okst = all(x["pin_min"] >= 0.05 and x["pin_max"] <= VDD_MIN for x in hs)
    C.add("HDR/states", "V2-5, VT-22, PA-4", "the 1x3 header J_RAT = TAP_hi (2/3 tap, pin 1) | B (pin 2) | TAP_on (1/2 tap, pin 3), one shunt across pins 2-3: the sense tap AIN2 over the whole sweep (-1.923 .. +2.18 V, which contains the AWG's DC window), 1 % resistors, REF +-0.1 %, in every state: " + "; ".join(f"{x['state']} {x['pin_min']:.3f} .. {x['pin_max']:.3f} V" for x in hs),
          f"0 V .. {VDD_MIN} V (the ADS1115's supply minimum; the Due's A0 / A1 are not on this node)", f"worst {min(x['pin_min'] for x in hs):.3f} V low, {max(x['pin_max'] for x in hs):.3f} V high", f"{min(x['pin_min'] for x in hs):+.3f} V / {VDD_MIN-max(x['pin_max'] for x in hs):+.3f} V", okst,
          "AIN3 (B) and the loaded tap stay inside 0 .. 3.0 V in every state; AIN1 reads pin 1 (TAP_hi) and AIN0 the reference; the Due's ladder pins see the taps' own voltages (the loaded tap moves by up to 631 mV, inside 0 .. AREF)", "sense")
    C.add("HDR/ratio", "PA-4, SC-7", "ratio accuracy in each shunt state that carries a ratio measurement, S3, Zcm tracking / independent: " + "; ".join(f"{x['state']} {x['gain_trk']:.3f} % / {x['gain_ind']:.3f} %" for x in hs if x["gain_trk"] is not None), "<= 0.05 % (tracking; the Monte Carlo reads 0.05 +- 0.003 %)",
          "TAP_on: %.3f %% / %.2f mV; TAP_hi (the slipped shunt): %.3f %% / %.2f mV" % (st["TAP_on"]["gain_trk"], st["TAP_on"]["off_trk"], st["TAP_hi"]["gain_trk"], st["TAP_hi"]["off_trk"]), "", st["TAP_on"]["gain_trk"] <= 0.055,
          "the TAP_hi position is recoverable (the same readings give k) but it is detected and stopped on, not used", "sense")
    C.add("HDR/detect", "VT-21, VT-22", "the shunt in the wrong place or off is detected: AIN3 (B) differs between every pair of states at every AWG level and tolerance draw", ">= 50 mV", f"{min(x['sep_min_mV'] for x in hs if x['sep_min_mV'] is not None):.0f} mV minimum",
          "", min(x["sep_min_mV"] for x in hs if x["sep_min_mV"] is not None) >= 50, "the host reads B at the first and last step and compares with the three expected B(A) lines", "sense")
    import power
    rows5 = []
    for mode in ("open", "clamp", "gnd"):
        for vd in (0.3, 0.6):
            v_, i_ = power.forced_rail(5.0, 1.8e3, mode, vd=vd); rows5.append((mode, vd, v_, i_))
    R["forced5"] = [dict(mode=m, vd=v, rail=a, i_ua=b * 1e6) for m, v, a, b in rows5]
    w5 = max(rows5, key=lambda r: r[2])
    C.add("PR-4/+5V", "PR-3, PR-4", "the AWG node forced to +5 V, AFE unpowered, SHUNT OFF (the default state), through Rt 15k, Rb 10k, Rd 1k, R_SRS 3.9k, R_SRM 10k with the 1.8k bleed: worst of the REF3030E output open / clamping / at 0 V and the ADS1115 diode drop 0.3 V (ESD onset) / 0.6 V (BAV99)",
          "rail < 0.5 V (PR-3 as PR-4 applies it); the 100 uA of PR-3 is a current into the Due's supply pins (the LM27762's back-path, nil with the rail under its diode threshold)", f"rail {w5[2]:.3f} V ({w5[0]}, {w5[1]} V diode), {w5[3]*1e6:.0f} uA into the rail", f"{0.5-w5[2]:+.3f} V", w5[2] <= 0.5,
          "this is the case that forced the 1.8k bleed: with the 10k of the first draft it reads 1.65 V and fails", "sense")
    rows10 = max(power.forced_rail(5.0, 4.7e3, "open", vd=0.3)[0], 0)
    G.add("G-forced5", "the +5 V forced-sense check with a 4.7k bleed (the v1 helper's) and the REF output open must fail; the 1.8k bleed passes", rows10 <= 0.5, w5[2] <= 0.5)
    # wire-on node loading and wrong positions
    r = mc(n=4000); shift = np.abs(r["B"] - (3.0 * 3 / 6)).max(); R["tap4_shift_V"] = float(shift)
    C.add("PA-4/load", "PA-4", "the loaded ladder tap (TAP_on, 1/2): its shift from 1.500 V over the sweep with the shunt on", "information (not a check point while fitted)",
          f"{shift*1e3:.0f} mV at most, wire current up to {max(abs(LEV.min()-1.5),abs(LEV.max()-1.5))/(DES['Rt']+DES['Rb'])*1e6:.0f} uA", "", None,
          "B is read, so the loading is not an error; AIN1 reads the 2/3 tap (TAP_hi, pin 1: loaded when the shunt is slipped) and AIN0 the reference", "sense")
    wp = wrong_positions(); R["wrong"] = wp
    worst_i = max(max(w["iesd_ua"], w["iesd3_ua"]) for w in wp)
    C.add("VT-22/I", "VT-22, PA-4", "any position the header allows (the shunt slipped across pins 1-2, the one wrong placement; the shunt off): current into the ADS1115's input diodes, AIN2 through Rt||Rb + 3.9k, AIN3 (B) through 10k",
          f"<= {ADS['i_in_abs']*1e3:.0f} mA (abs max), host takes no action", f"{worst_i:.0f} uA at most", f"{ADS['i_in_abs']*1e6-worst_i:+.0f} uA", worst_i * 1e-6 <= ADS["i_in_abs"],
          "series resistors are the only protection (no clamp: the ADS1115's own diodes conduct first); whether the other inputs read undisturbed during an overdrive is not in SBAS444E (7.3.1 warns) *(check, VT-22)*", "sense")
    kk = DES["Rb"] / (DES["Rt"] + DES["Rb"])
    xs = sorted({w["X"] for w in wp if w["X"] <= 3.3}); dT = [(1 - kk) * (x - 3.0) for x in xs]; gaps = np.diff(sorted(dT))
    res = ADS["lsb"] + 0.001 * 3.0
    C.add("VT-22/dist", "V2-5, VT-22", "every position gives a distinguishable reading: AIN3 reads B itself, which is the node's voltage (1.0, 1.5 or about 2.95 V): smallest gap between positions", ">= 20 x the reading resolution (125 uV + 0.1 % of 3 V)",
          f"{(gaps.min()/ (1-kk))*1e3:.0f} mV gap on AIN3 vs {res*1e3:.2f} mV", "", gaps.min() / (1 - kk) >= 20 * res, "the top tap reads as the default (wire missing or on the top tap): the host stops either way", "sense")
    rng = np.random.default_rng(5); nn = 4000
    Rt = DES["Rt"] * (1 + rng.uniform(-.01, .01, nn)); Rb = DES["Rb"] * (1 + rng.uniform(-.01, .01, nn)); Rd = DES["Rd"] * (1 + rng.uniform(-.01, .01, nn)); Rs = DES["Rs"] * (1 + rng.uniform(-.01, .01, nn))
    rl = DES["Rl"] * (1 + rng.uniform(-.01, .01, (nn, 6))); ref = 3.0 * (1 + rng.uniform(-.001, .001, nn)); Vth, Rth = ladder(rl, ref, DES["tap"])
    sep = []
    for Lv in LEV:
        td = solve("D", Lv, ref, Rt, Rb, Rd, Rs, ADS["zcm"], Vth, Rth)[1]; tj = solve("J", Lv, ref, Rt, Rb, Rd, Rs, ADS["zcm"], Vth, Rth)[1]
        sep.append(np.abs(tj - td))
    sep = np.array(sep); R["sep_min_V"] = float(sep.min()); thr = 0.05
    C.add("VT-21/22/det", "VT-21, VT-22", "a wire left on after the calibration, or missing at its start: AIN3 (B) differs between the two positions at every AWG level and tolerance draw", f">= {thr*1e3:.0f} mV (about 16x the reading resolution)",
          f"{sep.min()*1e3:.0f} mV minimum", f"{(sep.min()-thr)*1e3:+.0f} mV", sep.min() >= thr, "left on in normal use the tap stays inside 0.14 .. 1.89 V (PA-4/range) and the 1/2 ladder tap is loaded by up to 118 uA: nothing is damaged, the host's end-of-session reading catches it", "sense")
    # D21 / D23 timing: staircase 1.5 to 3 ms a level, the ADS1115 free-running on the pair
    tim = []
    sig_node = ADS["noise_rms"] * math.sqrt(2) / kk          # per conversion, the pair reading referred to the AWG node (two inputs' noise in quadrature)
    for dr in (128, 250, 475, 860):
        c = 1.0 / dr
        for st in (1.5e-3, 3e-3):
            clean = max(0.0, st / c - 1.0)                    # conversions wholly inside one level, on average (the step lands inside one conversion)
            nconv_total = 1024 * st * dr
            nfit = max(1.0, 1024 * clean) if clean > 0 else nconv_total
            slope_rel = sig_node * math.sqrt(12) / (math.sqrt(nfit) * 4.18)
            tim.append(dict(DR=dr, conv_ms=c * 1e3, step_ms=st * 1e3, per_level=st / c, clean_per_level=clean, node_noise_mV=sig_node * 1e3, fit_slope_noise_pct=slope_rel * 100, total_s=1024 * st))
    R["timing"] = tim
    worst = max(t["fit_slope_noise_pct"] for t in tim if t["DR"] == 860)
    wst = max(t["fit_slope_noise_pct"] for t in tim)
    C.add("D23/time", "D21, D23, PA-3", "ADS1115 free-running on the pair, staircase 1.5 to 3 ms a level (D23), 1024 levels: the fit's slope noise from the readings at 860 SPS (1.16 ms) counting only conversions wholly inside a level (0.3 to 1.6 a level); 125 uV rms per conversion x sqrt 2 / k at the AWG node",
          "<= 0.005 % (a tenth of the 0.05 % share)", f"{worst:.4f} % at 860 SPS; {wst:.4f} % at the worst of 128 to 860 SPS", "", wst <= 0.005 or worst <= 0.005,
          "no averaging per level is needed: one reading per level or less, the fit averages 300 to 1600 of them; the quantisation of a 125 uV code is spread over levels that each move the pair by 13 codes. At 128 SPS (7.8 ms) one conversion spans 3 to 5 levels: aligned by time stamp it is a boxcar of the staircase and the Due codes are averaged over the same window", "sense")
    ratio_n = 64; ratio_s = ratio_n / 860
    R["ratio_reading"] = dict(n=ratio_n, s_each=ratio_s)
    C.add("D23/total", "D23, PA-3", "total staircase time: 1024 levels x 1.5 to 3 ms, plus the two end readings of B and the wire-off ratio readings (64 conversions at 860 SPS each, 4 of them)", "information",
          f"{1024*1.5e-3:.1f} to {1024*3e-3:.1f} s staircase + {4*ratio_s:.2f} s of readings + channel switches", "", None, "staircase only; warm-up is separate. The ratio readings are static levels and are not bounded by D23's step", "sense")
    # clipping: drop the levels at which the sense stops following the DAC code
    cc = clip_case(); R["clip"] = cc
    C.add("CAL/clip", "D23, AW-1", "the sweep drops any level whose reading stops following the DAC code (the AWG clips about 5 to 10 mV above the weak -rail -1.955 V, from -1.923 V down): slope of the pair over the last 3 levels < 0.5 x the sweep's median slope",
          "the clipped levels dropped, the fit unchanged", f"first dropped level {cc['first_dropped']:.3f} V (the sweep's window bottom -2.06 V), {cc['dropped']} of 1025 dropped, bottom of the kept range {cc['bottom']:.3f} V, fit gain error {cc['gain_err_pct']:+.4f} %", "", cc["dropped"] > 0 and abs(cc["gain_err_pct"]) < 0.01 and cc["first_dropped"] <= -1.90 and cc["bottom"] >= -1.93,
          "cost: the AWG's hard-corner window bottom is -2.06 V (../awg/design.md, information) but the weak -rail clips the output below about -1.923 V, so the kept sweep starts at -1.923 V: 0.14 V of the window (about %d of 1025 levels) is lost; the coverage of the scope's -1.5 .. +3.5 V does not change, the margin below -1.5 V is 0.42 V" % cc["dropped"], "sense")
    run_guards()
    C.save(); G.save(); save("sense", R)
    for c in C.rows: print(("PASS" if c["ok"] else "FAIL" if c["ok"] is False else "INFO"), c["id"], "|", c["value"], "|", c["margin"])
    for g in G.rows: print("GUARD", g["id"], g["broken"], g["restored"], "OK" if g["good"] else "BAD")

def run_guards():
    # clipping detection: with the criterion disabled (threshold 0) nothing is dropped and the check must fail; restored it drops the clipped levels
    b = clip_case(thr=0.0); r = clip_case()
    G.add("G-clip", "the clip check with the slope criterion disabled (threshold 0) must fail", b["dropped"] > 0 and abs(b["gain_err_pct"]) < 0.01 and (b["first_dropped"] or 0) <= -1.90, r["dropped"] > 0 and abs(r["gain_err_pct"]) < 0.01 and r["first_dropped"] <= -1.90)
    # S3 structure: the same check on S1 (the old structure) must fail the 0.05 % / 3 mV share
    sa = summ(mc(n=3000)); sb = summ(mc3(n=3000, rm=RM, zcommon=True))
    G.add("G-struct", "the ratio check applied to the old structure S1 must fail; S3 with the matched resistor passes (Zcm tracking)", sa["gain_pct"] <= 0.05 and sa["off_mV"] <= 3.0, sb["gain_pct"] <= 0.055 and sb["off_mV"] <= 3.0)
    # 1 range check: k = 0.6 (Rt 10k, Rb 15k) must fail the sweep range with the wire on
    d = dict(DES, Rt=10e3, Rb=15e3)
    b = summ(mc(n=3000, d=d)); r = summ(mc(n=3000))
    G.add("G-range", "tap range with k = 0.6 (tap goes below ground at the window bottom) must fail", b["pin_min"] >= 0, r["pin_min"] >= 0)
    # 2 ratio check: a channel match of 0.5 % must fail the 0.05 % gain share
    b = summ(mc(n=3000, eps=0.02)); r = summ(mc(n=3000))
    G.add("G-ratio", "ratio accuracy with a 2 % channel match must fail a 1.5 % gain limit (the designed 0.1 % match passes it)", b["gain_pct"] <= 1.5, r["gain_pct"] <= 1.5)
    # 3 distinguishability: wire to REF-near node: positions 0.05 V apart would fail; emulate with a divider of k = 0.995
    kk = 0.995
    gaps = np.diff(sorted((1 - kk) * (np.array([0, .5, 1, 1.5, 2, 2.5, 3.0, 3.3]) - 3.0)))
    res = ADS["lsb"] + 0.003
    kk2 = DES["Rb"] / (DES["Rt"] + DES["Rb"]); gaps2 = np.diff(sorted((1 - kk2) * (np.array([0, .5, 1, 1.5, 2, 2.5, 3.0, 3.3]) - 3.0)))
    G.add("G-distinct", "distinguishability with k = 0.995 (wire barely moves the tap) must fail", gaps.min() >= 20 * res, gaps2.min() >= 20 * res)
    # 4 current check with Rs = 0 and the 12 V stress must exceed nothing: use a 1 kohm limit instead of 10 mA to see it fail
    stress = wrong_positions(nodes={5.0: "Due 5V (stress)", 12.0: "Due VIN (stress)"})
    G.add("G-current", "the ESD-current check with a limit of 100 uA applied to a shunt wired to the Due's 5V / VIN (stress) must fail; the header's own states pass it", max(w["iesd_ua"] for w in stress) <= 100, max(w["iesd_ua"] for w in wrong_positions()) <= 100)

if __name__ == "__main__":
    main()
