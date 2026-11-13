#!/usr/bin/env python3
"""AWG-into-scope coupling through the REF3030E (SC-9, VT-10's AWG case) with the +-5 V scope network, in ngspice, not scaled.

The AWG's offset current moves the REF3030E output (../awg/run.py case_ref: m volts peak-to-peak at f Hz for the full commanded swing,
REF3030E output impedance as its Fig. 6-14 read).  That movement reaches each scope's pin through R3 and the divider.  Here m is read from
../awg/raw/results.json (read only), applied as a source ON the reference node of the ported scope netlist (run.py's rails and chan,
the op-amp macro, both channels present), and the pin's response at f is read from ngspice.  1 LSB is AREF 3.3 V / 4096 at the pin, the
AWG study's own convention, so the figure compares row for row with its 1.69 LSB.

    docker/pcb/run.sh python3 -I range5v_refcoupling.py [--out FILE]          (run.py's profiles: v2 | 5v | 5vc)
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as R
import netlib as NL

AWG = os.path.join(HERE, "..", "awg", "raw", "results.json")
LSB_PIN = 3.3 / 4096


def gain(profile, f):
    R.set_range(profile)
    NL.set_workdir(None)
    p = R.pp(Rsrc=50.0)
    rails = NL.rails(p).replace("Vr vr0 0 dc 3.0", "Vr vr0 0 dc 3.0 ac 1")
    assert "ac 1" in rails
    t = (NL.header("refc") + rails + "Vsa asrc 0 dc 0\nVsb bsrc 0 dc 0\n" + NL.chan(p, "a") + NL.chan(p, "b") + f"""
.control
ac lin 1 {f} {f}
wrdata {NL.wr('refc', 'x')} v(apin) v(bpin)
.endc
.end
""")
    NL.run_ng("refc", t)
    d = NL.load("refc", "x")
    return float(abs(d[0, 1] + 1j * d[0, 2])), float(abs(d[0, 4] + 1j * d[0, 5]))


ZREF = [(10, 1), (100, 4), (200, 6), (300, 9), (500, 17), (700, 26), (1000, 45), (1300, 65), (1600, 95), (1900, 115), (2300, 100), (2700, 70), (3200, 40), (4000, 20), (6000, 8), (10000, 3)]


def ref_move(Rvr, C=14e-6, Rg2=3000.0, Rf=3000.0, dv=3.2):
    """../awg/run.py ref_move, 'graph' mode, copied (that file is not imported: it runs the AWG study): peak-to-peak REF movement (V) and its frequency
    for the full commanded +-1.6 V swing.  Checked against the committed raw/results.json at the Rvr it holds."""
    import numpy as np
    f = np.logspace(1, 4, 800)
    Zc = 1 / (2j * np.pi * f * C)
    Zn = Rvr * Zc / (Rvr + Zc)
    i = (dv / (1 + Rf / Rg2)) / np.abs(Rg2 + Zn)
    share = np.abs(Zc / (Rvr + Zc))
    z = np.exp(np.interp(np.log(f), np.log([a for a, b in ZREF]), np.log([b for a, b in ZREF])))
    z = np.interp(np.log(f), np.log([a for a, b in ZREF]), [b for a, b in ZREF])
    m = i * share * z
    k = int(np.argmax(m))
    return float(m[k]), float(f[k])


def rvr_cases(argv):
    """The scope network at the AWG's REF swing for Rvr 100 / 120 / 130 / 140 / 150, cases baseline, A and B (stray at N, as ../sensitivity_n_stray.json)."""
    committed = json.load(open(AWG))["ref"]["move"]["chosen, graph"]
    m130, f130 = ref_move(130.0)
    print(f"check of the copied formula against the AWG results file (Rvr 130 committed): {committed[0]*1e3:.4f} mV at {committed[1]:.0f} Hz vs {m130*1e3:.4f} mV at {f130:.0f} Hz")
    assert abs(committed[0] - m130) < 1e-6 and abs(committed[1] - f130) < 1, "formula differs from the AWG study's"
    out = {}
    for case, (cnp, cx) in {"baseline": (None, None), "A": (4.31e-12, 5e-17), "B": (0.81e-12, 5e-17)}.items():
        for rvr in (100.0, 120.0, 130.0, 140.0, 150.0):
            m, f = ref_move(rvr)
            R.set_range("5vc")
            if cnp is not None:
                NL.P0["Cn_par"], NL.P0["Cx"] = cnp, cx
            ga, gb = gain_here(f)
            out.setdefault(case, {})[f"{rvr:g}"] = dict(m_mV=m * 1e3, f_Hz=f, gain=ga, pin_mV=m * ga * 1e3, lsb=m * ga / LSB_PIN)
    return out


def gain_here(f):
    p = R.pp(Rsrc=50.0)
    rails = NL.rails(p).replace("Vr vr0 0 dc 3.0", "Vr vr0 0 dc 3.0 ac 1")
    t = (NL.header("refc") + rails + "Vsa asrc 0 dc 0\nVsb bsrc 0 dc 0\n" + NL.chan(p, "a") + NL.chan(p, "b") + NL.coupling(p) + f"""
.control
ac lin 1 {f} {f}
wrdata {NL.wr('refc', 'x')} v(apin) v(bpin)
.endc
.end
""")
    NL.run_ng("refc", t)
    d = NL.load("refc", "x")
    return float(abs(d[0, 1] + 1j * d[0, 2])), float(abs(d[0, 4] + 1j * d[0, 5]))


def main(argv):
    if "--rvr" in argv:
        out = rvr_cases(argv)
        for case, rows in out.items():
            print(f"case {case}: " + "  ".join(f"Rvr {k}: {v['m_mV']:.3f} mV -> {v['lsb']:.3f} LSB" for k, v in rows.items()))
        if "--out" in argv:
            json.dump(out, open(argv[argv.index("--out") + 1], "w"), indent=1)
        return 0
    mv = json.load(open(AWG))["ref"]["move"]
    out = {"awg_rows": {}}
    for prof in ("v2", "5v", "5vc"):
        row = {}
        for lab in ("chosen, graph", "chosen, 110 ohm bound", "chosen, 28 ohm loaded"):
            m, f = mv[lab][0], mv[lab][1]
            ga, gb = gain(prof, f)
            row[lab] = dict(m_mV=m * 1e3, f_Hz=f, gain_pin_over_ref=ga, gain_other_channel=gb, pin_mV=m * ga * 1e3, lsb=m * ga / LSB_PIN)
        out[prof] = row
    for prof in ("v2", "5v", "5vc"):
        r = out[prof]["chosen, graph"]
        print(f"{prof:4s} chosen/graph: {r['m_mV']:.3f} mV on the REF at {r['f_Hz']:.0f} Hz x {r['gain_pin_over_ref']:.4f} = {r['pin_mV']:.3f} mV at the pin = {r['lsb']:.3f} LSB   "
              f"(110 ohm bound {out[prof]['chosen, 110 ohm bound']['lsb']:.2f}, 28 ohm loaded {out[prof]['chosen, 28 ohm loaded']['lsb']:.2f})")
    ok = abs(out["v2"]["chosen, graph"]["lsb"] - mv["chosen, graph"][4]) < 0.02
    print("control: the old range reproduces the AWG study's", f"{mv['chosen, graph'][4]:.3f} LSB:", "yes" if ok else "NO")
    if "--out" in argv:
        json.dump(out, open(argv[argv.index("--out") + 1], "w"), indent=1)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
