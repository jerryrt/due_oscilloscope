"""fin_c.py BASE ROUTED OUT : outside the REFCAL fence the copper is the base's, item for item (the SES round trip merges collinear
tracks and moves items by 1 um); inside, the routed board's. A routed track that crosses the fence edge is clipped to the fence."""
import sys
import pcbnew
base_p, src, out = sys.argv[1:4]
FM = pcbnew.FromMM
F = (44.5, 4.6, 64.5, 36.0)
X0, X1 = FM(F[0] + 50), FM(F[2] + 50)
Y0, Y1 = FM(150 - F[3]), FM(150 - F[1])           # KiCad y of the fence edges (y flipped)
TOL = 1000                                         # 1 um
def inside(x, y):
    return X0 - TOL <= x <= X1 + TOL and Y0 - TOL <= y <= Y1 + TOL
base = pcbnew.LoadBoard(base_p)
b = pcbnew.LoadBoard(src)
def clip(p, q):
    """segment p-q clipped to the fence rect, or None"""
    (x0, y0), (x1, y1) = p, q
    t0, t1 = 0.0, 1.0
    dx, dy = x1 - x0, y1 - y0
    for pp, qq in ((-dx, x0 - X0), (dx, X1 - x0), (-dy, y0 - Y0), (dy, Y1 - y0)):
        if pp == 0:
            if qq < 0: return None
        else:
            r = qq / pp
            if pp < 0: t0 = max(t0, r)
            else: t1 = min(t1, r)
    if t0 >= t1: return None
    return (round(x0 + t0 * dx), round(y0 + t0 * dy)), (round(x0 + t1 * dx), round(y0 + t1 * dy))
rm, add = [], []
nclip = nout = 0
for t in list(b.GetTracks()):
    if t.GetClass() == 'PCB_VIA':
        p = t.GetPosition()
        if not inside(p.x, p.y): rm.append(t)
        continue
    s, e = t.GetStart(), t.GetEnd()
    if inside(s.x, s.y) and inside(e.x, e.y):
        continue
    rm.append(t)
    c = clip((s.x, s.y), (e.x, e.y))
    if c and (c[0] != c[1]) and abs(c[0][0] - c[1][0]) + abs(c[0][1] - c[1][1]) > 2000:
        add.append((t.GetNet(), t.GetLayer(), t.GetWidth(), c)); nclip += 1
    else:
        nout += 1
for t in rm: b.RemoveNative(t)
for net, lay, w, (p, q) in add:
    s = pcbnew.PCB_TRACK(b); s.SetStart(pcbnew.VECTOR2I(*p)); s.SetEnd(pcbnew.VECTOR2I(*q)); s.SetWidth(w); s.SetLayer(lay); s.SetNet(net)
    b.Add(s); s.thisown = False
ncopy = 0
for t in base.GetTracks():
    if t.GetClass() == 'PCB_VIA':
        p = t.GetPosition()
        if inside(p.x, p.y): continue
        v = pcbnew.PCB_VIA(b); v.SetPosition(p); v.SetWidth(t.GetWidth(pcbnew.F_Cu)); v.SetDrill(t.GetDrill()); v.SetViaType(t.GetViaType())
        v.SetNet(b.FindNet(t.GetNetname())); b.Add(v); v.thisown = False; ncopy += 1
    else:
        s, e = t.GetStart(), t.GetEnd()
        if inside(s.x, s.y) and inside(e.x, e.y): continue
        n = pcbnew.PCB_TRACK(b); n.SetStart(s); n.SetEnd(e); n.SetWidth(t.GetWidth()); n.SetLayer(t.GetLayer()); n.SetNet(b.FindNet(t.GetNetname()))
        b.Add(n); n.thisown = False; ncopy += 1
print('removed', len(rm), 'clipped-kept', nclip, 'dropped-outside', nout, 'base items restored', ncopy)
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard(out, b)
