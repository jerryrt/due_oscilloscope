import sys
sys.path[:0] = ['hardware/pcbkit']
import numpy as np
from pcbkit import board as kb, fills
for path, wins in (('hardware/afe-proto/whatif/fill-keepouts/_v2.kicad_pcb', [(20, 11, 28, 19)]), ('hardware/afe-proto/kicad/_h2.kicad_pcb', [(43, 13, 50, 18), (85, 32, 92, 38), (43, 7, 50, 13)])):
    b = kb.read_board(path, {'FRAME': (50.0, 150.0)})
    g = [i for i, n in enumerate(b.nets) if n.lstrip('/') == 'GND'][0]
    rp = fills.net_copper(b, 0, g, 40.0, with_net_items=False, frame=(17.0, -4.5, 117.0, 57.84))
    for ring in (0.05, 0.1, 0.15, 0.2, 0.3):
        out = []
        for (x0, y0, x1, y1) in wins:
            tr = []
            fills.rough_edges(b, rp, 0, g, 0.3, trace=tr,  )
            n = sum(1 for t in tr if t[0] == 'own' and x0 <= t[1][0] <= x1 and y0 <= t[1][1] <= y1)
            out.append(n)
        print(path.split('/')[-1], 'ring', ring, 'own items flagged per window', out)
