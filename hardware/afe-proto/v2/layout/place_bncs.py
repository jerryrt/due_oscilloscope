"""Put the three BNCs where the config says (boards/v2_layout.py BNC_X, BNC_Y, SCOPE_PITCH; owner's ruling 2026-11-13) and keep
everything that hangs on them with them. Pure text editing, no KiCad needed; idempotent (a board already at the config is written back
unchanged).

    python3 v2/layout/place_bncs.py BOARD.kicad_pcb [--write OUT.kicad_pcb]

For each BNC whose footprint is not at its configured y, by delta = new y - old y:
  - the footprint's own position moves (its pads, silk and designator are relative to it);
  - its input label ("CH1 IN", "CH2 IN") moves with it, and the scope boxes' silk lines (outlines.py) move by the same delta, except a line
    that lies on the edge of a box that did not move (the AWG's top edge, which CH2's box used to share); draw_outlines then draws what
    the new table lacks (CH2's own bottom edge);
  - the input run (the track from pin 1 to the first part of the input network, on pin 1's net) is replaced: horizontal from the pad to
    the east edge of the BNC fence plus |delta|, 45 degrees back to the old y at the fence edge, then the old run's own y to where it
    ended. The diagonal lies wholly inside the BNC fence rectangle, so the only copper outside a fence is the straight corridor the old
    run already had. Net, width, layer and the far end are the old run's.
The fills are stale afterwards: refill with v2/layout/refill_zones.py (in the image).
"""
import os
import re
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import draw_outlines  # noqa: E402
import outlines_from_silk as ofs  # noqa: E402
from pcbtools.boards import v2_layout as cfg  # noqa: E402

SX, SY = 50.0, 150.0          # Due mm -> sheet mm: x + 50, 150 - y
TOL = 1e-3
KEEP_SLACK = 0.1              # the AWG box's top edge is drawn 0.05 mm longer than the box (the shared line)


def fmt(v):
    return ('%.4f' % v).rstrip('0').rstrip('.')


def _fp_span(text, ref):
    """(start, end) of the footprint block of `ref`"""
    for m in re.finditer(r'\n\t\(footprint "[^"]*"\n', text):
        end = text.find('\n\t(footprint ', m.end())
        end = len(text) if end < 0 else end
        if re.search(r'\(property "Reference" "%s"' % re.escape(ref), text[m.start():end]):
            return m.start(), end
    raise KeyError(ref)


def footprint_y(text, ref):
    s, e = _fp_span(text, ref)
    m = re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)( [-\d.]+)?\)', text[s:e])
    return SY - float(m.group(2))


def move_footprint(text, ref, y):
    s, e = _fp_span(text, ref)
    blk = text[s:e]
    new = re.sub(r'(\n\t\t\(at [-\d.]+ )([-\d.]+)', lambda m: m.group(1) + fmt(SY - y), blk, count=1)
    return text[:s] + new + text[e:]


def pin1_net(text, ref):
    s, e = _fp_span(text, ref)
    return re.search(r'\(pad "1" .*?\(net "([^"]*)"\)', text[s:e], re.S).group(1)


def shift_label(text, label, delta):
    """the gr_text `label` moves by delta (Due y up, so the sheet y goes the other way)"""
    pat = re.compile(r'(\n\t\(gr_text "%s"\n\t\t\(at [-\d.]+ )([-\d.]+)' % re.escape(label))
    assert len(pat.findall(text)) == 1, label
    return pat.sub(lambda m: m.group(1) + fmt(float(m.group(2)) - delta), text)


def _on_edge(rect, seg, slack=TOL):
    """a sheet-mm silk line lies on an edge of a Due-mm rectangle (its ends within `slack` of the edge's extent)"""
    x0, y1 = rect[0] + SX, SY - rect[1]
    x1, y0 = rect[2] + SX, SY - rect[3]
    a, b, c, d = seg
    if abs(b - d) < TOL:
        return (abs(b - y0) < TOL or abs(b - y1) < TOL) and x0 - slack <= min(a, c) and max(a, c) <= x1 + slack
    if abs(a - c) < TOL:
        return (abs(a - x0) < TOL or abs(a - x1) < TOL) and y0 - slack <= min(b, d) and max(b, d) <= y1 + slack
    return False


