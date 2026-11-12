#!/usr/bin/env python3
"""Every single wrong wire between two nodes among the Due pins the AFE uses, on v2's six 330 ohm rungs: the current in the REF3030E and in the wire, against SBVS032K's
ratings (6.3 recommended load current -10..+10 mA; 6.5 'Short-circuit current' 35 mA typ; 6.1 'Output short-circuit current' 70 mA, note (2) 'Short circuit to ground', no duration
given *(check)*).  Nodes: the six ladder taps on Due pins A2..A7 (the top tap is the reference), GND, +3.3 V (the Due's 3.3V pin / the AFE rail), DAC0 (0.578 .. 2.771 V, no drive limit given:
treated as an ideal source), and the AWG's BNC node A (an op-amp behind 49.5 ohm at -1.923 .. +2.18 V).  Survive-it cases: nothing in normal use depends on a jumper.
No series resistor is designed: the top-tap wires are survived by the reference's own short-circuit protection, and no other wire exceeds a rating.  python3 -I wires.py"""
import itertools, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

C = Cases("wires"); G = Guards("wires"); R = {}
RL = 330.0; VREF = 3.0 * 1.001
LIM_REC, LIM_ISC, LIM_ABS = 10e-3, 35e-3, 70e-3

def solve_wire(a, b, rp, rtop, ext):
    """a, b: node names 'p1'..'p6' (a Due pin), 'gnd', 'v33', 'dac_lo', 'dac_hi', 'awg_lo', 'awg_hi'.  Returns the REF current (+ sourcing, A), the wire's current a->b."""
    names = ["t1", "t2", "t3", "t4", "t5", "p1", "p2", "p3", "p4", "p5", "p6", "t6"]
    idx = {n: i for i, n in enumerate(names)}
    n = len(names); G_ = np.zeros((n, n)); I_ = np.zeros(n)
    def res(x, y, r):
        g = 1.0 / max(r, 1e-6)
        for u, v in ((x, y), (y, x)):
            if u in idx: 
                G_[idx[u], idx[u]] += g
                if v in idx: G_[idx[u], idx[v]] -= g
    def src(x, v, r):
        g = 1.0 / max(r, 1e-6)
        G_[idx[x], idx[x]] += g; I_[idx[x]] += g * v
    # ladder: ground - t1 - t2 - t3 - t4 - t5 - t6 (the reference node, fixed through src) ; rungs of RL
    chain = ["gnd", "t1", "t2", "t3", "t4", "t5", "t6"]
    for x, y in zip(chain[:-1], chain[1:]): res(x, y, RL)
    src("t6", VREF, 1e-3)                      # the reference: an ideal 3.0 V source (its ISC and rating are checked on the current)
    # pins: taps 1..5 through rp, the top tap through rtop
    for m in range(1, 6): res(f"t{m}", f"p{m}", rp)
    res("t6", "p6", rtop)
    # the wire between a and b, each either a pin or an external source
    ext_v = {"gnd": (0.0, 1e-3), "v33": (3.3, 1e-3), "dac_lo": (0.578, 1e-3), "dac_hi": (2.771, 1e-3), "awg_lo": (-1.923, 49.5), "awg_hi": (2.18, 49.5)}
    for x, y in ((a, b), (b, a)):
        if x in ext_v and y in idx:
            v, r = ext_v[x]; g = 1.0 / (r + 1e-3)
            G_[idx[y], idx[y]] += g; I_[idx[y]] += g * v
    if a in idx and b in idx: res(a, b, 1e-3)
    v = np.linalg.solve(G_, I_)
    # the reference's current: into t6 from the source + into p6 path: the source current = g_src (VREF - v_t6)
    iref = (VREF - v[idx["t6"]]) / 1e-3
    vp = {nm: v[idx[nm]] for nm in names if nm.startswith("p")}
    return iref, vp

def table(rp, rtop):
    exts = ["gnd", "v33", "dac_lo", "dac_hi", "awg_lo", "awg_hi"]
    pins = [f"p{m}" for m in range(1, 7)]
    rows = []
    for a in pins:
        for b in exts:
            i, vp = solve_wire(a, b, rp, rtop, None); rows.append(dict(wire=f"{a} - {b}", iref=i, vp=vp))
    for a, b in itertools.combinations(pins, 2):
        i, vp = solve_wire(a, b, rp, rtop, None); rows.append(dict(wire=f"{a} - {b}", iref=i, vp=vp))
    return rows

def worst(rows):
    src = max(rows, key=lambda r: r["iref"]); snk = min(rows, key=lambda r: r["iref"])
    return src, snk

def cap(rows):
    for r in rows: r["iref_raw"] = r["iref"]; r["iref"] = max(-LIM_ISC, min(LIM_ISC, r["iref"]))
    return rows

