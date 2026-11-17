"""names.py IN.kicad_pcb OUT.kicad_pcb RECTS.json REPORT.json    (in the PCB image)

Block names (POWER, REF / CAL, CH1, CH2, AWG): one text size, 1.2 mm (as AFE-1), each at a CORNER of its block's main rectangle, inside it. The same corner for every
block wherever it fits: north-west is tried first for all; a block whose north-west corner is taken by a part, pad or other text takes the next corner in the order
NE, SW, SE and is named in the report. Inside means the text box (1.2 mm high, 0.95 mm advance per character) is 0.3 mm clear of the rectangle's lines; it must
lie on no courtyard, pad or other text. Silk text only: the gr_text's position and size change."""
import sys, re, json, math
sys.path.insert(0, '/work/hardware/afe-proto'); sys.path.append('/usr/lib/python3/dist-packages')
import numpy as np
from pcbtools import boardio, silkread as S

inp, out, rects_p, rep_p = sys.argv[1:5]
RECTS = json.load(open(rects_p)); txt = open(inp).read(); b = boardio.read_board(inp)
refs = list(b.fp_ref)
cour = [S._box(b.fp_cx0[i], b.fp_cy0[i], b.fp_cx1[i], b.fp_cy1[i]) for i in range(len(refs)) if int(b.fp_side[i]) == 0 and not np.isnan(b.fp_cx0[i])]
pads = [(x0, y0, x1, y1) for x0, y0, x1, y1 in zip(b.p_bx0, b.p_by0, b.p_bx1, b.p_by1)]
NAMES = {'POWER': 'POWER', 'REF / CAL': 'REFCAL', 'CH1': 'CH1', 'CH2': 'CH2', 'AWG': 'AWG'}
SIZE = 1.2
others = [(t.decode() if isinstance(t, bytes) else t, float(x), float(y), float(h)) for t, x, y, h in zip(b.t_text, b.t_x, b.t_y, b.t_h)]


def tbox(t, x, y):
    L = len(t) * 0.95 * SIZE
    return (x - L / 2, y - SIZE * 0.6, x + L / 2, y + SIZE * 0.6)


def lgap(a, c): return math.hypot(max(c[0] - a[2], 0.0, a[0] - c[2]), max(c[1] - a[3], 0.0, a[1] - c[3]))


def free(t, x, y, placed):
    bx = tbox(t, x, y)
    if any(S._overlap(bx, c) for c in cour): return False
    if any(lgap(bx, p) < 0.15 for p in pads): return False
    for (q, qx, qy, qh) in others:
        if q in NAMES or q == t: continue
        L = max(len(q) * 0.95 * qh, qh)
        if lgap(bx, (qx - L / 2, qy - L / 2, qx + L / 2, qy + L / 2)) < 0.4: return False
    return all(lgap(bx, o) >= 0.5 for o in placed.values())


placed = {}; report = {}
ORDER = ['NW', 'NE', 'SW', 'SE']
choice = {}
for corner in ORDER:                                         # try the same corner for every block first
    ok_all = True; trial = {}
    for t, blk in NAMES.items():
        rs = RECTS[blk]; x0, y0, x1, y1 = max(rs, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
        L = len(t) * 0.95 * SIZE; found = None
        for d in sorted((math.hypot(i * 0.1, j * 0.1), i * 0.1, j * 0.1) for i in range(0, 120) for j in range(0, 120)):
            _, dx, dy = d
            x = (x0 + 0.3 + L / 2 + dx) if 'W' in corner else (x1 - 0.3 - L / 2 - dx)
            y = (y1 - 0.3 - SIZE * 0.6 - dy) if corner[0] == 'N' else (y0 + 0.3 + SIZE * 0.6 + dy)
            if x - L / 2 < x0 + 0.3 - 1e-9 or x + L / 2 > x1 - 0.3 + 1e-9 or y - SIZE * 0.6 < y0 + 0.3 - 1e-9 or y + SIZE * 0.6 > y1 - 0.3 + 1e-9: continue
            if free(t, x, y, trial): found = (round(x, 2), round(y, 2), round(math.hypot(dx, dy), 2)); break
        if not found: ok_all = False; break
        trial[t] = tbox(t, found[0], found[1]); choice[t] = (corner, found)
    if ok_all: placed = dict(choice); report['all_blocks_at'] = corner; break
if not placed:                                               # per block: the first corner that has room
    for t, blk in NAMES.items():
        rs = RECTS[blk]; x0, y0, x1, y1 = max(rs, key=lambda r: (r[2] - r[0]) * (r[3] - r[1])); L = len(t) * 0.95 * SIZE; got = None
        for corner in ORDER:
            for d in sorted((math.hypot(i * 0.1, j * 0.1), i * 0.1, j * 0.1) for i in range(0, 120) for j in range(0, 120)):
                _, dx, dy = d
                x = (x0 + 0.3 + L / 2 + dx) if 'W' in corner else (x1 - 0.3 - L / 2 - dx)
                y = (y1 - 0.3 - SIZE * 0.6 - dy) if corner[0] == 'N' else (y0 + 0.3 + SIZE * 0.6 + dy)
                if x - L / 2 < x0 + 0.3 - 1e-9 or x + L / 2 > x1 - 0.3 + 1e-9 or y - SIZE * 0.6 < y0 + 0.3 - 1e-9 or y + SIZE * 0.6 > y1 - 0.3 + 1e-9: continue
                if free(t, x, y, {k: tbox(k, v[1][0], v[1][1]) for k, v in placed.items() if v}): got = (corner, (round(x, 2), round(y, 2), round(math.hypot(dx, dy), 2))); break
            if got: break
        placed[t] = got
    report['all_blocks_at'] = None
report['placed'] = {t: v for t, v in placed.items()}
t_ = txt
for t, v in placed.items():
    if not v:
        mm_ = re.search(r'\(gr_text "%s"\s+\(at ([-\d.]+) ([-\d.]+)' % re.escape(t), t_); v = ('kept', (float(mm_.group(1)) - 50.0, 150.0 - float(mm_.group(2))))
    (x, y) = v[1][0], v[1][1]
    m = re.search(r'\(gr_text "%s"\s+\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)\s+\(layer "F.SilkS"\)\s+\(uuid "[^"]+"\)\s+\(effects\s+\(font\s+\(size ([\d.]+) ([\d.]+)\)\s+\(thickness ([\d.]+)\)' % re.escape(t), t_)
    seg = t_[m.start():m.end()]
    seg = re.sub(r'\(at [-\d.]+ [-\d.]+(?: [-\d.]+)?\)', '(at %.3f %.3f 0)' % (x + 50.0, 150.0 - y), seg, count=1)
    seg = re.sub(r'\(size [\d.]+ [\d.]+\)', '(size %g %g)' % (SIZE, SIZE), seg, count=1)
    seg = re.sub(r'\(thickness [\d.]+\)', '(thickness %g)' % round(0.15 * SIZE, 3), seg, count=1)
    t_ = t_[:m.start()] + seg + t_[m.end():]
open(out, 'w').write(t_)
json.dump(report, open(rep_p, 'w'), indent=1)
print(json.dumps(report))
