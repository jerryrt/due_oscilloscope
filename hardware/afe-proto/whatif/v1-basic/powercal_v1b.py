#!/usr/bin/env python3
"""v1-basic: the power and calibration rows the Basic 1 % passives move, by the copied sim/powercal (run.py edited in
place in whatif/v1-basic/sim/powercal; every edit is marked 'v1-basic').

  P1-a / P1-b  LM27762 rails with 1 % feedback resistors: FB+ 75k + 100k over 100k, FB- 75k over 3 x 330k
  rails        nominal / datasheet-limit rails (VFB+- Sec 5.5 limits, resistors at 1 %)
  C1-a..d      ladder of 8 x 270 ohm 1 % (3 parallel + 5 series): tap impedance, settling, REF3030E load and headroom
  C2-a..c      PA-9 fit and the Due pin-leakage rule (0.5 uA x tap impedance) with 1 % ladder parts at 100 ppm/K
  P8-c (AN-4)  scope centring error at the ADC pin: Vmid divider 2 x 330k 1 %, sense filter 270 ohm 1 %, network 1 %
  P3           AFE current budget with the new ladder

    python3 -I powercal_v1b.py          -> results/powercal_v1b.json, prints the rows
"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
PC = os.path.join(HERE, "sim", "powercal")
sys.path.insert(0, PC)
import run as P          # chdirs into the copy

def main():
    out = {"rails": P.R["rails"], "RT_P": P.RT_P, "RT_N": P.RT_N, "RB_N": P.RB_N, "RTOL_FB": P.RTOL_FB}
    P.run_p1()
    P.run_p3()
    P.run_c1()
    P.run_c2()
    # AN-4 (P8-c): as the design states it (network at 1 % inside the MC) and the Vmid-source share alone, which is the term
    # sim/scope's +/-30 mV centring allowance stands for (the network's own tolerance is in sim/scope's perturbations)
    an4 = {}
    for lab, kw in (("as P8-c, network 1 %, Vmid divider 1 %, sense 270 ohm 1 %, ADVREF drop 5 mV", dict(delta=5e-3, rsf_tol=0.01)),
                    ("as P8-c, ADVREF drop 0.5 mV", dict(delta=0.5e-3, rsf_tol=0.01)),
                    ("Vmid source share only (network ideal), 5 mV drop", dict(delta=5e-3, tol_net=0.0, rsf_tol=0.01)),
                    ("current design reproduced: 0.1 % divider and network, 249 ohm, 5 mV drop", dict(delta=5e-3, tol_div=0.001, tol_net=0.001, rsf=249.0))):
        an4[lab] = P.an4_mc(**kw) * 1e3
        print(f"[AN-4] {lab}: {an4[lab]:.2f} mV (limit 30 mV)")
    out["an4_mV"] = an4
    out["cases"] = P.CASES
    out["c1_buffer"] = P.R.get("c1_buffer"); out["c1_zmax"] = P.R.get("c1_zmax")
    out["p1"] = dict(worst_pins_sch=P.R.get("p1_worst_pins_sch"), worst_pins_nosch=P.R.get("p1_worst_pins_nosch"), allowed=P.R.get("p1_allowed_overshoot"))
    out["ladder"] = dict(seg=P.SEG, total=P.RLAD_TOTAL, taps_V=[float(x) for x in P.F_NOM * P.VREF], zth=[float(x) for x in P.ZI_NOM])
    json.dump(out, open(os.path.join(HERE, "results", "powercal_v1b.json"), "w"), indent=1, default=float)

if __name__ == "__main__":
    main()
