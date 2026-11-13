"""Refill every zone of the integrated v2 board with pcbnew, so the fills honour the board's current design rules (the project's
min_copper_edge_clearance, 0.45 mm, in the .kicad_pro next to the board). Idempotent: refilling a filled board gives the same fills.
Only the zones' filled polygons change; nothing else is edited (the saver rewrites the file, so compare with BoardArrays).

    python3 v2/layout/refill_zones.py BOARD.kicad_pcb [--write OUT.kicad_pcb]      (in the PCB image; default: in place)

Prints each zone's own clearance / min thickness / edge-related settings, because a zone's own value can override the project's.
"""
import os
import re
import sys
import tempfile

import pcbnew


def _zones(text):
    """{(net, layer-or-layers, name): (start, end, filled_start)} of each top-level zone block; filled_start is where its
    filled_polygon blocks begin (None when it has none)"""
    out = {}
    for m in re.finditer(r'\n\t\(zone\n.*?\n\t\)(?=\n)', text, re.S):
        blk = m.group(0)
        key = ((re.search(r'\(net "([^"]*)"\)', blk) or [0, ''])[1], (re.search(r'\((layers? "[^)]*)\)', blk) or [0, ''])[1],
               (re.search(r'\(name "([^"]*)"\)', blk) or [0, ''])[1])
        f = blk.find('\n\t\t(filled_polygon')
        out[key] = (m.start(), m.end(), None if f < 0 else m.start() + f)
    return out


def splice_fills(old, new):
    """`old` with each zone's filled_polygon blocks taken from `new` (the saver reformats the whole file and reorders the zones;
    only the fills are wanted, so every other byte of `old` is kept)"""
    zo, zn = _zones(old), _zones(new)
    assert set(zo) == set(zn), (sorted(zo), sorted(zn))
    for key in sorted(zo, key=lambda k: -zo[k][0]):               # from the end, so offsets stay valid
        s, e, f = zo[key]
        ns, ne, nf = zn[key]
        fills = '' if nf is None else new[nf:ne - 3]
        old = old[:(f if f is not None else e - 3)] + fills + old[e - 3:]
    return old


def main(argv):
    path = argv[0]
    out = argv[argv.index('--write') + 1] if '--write' in argv else path
    pro = os.path.splitext(path)[0] + '.kicad_pro'          # the saver rewrites the project file too, dropping what it does not model
    pro_text = open(pro, 'rb').read() if os.path.exists(pro) else None
    b = pcbnew.LoadBoard(path)
    ds = b.GetDesignSettings()
    print('project min copper-to-edge: %.4f mm   min clearance: %.4f mm' % (pcbnew.ToMM(ds.m_CopperEdgeClearance), pcbnew.ToMM(ds.m_MinClearance)))
    zs = list(b.Zones())
    for z in zs:
        print('zone %-8s net %-8s layer %-6s own clearance %.3f  min thickness %.3f  priority %d  keepout %s' % (
            z.GetZoneName() or '-', z.GetNetname(), b.GetLayerName(z.GetFirstLayer()), pcbnew.ToMM(z.GetLocalClearance()),
            pcbnew.ToMM(z.GetMinThickness()), z.GetAssignedPriority(), z.GetIsRuleArea()))
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    with tempfile.TemporaryDirectory() as d:
        tmp = os.path.join(d, os.path.basename(path))
        b.Save(tmp)
        new = open(tmp).read()
    if pro_text is not None:
        open(pro, 'wb').write(pro_text)
    merged = splice_fills(open(path).read(), new)
    open(out, 'w').write(merged)
    print('refilled %d zones -> %s' % (len(zs), out))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
