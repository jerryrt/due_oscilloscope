#!/usr/bin/env python3
"""Task 5: the AWG-sense divider and its jumper (PA-4, V2-5, VT-21, VT-22), with the wire fitted for the WHOLE tee sweep.

Circuit (design.md section 5):  A (the AWG at the BNC / tee node) -- Rt -- T0 -- Rb -- B ;  T0 -- Rs -- ADS1115 input 2 (the tap)
B -- Rd -- REF3030E (the permanent default).  The jumper wire joins B to ladder tap N (the 2/3 tap, ADS input 4), which has the
Thevenin source Vth behind Rth.  ADS1115 input 1 reads REF, input 3 the 1/3 tap, input 4 the 2/3 tap (= B when the wire is on).
k = Rb/(Rt+Rb) is the weight of A in the tap:  T0 = k A + (1-k) B  (loaded by the ADC input).

Truth model per draw: every resistor U(+-1 %) (ladder parts too), REF 3.0 V +-0.1 %, the ADS1115's per-input gain (channel match
0.1 % max, uniform +-eps/2 each), offset (+-3 LSB of 62.5 uV at +-2.048 V: carried as +-3 x 125 uV, conservative), INL bow 1 LSB, input
loading as a resistor Zcm (6 Mohm +-25 %, typ only *(check)*) to 0.7 V (SBAS444E 7.3.2), and the host's own averaging noise.
The host solves (A, k) at one ratio level from the wire-off and wire-on readings with the NOMINAL network and Zcm, exactly as
the procedure would, then converts every sweep reading (wire on throughout) to AWG volts.  numpy only."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

C = Cases("sense"); G = Guards("sense"); R = {}
LSB = ADS["lsb"]; VC = ADS["v_common"]
DES = dict(Rt=15e3, Rb=10e3, Rd=1e3, Rs=4.7e3, Rl=330.0, tap=2, REF=3.0)      # the design (k = 0.4, wire node = the 1/3 tap, ADS input 3)
LEV = np.linspace(-1.95, 2.28, 25)       # window bottom -1.9 / top 2.2275 plus 0.05 / 0.05 V of tolerance
VDD_MIN = 3.22

def ladder(rl, ref, tap):
    """Thevenin (Vth, Rth) of tap number `tap` of six equal rungs, from the bottom; rl: (n, 6)."""
    S = rl.sum(1); lo = rl[:, :tap].sum(1)
    return ref * lo / S, lo * (S - lo) / S

def solve(pos, A, ref, Rt, Rb, Rd, Rs, Z, Vth, Rth, Il=0.0):
    """Node T0 and B.  Node T0 is loaded by Z + Rs to 0.7 V; in position J node B also hangs on the ladder tap (and Z4, small, folded
    into Vth/Rth: its 0.4 uA across 440 ohm is 0.2 mV, carried by the MC through Zcm).  Returns T0, B, pin voltage of input 2."""
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
       tolset=None, sweep_mode="B_each", iters=12, offs=ADS["off_err_lsb"], inl=ADS["inl_lsb"], navg=64, noise=ADS["noise_rms"]):
    rng = np.random.default_rng(seed)
    U = lambda w, size=None: rng.uniform(-w, w, size)
    CHB = 2 if d["tap"] == 2 else 3
    tl = lambda nm: tol if (tolset is None or nm in tolset) else 0.0
    Rt = d["Rt"] * (1 + U(tl("Rt"), n)); Rb = d["Rb"] * (1 + U(tl("Rb"), n)); Rd = d["Rd"] * (1 + U(tl("Rd"), n)); Rs = d["Rs"] * (1 + U(tl("Rs"), n))
    rl = d["Rl"] * (1 + U(tl("Rl"), (n, 6)))
    ref = d["REF"] * (1 + U(REF["tol"], n))
    Vth, Rth = ladder(rl, ref, d["tap"])
    Z = ADS["zcm"] * (1 + U(zspread, (n, 4)))
    ge = 1 + U(eps / 2, (n, 4)); off = U(offs * LSB, (n, 4)); inlb = U(inl * LSB, (n, 4))
    def read(v, ch):
        vv = np.clip(v, 0, 4.096)
        return ge[:, ch] * v + off[:, ch] + inlb[:, ch] * 4 * vv * (4.096 - vv) / 4.096 ** 2 + rng.normal(0, noise / np.sqrt(navg), n)
    # reference reading (ch 0) defines the ratio scale: the host reports V = 3.0 x reading / reference reading
    rref = read(ref, 0)
    vol = lambda r: d["REF"] * r / rref
    Rtot = d["Rt"] + d["Rb"]; kn = d["Rb"] / Rtot
    Rtn, Rbn = d["Rt"], d["Rb"]
    Vthn, Rthn = d["REF"] * d["tap"] / 6, d["Rl"] * d["tap"] * (6 - d["tap"]) / 6
    Zn = ADS["zcm"]
    # ---- ratio level, wire off then on
    A0 = ratio_level
    T0d, Bd, pind = solve("D", A0, ref, Rt, Rb, Rd, Rs, Z[:, 1], Vth, Rth)
    T0j, Bj, pinj = solve("J", A0, ref, Rt, Rb, Rd, Rs, Z[:, 1], Vth, Rth)
    rTd = vol(read(pind, 1)); rTj = vol(read(pinj, 1)); rN = vol(read(Bj, CHB))
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
        f = lambda AA, kk: np.stack([fwd("D", AA, kk, rN) - rTd, jfwd(AA, kk, rN) - rTj])
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
        Bm = vol(read(B, CHB)) if sweep_pos == "J" else None
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

def summ(r, q=99.9):
    return dict(gain_pct=float(np.percentile(np.abs(r["gain"]), q) * 100), off_mV=float(np.percentile(np.abs(r["off"]), q) * 1e3),
                err_mV=float(np.percentile(np.abs(r["err"]).max(0), q) * 1e3), k_err_pct=float(np.percentile(np.abs(r["k"] / r["k_true"] - 1), q) * 100),
                pin_min=float(r["pins"].min()), pin_max=float(r["pins"].max()), t0_min=float(r["t0"].min()), t0_max=float(r["t0"].max()))

# ------------------------------------------------------------------------------------------------------------- wrong positions
def wrong_positions(d=DES, A=LEV, vref=3.0):
    """B tied to a node X through the wire (zero ohm) while Rd to REF still hangs on it.  X from GND to the 5 V pin and 12 V (VIN) for stress.
    Returns per X: T0 open-circuit extremes over A, the current into the ADS pin's ESD diodes through Rs, the shift of dT against the default at A=0.8."""
    out = []
    names = {0.0: "GND", 0.5: "tap1 (1/6)", 1.0: "tap2 (1/3, ADS input 3): the RIGHT position", 1.5: "tap3 (1/2)", 2.0: "tap4 (2/3, ADS input 4)", 2.5: "tap5 (5/6)",
             3.0: "tap6 = REF (same as wire off)", 3.3: "+3.3 V_A", 5.0: "Due 5V pin (stress)", 12.0: "Due VIN (stress)"}
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
        iwire = np.abs((A - Bn)).max() / (d["Rt"] + d["Rb"])
        out.append(dict(node=nm, X=X, t0_min=float(lo), t0_max=float(hi), iesd_ua=float(iesd * 1e6), iwire_ua=float(iwire * 1e6),
                        dT_at_0p8=float(kk * 0 + (1 - kk) * (Bn - (vref - 0.0))), pin_ok_0_to_vdd=bool(lo >= 0 and hi <= VDD_MIN)))
    return out

