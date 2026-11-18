"""fill_clean.py BOARD [OUT] (--reference BOARD_OF_RECORD | --reference-input) [--top-width W] [--bottom-width W] [--clearance C] [--spoke S] [--gap G] [--big A]: the GND pours of a board as the owner wants them, and a report.

  - the build refuses (exit 2, nothing written) when the fill moved ground copper toward any POUR_NODES / POUR_INFO_NODES node, against the pour gaps of the reference board: name the board of record with
    --reference (the input may carry a stale fill that is no reference at all); without either flag it stops before doing anything;
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
        if z.GetIsRuleArea() or z.GetZoneName() == STRIP_NAME:
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


_DROPPED = []                                      # removed zones are kept alive: RemoveNative leaves the object to Python, and freeing it here crashes the next Zones() walk


def drop_keeps(b):
    for z in list(b.Zones()):
        if z.GetIsRuleArea() and z.GetZoneName() == KEEP_NAME:
            b.RemoveNative(z)
            _DROPPED.append(z)


def _rm(tmp):
    """remove a temporary board and the project file the editor wrote beside it"""
    for f in (tmp, os.path.splitext(tmp)[0] + '.kicad_pro'):
        if os.path.exists(f):
            os.remove(f)


def _fill_to(path, tmp, keeps, loose_w, clearance, spoke, gap, bot_w=None):
    from pcbtools.editor import edit
    with edit(path, tmp) as e:
        drop_keeps(e.b)
        for k in keeps:
            e.keepout(k, KEEP_NAME, tracks=False, vias=False, pour=True, layers='F')
        set_zones(e.b, loose_w, loose_w if bot_w is None else bot_w, clearance, spoke, gap, pcbnew.ISLAND_REMOVAL_MODE_NEVER)
        e.fill_zones()
    b = kb.read_board(tmp, {'FRAME': FRAME})
    _rm(tmp)
    g = [i for i, n in enumerate(b.nets) if n.lstrip('/') == 'GND'][0]
    fr = (17.0, -4.5, 117.0, 57.84)
    return fills.net_copper(b, 0, g, 40.0, with_net_items=True, frame=fr), b, g, fills.net_copper(b, 0, g, 40.0, with_net_items=False, frame=fr)


def derive_keeps(path, loose_w, clearance, spoke, gap, width, grid, outlines, join, rounds=6, shells=(), skip=None):
    """the no-pour rectangles of pcbkit.fills.keepouts, from the top pour filled at `loose_w` (its narrowest) with no keep-outs of ours, then `rounds` times: fill at `width` with
    them, and add what that fill still leaves that is not worth keeping (blobs on necks, dead-end fingers)"""
    tmp = path + '.keeps.tmp.kicad_pcb'
    bounds = (17.0, -4.5, 117.0, 57.84)
    r0, b0, g0, _ = _fill_to(path, tmp, [], loose_w, clearance, spoke, gap)
    protect = fills.pin_protect(b0, r0, g0, shells) if shells else None       # connector ground pins stay in the pour
    if skip is not None:                                                       # and so does the pour round each SMD ground pad that has not been given a via at its edge
        boxes = [(b0.p_bx0[i], b0.p_by0[i], b0.p_bx1[i], b0.p_by1[i]) for i in range(len(b0.p_x)) if b0.p_net[i] == g0 and b0.p_smd[i] and (b0.p_layer_mask[i] & 1) and (b0.fp_ref[b0.p_fp[i]], b0.p_pin[i]) not in skip]
        pb = fills.box_protect(r0, boxes)
        protect = pb if protect is None else (protect | pb)
    extra = None
    keeps = fills.keepout_polygons(r0, width, grid, join, outlines=outlines, bounds=bounds, protect=protect)
    for _ in range(rounds):
        r, bb, g, rp = _fill_to(path, tmp, keeps, width, clearance, spoke, gap)
        lo = fills.leftovers(r) | fills.rough_edges(bb, rp, 0, g, clearance, exempt=shells)
        extra = lo if extra is None else (extra | lo)
        if not lo.any():
            break
        new = fills.keepout_polygons(r0, width, grid, join, outlines=outlines, bounds=bounds, extra=extra, protect=protect)
        if new == keeps:
            break
        keeps = new
    return keeps


def _near_poly(x, y, poly, margin):
    """the point is inside the polygon or within `margin` of its edge"""
    inside = False
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
        dx, dy = x1 - x0, y1 - y0
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy)))
        if math.hypot(x - x0 - t * dx, y - y0 - t * dy) <= margin:
            return True
    return inside


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
        if not any(_near_poly(x, y, k, margin) for k in keeps):
            continue
        tr = np.any((np.hypot(b.s_x0 - x, b.s_y0 - y) <= r + b.s_w / 2 + 0.01) | (np.hypot(b.s_x1 - x, b.s_y1 - y) <= r + b.s_w / 2 + 0.01))
        pd = np.any((b.p_bx0 - r <= x) & (x <= b.p_bx1 + r) & (b.p_by0 - r <= y) & (y <= b.p_by1 + r))
        if not tr and not pd:
            out.append((int(b.v_idx[i]), float(x), float(y)))
    return out


STRIP_NAME = 'shellstrip'
STRIPS = False                                     # GND strip zones towards a connector pin: off (they leave pieces under the 1.0 mm minimum width); the pins are named exceptions instead


def drop_strips(b):
    for z in list(b.Zones()):
        if (not z.GetIsRuleArea()) and z.GetZoneName() == STRIP_NAME:
            b.RemoveNative(z)
            _DROPPED.append(z)


def add_strips(e, rects, clearance, spoke, gap, min_w=0.3):
    """a GND zone on F.Cu for each rectangle (Due mm): thermal reliefs, minimum width `min_w` (the top pour's own minimum is wider)"""
    for (x0, y0, x1, y1) in rects:
        z = pcbnew.ZONE(e.b)
        z.SetLayer(pcbnew.F_Cu)
        z.SetNet(e._net('GND'))
        z.SetZoneName(STRIP_NAME)
        for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            z.AppendCorner(e._pt(px, py), -1)
        z.SetMinThickness(pcbnew.FromMM(min_w))
        z.SetLocalClearance(pcbnew.FromMM(clearance))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(pcbnew.FromMM(gap))
        z.SetThermalReliefSpokeWidth(pcbnew.FromMM(spoke))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        e.b.Add(z)
        e._give(z)


def _gnd_boxes(path):
    b = kb.read_board(path, {'FRAME': FRAME})
    g = [i for i, n in enumerate(b.nets) if n.lstrip('/') == 'GND'][0]
    return [(b.fp_ref[b.p_fp[i]], b.p_pin[i], float(b.p_x[i]), float(b.p_y[i]), (float(b.p_bx0[i]), float(b.p_by0[i]), float(b.p_bx1[i]), float(b.p_by1[i])))
            for i in range(len(b.p_x)) if b.p_net[i] == g and b.p_smd[i] and (b.p_layer_mask[i] & 1)]


def run(path, out, top_w=1.0, bot_w=0.5, clearance=0.3, spoke=0.3, gap=0.3, big=10.0, grid=0.5, join=1.0, outlines=(), verbose=True, shells=(), gndpad_min=0.2):
    from pcbtools.editor import edit
    src = path
    work = path + '.work.tmp.kicad_pcb'
    moved, skipped_pads = [], []
    strips = []
    edge = set()
    for attempt in range(8):
        keeps = derive_keeps(src, 0.2, clearance, spoke, gap, top_w, grid, outlines, join, shells=shells, skip=edge)
        from pcbtools import gndpads                              # imported late: pcbnew's zone objects break when this module's imports come first
        probe = path + '.probe.tmp.kicad_pcb'
        bad = []                                                   # the SMD GND pads the pour still does not touch, from the filled board
        with edit(src, probe) as e:
            drop_keeps(e.b)
            drop_strips(e.b)
            for k in keeps:
                e.keepout(k, KEEP_NAME, tracks=False, vias=False, pour=True, layers='F')
            set_zones(e.b, top_w, bot_w, clearance, spoke, gap, pcbnew.ISLAND_REMOVAL_MODE_NEVER)
            add_strips(e, strips, clearance, spoke, gap)
            e.fill_zones()
        try:
            lost, near = gndpads.failing(probe, gndpad_min, shells=shells)
            shell_now = list(gndpads.failing.shell)
            bad = [p for p in lost + near if (p[0], p[1]) not in edge]
        finally:
            _rm(probe)
        if STRIPS and shell_now and not strips:                                 # connector GND pins the pour cannot reach (a 2.54 mm row leaves no 1.0 mm web): each gets a GND strip zone towards the interior
            strips = gndpads.strip_rects(shell_now)
            continue
        if not bad:
            break
        done, skipped = gndpads.relocate(src, work, bad)
        moved += done
        skipped_pads += skipped
        edge |= {(r, pn) for r, pn, *_ in bad}
        src = work
        if not done:
            break
    if edge:                                                      # the last round may have moved vias: the keep-outs are derived once more from the board as it ends
        keeps = derive_keeps(src, 0.2, clearance, spoke, gap, top_w, grid, outlines, join, shells=shells, skip=edge)
    tmp = path + '.fillclean.tmp.kicad_pcb'
    dead = dead_vias(src, keeps)
    with edit(src, tmp) as e:
        drop_keeps(e.b)
        drop_strips(e.b)
        e.remove_vias([d[0] for d in dead])
        for k in keeps:
            e.keepout(k, KEEP_NAME, tracks=False, vias=False, pour=True, layers='F')
        set_zones(e.b, top_w, bot_w, clearance, spoke, gap, pcbnew.ISLAND_REMOVAL_MODE_NEVER)
        add_strips(e, strips, clearance, spoke, gap)
        e.fill_zones()
    try:
        b, r, lab, comps = islands(tmp, big)
    finally:
        _rm(tmp)
    vias, report = [], []
    for comp, area, (cx, cy), connected in sorted(comps, key=lambda c: -c[1]):
        if connected or area < 0.5:
            continue
        pts = []
        if area >= big:                                    # a via well inside the pour (1.5 mm of pour to every side: the pour edge then never hugs it), else as far in as there is room
            for rad in (1.5, 1.2, 0.9):
                pts = stitch_points(b, r, lab, comp, area, min_radius=rad)
                if pts:
                    break
        report.append((area, (cx, cy), len(pts)))
        vias += pts
    with edit(src, out) as e:
        drop_keeps(e.b)
        drop_strips(e.b)
        e.remove_vias([d[0] for d in dead])
        for k in keeps:
            e.keepout(k, KEEP_NAME, tracks=False, vias=False, pour=True, layers='F')
        set_zones(e.b, top_w, bot_w, clearance, spoke, gap, pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        add_strips(e, strips, clearance, spoke, gap)
        if vias:
            e.add_vias('GND', [p[0] for p in vias], [p[1] for p in vias], 0.6, 0.3)
        e.fill_zones()
    kept = [x for x in report if x[2]]
    dropped = [x for x in report if not x[2]]
    if verbose:
        print('%d no-pour polygons (grid %.2f mm, edges at 0/45/90 degrees):' % (len(keeps), grid))
        for k in keeps:
            print('   keep-out polygon, %d corners, %.1f mm2, from (%.2f, %.2f)' % (len(k), abs(sum(k[i][0] * k[(i + 1) % len(k)][1] - k[(i + 1) % len(k)][0] * k[i][1] for i in range(len(k)))) / 2, k[0][0], k[0][1]))
        print('%d orphan GND vias inside a keep-out removed (nothing of theirs on the top copper): %s' % (len(dead), ', '.join('(%.1f, %.1f)' % (d[1], d[2]) for d in dead)))
        print('%d SMD GND pads got their via at the pad edge (the pour cannot hold them): %s' % (len(moved), ', '.join('%s.%s' % (m[0], m[1]) for m in moved)))
        if skipped_pads:
            print('   not relocated: %s' % '; '.join('%s.%s (%s)' % t for t in skipped_pads))
        if strips:
            print('%d GND strip zones (minimum width 0.3) reach connector GND pins from the board interior: %s' % (len(strips), ', '.join('(%.1f..%.1f, %.1f..%.1f)' % (r[0], r[2], r[1], r[3]) for r in strips)))
        print('top GND pour: %d parts hang free of every GND item; %d of 10 mm2 or more are stitched, %d dropped (%.0f mm2 in %d pieces)' % (len(report), len(kept), len(dropped), sum(a for a, _, _ in dropped), len(dropped)))
        for a, (x, y), n in kept:
            print('   stitched pour %.1f mm2 at (%.1f, %.1f): %d via%s' % (a, x, y, n, '' if n == 1 else 's'))
    if src == work:
        _rm(work)
    return keeps, kept, dropped, vias


if __name__ == '__main__':
    def opt(name, default):
        return float(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
    cfgname = sys.argv[sys.argv.index('--config') + 1] if '--config' in sys.argv else 'v1_layout'
    import importlib
    cfg = importlib.import_module('pcbtools.boards.' + cfgname)
    outl = [tuple(r) for rs in cfg.OUTLINE.values() for r in rs]
    skip = {'--top-width', '--bottom-width', '--clearance', '--spoke', '--gap', '--big', '--grid', '--join', '--config', '--reference'}
    args = [a for k, a in enumerate(sys.argv[1:], 1) if not a.startswith('--') and not (k > 1 and sys.argv[k - 1] in skip)]
    fills.SHELL_SKIP.update((str(e[0]), str(e[1])) for e in getattr(cfg, 'FILL_SHELL_EXCEPTIONS', ()))
    from pcbkit import board as _kb, rules as _rules
    from pcbtools import rules as _afe_rules
    _src, _dst = args[0], (args[1] if len(args) > 1 else args[0])
    if '--reference' in sys.argv:                                     # the figures to hold: the board of record's pour gaps (the input may carry a stale fill that no longer is the pour)
        _ref = sys.argv[sys.argv.index('--reference') + 1]
    elif '--reference-input' in sys.argv:
        _ref = _src                                                    # explicit: the input board's own fill is the reference
    else:
        sys.exit('fill_clean: name the board whose pour gaps this fill must not make worse (--reference BOARD, the board of record), or --reference-input to hold the input board\'s own; a guard that silently reads a stale fill cannot fire')
    _before = _kb.read_board(_ref, {'FRAME': FRAME})          # the board as it came in: its pour gaps are the figures the fill may not make worse
    run(args[0], args[1] if len(args) > 1 else args[0], opt('--top-width', 1.0), opt('--bottom-width', 0.5), opt('--clearance', 0.3), opt('--spoke', 0.3), opt('--gap', 0.3), opt('--big', 10.0), opt('--grid', 0.5), opt("--join", 1.0), outl, shells=tuple(getattr(cfg, 'FILL_SHELL_PREFIXES', ())), gndpad_min=float(getattr(cfg, 'FILL_GNDPAD_MIN', 0.2)))
    _worse = _rules.pour_gap_regressions(_before, _kb.read_board(_dst, {'FRAME': FRAME}), _afe_rules._pour_cfg(cfg))
    if _worse:
        for n, kind, g0, g1 in _worse:
            print('REFUSED: the fill moved ground %s toward %s: %.3f mm -> %.3f mm' % (kind, n, g0, g1))
        if _dst != _src and os.path.exists(_dst):
            os.remove(_dst)
        sys.exit(2)
    print('pour gaps held: every judged node keeps at least its gap to the ground tracks and the pour on %s' % _ref)
