"""python3 movehash.py BOARD [BOARD2]  (in the PCB image): a hash of everything that is not silk: every footprint's reference, layer, position and rotation, every track
(segment and arc), via and zone (net, layer, geometry, outline). With two boards it prints EQUAL or the categories that differ. Parts and copper must not move."""
import sys, hashlib, pcbnew
def digest(path):
    b = pcbnew.LoadBoard(path); out = {}
    def h(lines): return hashlib.sha256('\n'.join(sorted(lines)).encode()).hexdigest()[:16], len(lines)
    out['footprints'] = h(['%s|%d|%d|%d|%.3f' % (f.GetReference(), f.GetPosition().x, f.GetPosition().y, f.GetLayer(), f.GetOrientationDegrees()) for f in b.GetFootprints()])
    out['pads'] = h(['%s.%s|%s|%d|%d' % (f.GetReference(), p.GetNumber(), p.GetNetname(), p.GetPosition().x, p.GetPosition().y) for f in b.GetFootprints() for p in f.Pads()])
    seg, via = [], []
    for t in b.GetTracks():
        if t.GetClass() == 'PCB_VIA': via.append('%s|%d|%d|%d|%d' % (t.GetNetname(), t.GetPosition().x, t.GetPosition().y, t.GetWidth(), t.GetDrill()))
        else: seg.append('%s|%s|%d|%d|%d|%d|%d|%d' % (t.GetClass(), t.GetNetname(), t.GetLayer(), t.GetStart().x, t.GetStart().y, t.GetEnd().x, t.GetEnd().y, t.GetWidth()))
    out['tracks'] = h(seg); out['vias'] = h(via)
    z = []
    for zone in b.Zones():
        o = zone.Outline(); pts = [(o.CVertex(i).x, o.CVertex(i).y) for i in range(o.FullPointCount())]
        z.append('%s|%d|%s' % (zone.GetNetname(), zone.GetLayer(), pts))
    out['zones'] = h(z)
    return out
a = digest(sys.argv[1])
for k, v in a.items(): print(k, v[0], v[1])
if len(sys.argv) > 2:
    c = digest(sys.argv[2]); bad = [k for k in a if a[k] != c[k]]
    print('EQUAL' if not bad else 'DIFFERENT: ' + ', '.join(bad))