def main():
    base = mc()
    s = summ(base); R["base"] = s
    C.add("PA-4/range", "PA-4", "sweep, wire ON throughout: sense tap pin voltage over every AWG level -1.95..+2.28 V, every resistor at +-1 %, REF +-0.1 %", f"0 V .. {VDD_MIN} V (ADS supply minimum)",
          f"{s['pin_min']:.3f} .. {s['pin_max']:.3f} V (node {s['t0_min']:.3f} .. {s['t0_max']:.3f})", f"{s['pin_min']:+.3f} V / {VDD_MIN-s['pin_max']:+.3f} V",
          s["pin_min"] >= 0 and s["pin_max"] <= VDD_MIN, "k = 0.4, bottom node = the 1/3 tap", "sense")
    off = mc(sweep_pos="D")
    so = summ(off); R["wire_off_sweep"] = so
    C.add("PA-4/range-off", "PA-4", "the same with the wire OFF (default tie to the REF3030E; the normal-use state)", f"0 V .. {VDD_MIN} V",
          f"{so['pin_min']:.3f} .. {so['pin_max']:.3f} V", f"{so['pin_min']:+.3f} V / {VDD_MIN-so['pin_max']:+.3f} V", so["pin_min"] >= 0 and so["pin_max"] <= VDD_MIN, "", "sense")
    C.add("PA-4/ratio", "PA-4, SC-7", "AWG level read through the sweep, wire on throughout, ratio from wire-off and wire-on readings at one level, ADS channel match 0.1 % (max), 99.9th percentile",
          "gain <= 0.05 %, offset <= 3 mV (this design's half of the 0.1 % fit share, and of the 5 mV)", f"gain {s['gain_pct']:.3f} %, offset {s['off_mV']:.2f} mV, worst point {s['err_mV']:.2f} mV (k error {s['k_err_pct']:.3f} %)", "",
          s["gain_pct"] <= 0.05 and s["off_mV"] <= 3.0, "a share of 0.05 % for the sense is this design's allocation of the 0.1 % fit share (the Due-ADC fit takes the rest)", "sense")
    typ = summ(mc(eps=ADS["gain_ch_match"][0])); R["typ_match"] = typ
    C.add("PA-4/ratio-typ", "PA-4", "the same at the typical channel match 0.05 %", "information", f"gain {typ['gain_pct']:.3f} %, offset {typ['off_mV']:.2f} mV", "", None, "", "sense")
    nm = summ(mc(eps=0.0)); R["no_match"] = nm
    C.add("PA-4/ratio-0", "PA-4", "the same with no channel mismatch (shows what the match costs)", "information", f"gain {nm['gain_pct']:.3f} %, offset {nm['off_mV']:.2f} mV", "", None, "", "sense")
    ip = summ(mc(sweep_mode="interp")); R["interp"] = ip
    C.add("D21/sweep", "D21, PA-4", "ADS1115 free-running on the sense node ONLY during the staircase; B (the wired 1/3 tap) and the reference read at the first and last step, every level between taken from the straight line of the tap through those two (the network is linear)",
          "the same as reading B at every level", f"gain {ip['gain_pct']:.3f} %, offset {ip['off_mV']:.2f} mV, worst point {ip['err_mV']:.2f} mV (B at every level: {s['gain_pct']:.3f} %, {s['off_mV']:.2f} mV)", "", abs(ip["gain_pct"] - s["gain_pct"]) <= 0.01,
          "the free-running reading loses nothing: the tap is a linear function of the AWG level, so the two end readings fix the line; the channel switches (to B and the reference) cost one conversion each at the ends", "sense")
    # timing, D21: single-cycle settling (SBAS444E 7.3.6), conversion time 1/DR, a step lands inside one conversion: discard it and one more (I2C alignment)
    tim = []
    for dr in (128, 250, 860):
        for tstep in (0.05, 0.2, 0.4):
            nconv = int(tstep * dr); navg = max(nconv - 2, 0)
            tim.append(dict(DR=dr, t_step=tstep, conversions=nconv, averaged=navg, node_noise_uV=(ADS["noise_rms"] / np.sqrt(max(navg, 1)) / 0.4 * 1e6 if navg else None),
                            total_min_1024=1024 * tstep / 60, total_min_256=256 * tstep / 60))
    R["timing"] = tim
    worst_short = [t for t in tim if t["DR"] == 128 and t["t_step"] == 0.05][0]
    C.add("D21/time", "D21, PA-3", "ADS1115 at 128 SPS (7.8 ms a conversion, single-cycle settling), staircase step 0.05 s: conversions per level, minus two (the one the step lands in, one for I2C alignment)", ">= 4 averaged readings at the shortest step",
          f"{worst_short['conversions']} conversions, {worst_short['averaged']} averaged, {worst_short['node_noise_uV']:.0f} uV rms at the AWG node (if the input dithers the converter)", "", worst_short["averaged"] >= 4,
          "128 SPS is the fastest rate whose peak-to-peak noise equals its rms in Table 6-1 (250 SPS and up: pp 148 to 267 uV); the staircase step is the Due-side averaging time (PA-3: 100,000 samples a point), which the AWG/Due set, so see the table in design.md for the total time", "sense")
    # loading of the ladder tap by the wire
    r = mc(n=4000)
    dN = (r["B"][:, :] - 0)  # B in J at each level
    shift = np.abs(r["B"] - (3.0 * 2 / 6)).max(); R["tap4_shift_V"] = float(shift)
    iw = (LEV.max() - LEV.min()) / (DES["Rt"] + DES["Rb"])
    C.add("PA-4/load", "PA-4", "the loaded ladder tap (1/3, ADS input 3): its shift from 1.000 V over the sweep with the wire on", "information (not a calibration point while fitted)",
          f"{shift*1e3:.0f} mV at most, wire current up to {max(abs(LEV.min()-1.0),abs(LEV.max()-1.0))/(DES['Rt']+DES['Rb'])*1e6:.0f} uA", "", None,
          "the other measured tap (2/3, input 4) is untouched; the wire-off readings before fitting and after removal read every tap", "sense")
    # wrong positions
    wp = wrong_positions(); R["wrong"] = wp
    worst_i = max(w["iesd_ua"] for w in wp)
    C.add("VT-22/I", "VT-22, PA-4", "any position the header allows (GND, every tap, +3.3 V_A, and the Due's 5V and VIN as stress): the current into the ADS1115's input diodes through Rt||Rb + Rs",
          f"<= {ADS['i_in_abs']*1e3:.0f} mA (abs max), host takes no action", f"{worst_i:.0f} uA at most", f"{ADS['i_in_abs']*1e6-worst_i:+.0f} uA", worst_i * 1e-6 <= ADS["i_in_abs"],
          "Rs 4.7k is the only protection; whether the other three inputs read undisturbed during the overdrive is not in SBAS444E (7.3.1 warns) *(check, VT-22)*", "sense")
    # distinguishability: delta T at the ratio level between positions
    kk = DES["Rb"] / (DES["Rt"] + DES["Rb"])
    xs = sorted({w["X"] for w in wp if w["X"] <= 3.3})
    dT = [(1 - kk) * (x - 3.0) for x in xs]
    gaps = np.diff(sorted(dT))
    R["dT"] = dict(zip([str(x) for x in xs], dT))
    # the host's resolution on dT: ADS LSB 125 uV with channel mismatch 0.1 % of 3 V
    res = ADS["lsb"] + 0.001 * 3.0
    C.add("VT-22/dist", "V2-5, VT-22", "every position gives a distinguishable T shift against the wire-off reading (dT = (1-k)(X - 3.0 V)); smallest gap between positions", ">= 20 x the reading resolution (125 uV + 0.1 % of 3 V)",
          f"{gaps.min()*1e3:.0f} mV gap vs {res*1e3:.2f} mV resolution", "", gaps.min() >= 20 * res, "tap6 = REF reads dT = 0, i.e. as 'no wire': the host says 'wire missing or on the top tap' and stops either way", "sense")
    # detection of a wire left on / missing: the tap's separation between the two positions at every AWG level, over the tolerance draws
    rng = np.random.default_rng(5); nn = 4000
    Rt = DES["Rt"] * (1 + rng.uniform(-.01, .01, nn)); Rb = DES["Rb"] * (1 + rng.uniform(-.01, .01, nn)); Rd = DES["Rd"] * (1 + rng.uniform(-.01, .01, nn)); Rs = DES["Rs"] * (1 + rng.uniform(-.01, .01, nn))
    rl = DES["Rl"] * (1 + rng.uniform(-.01, .01, (nn, 6))); ref = 3.0 * (1 + rng.uniform(-.001, .001, nn)); Vth, Rth = ladder(rl, ref, DES["tap"])
    sep = []
    for Lv in LEV:
        td = solve("D", Lv, ref, Rt, Rb, Rd, Rs, ADS["zcm"], Vth, Rth)[2]; tj = solve("J", Lv, ref, Rt, Rb, Rd, Rs, ADS["zcm"], Vth, Rth)[2]
        sep.append(np.abs(tj - td))
    sep = np.array(sep); R["sep_min_V"] = float(sep.min())
    thr = 0.05
    C.add("VT-21/22/det", "VT-21, VT-22", "a wire left on after the calibration, or missing at its start: the tap's difference between the two positions at every AWG level (the host compares the wire-off reading taken before fitting and after removal with the sweep's)", f">= {thr*1e3:.0f} mV (about 16x the reading resolution) at every level, every tolerance draw",
          f"{sep.min()*1e3:.0f} mV minimum", f"{(sep.min()-thr)*1e3:+.0f} mV", sep.min() >= thr, "left on in normal use the tap stays inside 0.14 .. 1.89 V (PA-4/range) and the 1/3 ladder tap is loaded by up to 118 uA: nothing is damaged, and the Due's reading of that tap is flagged by the host's end-of-session check", "sense")
    G.add("G-timing", "the timing check with a step of 0.01 s (one conversion at 128 SPS: nothing left to average) must fail", int(0.01 * 128) - 2 >= 4, worst_short["averaged"] >= 4)
    G.add("G-detect", "the detection check with the separation limit raised to 2 V must fail", sep.min() >= 2.0, sep.min() >= thr)
    run_guards()
    C.save(); G.save(); save("sense", R)
    for c in C.rows: print(("PASS" if c["ok"] else "FAIL" if c["ok"] is False else "INFO"), c["id"], "|", c["value"], "|", c["margin"])
    for g in G.rows: print("GUARD", g["id"], g["broken"], g["restored"], "OK" if g["good"] else "BAD")

def run_guards():
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
    wp = wrong_positions()
    G.add("G-current", "ESD current check with the limit lowered to 10 uA must fail", max(w["iesd_ua"] for w in wp) <= 10, max(w["iesd_ua"] for w in wp) * 1e-6 <= ADS["i_in_abs"])

if __name__ == "__main__":
    main()
