"""rule_areas.py BOARD X,Y ...: the rule areas of a board that contain each Due-mm point (not our own 'fillkeep'), with name, layers, what they forbid, and their extent"""
import sys
sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
pts = [tuple(map(float, a.split(','))) for a in sys.argv[2:]]
for z in b.Zones():
    if not z.GetIsRuleArea() or z.GetZoneName() == 'fillkeep':
        continue
    bb = z.GetBoundingBox()
    for (x, y) in pts:
        pt = pcbnew.VECTOR2I(pcbnew.FromMM(50 + x), pcbnew.FromMM(150 - y))
        if z.Outline().Contains(pt):
            print((x, y), repr(z.GetZoneName()), [b.GetLayerName(l) for l in z.GetLayerSet().Seq()], 'no tracks', z.GetDoNotAllowTracks(), 'no vias', z.GetDoNotAllowVias(), 'no pour', z.GetDoNotAllowZoneFills(),
                  'extent', round(pcbnew.ToMM(bb.GetLeft()) - 50, 2), round(150 - pcbnew.ToMM(bb.GetBottom()), 2), round(pcbnew.ToMM(bb.GetRight()) - 50, 2), round(150 - pcbnew.ToMM(bb.GetTop()), 2))
