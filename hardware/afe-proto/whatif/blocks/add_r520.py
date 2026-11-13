"""base_34b2e51 -> base: add the sense-bottom bridge R520 (0603 0R, a copy of R515's footprint) and move R512.1 to SNS_B_N"""
import sys
import pcbnew
src, out = sys.argv[1:3]
b = pcbnew.LoadBoard(src)
r = b.FindFootprintByReference('R515')
n = pcbnew.FOOTPRINT(r)
n.SetReference('R520')
n.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(50.0 + 47.0), pcbnew.FromMM(150.0 - 10.6)))
n.SetOrientationDegrees(0)
b.Add(n)
n.thisown = False
for name in ('/SNS_B_N',):
    ni = pcbnew.NETINFO_ITEM(b, name)
    b.Add(ni)
    ni.thisown = False
for pad in n.Pads():
    pad.SetNet(b.FindNet('/SNS_B' if pad.GetNumber() == '1' else '/SNS_B_N'))
for pad in b.FindFootprintByReference('R512').Pads():
    if pad.GetNumber() == '1':
        pad.SetNet(b.FindNet('/SNS_B_N'))
b.Save(out)
print('saved', out, [(p.GetNumber(), p.GetNetname()) for p in n.Pads()], [(p.GetNumber(), p.GetNetname()) for p in b.FindFootprintByReference('R512').Pads()])
