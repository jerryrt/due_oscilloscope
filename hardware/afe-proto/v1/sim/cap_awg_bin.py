"""/AWG_BIN (the AWG's +IN node) and /AWG_BPL (the divider's middle node): self capacitance, converged, no pour / pour.
cd hardware/afe-proto && PYTHONPATH=. PCBTOOLS_V1_SOURCE=/work/hardware/afe-proto/kicad python3 v1/sim/cap_awg_bin.py kicad/afe-proto.kicad_pcb"""
import sys
from pcbtools import cap, check
from pcbtools.boards import v1 as cfg
b = check.load(sys.argv[1])
for n in ('/AWG_BIN', '/AWG_BPL'):
    for pour, r in cap.converge_self(b, n, 3.0, gnd=cfg.GND).items():
        print(cap.converged_line((n, pour), r), flush=True)
        print('   padcorrected', r.get('extrapolated_padcorrected'), 'uncertainty', r['uncertainty'], flush=True)
