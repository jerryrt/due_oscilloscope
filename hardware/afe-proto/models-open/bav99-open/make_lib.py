"""Fits the BAV99 diode parameters to the digitised datasheet curves in FACTS.md and writes bav99.lib and
fit_residuals.json beside this file (python3 make_lib.py; needs numpy, scipy and ngspice for the TT step).
Every input number below is a FACTS.md figure (Fig. 1, 2, 3 tables; Table 7 trr). Nothing else is used."""
import json, os, subprocess, tempfile, re
import numpy as np
from scipy.optimize import least_squares, brentq

HERE = os.path.dirname(os.path.abspath(__file__))
K = 1.380649e-23; Q = 1.602176634e-19
TNOM = 25.0; TN = TNOM + 273.15

# FACTS Fig. 1 (typical VF in V against IF in mA, curves by Tamb in C), accuracy +-5 mV to 30 mA, +-8 mV at 100/300 mA
IF_MA = np.array([0.1, 0.3, 1, 3, 10, 30, 100, 300])
VF = {150: [.188, .263, .348, .429, .526, .639, .840, 1.210], 85: [.352, .415, .486, .554, .638, .739, .914, 1.247],
      25: [.497, .550, .611, .671, .743, .827, .984, 1.288], -40: [.654, .698, .745, .790, .847, .920, 1.060, 1.349]}
VF_ACC = np.array([5, 5, 5, 5, 5, 5, 8, 2.]) * 1e-3   # 300 mA row weighted x4 (fit weight, not the stated accuracy)
# FACTS Fig. 2 (typical IR in uA against VR in V), accuracy about +-3 % (0.012 decade)
VR = np.array([1, 10, 25, 50, 75, 95, 99.])
IR = {150: [9.6, 13.7, 16.5, 19.6, 22.6, 27.5, 29.4], 85: [.32, .48, .59, .72, .85, 1.07, 1.17],
      25: [4.9e-3, 6.9e-3, 8.5e-3, 1.05e-2, 1.32e-2, 1.94e-2, 2.2e-2], -40: [3.4e-5, 3.6e-5, 4.1e-5, 5.0e-5, 5.5e-5, 6.4e-5, 6.4e-5]}
# FACTS Fig. 3 (Cd in pF against VR in V, 25 C), accuracy +-0.01 pF
CV = np.array([0, 1, 2, 4, 8, 12, 16.]); CD = np.array([.60, .52, .49, .475, .46, .457, .455])
TRR_MAX_NS = 4.0     # FACTS Table 7, IF = IR = 10 mA, IR(meas) = 1 mA, RL = 100 ohm
BV_CHOICE, IBV_CHOICE = 125.0, 1e-5      # MODELLING CHOICE: FACTS gives no breakdown voltage


def vf_model(p, tc, i):
    lis, n, rs, eg, xti, lik, trs = p
    t = tc + 273.15; vt = K * t / Q; r = t / TN; ikf = np.exp(lik)
    is_ = np.exp(lis) * np.exp((r - 1) * eg / (n * vt)) * r ** (xti / n)
    a = 1 / np.sqrt(ikf)
    ifw = ((a * i + np.sqrt(a * a * i * i + 4 * i)) / 2) ** 2      # inverts ngspice's knee, I = If / (1 + sqrt(If/IKF)) (read off ngspice by sweep)
    return n * vt * np.log(ifw / is_ + 1) + i * rs * (1 + trs * (t - TN))


def is_at(p, tc):
    lis, n, rs, eg, xti = p[:5]
    t = tc + 273.15; vt = K * t / Q; r = t / TN
    return np.exp(lis) * np.exp((r - 1) * eg / (n * vt)) * r ** (xti / n)


def fit_forward():
    i = IF_MA * 1e-3
    res = lambda p: np.concatenate([(vf_model(p, t, i) - np.array(v)) / VF_ACC for t, v in VF.items()])
    best = None
    for n0 in (1.5, 2.0):
        for eg0 in (0.9, 1.2):
            for lik in (-4, -2):
                s = least_squares(res, [-19, n0, 1.0, eg0, 3.0, lik, 0.0],
                                  bounds=([-60, 1, 0, 0.3, 0, -9, -0.05], [-5, 3, 20, 2, 10, 2, 0.05]))
                if best is None or s.cost < best.cost: best = s
    return best.x


