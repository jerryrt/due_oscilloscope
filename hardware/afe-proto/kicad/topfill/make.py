"""make.py IN OUT: one F.Cu GND zone over the board, keeping 0.6 mm from the 8 hi-Z divider nets (LR-3's beside rule) and 0.5 mm from the AWG inverting node (LR-4's pour gap),
no islands, and GND stitching vias on a grid in the open fill, kept out of the analog fences (LR-1) and out of every courtyard. Parts, pads and tracks are untouched."""
import sys, math, json
sys.path.insert(0, '.'); sys.path.append('/usr/lib/python3/dist-packages')
import numpy as np
import pcbnew
from pcbkit import board as KB
from pcbtools.frame import FRAME
from pcbtools.editor import edit
from pcbtools.boards import v1 as C
inp, outp = sys.argv[1], sys.argv[2]
PITCH = float(sys.argv[3]) if len(sys.argv) > 3 else 5.08
KEEP = {n: 0.6 for n in C.HIZ}; KEEP.update({n: 0.5 for n in C.POUR_NODES})
b = KB.read_board(inp, FRAME)
bd = pcbnew.LoadBoard(inp); mm = pcbnew.ToMM
def duebox(bb):
    x0, y0 = KB.to_frame(mm(bb.GetX()), mm(bb.GetY()), FRAME); x1, y1 = KB.to_frame(mm(bb.GetRight()), mm(bb.GetBottom()), FRAME)
    return (float(min(x0, x1)), float(min(y0, y1)), float(max(x0, x1)), float(max(y0, y1)))
polys = []          # keep-away polygons, Due mm
for t in bd.GetTracks():
    if t.GetClass() == 'PCB_VIA' or t.GetLayer() != pcbnew.F_Cu: continue
    n = t.GetNetname()
    if n not in KEEP: continue
    d = KEEP[n]; w = mm(t.GetWidth())
    p = KB.to_frame(mm(t.GetStart().x), mm(t.GetStart().y), FRAME); q = KB.to_frame(mm(t.GetEnd().x), mm(t.GetEnd().y), FRAME)
    p = (float(p[0]), float(p[1])); q = (float(q[0]), float(q[1])); L = math.hypot(q[0] - p[0], q[1] - p[1])
    ux, uy = ((q[0] - p[0]) / L, (q[1] - p[1]) / L) if L > 1e-9 else (1.0, 0.0); nx, ny = -uy, ux; h = w / 2 + d
    polys.append((n, [(p[0] - ux * d + nx * h, p[1] - uy * d + ny * h), (q[0] + ux * d + nx * h, q[1] + uy * d + ny * h), (q[0] + ux * d - nx * h, q[1] + uy * d - ny * h), (p[0] - ux * d - nx * h, p[1] - uy * d - ny * h)]))
for fp in bd.GetFootprints():
    for pd in fp.Pads():
        n = pd.GetNetname()
        if n in KEEP:
            x0, y0, x1, y1 = duebox(pd.GetBoundingBox()); d = KEEP[n]
            polys.append((n, [(x0 - d, y0 - d), (x1 + d, y0 - d), (x1 + d, y1 + d), (x0 - d, y1 + d)]))
print('keep-away polygons', len(polys), {n: sum(1 for q in polys if q[0] == n) for n in KEEP})
with edit(inp, outp) as e:
    for k, (n, pts) in enumerate(polys):
        z = e.pcb.ZONE(e.b); z.SetIsRuleArea(True)
        ls = e.pcb.LSET(); ls.AddLayer(e._layer('F')); z.SetLayerSet(ls)
        z.SetDoNotAllowTracks(False); z.SetDoNotAllowVias(False); z.SetDoNotAllowZoneFills(True); z.SetDoNotAllowPads(False); z.SetDoNotAllowFootprints(False)
        z.SetZoneName('keepaway ' + n[1:])
        for px, py in pts: z.AppendCorner(e._pt(px, py), -1)
        e.b.Add(z); e._give(z)
    zone = e.pour('GND', 'F')
    zone.SetZoneName('F.Cu GND')
    # stitching vias on a grid in the open fill
    ps = zone.GetFilledPolysList(e._layer('F'))
    def inside(x, y):
        kx, ky = KB.from_frame(x, y, FRAME); return ps.Contains(pcbnew.VECTOR2I(pcbnew.FromMM(float(kx)), pcbnew.FromMM(float(ky))))
    fences = [r for B in C.ANALOG_FENCE for r in C.OUTLINE[B]]
    court = [(float(b.fp_cx0[i]), float(b.fp_cy0[i]), float(b.fp_cx1[i]), float(b.fp_cy1[i])) for i in range(len(b.fp_ref)) if not np.isnan(b.fp_cx0[i])]
    silk = [duebox(d.GetBoundingBox()) for d in bd.GetDrawings() if d.GetLayer() == pcbnew.F_SilkS] + [duebox(it.GetBoundingBox()) for fp in bd.GetFootprints() for it in fp.GraphicalItems() if it.GetLayer() == pcbnew.F_SilkS]
    vx = [float(x) for x in b.v_x]; vy = [float(y) for y in b.v_y]
    ang = np.linspace(0, 2 * math.pi, 9)[:-1]; RING = 0.7
    pts = []
    for gx in np.arange(C.DUE_RECT[0] + 2.0, C.DUE_RECT[2] - 1.0, PITCH):
        for gy in np.arange(C.DUE_RECT[1] + 2.0, C.DUE_RECT[3] - 1.0, PITCH):
            if any(r[0] - 0.5 <= gx <= r[2] + 0.5 and r[1] - 0.5 <= gy <= r[3] + 0.5 for r in fences): continue
            if any(c[0] - 0.3 <= gx <= c[2] + 0.3 and c[1] - 0.3 <= gy <= c[3] + 0.3 for c in court): continue
            if any(math.hypot(gx - a, gy - c) < 1.0 for a, c in zip(vx, vy)): continue
            if any(q[0] - 0.5 <= gx <= q[2] + 0.5 and q[1] - 0.5 <= gy <= q[3] + 0.5 for q in silk): continue          # no via under silk: the identity block, block outlines and names, part outlines
            if not (inside(gx, gy) and all(inside(gx + RING * math.cos(a), gy + RING * math.sin(a)) for a in ang)): continue
            pts.append((gx, gy))
    print('stitching vias', len(pts), 'pitch', PITCH)
    if pts:
        e.add_vias('GND', [p[0] for p in pts], [p[1] for p in pts], 0.6, 0.3)
    e.fill_zones()
json.dump(pts, open(outp.replace('.kicad_pcb', '_stitch.json'), 'w'))
