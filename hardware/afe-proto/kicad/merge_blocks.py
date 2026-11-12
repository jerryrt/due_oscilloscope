"""merge_blocks.py: merge per-block board copies into an integrator board.

USAGE
    python3.14 -I merge_blocks.py OUT.kicad_pcb [--base BASE.kicad_pcb] BLOCK=BOARD.kicad_pcb [BLOCK=BOARD ...]
    Each BOARD is a copy of the base (same netlist, same footprint UUIDs) that one block agent worked on.
    For each BLOCK, in the order given: fence_check's rules are applied first; a block board that moved a foreign part
    or changed copper outside its fences is REPORTED AND NOT MERGED (exit 1, the others still merge).  A clean block
    contributes (a) the position, rotation and designator text of every part it owns and (b) the tracks and vias wholly
    inside its fences; the base's own tracks and vias inside those fences are removed first.  Zones are the base's
    (refill the pour afterwards: route.py's pour(), or KiCad's Fill All Zones).
    Exit 0 = all merged, 1 = a block refused, 2 = bad input.

FOR ANOTHER BOARD (v1): edit CONFIG in fence_check.py (board path, transform, floorplan module with FENCES, hundreds
map, owner overrides); nothing here names a part, net or block.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fence_check as fc
from fence_check import pcb, C


KEEP = []


def clone(t, base, net):
    """a new track or via on `base` with t's geometry and the base's net item"""
    if t.GetClass() == 'PCB_VIA':
        v = pcb.PCB_VIA(base)
        v.SetPosition(t.GetPosition()); v.SetViaType(t.GetViaType())
        v.SetLayerPair(t.TopLayer(), t.BottomLayer())
        v.SetWidth(t.GetWidth(pcb.F_Cu)); v.SetDrill(t.GetDrillValue())
    else:
        v = pcb.PCB_TRACK(base)
        v.SetStart(t.GetStart()); v.SetEnd(t.GetEnd()); v.SetLayer(t.GetLayer()); v.SetWidth(t.GetWidth())
    v.SetNet(net)
    return v


def merge(base, orig, blocks):
    """blocks: {name: board}; mutates base; orig is an untouched copy of it; returns (merged names, report lines)"""
    rep, done = [], []
    rects = [(b, r) for b in fc.FENCES for r in fc.FENCES[b]]
    for i, (b1, r1) in enumerate(rects):                  # fences of different blocks must not overlap
        for b2, r2 in rects[i + 1:]:
            if b1 != b2 and r1[0] < r2[2] and r2[0] < r1[2] and r1[1] < r2[3] and r2[1] < r1[3]:
                rep.append(f'warning: fences of {b1} and {b2} overlap: {r1} / {r2}')
    netitems = {str(k): v for k, v in base.GetNetInfo().NetsByName().items()}
    fps = {f.GetReference(): f for f in base.GetFootprints()}
    for name, bb in blocks.items():
        bad = fc.check(name, bb, orig)
        if bad:
            rep += [f'{name}: REFUSED: {m}' for m in bad]
            continue
        bfp = {f.GetReference(): f for f in bb.GetFootprints()}
        for ref, f in fps.items():
            if fc.owner(ref) == name:
                g = bfp[ref]
                f.SetPosition(g.GetPosition()); f.SetOrientationDegrees(g.GetOrientationDegrees())
                f.Reference().SetPosition(g.Reference().GetPosition())
                f.Reference().SetTextAngle(g.Reference().GetTextAngle())
        for key, t, pts in fc.copper_items(base):
            if fc.in_fences(name, pts):
                base.Remove(t)
                KEEP.append(t)                       # a removed item must outlive its python wrapper (pcbnew SWIG)
        n = 0
        for key, t, pts in fc.copper_items(bb):
            if fc.in_fences(name, pts):
                base.Add(clone(t, base, netitems[str(t.GetNetname())]))
                n += 1
        rep.append(f'{name}: merged ({n} tracks/vias in its fences)')
        done.append(name)
    return done, rep


def main(argv):
    args, base_path, pairs = argv[1:], fc.C['BOARD'], {}
    if '--base' in args:
        k = args.index('--base')
        base_path = args[k + 1]
        del args[k:k + 2]
    if len(args) < 2 or any('=' not in a for a in args[1:]) or any(a.split('=')[0] not in fc.FENCES for a in args[1:]):
        print(__doc__)
        return 2
    out = args[0]
    for a in args[1:]:
        k, v = a.split('=', 1)
        pairs[k] = pcb.LoadBoard(v)
        KEEP.append(pairs[k])
    base = pcb.LoadBoard(base_path)
    orig = pcb.LoadBoard(base_path)                    # an untouched copy: every block is checked against the original
    done, rep = merge(base, orig, pairs)
    print('\n'.join(rep))
    base.Save(out)
    return 0 if len(done) == len(pairs) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
