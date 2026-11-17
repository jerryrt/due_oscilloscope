"""lockcheck.py LANES_BOARD FINAL_BOARD: LOCKS EXACT - every lane and guard track and via of stage0 is on the final board with the same net, layer, ends and width."""
import sys
sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew
mm = pcbnew.ToMM
def keys(path):
    b = pcbnew.LoadBoard(path); T = set(); V = set()
    for t in b.GetTracks():
        if t.GetClass() == 'PCB_VIA':
            p = t.GetPosition(); V.add((t.GetNetname(), round(mm(p.x), 3), round(mm(p.y), 3)))
        else:
            a, c = t.GetStart(), t.GetEnd()
            T.add((t.GetNetname(), t.GetLayerName(), tuple(sorted([(round(mm(a.x), 3), round(mm(a.y), 3)), (round(mm(c.x), 3), round(mm(c.y), 3))])), round(mm(t.GetWidth()), 3)))
    return T, V
T0, V0 = keys(sys.argv[1]); T1, V1 = keys(sys.argv[2])
mt = sorted(T0 - T1); mv = sorted(V0 - V1)
print('LOCKS EXACT: tracks %d/%d, vias %d/%d %s' % (len(T0) - len(mt), len(T0), len(V0) - len(mv), len(V0), 'OK' if not mt and not mv else 'MISSING ' + str((mt[:3], mv[:3]))))
