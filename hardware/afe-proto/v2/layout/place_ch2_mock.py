"""STEP 1 of the AFE-2 relayout, a MOCK-UP: CH2 re-placed with a label zone above every part (owner convention 2026-11-15).
Pure text splice of BOARD.kicad_pcb (no pcbnew rewrite); the board is left unrouted where CH2 moved.

    python3 place_ch2_mock.py BOARD.kicad_pcb PLACE.json OUT.kicad_pcb

PLACE.json: {"st": {ref: [x, y]}, "rel": {ref: courtyard relative to the origin}, "old_pads": [...]} the new footprint origins of CH2's parts, Due mm (translation only: rotations are kept).
What it does, in order:
  1. moves each CH2 footprint (origin only; pads, silk and courtyard follow);
  2. every CH2 part's designator horizontal (0 degrees), centred over its courtyard, LABEL_UP above its top (silkread's rule);
  3. the three BNCs: function label vertical at one offset in each frame, designator on the bottom silk, mirrored, at one offset
     (the offsets of silk-runs' bncframe, whose code this restates because silkapply is not on this branch);
  4. removes the copper that no longer fits: CH2's own nets, and any other segment or via that touches an old pad of a moved part
     or a new courtyard (the list is printed; the block is meant to be re-routed);
  5. the silk outline of CH2 gets the west extension (BLOCK_EXT) as solid lines.
"""
import json, math, re, sys, uuid
SX, SY = 50.0, 150.0
MOVE = ['R201', 'R202', 'R203', 'R204', 'R205', 'R206', 'R207', 'R208', 'C201', 'C202', 'C203', 'D201', 'TP201']
LABEL_UP = 0.3          # courtyard top to the bottom of silkread's 1.0 mm text box
BNC_LABEL_OFFSET = (-2.75, 1.0)    # board mm from each BNC origin, all three: vertical, centred in the strip between the body and J605
BNC_DES_OFFSET = (3.2, 0.0)
BLOCK_NAME_AT = (90.25, 20.8)    # Due mm, centre of the block name "CH2"
BNCS = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}
OWN = ('/CH2_IN', '/CH2_N', '/CH2_M1', '/CH2_M2', '/CH2_M3', '/CH2_NP', '/CH2_OUT')
SHARED = ('/A0', '/VREF_P', '/GND', '/+3V3A_U')
BLOCK_EXT = []                # the mock-up fits CH2's present outline: no extension is drawn


def fmt(v): return ('%.4f' % v).rstrip('0').rstrip('.')


def fp_span(t, ref):
    for m in re.finditer(r'\n\t\(footprint "[^"]*"\n', t):
        e = t.find('\n\t(footprint ', m.end()); e = len(t) if e < 0 else e
        if '(property "Reference" "%s"' % ref in t[m.start():e]: return m.start(), e
    raise KeyError(ref)


def fp_at(blk):
    m = re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', blk)
    return float(m.group(1)), float(m.group(2)), float(m.group(3) or 0), m