def shift_box(text, old_rect, delta, keep_rects):
    """the silk lines on the edges of old_rect (Due mm) move by delta, unless they also lie on an edge of one of keep_rects"""
    pat = re.compile(r'\n\t\(gr_line\n\t\t\(start ([-\d.]+) ([-\d.]+)\)\n\t\t\(end ([-\d.]+) ([-\d.]+)\)(.*?)\n\t\t\(layer "F\.SilkS"\)', re.S)
    n = [0]

    def sub(m):
        seg = tuple(float(m.group(i)) for i in (1, 2, 3, 4))
        if not _on_edge(old_rect, seg) or any(_on_edge(k, seg, KEEP_SLACK) for k in keep_rects):
            return m.group(0)
        n[0] += 1
        return m.group(0).replace(f'(start {m.group(1)} {m.group(2)})', f'(start {m.group(1)} {fmt(float(m.group(2)) - delta)})') \
                         .replace(f'(end {m.group(3)} {m.group(4)})', f'(end {m.group(3)} {fmt(float(m.group(4)) - delta)})')
    return pat.sub(sub, text), n[0]


def _segment(x0, y0, x1, y1, w, layer, net, key):
    return ('\n\t(segment\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(width %s)\n\t\t(layer "%s")\n\t\t(net "%s")\n\t\t(uuid "%s")\n\t)'
            % (fmt(x0), fmt(y0), fmt(x1), fmt(y1), w, layer, net, uuid.uuid5(uuid.NAMESPACE_URL, key)))


_SEG = re.compile(r'\n\t\(segment\n\t\t\(start ([-\d.]+) ([-\d.]+)\)\n\t\t\(end ([-\d.]+) ([-\d.]+)\)\n\t\t\(width ([\d.]+)\)\n\t\t\(layer "([^"]*)"\)\n\t\t\(net "%s"\)\n\t\t\(uuid "[^"]*"\)\n\t\)')


def reroute(text, ref, y_old, y_new, fence_x0):
    """rebuild the lead from pin 1 (x = BNC_X, y_old) on pin 1's net: pad -> [east stub] -> jog -> the corridor, which keeps its own y and far
    end. The run as found is either the old straight corridor from the pad (one segment) or a lead this function made (a stub, a jog and the
    corridor); the corridor is the last segment, horizontal, starting at the west edge of the BNC fence. The jog runs at 45 degrees from
    x = fence edge + |dy| when that is no further east than the pad's centre, else from the pad's centre at the steeper angle that reaches the
    fence edge."""
    net = pin1_net(text, ref)
    segs = [(m, tuple(float(m.group(i)) for i in (1, 2, 3, 4)), m.group(5), m.group(6)) for m in re.finditer(_SEG.pattern % re.escape(net), text)]
    key = lambda v: (round(v[0], 3), round(v[1], 3))
    cur = (round(cfg.BNC_X + SX, 3), round(SY - y_old, 3))
    chain = []
    while True:
        nxt = [s for s in segs if key(s[1][:2]) == cur and s not in chain]
        if not nxt:
            break
        chain.append(nxt[0])
        if nxt[0][1][0] <= fence_x0 + SX + 1e-3 and abs(nxt[0][1][1] - nxt[0][1][3]) < 1e-6:
            break                                                        # the corridor: it starts at the fence edge and is horizontal
        cur = key(nxt[0][1][2:])
    assert chain and len(chain) in (1, 3), (ref, net, len(chain))
    corridor = chain[-1]
    cx0, cy0, cx1, cy1 = corridor[1]
    w, layer = corridor[2], corridor[3]
    x_b, y_b = cx0, cy0                                                  # the corridor's west end: the fence edge, the corridor's own y
    assert abs(x_b - (fence_x0 + SX)) < 1e-3 or len(chain) == 1, (x_b, fence_x0)
    d = abs((SY - y_new) - y_b)
    x_a = min(x_b + d, cfg.BNC_X + SX)
    keyb = f'place_bncs {ref} {net}'
    pad_xy = (cfg.BNC_X + SX, SY - y_new)
    segs_new = []
    if len(chain) == 1:                                                  # old straight run: split it at the fence edge
        x_b = fence_x0 + SX
        corridor_new = (x_b, y_b, cx1, cy1)
    else:
        corridor_new = None
    if x_a < pad_xy[0] - 1e-6:
        segs_new.append((pad_xy[0], pad_xy[1], x_a, pad_xy[1]))
    segs_new.append((x_a, pad_xy[1], x_b, y_b))
    if corridor_new:
        segs_new.append(corridor_new)
    first = chain[0][0].start()
    last = chain[-1][0].end()
    body = ''.join(_segment(*s, w, layer, net, f'{keyb} {i}') for i, s in enumerate(segs_new))
    if len(chain) == 3:                                                  # keep the corridor segment byte for byte
        assert chain[1][0].start() == chain[0][0].end() and chain[1][0].end() == chain[2][0].start(), 'the lead is not three adjacent segments'
        last = chain[1][0].end()
    text = text[:first] + body + text[last:]
    return text, segs_new


