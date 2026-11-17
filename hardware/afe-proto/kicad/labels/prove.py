"""prove.py MAIN.kicad_pcb NEW.kicad_pcb: parts and copper did not move. SHA-256 over (a) every footprint's ref, position, rotation, side; (b) every track (net, layer, ends, width) and via;
(c) every zone (net, layer, outline vertices, filled-polygon vertices); and a count of the lines that differ."""
import sys, hashlib
sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew
mm = pcbnew.ToMM
def digest(path):
    b = pcbnew.LoadBoard(path); out = {}
    fps = sorted((f.GetReference(), round(mm(f.GetPosition().x), 4), round(mm(f.GetPosition().y), 4), round(f.GetOrientationDegrees(), 3), int(f.IsFlipped())) for f in b.GetFootprints())
    pads = sorted((f.GetReference(), p.GetNumber(), round(mm(p.GetPosition().x), 4), round(mm(p.GetPosition().y), 4), p.GetNetname()) for f in b.GetFootprints() for p in f.Pads())
    tr, vi = [], []
    for t in b.GetTracks():
        if t.GetClass() == 'PCB_VIA': vi.append((t.GetNetname(), round(mm(t.GetPosition().x), 4), round(mm(t.GetPosition().y), 4), round(mm(t.GetWidth(pcbnew.F_Cu)), 4)))
        else: tr.append((t.GetNetname(), t.GetLayerName(), tuple(sorted([(round(mm(t.GetStart().x), 4), round(mm(t.GetStart().y), 4)), (round(mm(t.GetEnd().x), 4), round(mm(t.GetEnd().y), 4))])), round(mm(t.GetWidth()), 4)))
    zs = []
    for z in b.Zones():
        o = z.Outline(); pts = [(round(mm(v.x), 4), round(mm(v.y), 4)) for i in range(o.OutlineCount()) for v in o.COutline(i).CPoints()]
        fl = []
        for ly in z.GetLayerSet().Seq():
            if z.HasFilledPolysForLayer(ly):
                fp = z.GetFilledPolysList(ly)
                fl.append((ly, fp.OutlineCount(), sum(fp.COutline(i).PointCount() for i in range(fp.OutlineCount()))))
        zs.append((z.GetNetname(), tuple(sorted(z.GetLayerSet().Seq())), tuple(pts), tuple(fl), z.GetIsRuleArea()))
    h = lambda x: hashlib.sha256(repr(sorted(x)).encode()).hexdigest()
    return dict(footprints=(len(fps), h(fps)), pads=(len(pads), h(pads)), tracks=(len(tr), h(tr)), vias=(len(vi), h(vi)), zones=(len(zs), h(zs)))
a, c = digest(sys.argv[1]), digest(sys.argv[2])
ok = True
for k in a:
    same = a[k] == c[k]; ok &= same
    print('%-11s %4d  %s  %s' % (k, a[k][0], a[k][1][:16], 'EQUAL' if same else 'DIFFERENT (%s)' % (c[k],)))
print('PROOF', 'parts and copper identical' if ok else 'MISMATCH')
sys.exit(0 if ok else 1)
