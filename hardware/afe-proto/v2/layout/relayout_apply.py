"""AFE-2 relayout, phase 1: write the placement into the board by text splice (no pcbnew rewrite; the .kicad_pro is not touched).

    python3 relayout_apply.py BOARD.kicad_pcb DUMP.json OUT.kicad_pcb PLACE.json [PLACE.json ...]

PLACE.json files: {"st": {ref: [x, y]}} the new origins (Due mm) of the parts they name; CH2's is the mock-up's own (with "old_pads" etc. ignored).
Does, in order: moves each named footprint (origin only, rotation kept); sets every top designator horizontal, centred over the courtyard, at the
height relayout_place.py reserved; the edge header J601 and J605 per the owner's rule; the three BNCs' labels (as place_ch2_mock.py); J501's
function texts below it; the five block names to free corners; strips every track and via of every net that touches a moved part (the board is
to be re-routed; the zones are left as they are, stale); replaces the block outlines on the top silk by solid lines round REGIONS.
"""
import json, math, os, re, sys, uuid
import numpy as np
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import relayout_place as RP
import outlines as OUT
from place_ch2_mock import fmt, fp_span, fp_at, BNCS, BNC_LABEL_OFFSET, BNC_DES_OFFSET, SX, SY
NAMES = {'POWER': 'POWER', 'REFCAL': 'REF / CAL', 'CH1': 'CH1', 'CH2': 'CH2', 'AWG': 'AWG'}


def set_ref(t, ref, cx, cy, ang=0):
    """designator of `ref` horizontal with its centre at (cx, cy) Due mm"""
    s, e = fp_span(t, ref); blk = t[s:e]
    fx, fy, fa, _ = fp_at(blk)
    dx, dy = cx + SX - fx, SY - cy - fy; a = math.radians(fa)
    loc = (dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a))
    i = blk.index('(property "Reference" "%s"' % ref); j = blk.index('\n\t\t)', i)
    prop = re.sub(r'\(at [-\d.]+ [-\d.]+(?: [-\d.]+)?\)', '(at %s %s %d)' % (fmt(loc[0]), fmt(loc[1]), ang), blk[i:j], count=1)
    prop = re.sub(r'\(layer "[^"]*"\)', '(layer "F.SilkS")', prop, count=1)
    return t[:s] + blk[:i] + prop + blk[j:] + t[e:]


def move_text(t, word, x, y, ang=None, nth=0):
    ms = list(re.finditer(r'\n\t\(gr_text "%s"\n\t\t\(at ([-\d.]+) ([-\d.]+)( [-\d.]+)?\)' % re.escape(word), t))
    m = ms[nth]
    a = m.group(3) if ang is None else ' %s' % fmt(ang)
    new = '\n\t(gr_text "%s"\n\t\t(at %s %s%s)' % (word, fmt(x + SX), fmt(SY - y), a or '')
    return t[:m.start()] + new + t[m.end():]


def outline_lines(rects):
    """the boundary of a union of rectangles as segments (x0, y0, x1, y1): each rect edge less the stretches that border another rect of the union"""
    segs = []
    for k, r in enumerate(rects):
        for side in range(4):
            if side < 2:      # bottom (y0), top (y1): horizontal
                y = r[1] if side == 0 else r[3]; iv = [(r[0], r[2])]
                for q in rects:
                    if q is r: continue
                    if abs((q[3] if side == 0 else q[1]) - y) < 1e-9:
                        lo, hi = max(r[0], q[0]), min(r[2], q[2])
                        iv = [p for a, b in iv for p in ([(a, b)] if hi <= a or lo >= b else [(a, lo)] * (lo > a) + [(hi, b)] * (hi < b))]
                segs += [(a, y, b, y) for a, b in iv if b - a > 1e-9]
            else:
                x = r[0] if side == 2 else r[2]; iv = [(r[1], r[3])]
                for q in rects:
                    if q is r: continue
                    if abs((q[2] if side == 2 else q[0]) - x) < 1e-9:
                        lo, hi = max(r[1], q[1]), min(r[3], q[3])
                        iv = [p for a, b in iv for p in ([(a, b)] if hi <= a or lo >= b else [(a, lo)] * (lo > a) + [(hi, b)] * (hi < b))]
                segs += [(x, a, x, b) for a, b in iv if b - a > 1e-9]
    return segs


