import sys, math
sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew
b = pcbnew.LoadBoard('/work/hardware/afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pcb')
mm = pcbnew.ToMM
def X(v): return round(mm(v) - 50.0, 3)
def Y(v): return round(150.0 - mm(v), 3)
fps = {f.GetReference(): f for f in b.GetFootprints()}
mh = fps['MH602']; c = mh.GetPosition(); cx, cy = X(c.x), Y(c.y)
hole = [p for p in mh.Pads()][0]
print('MH602 centre', cx, cy, 'hole drill', mm(hole.GetDrillSize().x), 'pad size', mm(hole.GetSize().x), 'attr', hole.GetAttribute())
def courtyard(f):
    bb = f.GetCourtyard(pcbnew.F_CrtYd).BBox(); return (X(bb.GetLeft()), Y(bb.GetBottom()), X(bb.GetRight()), Y(bb.GetTop()))
print('MH602 courtyard', courtyard(mh))
for r in ('J605', 'J607'):
    f = fps[r]; print(r, 'at', X(f.GetPosition().x), Y(f.GetPosition().y), 'rot', f.GetOrientationDegrees(), 'courtyard', courtyard(f))
    best = []
    for p in f.Pads():
        pp = p.GetPosition(); d = math.hypot(X(pp.x) - cx, Y(pp.y) - cy)
        best.append((d, p.GetNumber(), X(pp.x), Y(pp.y), mm(p.GetSize().x), mm(p.GetSize().y), mm(p.GetDrillSize().x)))
    best.sort(); print('  nearest pads (centre dist, pin, x, y, w, h, drill):', best[:3])
    # body: F.Fab / silk extents
    xs = []
    for g in f.GraphicalItems():
        if g.GetLayer() in (pcbnew.F_Fab, pcbnew.F_SilkS):
            bb = g.GetBoundingBox(); xs.append((g.GetLayerName(), X(bb.GetLeft()), Y(bb.GetBottom()), X(bb.GetRight()), Y(bb.GetTop())))
    fab = [t for t in xs if t[0] == 'F.Fab']
    if fab: print('  F.Fab extent', min(t[1] for t in fab), min(t[2] for t in fab), max(t[3] for t in fab), max(t[4] for t in fab))
    sl = [t for t in xs if t[0] == 'F.SilkS']
    if sl: print('  F.SilkS extent', min(t[1] for t in sl), min(t[2] for t in sl), max(t[3] for t in sl), max(t[4] for t in sl))
    # hole-to-copper clearance: nearest pad edge to the hole circle
    for p in f.Pads():
        pp = p.GetPosition(); w, h = mm(p.GetSize().x), mm(p.GetSize().y)
        dx = max(abs(X(pp.x) - cx) - w / 2, 0); dy = max(abs(Y(pp.y) - cy) - h / 2, 0); d = math.hypot(dx, dy) - mm(hole.GetDrillSize().x) / 2
        if d < 3: print('  pad', p.GetNumber(), 'copper edge to hole wall', round(d, 3))
