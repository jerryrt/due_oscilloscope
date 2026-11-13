"""VNEG split at R410: the pads beyond it (U301.4, C303.1, TP405.1, R410.2) go on /VNEG_O; with --tracks every VNEG track and via too
(an AWG-block board, whose only VNEG copper is beyond R410)"""
import sys
import pcbnew
src, out = sys.argv[1:3]
b = pcbnew.LoadBoard(src)
if not b.FindNet('/VNEG_O'):
    ni = pcbnew.NETINFO_ITEM(b, '/VNEG_O')
    b.Add(ni)
    ni.thisown = False
no = b.FindNet('/VNEG_O')
for ref, pin in (('U301', '4'), ('C303', '1'), ('TP405', '1'), ('R410', '2')):
    for pad in b.FindFootprintByReference(ref).Pads():
        if pad.GetNumber() == pin:
            pad.SetNet(no)
n = 0
if '--tracks' in sys.argv:
    for t in b.GetTracks():
        if t.GetNetname() == '/VNEG':
            t.SetNet(no)
            n += 1
b.Save(out)
print('saved', out, 'retagged tracks', n)
