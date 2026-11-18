"""handroute.py ROUTES BOARD [OUT]: hand-made copper edits of one board, from a table (pcbtools/handroutes_v1.py).

ROUTES is a module of `ROUTES = [dict(net=..., why=..., rm=[((x0, y0), (x1, y1)), ...], add=[(width, [(x, y), ...]), ...]), ...]` in Due mm on F.Cu: every `rm` segment of that net (matched by its two
end points, either way round, within 2 um) is removed, and every `add` polyline becomes segments of that width. A segment that is not found is an error: a table that no longer matches the board
does not apply half of itself. Only tracks change: no part, pad or via moves. Run in the PCB image from hardware/afe-proto; the board's project file is restored by the caller (the editor rewrites it).
"""
import importlib
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..', '..', 'pcbkit'), os.path.join(HERE, '..')]
sys.path.append('/usr/lib/python3/dist-packages')
from pcbkit import board as kb
from pcbtools.editor import edit
from pcbtools.frame import FRAME


def apply(path, out, routes):
    b = kb.read_board(path, {'FRAME': FRAME})
    names = [n.lstrip('/') for n in b.nets]
    remove = []
    vrm, vadd = [], []
    for r in routes:
        for (vx, vy) in r.get('vias_rm', ()):
            hit = [k for k in range(len(b.v_x)) if abs(b.v_x[k] - vx) < 2e-3 and abs(b.v_y[k] - vy) < 2e-3]
            if len(hit) != 1:
                raise SystemExit('%s: via (%s, %s) matches %d vias, not one' % (r.get('why', ''), vx, vy, len(hit)))
            vrm.append(int(b.v_idx[hit[0]]))
        vadd += [(r['net'], x, y) for x, y in r.get('vias_add', ())]
    for r in routes:
        net = r['net'].lstrip('/')
        for ent in r.get('rm', ()):
            a, c = ent[0], ent[1]
            every = len(ent) > 2 and ent[2] == 'all'          # identical duplicates (the old copper has some) all go
            hit = [k for k in range(len(b.s_x0)) if b.s_layer[k] == 0 and names[int(b.s_net[k])] == net and (
                (abs(b.s_x0[k] - a[0]) < 2e-3 and abs(b.s_y0[k] - a[1]) < 2e-3 and abs(b.s_x1[k] - c[0]) < 2e-3 and abs(b.s_y1[k] - c[1]) < 2e-3) or
                (abs(b.s_x0[k] - c[0]) < 2e-3 and abs(b.s_y0[k] - c[1]) < 2e-3 and abs(b.s_x1[k] - a[0]) < 2e-3 and abs(b.s_y1[k] - a[1]) < 2e-3))]
            if (len(hit) != 1 and not every) or not hit:
                raise SystemExit('%s: segment %s-%s of %s matches %d tracks, not one (add "all" to remove duplicates)' % (r.get('why', ''), a, c, net, len(hit)))
            remove += [int(b.s_idx[k]) for k in hit]
    with edit(path, out) as e:
        e.remove_tracks(remove)
        e.remove_vias(vrm)
        for net, x, y in vadd:
            e.add_vias(net, [x], [y], 0.6, 0.3)
        for r in routes:
            for w, pts in r.get('add', ()):
                for p, q in zip(pts, pts[1:]):
                    e.add_tracks(r['net'], 'F', p[0], p[1], q[0], q[1], w)
        e.fill_zones()
    return len(remove), sum(len(pts) - 1 for r in routes for _, pts in r.get('add', ()))


if __name__ == '__main__':
    mod = importlib.import_module('pcbtools.' + sys.argv[1])
    path = sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else path
    n, m = apply(path, out, mod.ROUTES)
    print('%d segments removed, %d added' % (n, m))