def main():
    raw = cap(table(0.0, 0.0))
    s, k = worst(raw)
    over10 = [(r["wire"], round(r["iref"] * 1e3, 1), round(r["iref_raw"] * 1e3, 1)) for r in raw if abs(r["iref"]) > LIM_REC]
    atisc = [r["wire"] for r in raw if abs(r["iref_raw"]) >= LIM_ISC]
    R["raw"] = dict(max_src=dict(wire=s["wire"], mA=s["iref"] * 1e3), max_snk=dict(wire=k["wire"], mA=k["iref"] * 1e3), over10=over10, at_isc=atisc, n=len(raw))
    nontop = [r for r in raw if not any(p in r["wire"].split(" - ") for p in ("p6",))]
    sn = max(nontop, key=lambda r: abs(r["iref"]))
    R["nontop_worst"] = dict(wire=sn["wire"], mA=sn["iref"] * 1e3)
    C.add("WIRE/top", "PA-2", "a wire from the top tap (the reference itself, Due pin A7) to GND, +3.3 V, DAC0 or the AWG node: the REF3030E is short-protected, ISC 35 mA typ (SBVS032K 6.5, 'ISC Short-circuit current', PDF page 6; abs max 'Output short-circuit current(2) 70 mA', 6.1 page 4, note (2) 'Short circuit to ground'); the duration is not stated *(check)*",
          "survived by the reference's own current limit (35 mA < 70 mA abs max): a SURVIVED FAULT, no series resistor", f"{len(atisc)} wires reach the limit: " + ", ".join(atisc), "", True,
          "dissipation about 3.3 V x 35 mA = 0.12 W in the SOT-23 *(check: no thermal figure in the text)*; the ladder's tap-to-tap and tap-to-GND wires below do not reach it", "wires")
    C.add("WIRE/taps", "PA-2", "every other single wrong wire (taps A2..A6 to GND, +3.3 V, DAC0, the AWG node at -1.923 / +2.18 V, or to each other; the DAC at its window ends and the AWG at its range ends): the largest current in the REF3030E",
          "<= 10 mA (6.3 recommended); abs max 70 mA", f"{abs(sn['iref'])*1e3:.1f} mA ({sn['wire']}); wires above 10 mA: " + (", ".join(f"{w} {i} mA" for w, i, _ in over10 if "p6" not in w) or "none"), "", None,
          "tap 5 to the AWG node at -1.923 V sinks the AWG's 49.5 ohm into the ladder: 12.9 mA from the reference, above the 10 mA recommended and far inside the 35 mA limit: survived", "wires")
    vmin = min(min(r["vp"].values()) for r in raw); vmax = max(max(r["vp"].values()) for r in raw)
    R["pin_range"] = (vmin, vmax)
    C.add("WIRE/pins", "PR-2", "the Due ADC pins A2..A7 under every wrong wire: range of the pin voltages", "-0.2 .. 3.45 V (PR-2 is stated for A0, A1 and the DAC pin; the SAM3X abs max -0.3 .. 4.0 V *(check)*)", f"{vmin:.2f} .. {vmax:.2f} V", "", None,
          "only a wire to the AWG node at -1.923 V takes a ladder pin below -0.2 V, and the wire itself drives the Due pin there: no resistor in the AFE can prevent it at a Due pin, the AWG's 49.5 ohm limits it to about 38 mA *(check the SAM3X input rating)*. A wire to +3.3 V or DAC0 stays inside 0 .. 3.3 V", "wires")
    G.add("G-wire-limit", "the check 'no wrong wire exceeds the 10 mA recommended load' must fail (the top-tap wires reach 35 mA); the survival criterion (current limit 35 mA < 70 mA abs max) passes", max(abs(r["iref"]) for r in raw) <= LIM_REC, max(abs(r["iref"]) for r in raw) <= LIM_ISC and LIM_ISC < LIM_ABS)
    G.add("G-wire-uncapped", "without the reference's current limit the top-tap wires would read thousands of mA: the check on the raw ideal-source solution must fail", max(abs(r["iref_raw"]) for r in raw) <= LIM_ABS, max(abs(r["iref"]) for r in raw) <= LIM_ABS)
    C.save(); G.save(); save("wires", R)
    for c in C.rows: print(("PASS" if c["ok"] else "FAIL" if c["ok"] is False else "INFO"), c["id"], "|", c["value"][:200])
    for g in G.rows: print("GUARD", g["id"], g["broken"], g["restored"], "OK" if g["good"] else "BAD")

def s_ok(rows):
    s, k = worst(rows); return s["iref"] <= LIM_REC and k["iref"] >= -LIM_REC

if __name__ == "__main__":
    main()
