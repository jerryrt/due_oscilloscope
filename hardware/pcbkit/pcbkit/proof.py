"""Nothing moved: hashes of footprints, pads, tracks, vias and zones, and a netlist comparison.

    python3 -m pcbkit.proof BOARD [BOARD2]       the digest of one board, or EQUAL / the categories that differ between two (exit 1 on a difference)

digest(path) -> {category: (count, sha256-prefix)} over exact integer nanometres:
  footprints  reference, layer, position, orientation
  pads        owner, pad number, net, position
  tracks      class (segment or arc), net, layer, ends (and the mid point of an arc), width
  vias        net, position, width, drill
  zones       net, layers, outline vertices, rule-area flag (the filled polygons are not part of it: a fill is recomputed, a move is not)
netdiff(path_a, path_b) -> [str] differences of the pad-to-net map (a part or pad on one side only, a pad on another net): the netlist comparison.
The two earlier scripts (prove.py rounded to 4 decimals and read the fill; movehash.py used nanometres) are this one: nanometres, no fill."""
import hashlib, sys
sys.path.append('/usr/lib/python3/dist-packages')

CATEGORIES = ('footprints', 'pads', 'tracks', 'vias', 'zones')


def _h(lines):
    return len(lines), hashlib.sha256('\n'.join(sorted(lines)).encode()).hexdigest()[:16]


def digest(path):
    import pcbnew
    b = pcbnew.LoadBoard(path)
    out = {}
    out['footprints'] = _h(['%s|%d|%d|%d|%.3f' % (f.GetReference(), f.GetPosition().x, f.GetPosition().y, f.GetLayer(), f.GetOrientationDegrees()) for f in b.GetFootprints()])
    out['pads'] = _h(['%s.%s|%s|%d|%d' % (f.GetReference(), p.GetNumber(), p.GetNetname(), p.GetPosition().x, p.GetPosition().y) for f in b.GetFootprints() for p in f.Pads()])
    seg, via = [], []
    for t in b.GetTracks():
        if t.GetClass() == 'PCB_VIA':
            via.append('%s|%d|%d|%d|%d' % (t.GetNetname(), t.GetPosition().x, t.GetPosition().y, t.GetWidth(), t.GetDrill()))
        else:
            mid = (t.GetMid().x, t.GetMid().y) if t.GetClass() == 'PCB_ARC' else ()
            seg.append('%s|%s|%d|%d|%d|%d|%d|%d|%s' % (t.GetClass(), t.GetNetname(), t.GetLayer(), t.GetStart().x, t.GetStart().y, t.GetEnd().x, t.GetEnd().y, t.GetWidth(), mid))
    out['tracks'], out['vias'] = _h(seg), _h(via)
    z = []
    for zone in b.Zones():
        o = zone.Outline()
        pts = [(o.CVertex(i).x, o.CVertex(i).y) for i in range(o.FullPointCount())]
        z.append('%s|%s|%s|%s' % (zone.GetNetname(), sorted(zone.GetLayerSet().Seq()), pts, zone.GetIsRuleArea()))
    out['zones'] = _h(z)
    return out


def compare(a, b):
    """[] when two digests are equal, else the categories that differ"""
    return [k for k in CATEGORIES if a[k] != b[k]]


def pad_nets(path):
    import pcbnew
    b = pcbnew.LoadBoard(path)
    return {(f.GetReference(), str(p.GetNumber())): p.GetNetname() for f in b.GetFootprints() for p in f.Pads()}


def netdiff(path_a, path_b):
    """differences of the pad-to-net maps of two boards, as short strings ([] when identical)"""
    a, b = pad_nets(path_a), pad_nets(path_b)
    bad = []
    for k in sorted(set(a) - set(b)):
        bad.append('%s.%s only in %s' % (k[0], k[1], path_a))
    for k in sorted(set(b) - set(a)):
        bad.append('%s.%s only in %s' % (k[0], k[1], path_b))
    for k in sorted(set(a) & set(b)):
        if a[k] != b[k]:
            bad.append('%s.%s: %r against %r' % (k[0], k[1], a[k], b[k]))
    return bad


def main(argv):
    a = digest(argv[0])
    for k in CATEGORIES:
        print(k, a[k][0], a[k][1])
    if len(argv) > 1:
        c = digest(argv[1])
        bad = compare(a, c)
        nd = netdiff(argv[0], argv[1])
        print('EQUAL' if not bad else 'DIFFERENT: ' + ', '.join(bad))
        print('netdiff', len(nd))
        for s in nd[:20]:
            print(' ', s)
        return 1 if (bad or nd) else 0
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
