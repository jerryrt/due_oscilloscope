"""AWG block onto the current baseline: AWG parts (hundreds 3) take their pose and reference-text pose from the old AWG block board,
and every track / via of the old board wholly inside an AWG fence is copied; /VNEG copper goes to /VNEG_O (R410 split)."""
import sys
import pcbnew
old_p, base_p, out = sys.argv[1:4]
FENCES = [(69.8, 4.4, 95.5, 19.4), (98.5, 0.6, 116.4, 15.5)]
mm = pcbnew.ToMM
FM = pcbnew.FromMM
old, b = pcbnew.LoadBoard(old_p), pcbnew.LoadBoard(base_p)


def due(p):
    return mm(p.x) - 50.0, 150.0 - mm(p.y)


def inside(x, y):
    return any(a <= x <= c and d <= y <= e for a, d, c, e in FENCES)


moved = 0
for f in old.GetFootprints():
    r = f.GetReference()
    digits = ''.join(c for c in r if c.isdigit())
    if not (len(digits) >= 3 and digits[0] == '3'):          # hundreds 3 (R305, TP301, ...): the prefix may be one or two letters
        continue
    g = b.FindFootprintByReference(r)
    if g is None:
        print('not in base:', r)
        continue
    g.SetPosition(f.GetPosition())
    g.SetOrientation(f.GetOrientation())
    if g.IsFlipped() != f.IsFlipped():
        g.Flip(g.GetPosition(), False)
    tx, ts = f.Reference(), g.Reference()
    ts.SetPosition(tx.GetPosition())
    ts.SetTextAngle(tx.GetTextAngle())
    ts.SetTextSize(tx.GetTextSize())
    ts.SetTextThickness(tx.GetTextThickness())
    ts.SetVisible(tx.IsVisible())
    moved += 1
nt = nv = 0
for t in old.GetTracks():
    net = str(t.GetNetname())
    net = '/VNEG_O' if net == '/VNEG' else net
    ni = b.FindNet(net)
    if t.GetClass() == 'PCB_VIA':
        x, y = due(t.GetPosition())
        if not inside(x, y):
            continue
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(t.GetPosition()); v.SetWidth(t.GetWidth(pcbnew.F_Cu)); v.SetDrill(t.GetDrill())
        v.SetNet(ni); v.SetViaType(t.GetViaType())
        b.Add(v); v.thisown = False; nv += 1
    else:
        (x0, y0), (x1, y1) = due(t.GetStart()), due(t.GetEnd())
        if not (inside(x0, y0) and inside(x1, y1)):
            continue
        s = pcbnew.PCB_TRACK(b)
        s.SetStart(t.GetStart()); s.SetEnd(t.GetEnd()); s.SetWidth(t.GetWidth()); s.SetLayer(t.GetLayer()); s.SetNet(ni)
        b.Add(s); s.thisown = False; nt += 1
b.Save(out)
print('AWG parts', moved, 'tracks', nt, 'vias', nv, '->', out)
