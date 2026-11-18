"""fill_clean.py BOARD [OUT] [--top-width W] [--bottom-width W] [--clearance C] [--spoke S] [--gap G] [--big A]: the GND pours of a board as the owner wants them, and a report.

  - the top GND zone connects SMD GND pads by thermal reliefs (gap G, spoke S), the bottom plane stays solid;
  - the minimum fill width is W on the top and W on the bottom (KiCad then drops what is narrower), the zones' clearance C;
  - a pour of A mm2 or more that the minimum width would leave hanging (cut off from every pad, via and track of the net) is kept: GND stitching vias go into it, one per 100 mm2 at least 8 mm
    apart, clear of courtyards; the rest of such pours are dropped with the island removal as before.
Run in the PCB image from hardware/afe-proto. Prints each stitched pour with its area and via count, and the pours dropped (count and area). With OUT the board is written (zones refilled)."""
from __future__ import annotations

import math
import os
import sys

import numpy as np
from scipy import ndimage as ndi

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..', '..', 'pcbkit'), os.path.join(HERE, '..')]
sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew
from pcbkit import board as kb, fills
from pcbtools.frame import FRAME




def set_zones(b, top_w, bot_w, clearance, spoke, gap, island):
    for z in b.Zones():
        if z.GetIsRuleArea():
            continue
        top = z.GetLayer() == pcbnew.F_Cu
        z.SetMinThickness(pcbnew.FromMM(top_w if top else bot_w))
        z.SetLocalClearance(pcbnew.FromMM(clearance))
        if top:
            z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
            z.SetThermalReliefGap(pcbnew.FromMM(gap))
            z.SetThermalReliefSpokeWidth(pcbnew.FromMM(spoke))
        else:
            z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        z.SetIslandRemovalMode(island)


def islands(path, big, ppmm=40.0):
    """the top GND pour as the board file has it, found with island removal off: [(area, (cx, cy), connected)] for every part of it, and the raster"""
    b = kb.read_board(path, {'FRAME': FRAME})
    g = [i for i, n in enumerate(b.nets) if n.lstrip('/') == 'GND'][0]
    r_fill = fills.net_copper(b, 0, g, ppmm, with_net_items=False)
    r_all = fills.net_copper(b, 0, g, ppmm, with_net_items=True)
    lab, n = ndi.label(r_fill.mask, structure=np.ones((3, 3)))
    anchored = set(np.unique(lab[(r_all.anchors > 0) & (lab > 0)]).tolist())
    k = ppmm
    out = []
    for i in range(1, n + 1):
        m = lab == i
        area = float(m.sum()) / (k * k)
        cy, cx = ndi.center_of_mass(m)
        out.append((i, area, r_fill.to_mm((cy, cx)), i in anchored))
    return b, r_fill, lab, out


def stitch_points(b, r, lab, comp, area, min_radius=0.9, spacing=8.0, court_margin=0.3):
    """via positions (board-frame mm) inside component `comp`: peaks of the distance to the edge, at least `min_radius` from it, `spacing` apart, one per 100 mm2 (at least one), outside courtyards"""
    m = lab == comp
    edt = ndi.distance_transform_edt(m) / r.ppmm
    court = [(b.fp_cx0[i], b.fp_cy0[i], b.fp_cx1[i], b.fp_cy1[i]) for i in range(len(b.fp_ref)) if not np.isnan(b.fp_cx0[i])]
    want = max(1, int(math.ceil(area / 100.0)))
    pts = []
    work = edt.copy()
    while len(pts) < want:
        i = int(np.argmax(work))
        rr, cc = divmod(i, work.shape[1])
        if work[rr, cc] < min_radius:
            break
        x, y = r.to_mm((rr, cc))
        if any(c[0] - court_margin <= x <= c[2] + court_margin and c[1] - court_margin <= y <= c[3] + court_margin for c in court):
            work[max(0, rr - 20):rr + 21, max(0, cc - 20):cc + 21] = 0.0
            continue
        pts.append((x, y))
        rad = int(spacing * r.ppmm)
        work[max(0, rr - rad):rr + rad + 1, max(0, cc - rad):cc + rad + 1] = 0.0
    return pts


KEEP_NAME = 'fillkeep'


def drop_keeps(b):
    for z in list(b.Zones()):
        if z.GetIsRuleArea() and z.GetZoneName() == KEEP_NAME:
            b.Remove(z)


def _fill_to(path, tmp, keeps, loose_w, clearance, spoke, gap, bot_w=None):
    from pcbtools.editor import edit
    with edit(path, tmp) as e:
        drop_keeps(e.b)
        for k in keeps:
            e.keepout(k, KEEP_NAME, tracks=False, vias=False, pour=True, layers='F')
        set_zones(e.b, loose_w, loose_w if bot_w is None else bot_w, clearance, spoke, gap, pcbnew.ISLAND_REMOVAL_MODE_NEVER)
        e.fill_zones()
    b = kb.read_board(tmp, {'FRAME': FRAME})
    os.remove(tmp)
    g = [i for i, n in enumerate(b.nets) if n.lstrip('/') == 'GND'][0]
    return fills.net_copper(b, 0, g, 40.0, with_net_items=True, frame=(17.0, -4.5, 117.0, 57.84))


