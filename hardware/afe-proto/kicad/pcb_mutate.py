"""Write a deliberately broken copy of the board, for check.py's mutation arms (each must make a P-check fail).

    /usr/bin/python3.14 -I pcb_mutate.py <board> <mode>      mode: net | overlap | header
"""
import sys

import pcbnew as pcb

b = pcb.LoadBoard(sys.argv[1])
fp = {f.GetReference(): f for f in b.GetFootprints()}
mode = sys.argv[2]
if mode == 'net':          # R30 (RF, CH1) with its two pad nets exchanged
    a, c = list(fp['R30'].Pads())
    na, nc = a.GetNet(), c.GetNet()
    a.SetNet(nc); c.SetNet(na)
elif mode == 'overlap':    # R10 dropped onto R11
    fp['R10'].SetPosition(fp['R11'].GetPosition())
elif mode == 'header':     # ADCL0 0.2 mm off its V03 position
    p = fp['J5'].GetPosition()
    fp['J5'].SetPosition(pcb.VECTOR2I(p.x + pcb.FromMM(0.2), p.y))
else:
    raise SystemExit(mode)
b.Save(sys.argv[1])
