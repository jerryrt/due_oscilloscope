"""Read the board back through pcbnew and print what check.py needs, as JSON.

    /usr/bin/python3.14 -I hardware/afe-proto/kicad/pcb_dump.py afe-proto.kicad_pcb

pads: [ref, pad number, net without the leading '/'];  footprints: ref, whether every pad lies inside the outline;
header_err_mm: the largest distance of a Due-header pad from its V03 position (due-header-table.md section 2).
"""
import json
import math
import sys

import pcbnew as pcb

OX, OY = 50.0, 150.0
X0, X1, Y0, Y1 = 17.0, 117.0, 0.0, 53.34


def v03():
    """(ref, pin) -> (x, Yup) for every pin of the seven Due headers."""
    out = {}
    rows = {'J601': (27.94, 2.54, 1, 8), 'J602': (50.80, 2.54, 1, 8), 'J603': (73.66, 2.54, 1, 8),
            'J604': (63.50, 50.80, -1, 8), 'J605': (68.58, 50.80, 1, 8), 'J606': (41.656, 50.80, -1, 10)}
    for ref, (x, y, d, n) in rows.items():
        for k in range(n):
            out[(ref, str(k + 1))] = (x + d * 2.54 * k, y)
    for k in range(36):
        out[('J607', str(k + 1))] = (93.98 if k % 2 == 0 else 96.52, 50.80 - 2.54 * (k // 2))
    return out


def main(path):
    b = pcb.LoadBoard(path)
    pads, fps = [], []
    want = v03(); err = 0.0; seen = 0
    for f in b.GetFootprints():
        ref = f.GetReference()
        inside = True
        for p in f.Pads():
            x, y = pcb.ToMM(p.GetPosition().x) - OX, OY - pcb.ToMM(p.GetPosition().y)
            inside &= X0 <= x <= X1 and Y0 <= y <= Y1
            pads.append([ref, p.GetNumber(), p.GetNetname().lstrip('/')])
            if (ref, p.GetNumber()) in want:
                wx, wy = want[(ref, p.GetNumber())]
                err = max(err, math.hypot(x - wx, y - wy)); seen += 1
        fps.append(dict(ref=ref, inside=inside))
    if seen != len(want):
        err = float('inf')       # a header pad missing is a failure, not a pass on fewer pads
    print(json.dumps(dict(pads=pads, footprints=fps, header_err_mm=err, header_pads=seen)))


if __name__ == '__main__':
    main(sys.argv[1])
