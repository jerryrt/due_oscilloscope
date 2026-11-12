#!/usr/bin/env python3
"""v1 S3 PR-3 on kvm_02's worst case; bleed scan; the +-12 V scope case; comparison with kvm_02's choices.  Writes results/pr3.json."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net, pr3
from net import RES
from s3 import s3design
FINAL = s3design(22e3, 15e3, 3.9e3, 13e3, "TAP3")
KVM = s3design(15e3, 10e3, 3.9e3, 10e3, "TAP3")
BLEEDS = [4.7e3, 3.9e3, 3.3e3, 2.7e3, 2.2e3, 2.0e3, 1.8e3, 1.5e3, 1.2e3]
LADDER = ("zero", "open", "clamp"); NOLAD = ("open_nl", "clamp_nl")
R = {}
def worst_over(d, V, bleed, states, vd=0.3):
    best = None
    for w in (None, d["wire"]):
        for rs in states:
            x = pr3.forced(d, V, w, rs, vd=vd, bleed=bleed)
            if best is None or x["rail_V"] > best[1]["rail_V"]: best = ((w or "off", rs), x)
    return best

def main():
    R["scan"] = {}
    for nm, d in (("final 22k/15k Rs3.9k Rm13k", FINAL), ("kvm_02 15k/10k Rs3.9k Rm10k", KVM)):
        for b in BLEEDS:
            real = worst_over(d, 5.0, b, LADDER); nol = worst_over(d, 5.0, b, NOLAD)
            R["scan"][f"{nm}|{b/1e3:g}k"] = dict(real=dict(case=real[0], **real[1]), no_ladder=dict(case=nol[0], **nol[1]))
            print(f"{nm:30s} bleed {b/1e3:4.1f}k | ladder present: {real[1]['rail_V']:.3f} V {real[1]['i_rail_uA']:.0f} uA {real[0]} | kvm no-ladder: {nol[1]['rail_V']:.3f} V {nol[1]['i_rail_uA']:.0f} uA {nol[0]}")
    # the earlier assumptions, reproduced: REF at 0 V and a 0.6 V drop, kvm_02's circuit and mine
    R["earlier_assumptions"] = {}
    for nm, d in (("final", FINAL), ("kvm", KVM)):
        x = worst_over(d, 5.0, 4.7e3, ("zero",), vd=0.6); R["earlier_assumptions"][nm] = x[1]
        print("earlier assumptions (REF 0 V, drop 0.6 V, bleed 4.7k):", nm, "%.3f V %.0f uA" % (x[1]["rail_V"], x[1]["i_rail_uA"]))
    # +1.8 V and the others on the final circuit with 4.7k and the proposed bleed
    for b in (4.7e3, 1.8e3):
        for V in (1.8, 5.0):
            rl = worst_over(FINAL, V, b, LADDER); nl = worst_over(FINAL, V, b, NOLAD)
            R[f"final_{V}_{b/1e3:g}k"] = dict(real=rl[1], nl=nl[1])
    # scope case
    R["scope12"] = {}
    for b in (4.7e3, 1.8e3):
        R["scope12"][f"{b/1e3:g}k"] = {rs: pr3.scope12(b, rs) for rs in ("zero", "clamp")}
    print("scope +12 V both inputs:", R["scope12"])
    G = []
    def g(i, w, broken_fail, restored_pass): G.append(dict(id=i, what=w, broken="fails" if broken_fail else "PASSES (guard void)", restored="passes" if restored_pass else "FAILS", good=bool(broken_fail and restored_pass)))
    kn = R["scan"]["kvm_02 15k/10k Rs3.9k Rm10k|1.8k"]
    g("G-pr3-repro", "my engine must reproduce kvm_02's published 0.434 V / 241 uA for their 15k/10k circuit with the 1.8k bleed (within 3 %): with the ladder left on the reference node (0.287 V / 159 uA) it does not; with the ladder out it does",
      not (abs(kn["real"]["rail_V"] - 0.434) / 0.434 < 0.03), abs(kn["no_ladder"]["rail_V"] - 0.434) / 0.434 < 0.03 and abs(kn["no_ladder"]["i_rail_uA"] - 241) / 241 < 0.03)
    f = {b: R["scan"][f"final 22k/15k Rs3.9k Rm13k|{b}k"]["no_ladder"]["rail_V"] for b in ("4.7", "2.2")}
    g("G-pr3-bleed", "the worst-case rail limit (0.5 V) applied to the 4.7k bleed (0.746 V) must fail; the 2.2k bleed (0.382 V) passes", f["4.7"] > 0.5, f["2.2"] < 0.5)
    sc = pr3.scope12(1e9, "clamp")
    g("G-pr3-scope", "the +-12 V scope case with the bleed removed (1 GOhm) must fail 0.5 V; with 2.2k it passes", sc["rail_V"] > 0.5, pr3.scope12(2.2e3, "clamp")["rail_V"] < 0.5)
    R["guards"] = G
    for x in G: print("GUARD", x["id"], x["broken"], x["restored"], "OK" if x["good"] else "BAD")
    R["scope12"]["2.2k"] = {rs: pr3.scope12(2.2e3, rs) for rs in ("zero", "clamp")}
    json.dump(R, open(os.path.join(RES, "pr3.json"), "w"), indent=1, default=float)

if __name__ == "__main__":
    main()