def main(board, place, out):
    t = open(board).read()
    st = {k: tuple(v) for k, v in json.load(open(place))['st'].items()}
    REL = json.load(open(place))['rel']
    oldpads, newcy, lbox = [], {}, {}
    w_old = None
    for ref in MOVE:                                   # 1. move
        s, e = fp_span(t, ref); blk = t[s:e]
        fx, fy, fa, m = fp_at(blk)
        nx, ny = st[ref][0] + SX, SY - st[ref][1]
        blk = blk[:m.start()] + '\n\t\t(at %s %s%s)' % (fmt(nx), fmt(ny), (' ' + fmt(fa)) if m.group(3) is not None else '') + blk[m.end():]
        t = t[:s] + blk + t[e:]
    LAB = json.load(open(place))['lab_only']           # parts of other blocks whose labels sit in CH2's area: text only, the part stays
    for ref in MOVE + list(LAB):                       # 2. designators
        s, e = fp_span(t, ref); blk = t[s:e]
        fx, fy, fa, _ = fp_at(blk)
        pos = st[ref] if ref in st else LAB[ref]
        rel = REL[ref]; c = (pos[0] + rel[0], pos[1] + rel[1], pos[0] + rel[2], pos[1] + rel[3])
        if ref in st: newcy[ref] = c
        hw = 0.5 * len(ref) * 0.9 * 1.0 + 0.1
        lbox[ref] = ((c[0] + c[2]) / 2 - hw, c[3] + LABEL_UP - 0.1, (c[0] + c[2]) / 2 + hw, c[3] + LABEL_UP + 1.1)
        lx, ly = (c[0] + c[2]) / 2 + SX, SY - (c[3] + LABEL_UP + 0.5)              # label centre, sheet mm
        dx, dy = lx - fx, ly - fy
        a = math.radians(fa)
        loc = (dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a))
        i = blk.index('(property "Reference" "%s"' % ref); j = blk.index('\n\t\t)', i)
        prop = re.sub(r'\(at [-\d.]+ [-\d.]+(?: [-\d.]+)?\)', '(at %s %s 0)' % (fmt(loc[0]), fmt(loc[1])), blk[i:j], count=1)
        t = t[:s] + blk[:i] + prop + blk[j:] + t[e:]
    for ref, word in BNCS.items():                     # 3. BNCs
        s, e = fp_span(t, ref); blk = t[s:e]
        fx, fy, fa, _ = fp_at(blk)
        ox, oy = fx - SX, SY - fy
        lm = re.search(r'\n\t\(gr_text "%s"\n\t\t\(at ([-\d.]+) ([-\d.]+)( [-\d.]+)?\)' % re.escape(word), t)
        nl = lm.group(0).replace('(at %s %s' % (lm.group(1), lm.group(2)), '(at %s %s' % (fmt(ox + BNC_LABEL_OFFSET[0] + SX), fmt(SY - (oy + BNC_LABEL_OFFSET[1]))), 1)
        t = t.replace(lm.group(0), nl, 1)
        k = t.index('(gr_text "%s"' % word); k2 = t.index('\n\t)', k)
        t = t[:k] + t[k:k2].replace('\n\t\t\t(justify left)', '') + t[k2:]
        s, e = fp_span(t, ref); blk = t[s:e]
        X, Y = ox + BNC_DES_OFFSET[0] + SX, SY - (oy + BNC_DES_OFFSET[1])
        dx, dy = X - fx, Y - fy; a = math.radians(fa)
        loc = (dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a))
        i = blk.index('(property "Reference" "%s"' % ref); j = blk.index('\n\t\t)', i)
        prop = re.sub(r'\(at [-\d.]+ [-\d.]+(?: [-\d.]+)?\)', '(at %s %s)' % (fmt(loc[0]), fmt(loc[1])), blk[i:j], count=1)
        prop = re.sub(r'\(layer "[^"]*"\)', '(layer "B.SilkS")', prop, count=1)
        if '(justify mirror)' not in prop:
            q = prop.rindex('\n\t\t\t)'); prop = prop[:q] + '\n\t\t\t\t(justify mirror)' + prop[q:]
        t = t[:s] + blk[:i] + prop + blk[j:] + t[e:]
    # the block's name (silk text "CH2") moves to the free corner found by scratch-outputs/relayout-mock/freespot.py: 0.5 mm clear of every label and courtyard
    m = re.search(r'\n\t\(gr_text "CH2"\n\t\t\(at ([-\d.]+) ([-\d.]+)', t)
    t = t.replace(m.group(0), m.group(0).replace('(at %s %s' % (m.group(1), m.group(2)), '(at %s %s' % (fmt(BLOCK_NAME_AT[0] + SX), fmt(SY - BLOCK_NAME_AT[1]))), 1)
    # 4. copper
    removed = {}
    def hit(a, b, w, r, g):
        x0, y0, x1, y1 = r[0] - g - w, r[1] - g - w, r[2] + g + w, r[3] + g + w
        t0, t1 = 0.0, 1.0; dx, dy = b[0] - a[0], b[1] - a[1]
        for p_, q_ in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
            if p_ == 0:
                if q_ < 0: return False
            else:
                u = q_ / p_
                if p_ < 0:
                    if u > t1: return False
                    t0 = max(t0, u)
                else:
                    if u < t0: return False
                    t1 = min(t1, u)
        return t0 <= t1
    def drop(m, pts, w, net):
        P = [(x - SX, SY - y) for x, y in pts]
        why = None
        if net in OWN: why = 'own net'
        elif any(hit(P[0], P[-1], w / 2, c, 0.15) for c in newcy.values()): why = 'under a new courtyard'
        elif P[0] == P[-1] and any(hit(P[0], P[-1], w / 2, c, 0.1) for c in lbox.values()): why = 'under a label (vias only; traces may run under labels)'
        elif net in SHARED and any(math.hypot(p[0] - o[0], p[1] - o[1]) < 0.4 for p in P for o in oldpads): why = 'was on a moved part'
        if why: removed.setdefault((net, why), []).append(1)
        return why is not None
    # old pads, not part origins: gather every pad centre of the moved parts before the move
    oldpads[:] = [tuple(p) for p in json.load(open(place))['old_pads']]
    def segsub(m):
        a = [float(m.group(i)) for i in (1, 2, 3, 4)]
        return '' if drop(m, [(a[0], a[1]), (a[2], a[3])], float(m.group(5)), m.group(7)) else m.group(0)
    t = re.sub(r'\n\t\(segment\n\t\t\(start ([-\d.]+) ([-\d.]+)\)\n\t\t\(end ([-\d.]+) ([-\d.]+)\)\n\t\t\(width ([\d.]+)\)\n\t\t\(layer "([^"]*)"\)\n\t\t\(net "([^"]*)"\)\n\t\t\(uuid "[^"]*"\)\n\t\)', segsub, t)
    def viasub(m):
        x, y, sz = float(m.group(1)), float(m.group(2)), float(m.group(3))
        return '' if drop(m, [(x, y), (x, y)], sz, m.group(4)) else m.group(0)
    t = re.sub(r'\n\t\(via\n\t\t\(at ([-\d.]+) ([-\d.]+)\)\n\t\t\(size ([\d.]+)\)\n\t\t\(drill [\d.]+\)\n\t\t\(layers "F\.Cu" "B\.Cu"\)\n\t\t\(net "([^"]*)"\)\n\t\t\(uuid "[^"]*"\)\n\t\)', viasub, t)
    ex = BLOCK_EXT[0] if BLOCK_EXT else (0, 0, 0, 0)
    def edge(m):
        a = [float(m.group(i)) for i in (1, 2, 3, 4)]
        if abs(a[0] - (69.0 + SX)) < 1e-6 and abs(a[2] - a[0]) < 1e-6:                  # a piece of the old west edge, sheet mm
            lo, hi = sorted((a[1], a[3])); cut = SY - ex[1]; top = SY - ex[3]          # the extension spans sheet y top..cut
            if hi <= cut and lo >= top - 1e-6: return ''
            if lo < cut and hi > cut:                                                  # keep [cut, hi]
                y0, y1 = (cut, hi) if a[1] <= a[3] else (hi, cut)
                return m.group(0).replace('(start %s %s)' % (m.group(1), m.group(2)), '(start %s %s)' % (m.group(1), fmt(y0))).replace('(end %s %s)' % (m.group(3), m.group(4)), '(end %s %s)' % (m.group(3), fmt(y1)))
        return m.group(0)
    t = re.sub(r'\n\t\(gr_line\n\t\t\(start ([-\d.]+) ([-\d.]+)\)\n\t\t\(end ([-\d.]+) ([-\d.]+)\)\n\t\t\(stroke(?:(?!\n\t\)).)*?\(layer "F\.SilkS"\)\n\t\t\(uuid "[^"]*"\)\n\t\)', edge, t, flags=re.S)
    # 5. outline of the west extension: the old west edge between its two ends is replaced by the extension's outline
    lines = []
    for (x0, y0, x1, y1) in BLOCK_EXT:
        for (a, b, c, d) in ((x0, y0, x0, y1), (x0, y1, x1, y1), (x0, y0, x1, y0)):
            lines.append('\n\t(gr_line\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(stroke\n\t\t\t(width 0.15)\n\t\t\t(type default)\n\t\t)\n\t\t(layer "F.SilkS")\n\t\t(uuid "%s")\n\t)'
                         % (fmt(a + SX), fmt(SY - b), fmt(c + SX), fmt(SY - d), uuid.uuid5(uuid.NAMESPACE_URL, 'ch2ext%s%s%s%s' % (a, b, c, d))))
    k = t.index('\n\t(gr_line'); t = t[:k] + ''.join(lines) + t[k:]
    open(out, 'w').write(t)
    for (n, w), v in sorted(removed.items()): print('removed %3d  %s  (%s)' % (len(v), n, w))


if __name__ == '__main__':
    main(*sys.argv[1:4])