def fit_cap():
    f = lambda p, v: p[0] + p[1] * (1 + v / p[2]) ** (-p[3])
    best = None
    for vj0 in (.3, .7, 1.0):
        for m0 in (.3, .5):
            s = least_squares(lambda p: (f(p, CV) - CD) / 0.01, [.45, .15, vj0, m0], bounds=([0, 0, .05, .05], [1, 2, 2, 0.98]))
            if best is None or s.cost < best.cost: best = s
    return best.x, f


def trr_ns(tt, run_dir):
    """Simulated trr in the Fig. 5 conditions: 50 ohm source + 50 ohm scope in series with the diode, IF = 10 mA forward,
    switched to a reverse level that limits the reverse current to IR = 10 mA, 0.6 ns edge; trr from the current zero
    crossing to the reverse current falling back to 1 mA."""
    deck = f"""trr
.include {os.path.join(run_dir, 'trr_model.lib')}
Vs s 0 PULSE(1.75 -1.0 20n 0.6n 0.6n 100n 400n)
Rs s a 50
X1 a b b BAV99_OPEN
Rl b 0 50
.options gmin=1e-15
.temp 25
.tran 0.02n 80n 0 0.02n
.control
run
wrdata {os.path.join(run_dir, 'trr.dat')} i(Vs)
.endc
.end
"""
    open(os.path.join(run_dir, 'trr.cir'), 'w').write(deck)
    subprocess.run(["ngspice", "-b", "trr.cir"], cwd=run_dir, capture_output=True, text=True, timeout=120)
    a = np.loadtxt(os.path.join(run_dir, 'trr.dat')); t, i = a[:, 0], -a[:, 1]    # i = diode forward current
    k0 = np.argmax(t > 20.3e-9)
    kz = k0 + np.argmax(i[k0:] < 0)                       # zero crossing
    tz = t[kz - 1] + (t[kz] - t[kz - 1]) * i[kz - 1] / (i[kz - 1] - i[kz])
    kr = kz + np.argmin(i[kz:] > -1e-3) if False else None
    ipk = np.argmin(i[kz:]) + kz
    kr = ipk + np.argmax(i[ipk:] > -1e-3)
    tr = t[kr - 1] + (t[kr] - t[kr - 1]) * (-1e-3 - i[kr - 1]) / (i[kr] - i[kr - 1])
    return (tr - tz) * 1e9


