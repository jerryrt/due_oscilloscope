"""fence_check.py: reject a block board that moved a part or changed copper outside its own block.

USAGE
    python3.14 -I fence_check.py BLOCK BLOCK_BOARD.kicad_pcb [BASE_BOARD.kicad_pcb]
    BLOCK is a key of FENCES (POWER, REFCAL, SCOPE, AWG); BASE defaults to the baseline BOARD below.
    Exit 0 = clean, 1 = violations (each printed), 2 = bad input.
    A block board is a copy of the baseline (same netlist, same footprint UUIDs) in which one block agent worked.
    Rules: (1) every part that does not belong to BLOCK has the position, rotation and side it has in the base;
    (2) the set of tracks and vias that are not wholly inside one of BLOCK's fences is identical to the base's
    (copper inside the fence is the agent's to change; a track crossing a fence edge counts as outside).
    Zones and silk are not compared (the integrator refills the pour).
    merge_blocks.py imports everything from here, so this table is the only one.

FOR ANOTHER BOARD (v1) change only the CONFIG table below: the board path, the transform, the floorplan module that
holds FENCES = {block: [(x0, y0, x1, y1), ...]} in the board's own mm, the hundreds-digit map, and OWNER_OVERRIDE.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew as pcb   # noqa: E402

# ----------------------------------------------------------------------------------------------- CONFIG (one table)
CONFIG = dict(
    BOARD=os.path.join(HERE, 'afe-v2.kicad_pcb'),   # the baseline / integrator board
    FLOORPLAN='floorplan',                           # module with FENCES: {block: [(x0, y0, x1, y1), ...]}
    OX=50.0, OY=150.0,                               # as build_pcb.py: board_x = OX + x, board_y = OY - y (y up)
    # hundreds digit of a designator -> block (None: the edge parts nobody owns); SCOPE owns 1xx and 2xx
    HUNDREDS={'1': 'SCOPE', '2': 'SCOPE', '3': 'AWG', '4': 'POWER', '5': 'REFCAL', '6': None},
    OWNER_OVERRIDE={},                               # ref -> block, where the digit is wrong (BR1xx/BR2xx follow design.py)
    TOL_MM=0.001,                                    # position tolerance
)
# -----------------------------------------------------------------------------------------------------------------
C = CONFIG
FENCES = __import__(C['FLOORPLAN']).FENCES


def due(v):
    return (pcb.ToMM(v.x) - C['OX'], C['OY'] - pcb.ToMM(v.y))


def owner(ref):
    if ref in C['OWNER_OVERRIDE']:
        return C['OWNER_OVERRIDE'][ref]
    d = ''.join(ch for ch in ref if ch.isdigit())
    return C['HUNDREDS'].get(d[:1]) if len(d) >= 3 else None


def inside(pt, rect, pad=0.0):
    return rect[0] - pad <= pt[0] <= rect[2] + pad and rect[1] - pad <= pt[1] <= rect[3] + pad


def in_fences(block, pts):
    """True when every point lies in one and the same fence of the block"""
    return any(all(inside(p, r, 1e-6) for p in pts) for r in FENCES[block])


def part_state(f):
    x, y = due(f.GetPosition())
    return (round(x, 3), round(y, 3), round(f.GetOrientationDegrees() % 360, 2), int(f.GetLayer()))


def parts(board):
    return {f.GetReference(): part_state(f) for f in board.GetFootprints()}


def copper_items(board):
    """[(key, item, pts)]: key identifies a track or via exactly (net, layer, ends, width / diameter, drill) to 1 um"""
    out = []
    r = lambda v: round(v, 3)
    for t in board.GetTracks():
        if t.GetClass() == 'PCB_VIA':
            p = due(t.GetPosition())
            key = ('via', t.GetNetname(), r(p[0]), r(p[1]), r(pcb.ToMM(t.GetWidth(pcb.F_Cu))), r(pcb.ToMM(t.GetDrillValue())))
            out.append((key, t, [p]))
        else:
            a, b = due(t.GetStart()), due(t.GetEnd())
            a, b = sorted(((r(a[0]), r(a[1])), (r(b[0]), r(b[1]))))
            out.append((('trk', t.GetNetname(), int(t.GetLayer()), a, b, r(pcb.ToMM(t.GetWidth()))), t, [a, b]))
    return out


def outside_keys(board, block):
    return sorted(k for k, _, pts in copper_items(board) if not in_fences(block, pts))


def check(block, bboard, base):
    """list of violation strings"""
    bad = []
    pb, pa = parts(base), parts(bboard)
    for r in sorted(set(pb) | set(pa)):
        if owner(r) == block:
            continue
        if r not in pa or r not in pb:
            bad.append(f'{r}: part {"missing from the block board" if r not in pa else "not in the base"}')
        elif max(abs(pa[r][0] - pb[r][0]), abs(pa[r][1] - pb[r][1])) > C['TOL_MM'] or pa[r][2:] != pb[r][2:]:
            bad.append(f'{r} (belongs to {owner(r)}): moved {pb[r]} -> {pa[r]}')
    ob, oa = outside_keys(base, block), outside_keys(bboard, block)
    sb, sa = set(ob), set(oa)
    for k in sorted(sb - sa):
        bad.append(f'copper outside the {block} fence removed or changed: {k}')
    for k in sorted(sa - sb):
        bad.append(f'copper outside the {block} fence added or changed: {k}')
    if len(ob) != len(oa) and sb == sa:
        bad.append(f'copper outside the {block} fence: duplicate items differ ({len(ob)} vs {len(oa)})')
    return bad


def main(argv):
    if len(argv) not in (3, 4) or argv[1] not in FENCES:
        print(__doc__)
        return 2
    base = pcb.LoadBoard(argv[3] if len(argv) == 4 else C['BOARD'])
    blk = pcb.LoadBoard(argv[2])
    if base is None or blk is None:
        print('cannot load a board')
        return 2
    bad = check(argv[1], blk, base)
    for b in bad:
        print('FAIL', b)
    print(f'{argv[1]}: {"clean" if not bad else str(len(bad)) + " violation(s)"}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