def derive_keeps(path, loose_w, clearance, spoke, gap, width, grid, outlines, join, rounds=6):
    """the no-pour rectangles of pcbkit.fills.keepouts, from the top pour filled at `loose_w` (its narrowest) with no keep-outs of ours, then `rounds` times: fill at `width` with
    them, and add what that fill still leaves that is not worth keeping (blobs on necks, dead-end fingers)"""
    tmp = path + '.keeps.tmp.kicad_pcb'
    bounds = (17.0, -4.5, 117.0, 57.84)
    r0 = _fill_to(path, tmp, [], loose_w, clearance, spoke, gap)
    extra = None
    keeps = fills.keepouts(r0, width, grid, join, outlines=outlines, bounds=bounds)
    for _ in range(rounds):
        r = _fill_to(path, tmp, keeps, width, clearance, spoke, gap)
        lo = fills.leftovers(r)
        extra = lo if extra is None else (extra | lo)
        if not lo.any():
            break
        keeps = fills.keepouts(r0, width, grid, join, outlines=outlines, bounds=bounds, extra=extra)
    return keeps


def dead_vias(path, keeps, margin=0.35):
    """positions in the track enumeration of the GND vias that would dangle: nothing of theirs on the top copper (no track end, no pad) and inside a no-pour rectangle, so
    only the bottom plane would hold them (KiCad's via_dangling). They are not a pad's own via, so LR-1 does not count them."""
    b = kb.read_board(path, {'FRAME': FRAME})
    g = [i for i, n in enumerate(b.nets) if n.lstrip('/') == 'GND'][0]
    out = []
    for i in range(len(b.v_x)):
        if b.v_net[i] != g:
            continue
        x, y, r = b.v_x[i], b.v_y[i], b.v_dia[i] / 2
        if not any(k[0] - margin <= x <= k[2] + margin and k[1] - margin <= y <= k[3] + margin for k in keeps):
            continue
        tr = np.any((np.hypot(b.s_x0 - x, b.s_y0 - y) <= r + b.s_w / 2 + 0.01) | (np.hypot(b.s_x1 - x, b.s_y1 - y) <= r + b.s_w / 2 + 0.01))
        pd = np.any((b.p_bx0 - r <= x) & (x <= b.p_bx1 + r) & (b.p_by0 - r <= y) & (y <= b.p_by1 + r))
        if not tr and not pd:
            out.append((int(b.v_idx[i]), float(x), float(y)))
    return out


def run(path, out, top_w=1.0, bot_w=0.5, clearance=0.3, spoke=0.3, gap=0.3, big=10.0, grid=0.5, join=1.0, outlines=(), verbose=True):
    from pcbtools.editor import edit
    keeps = derive_keeps(path, 0.2, clearance, spoke, gap, top_w, grid, outlines, join)
    tmp = path + '.fillclean.tmp.kicad_pcb'
    dead = dead_vias(path, keeps)
    with edit(path, tmp) as e:
        drop_keeps(e.b)
        e.remove_vias([d[0] for d in dead])
        for k in keeps:
            e.keepout(k, KEEP_NAME, tracks=False, vias=False, pour=True, layers='F')
        set_zones(e.b, top_w, bot_w, clearance, spoke, gap, pcbnew.ISLAND_REMOVAL_MODE_NEVER)
        e.fill_zones()
    try:
        b, r, lab, comps = islands(tmp, big)
    finally:
        os.remove(tmp)
    vias, report = [], []
    for comp, area, (cx, cy), connected in sorted(comps, key=lambda c: -c[1]):
        if connected or area < 0.5:
            continue
        pts = stitch_points(b, r, lab, comp, area) if area >= big else []
        report.append((area, (cx, cy), len(pts)))
        vias += pts
    with edit(path, out) as e:
        drop_keeps(e.b)
        e.remove_vias([d[0] for d in dead])
        for k in keeps:
            e.keepout(k, KEEP_NAME, tracks=False, vias=False, pour=True, layers='F')
        set_zones(e.b, top_w, bot_w, clearance, spoke, gap, pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        if vias:
            e.add_vias('GND', [p[0] for p in vias], [p[1] for p in vias], 0.6, 0.3)
        e.fill_zones()
    kept = [x for x in report if x[2]]
    dropped = [x for x in report if not x[2]]
    if verbose:
        print('%d no-pour rectangles (grid %.2f mm):' % (len(keeps), grid))
        for k in keeps:
            print('   keep-out (%.2f, %.2f)-(%.2f, %.2f)  %.1f x %.1f mm' % (k + (k[2] - k[0], k[3] - k[1])))
        print('%d orphan GND vias inside a keep-out removed (nothing of theirs on the top copper): %s' % (len(dead), ', '.join('(%.1f, %.1f)' % (d[1], d[2]) for d in dead)))
        print('top GND pour: %d parts hang free of every GND item; %d of 10 mm2 or more are stitched, %d dropped (%.0f mm2 in %d pieces)' % (len(report), len(kept), len(dropped), sum(a for a, _, _ in dropped), len(dropped)))
        for a, (x, y), n in kept:
            print('   stitched pour %.1f mm2 at (%.1f, %.1f): %d via%s' % (a, x, y, n, '' if n == 1 else 's'))
    return keeps, kept, dropped, vias


if __name__ == '__main__':
    def opt(name, default):
        return float(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
    cfgname = sys.argv[sys.argv.index('--config') + 1] if '--config' in sys.argv else 'v1_layout'
    import importlib
    cfg = importlib.import_module('pcbtools.boards.' + cfgname)
    outl = [tuple(r) for rs in cfg.OUTLINE.values() for r in rs]
    skip = {'--top-width', '--bottom-width', '--clearance', '--spoke', '--gap', '--big', '--grid', '--join', '--config'}
    args = [a for k, a in enumerate(sys.argv[1:], 1) if not a.startswith('--') and not (k > 1 and sys.argv[k - 1] in skip)]
    run(args[0], args[1] if len(args) > 1 else args[0], opt('--top-width', 1.0), opt('--bottom-width', 0.5), opt('--clearance', 0.3), opt('--spoke', 0.3), opt('--gap', 0.3), opt('--big', 10.0), opt('--grid', 0.5), opt("--join", 1.0), outl)
