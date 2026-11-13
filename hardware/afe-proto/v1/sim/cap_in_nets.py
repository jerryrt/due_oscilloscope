"""IN nets: the 0.05 mm level of --converge does not fit 3M cells (23 x 25 mm window), so the three levels are 0.4/0.2/0.1 mm.
python3 cap_in_nets.py BOARD  (run in the image with PCBTOOLS_V1_SOURCE set, cwd hardware/afe-proto)"""
import sys
from pcbtools import cap, check
from pcbtools.boards import v1 as cfg
b = check.load(sys.argv[1])
HS = (0.4, 0.2, 0.1)
for pour in (False, True):
    print(cap.converged_line(('IN-IN', pour), cap.converge_pair(b, ['/CH1_IN', '/CH2_IN'], 3.0, pour, (0.8, 0.4, 0.2), gnd=cfg.GND)), flush=True)
for n in ('/CH1_IN', '/CH2_IN'):
    for pour, r in cap.converge_self(b, n, 3.0, HS, gnd=cfg.GND).items():
        print(cap.converged_line((n, pour), r), flush=True)
# N-N and NP-NP in fF (the --converge line prints pF to 4 places, which is 0.1 fF)
for lab, nets, h in (('N-N', ('/CH1_N', '/CH2_N'), 0.2), ('N-N', ('/CH1_N', '/CH2_N'), 0.1), ('NP-NP', ('/CH1_NP', '/CH2_NP'), 0.1)):
    for pour in (False, True):
        w = cap.window(b, nets, 0.75)
        c = cap.pair_caps(b, list(nets), w, pour, h, gnd=cfg.GND)[nets]
        print(f'{lab} h={h} pour={pour} pad 0.75: {c * 1e3:.4f} fF', flush=True)