def main():
    pf = fit_forward(); (pc, fcap) = fit_cap()
    cp, cjo, vj, m = pc
    lis, n, rs, eg, xti, lik, trs = pf
    # leakage: table of what the diode's own IS(T) does not supply, per curve, in uA
    extra = {t: np.maximum(np.array(v) - is_at(pf, t) * 1e6, 1e-9) for t, v in IR.items()}
    temps = sorted(IR, reverse=True)                       # 150, 85, 25, -40 : ascending 1/T
    inv_t = [1.0 / (t + 273.15) for t in temps]
    common = dict(IS=np.exp(lis), N=n, RS=rs, IKF=np.exp(lik), TRS1=trs, EG=eg, XTI=xti, CJO=cjo * 1e-12, VJ=vj, M=m,
                  BV=BV_CHOICE, IBV=IBV_CHOICE)

    def model_line(tt):
        return (".model BAV99_OPEN_D D(IS={IS:.5g} N={N:.5g} RS={RS:.5g} IKF={IKF:.5g} TRS1={TRS1:.5g} EG={EG:.5g} XTI={XTI:.5g} "
                "CJO={CJO:.5g} VJ={VJ:.5g} M={M:.5g} FC=0.5 TT={tt:.5g} BV={BV:g} IBV={IBV:g} TNOM=25)").format(tt=tt, **common)
    def build(tt):
        pw = lambda x, ys: ", ".join(f"{a:.6g},{b:.6g}" for a, b in zip(x, ys))
        lg = {t: np.log10(extra[t]) for t in temps}
        L = []
        L.append("* BAV99 dual series switching diode, open model.   SPDX-License-Identifier: CC-BY-SA-4.0   (CC-BY-SA 4.0)")
        L.append("* Clean-room model: built only from FACTS.md (datasheet facts); no vendor SPICE model was consulted.")
        L.append("* Subcircuit pin order: .subckt BAV99_OPEN A1 K2 CA   pin 1 = A1 (anode of diode 1), pin 2 = K2 (cathode of diode 2),")
        L.append("*   pin 3 = CA (the common node: cathode of diode 1 joined to anode of diode 2).")
        L.append("* Each diode = BAV99_OPEN_D (forward, junction capacitance, recovery, breakdown) + a fixed parallel capacitance +")
        L.append("*   a reverse-leakage current source tabulated from the 'IR vs VR' curves at -40, 25, 85 and 150 C (log-linear in V")
        L.append("*   between the digitised points, linear in 1/T between the curves, flat outside them, linear to 0 below 1 V).")
        L.append("* Use .options gmin=1e-15 for reverse currents at the -40 C curve (ngspice's default gmin of 1e-12 S is larger than them).")
        L.append("* Parameters fitted by make_lib.py; residuals in fit_residuals.json.  BV/IBV and TT are labelled modelling choices")
        L.append("* (PROVENANCE.md): BV is not in the datasheet; TT is set so simulated trr = the 4 ns Table 7 maximum.")
        L.append(f"* Parallel capacitance CP = {cp:.5g} pF is the constant part of the Cd-vs-VR curve (Fig. 3); CJO is the voltage-dependent part.")
        L.append(model_line(tt))
        L.append("")
        L.append(".subckt BAV99_OPEN_HALF a k")
        L.append("D1 a k BAV99_OPEN_D")
        L.append(f"CP a k {cp:.5g}p")
        L.append("* reverse voltage, clamped to the digitised range 0..99 V")
        L.append("Bvr vr 0 V = max(min(-v(a,k), 99), 0)")
        L.append("* 1/T clamped to the range of the four curves; ngspice pwl() extrapolates, so each hat weight is floored at 0")
        L.append(f"Bt t 0 V = max(min(1/(temper+273.15), {inv_t[-1]:.8g}), {inv_t[0]:.8g})")
        for j in range(4):
            pts = []
            if j > 0: pts += [inv_t[j - 1], 0]
            pts += [inv_t[j], 1]
            if j < 3: pts += [inv_t[j + 1], 0]
            if j == 0: pts = [inv_t[0], 1, inv_t[1], 0]
            if j == 3: pts = [inv_t[2], 0, inv_t[3], 1]
            L.append(f"Bw{j} w{j} 0 V = max(pwl(v(t), " + ", ".join(f"{x:.8g},{y:g}" for x, y in zip(pts[0::2], pts[1::2])) + "), 0)")
            L.append(f"Bl{j} l{j} 0 V = pwl(max(v(vr),1), " + pw(VR, lg[temps[j]]) + ")")
        L.append("* extra reverse current in A: log10(uA) blended over 1/T, scaled to 0 below 1 V")
        L.append("Bleak a k I = -min(v(vr),1) * 1e-6 * pwr(10, v(w0)*v(l0) + v(w1)*v(l1) + v(w2)*v(l2) + v(w3)*v(l3))")
        L.append(".ends BAV99_OPEN_HALF")
        L.append("")
        L.append(".subckt BAV99_OPEN A1 K2 CA")
        L.append("X1 A1 CA BAV99_OPEN_HALF")
        L.append("X2 CA K2 BAV99_OPEN_HALF")
        L.append(".ends BAV99_OPEN")
        return "\n".join(L) + "\n"
    run = tempfile.mkdtemp(prefix="bav99trr")
    def f_tt(tt):
        open(os.path.join(run, 'trr_model.lib'), 'w').write(build(tt))
        return trr_ns(tt, run) - TRR_MAX_NS
    tt = brentq(f_tt, 0.1e-9, 12e-9, xtol=1e-12)
    trr0 = f_tt(1e-12) + TRR_MAX_NS
    open(os.path.join(HERE, "bav99.lib"), "w").write(build(tt))

    resid = {"forward_mV_model_minus_digitised": {str(t): [round(float(x) * 1e3, 2) for x in vf_model(pf, t, IF_MA * 1e-3) - np.array(v)] for t, v in VF.items()},
             "capacitance_pF_model_minus_digitised": [round(float(x), 4) for x in fcap(pc, CV) - CD],
             "params": {k: float(v) for k, v in zip(["ln_IS", "N", "RS", "EG", "XTI", "ln_IKF", "TRS1"], pf)},
             "cap_params": dict(zip(["CP_pF", "CJO_pF", "VJ", "M"], map(float, pc))),
             "TT_s": tt, "trr_at_TT_1ps_ns": trr0, "trr_target_ns": TRR_MAX_NS}
    json.dump(resid, open(os.path.join(HERE, "fit_residuals.json"), "w"), indent=1)
    print(json.dumps(resid, indent=1))


if __name__ == "__main__":
    main()