def fence_x0_for(ref_y_old):
    """x of the west edge of the SCOPE/AWG fence rectangle that holds the BNC pad"""
    for name, rects in cfg.FENCES.items():
        for (x0, y0, x1, y1) in rects:
            if x0 <= cfg.BNC_X <= x1 and y0 <= ref_y_old <= y1:
                return x0
    raise KeyError(ref_y_old)


def set_label(text, ref, x, y):
    """the Reference text of `ref` centred at (x, y) Due mm, turn unchanged (the footprint is not rotated: its text offset is relative)"""
    s, e = _fp_span(text, ref)
    blk = text[s:e]
    fm = re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)( [-\d.]+)?\)', blk)
    assert not fm.group(3) or abs(float(fm.group(3))) < 1e-9, f'{ref} is rotated: set_label assumes an unrotated footprint'
    fx, fy = float(fm.group(1)), float(fm.group(2))
    pat = re.compile(r'(\(property "Reference" "%s"\n\t\t\t\(at )([-\d.]+) ([-\d.]+)( [-\d.]+\))' % re.escape(ref))
    m = pat.search(blk)
    new = (fmt(x + SX - fx), fmt(SY - y - fy))
    if (fmt(float(m.group(2))), fmt(float(m.group(3)))) == new:
        return text, False
    blk = pat.sub(lambda m: m.group(1) + new[0] + ' ' + new[1] + m.group(4), blk, count=1)
    return text[:s] + blk + text[e:], True


def place(text):
    """(new text, report lines)"""
    import outlines
    rep = []
    old_rects = {}
    moves = []
    for ref, y in cfg.BNC_Y.items():
        cur = footprint_y(text, ref)
        if abs(cur - y) > TOL:
            moves.append((ref, cur, y))
    keep = [r for r in outlines.RECTS['AWG'][1:]]
    for ref, cur, y in moves:
        delta = y - cur
        block = {'J101': 'CH1', 'J201': 'CH2'}.get(ref)
        if block is None:
            raise SystemExit(f'{ref} is not a scope BNC: its run and box are not handled here')
        lo, hi = outlines.BNC_BOX[block]
        old_rect = (98.5, round(cur + lo, 3), 116.4, round(cur + hi, 3))
        fx = fence_x0_for(cur)
        text = move_footprint(text, ref, y)
        text = shift_label(text, f'{block} IN', delta)
        text, nlines = shift_box(text, old_rect, delta, keep)
        text, segs = reroute(text, ref, cur, y, fx)
        rep.append(f'{ref}: y {cur:g} -> {y:g}, label and {nlines} silk lines moved, run replaced by {len(segs)} segments')
    for ref, (x, y) in cfg.DESIGNATOR_AT.items():
        text, did = set_label(text, ref, x, y)
        if did:
            rep.append(f'{ref}: designator to ({x:g}, {y:g})')
    text, added = draw_outlines.draw(text)
    if added:
        rep.append(f'silk drawn for {len(added)} rectangle(s) of the table that the box move left without')
    return text, rep


def main(argv):
    src = argv[1]
    out = argv[argv.index('--write') + 1] if '--write' in argv else None
    with open(src) as fh:
        text = fh.read()
    new, rep = place(text)
    print('\n'.join(rep) or 'already at the config')
    if out:
        with open(out, 'w') as fh:
            fh.write(new)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
