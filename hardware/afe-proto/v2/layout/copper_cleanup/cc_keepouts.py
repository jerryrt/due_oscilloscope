"""pour keep-outs of our own, as data: cc_keepouts.py IN OUT

The fill step derives the no-pour areas of the top GND pour itself ('fillkeep', rebuilt every run), and where it leaves a bulge of pour that brings the pour edge nearer a protected node than the board of record
had it, no via placement moves it. A rule area named 'pourkeep' is the board's own and the fill step keeps it. Each entry: (name of the reason, [(x, y)] polygon in Due mm). The board's pour gaps
(LR-4: `pour_gap`) may not read smaller than on the board of record."""
import re
import sys
import uuid
sys.path[:0] = [__import__('os').path.dirname(__import__('os').path.abspath(__file__))]
from cc_normalize import top_blocks

FRAME = (50.0, 150.0)
KEEPOUTS = [
    # CH1_OUT's pour gap: a 0.5 mm bulge of the pour (x 85.5 to 86.0, y 32.9 to 34.5) east of U101.6 brought the pour edge 0.057 mm nearer the pad than the board of record (2.021 against 2.078 mm)
    ('bulge east of U101.6', [(85.3, 32.85), (86.05, 32.85), (86.05, 34.55), (85.3, 34.55)]),
]


def block(name, poly):
    pts = ' '.join('(xy %s %s)' % tuple(('%.6f' % v).rstrip('0').rstrip('.') for v in (FRAME[0] + x, FRAME[1] - y)) for x, y in poly)
    u = uuid.uuid5(uuid.NAMESPACE_URL, 'afe2-cc/pourkeep/' + name)
    return ('\n\t(zone\n\t\t(layer "F.Cu")\n\t\t(uuid "%s")\n\t\t(name "pourkeep")\n\t\t(hatch edge 0.5)\n\t\t(connect_pads\n\t\t\t(clearance 0)\n\t\t)\n\t\t(min_thickness 0.25)\n'
            '\t\t(keepout\n\t\t\t(tracks allowed)\n\t\t\t(vias allowed)\n\t\t\t(pads allowed)\n\t\t\t(copperpour not_allowed)\n\t\t\t(footprints allowed)\n\t\t)\n\t\t(placement\n\t\t\t(enabled no)\n\t\t\t(sheetname "")\n\t\t)\n'
            '\t\t(fill\n\t\t\t(thermal_gap 0.5)\n\t\t\t(thermal_bridge_width 0.5)\n\t\t\t(island_removal_mode 0)\n\t\t)\n\t\t(polygon\n\t\t\t(pts\n\t\t\t\t%s\n\t\t\t)\n\t\t)\n\t)' % (u, pts))


if __name__ == '__main__':
    t = open(sys.argv[1]).read()
    last = [(a, b) for a, b in top_blocks(t) if t[a + 1:b].split(None, 1)[0].split('\n')[0] == 'zone'][-1]
    t = t[:last[1]] + ''.join(block(n, p) for n, p in KEEPOUTS) + t[last[1]:]
    open(sys.argv[2], 'w').write(t)
    print('added', len(KEEPOUTS), 'pour keep-outs')
