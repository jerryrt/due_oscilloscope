"""One-off extraction of the v1 board's LM27762 capacitor geometry for pw2_ac_v1.py (needs pcbnew: the image only).
Prints, per capacitor: its signal pad, distance to the nearest same-net U401 pad, the widths of the track segments on that net
touching the cap pad, GND vias within VIA_RADIUS_MM of its GND pad, and which layers the segments are on."""
import sys
from pathlib import Path
import numpy as np
AFE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AFE))
from pcbtools import boardio

CAPS = ["C401", "C403", "C404", "C405", "C406", "C407", "C408", "C409", "C410", "C402"]


def main(path):
    b = boardio.read_board(path)
    nets = list(b.nets) if hasattr(b, "nets") else None
    refs = list(b.fp_ref)
    g = nets.index("/GND") if "/GND" in nets else None
    u = refs.index("U401")
    for r in CAPS:
        i = refs.index(r)
        pads = np.where(b.p_fp == i)[0]
        for j in pads:
            n = b.p_net[j]
            if n == g:
                d = np.hypot(b.v_x - b.p_x[j], b.v_y - b.p_y[j])
                print(f"{r} pad{b.p_pin[j]} GND vias<=1.5mm: {int(np.sum((d<=1.5)&(b.v_net==g)))}")
                continue
            up = [k for k in np.where(b.p_fp == u)[0] if b.p_net[k] == n]
            dist = min((float(np.hypot(b.p_x[k]-b.p_x[j], b.p_y[k]-b.p_y[j])) for k in up), default=None)
            touching = [(round(float(b.s_w[s]), 3), int(b.s_layer[s])) for s in range(len(b.s_x0))
                        if b.s_net[s] == n and (np.hypot(b.s_x0[s]-b.p_x[j], b.s_y0[s]-b.p_y[j]) < 0.35 or np.hypot(b.s_x1[s]-b.p_x[j], b.s_y1[s]-b.p_y[j]) < 0.35)]
            allw = sorted({round(float(w), 3) for w, nn in zip(b.s_w, b.s_net) if nn == n})
            print(f"{r} pad{b.p_pin[j]} net={nets[n]} dist_to_U401={dist} touching(w,layer)={touching} net_widths={allw}")


if __name__ == "__main__":
    main(sys.argv[1])