def main(board, dump, out, places):
    t = open(board).read()
    D, P = RP.load(dump)
    new, rot_new, ls_new = {}, {}, {}
    for f in places:
        for k, v in json.load(open(f))['st'].items():
            new[k] = (v[0], v[1])
            if len(v) > 2: rot_new[k] = v[2]
            if len(v) > 3: ls_new[k] = v[3]
    kof = {r: int(round((rot_new[r] - P[r]['rot']) / 90.0)) % 4 for r in rot_new}
    G = {r: RP.part_geom(p, kof.get(r, 0), ls_new.get(r, 0)) for r, p in P.items()}
    for r in new: assert r in P and r not in RP.FIXED, r
    pos = {r: new.get(r, (P[r]['x'], P[r]['y'])) for r in P}
    for r, (x, y) in new.items():                                   # 1. move (and turn)
        s, e = fp_span(t, r); blk = t[s:e]
        fx, fy, fa, m = fp_at(blk)
        ra = rot_new.get(r, fa)
        blk = blk[:m.start()] + '\n\t\t(at %s %s%s)' % (fmt(x + SX), fmt(SY - y), (' ' + fmt(ra)) if (m.group(3) is not None or abs(ra) > 1e-9) else '') + blk[m.end():]
        dlt = ra - fa
        if abs(dlt) > 1e-9:                                         # the pads' and the texts' angles are absolute in the file: turn them by the same amount
            blk = re.sub(r'(\(pad "[^"]*" [^\n]*\n\t\t\t\(at [-\d.]+ [-\d.]+ )?([-\d.]+)?\)', lambda mm: mm.group(0), blk) if False else blk
            def padfix(mm, dlt=dlt):
                a = ((float(mm.group(3) or 0) + dlt + 180.0) % 360.0) - 180.0
                return '%s(at %s %s %s)' % (mm.group(1), mm.group(2), mm.group(4), fmt(a))
            blk = re.sub(r'(\(pad "[^"]*" [^\n]*\n\t\t\t)\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', lambda mm: '%s(at %s %s %s)' % (mm.group(1), mm.group(2), mm.group(3), fmt(((float(mm.group(4) or 0) + dlt + 180.0) % 360.0) - 180.0)), blk)
            blk = re.sub(r'(\(fp_text [^\n]*\n\t\t\t)\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', lambda mm: '%s(at %s %s %s)' % (mm.group(1), mm.group(2), mm.group(3), fmt(((float(mm.group(4) or 0) + dlt + 180.0) % 360.0) - 180.0)), blk)
        t = t[:s] + blk + t[e:]
    lab = {}                                                         # 2. designators (conservative boxes, for the name search)
    for r, p in P.items():
        if r in ('J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607'): continue
        if r in RP.FIXED: continue
        if r not in new and not os.environ.get('APPLY_ALL_LABELS'): continue      # a block not re-placed in this round keeps its labels
        g = G[r]; x, y = pos[r]
        cx = (g['lab'][0] + g['lab'][2]) / 2 + x; ly = (g['lab'][1] + g['lab'][3]) / 2 + y
        if r in BNCS or r.startswith('MH'): continue
        t = set_ref(t, r, cx, ly)
        lab[r] = (cx - RP.LAB_W * len(r) / 2, ly - RP.LAB_H / 2, cx + RP.LAB_W * len(r) / 2, ly + RP.LAB_H / 2)
    for ur in ('U101', 'U301', 'U401'):                                       # beside their pin-free east ends (D30 named exceptions)
        ul, uz, (ucx, ucy) = RP.u101_label_east(P, dict(new), ur)
        t = set_ref(t, ur, ucx, ucy); lab[ur] = ul
    for h in ('J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607'):          # edge headers: the owner's rule (bcbc1e3d), RP.header_label
        hx, hy = RP.header_label(P[h]); t = set_ref(t, h, hx, hy)
        lab[h] = (hx - RP.LAB_W * 2, hy - RP.LAB_H / 2, hx + RP.LAB_W * 2, hy + RP.LAB_H / 2)
    for ref, word in BNCS.items():                                  # 3. BNCs
        s, e = fp_span(t, ref); blk = t[s:e]
        fx, fy, fa, _ = fp_at(blk); ox, oy = fx - SX, SY - fy
        t = move_text(t, word, ox + BNC_LABEL_OFFSET[0], oy + BNC_LABEL_OFFSET[1])
        k = t.index('(gr_text "%s"' % word); k2 = t.index('\n\t)', k)
        t = t[:k] + t[k:k2].replace('\n\t\t\t(justify left)', '') + t[k2:]
        s, e = fp_span(t, ref); blk = t[s:e]
        X, Y = ox + BNC_DES_OFFSET[0] + SX, SY - (oy + BNC_DES_OFFSET[1]); dx, dy = X - fx, Y - fy; a = math.radians(fa)
        loc = (dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a))
        i = blk.index('(property "Reference" "%s"' % ref); j = blk.index('\n\t\t)', i)
        prop = re.sub(r'\(at [-\d.]+ [-\d.]+(?: [-\d.]+)?\)', '(at %s %s)' % (fmt(loc[0]), fmt(loc[1])), blk[i:j], count=1)
        prop = re.sub(r'\(layer "[^"]*"\)', '(layer "B.SilkS")', prop, count=1)
        if '(justify mirror)' not in prop:
            q = prop.rindex('\n\t\t\t)'); prop = prop[:q] + '\n\t\t\t\t(justify mirror)' + prop[q:]
        t = t[:s] + blk[:i] + prop + blk[j:] + t[e:]
    jx, jy = pos['J501']                                            # 4. J501's function texts
    for w, (ox, oy, tw, th) in (RP.J501_TEXTS.items() if 'J501' in new else []):
        t = move_text(t, w, jx + ox, jy + oy, 0)
    # 5. block names: RP.name_box (the top-left-most free place of the block, reserved before the parts were placed)
    for blk, word in NAMES.items():
        b = RP.name_box(blk, P, G)
        t = move_text(t, word, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        print('name', word, 'at', round((b[0] + b[2]) / 2, 2), round((b[1] + b[3]) / 2, 2))
    # 6. copper: every track and via of a net a moved part touches goes
    moved_nets = {q['net'] for r in new for q in P[r]['pads']}
    cnt = {}
    def segsub(m):
        if m.group(7) in moved_nets: cnt['seg'] = cnt.get('seg', 0) + 1; return ''
        cnt['kept'] = cnt.get('kept', 0) + 1; return m.group(0)
    t = re.sub(r'\n\t\(segment\n\t\t\(start ([-\d.]+) ([-\d.]+)\)\n\t\t\(end ([-\d.]+) ([-\d.]+)\)\n\t\t\(width ([\d.]+)\)\n\t\t\(layer "([^"]*)"\)\n\t\t\(net "([^"]*)"\)\n\t\t\(uuid "[^"]*"\)\n\t\)', segsub, t)
    def viasub(m):
        if m.group(4) in moved_nets: cnt['via'] = cnt.get('via', 0) + 1; return ''
        cnt['kept'] = cnt.get('kept', 0) + 1; return m.group(0)
    t = re.sub(r'\n\t\(via\n\t\t\(at ([-\d.]+) ([-\d.]+)\)\n\t\t\(size ([\d.]+)\)\n\t\t\(drill [\d.]+\)\n\t\t\(layers "F\.Cu" "B\.Cu"\)\n\t\t\(net "([^"]*)"\)\n\t\t\(uuid "[^"]*"\)\n\t\)', viasub, t)
    print('copper removed:', cnt)
    # BNC input stubs: the bare minimum of copper the BNC pitch rule holds (a track starting at pin 1's centre), the rest of the run is to be routed
    for ref, word in BNCS.items():
        if ref == 'J301': continue
        s_, e_ = fp_span(t, ref); blk_ = t[s_:e_]
        fx_, fy_, _, _ = fp_at(blk_)
        net = re.search(r'\(pad "1" .*?\(net "([^"]*)"\)', blk_, re.S).group(1)
        if not re.search(r'\n\t\(segment\n\t\t\(start %s %s\)' % (re.escape(fmt(fx_)), re.escape(fmt(fy_))), t):
            seg = ('\n\t(segment\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(width 0.25)\n\t\t(layer "F.Cu")\n\t\t(net "%s")\n\t\t(uuid "%s")\n\t)'
                   % (fmt(fx_), fmt(fy_), fmt(fx_ - 1.0), fmt(fy_), net, uuid.uuid5(uuid.NAMESPACE_URL, 'bncstub' + ref)))
            k_ = t.index('\n\t(segment') if '\n\t(segment' in t else t.index('\n\t(gr_line'); t = t[:k_] + seg + t[k_:]
    # 7. outlines
    def old(m):
        a = [float(m.group(i)) for i in (1, 2, 3, 4)]
        ok = (all(17.0 <= a[k] - SX <= 93.5 for k in (0, 2)) and all(4.0 <= SY - a[k] <= 50.5 for k in (1, 3))) or \
            (all(98.0 <= a[k] - SX <= 117.0 for k in (0, 2)) and all(0.5 <= SY - a[k] <= 54.0 for k in (1, 3)))      # the blocks' lines and the BNC boxes' (redrawn from the table)
        return '' if ok else m.group(0)
    t, n = re.subn(r'\n\t\(gr_line\n\t\t\(start ([-\d.]+) ([-\d.]+)\)\n\t\t\(end ([-\d.]+) ([-\d.]+)\)\n\t\t\(stroke(?:(?!\n\t\)).)*?\(layer "F\.SilkS"\)\n\t\t\(uuid "[^"]*"\)\n\t\)', lambda m: old(m), t, flags=re.S)
    keepouts = list(OUT.GAP_BOXES)
    for r_ in RP.FIXED:                                            # solid outlines stop 0.3 mm short of other silk: the headers' and the mounting holes' own
        sb = P[r_]['silk']
        if sb and r_ not in ('J101', 'J201', 'J301', 'U101'): keepouts.append((sb[0] - 0.3, sb[1] - 0.3, sb[2] + 0.3, sb[3] + 0.3))
    keepouts.append((21.55, 37.36, 32.15, 40.96))                    # the serial-number box
    lines = []
    for blk, rs in OUT.RECTS.items():
        for (a, b, c, d) in OUT.clip_boxes([g for g in OUT.boundary(rs) if min(g[0], g[2]) < 98.0], keepouts) + [g for g in OUT.boundary(rs) if min(g[0], g[2]) >= 98.0]:
            lines.append('\n\t(gr_line\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(stroke\n\t\t\t(width 0.15)\n\t\t\t(type default)\n\t\t)\n\t\t(layer "F.SilkS")\n\t\t(uuid "%s")\n\t)'
                         % (fmt(a + SX), fmt(SY - b), fmt(c + SX), fmt(SY - d), uuid.uuid5(uuid.NAMESPACE_URL, 'relayout%s%s%s%s%s' % (blk, a, b, c, d))))
    k = t.index('\n\t(gr_line'); t = t[:k] + ''.join(lines) + t[k:]
    open(out, 'w').write(t)
    print('outline lines: removed', n, 'drawn', len(lines))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
