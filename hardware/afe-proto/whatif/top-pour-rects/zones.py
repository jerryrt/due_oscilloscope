import sys
sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew
for p in sys.argv[1:]:
    b = pcbnew.LoadBoard(p)
    print(p)
    for z in b.Zones():
        bb = z.GetBoundingBox()
        print(' ', z.GetZoneName() or '-', b.GetLayerName(z.GetLayer()), 'rule' if z.GetIsRuleArea() else z.GetNetname(), z.GetNumCorners() if hasattr(z,'GetNumCorners') else '', round(bb.GetLeft()/1e6,2), round(bb.GetTop()/1e6,2), round(bb.GetRight()/1e6,2), round(bb.GetBottom()/1e6,2), 'clr', z.GetLocalClearance()/1e6, 'w', z.GetMinThickness()/1e6)
    nv = sum(1 for t in b.GetTracks() if t.GetClass()=='PCB_VIA' and t.GetNetname().endswith('GND'))
    print('  GND vias', nv)
