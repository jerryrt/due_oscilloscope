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
from pcbtools import boardio

FRAME = boardio.FRAME


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


def run(path, out, top_w=1.6, bot_w=0.5, clearance=0.3, spoke=0.3, gap=0.25, big=10.0, verbose=True):
    tmp = path + '.fillclean.tmp.kicad_pcb'
    b0 = pcbnew.LoadBoard(path)
    set_zones(b0, top_w, bot_w, clearance, spoke, gap, pcbnew.ISLAND_REMOVAL_MODE_NEVER)
    pcbnew.ZONE_FILLER(b0).Fill(b0.Zones())
    pcbnew.SaveBoard(tmp, b0)
    pro = os.path.splitext(path)[0] + '.kicad_pro'
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
    from pcbtools.editor import edit
    with edit(path, out) as e:
        set_zones(e.b, top_w, bot_w, clearance, spoke, gap, pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        if vias:
            e.add_vias('GND', [p[0] for p in vias], [p[1] for p in vias], 0.6, 0.3)
        e.fill_zones()
    kept = [x for x in report if x[2]]
    dropped = [x for x in report if not x[2]]
    if verbose:
        print('top GND pour: %d parts hang free of every GND item; %d of 10 mm2 or more are stitched, %d dropped (%.0f mm2 in %d pieces)' % (len(report), len(kept), len(dropped), sum(a for a, _, _ in dropped), len(dropped)))
        for a, (x, y), n in kept:
            print('   stitched pour %.1f mm2 at (%.1f, %.1f): %d via%s' % (a, x, y, n, '' if n == 1 else 's'))
    return kept, dropped, vias


if __name__ == '__main__':
    def opt(name, default):
        return float(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
    args = [a for k, a in enumerate(sys.argv[1:], 1) if not a.startswith('--') and not (k > 1 and sys.argv[k - 1].startswith('--'))]
    run(args[0], args[1] if len(args) > 1 else args[0], opt('--top-width', 1.6), opt('--bottom-width', 0.5), opt('--clearance', 0.3), opt('--spoke', 0.3), opt('--gap', 0.25), opt('--big', 10.0))
