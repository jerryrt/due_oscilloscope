"""AFE-1 REV A silkscreen for D30 (docs/afe.md): the identity block and the five block outlines, from pcbtools/boards/v1.py.

    python3 kicad/silk_rev_a.py [BOARD] [--write OUT]       default BOARD kicad/afe-proto.kicad_pcb; no --write: list what would change

Pure text splices, idempotent, silk only (no copper, no part). Later steps (run labels, beside labels, BNC labels) have their own tools
(pcbtools/silkruns.py, silkapply.py, silkbom.py, bncframe.py) and are run in the order pcbtools/README.md gives.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, P)
sys.path.insert(0, os.path.join(P, 'v2', 'layout'))
from pcbtools.boards import v1 as cfg  # noqa: E402
import draw_outlines  # noqa: E402
import place_identity  # noqa: E402


def bnc_labels(text):
    """the function labels of cfg.BNC_LABELS as gr_text on F.SilkS (1 mm, 90 degrees) where the board has none; pcbtools/bncframe.py puts them at the frame offset"""
    import uuid
    for ref, word in cfg.BNC_LABELS.items():
        if '(gr_text "%s"' % word in text:
            continue
        item = (f'\t(gr_text "{word}"\n\t\t(at 0 0 90)\n\t\t(layer "F.SilkS")\n\t\t(uuid "{uuid.uuid5(place_identity.NS, word + "label")}")\n'
                '\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1 1)\n\t\t\t\t(thickness 0.15)\n\t\t\t)\n\t\t)\n\t)\n')
        i = text.find('\n\t(gr_text ')                       # before the first board-level text: the pin-label splice inserts after the last one and keeps both byte for byte
        text = text[:i] + '\n' + item.rstrip('\n') + text[i:]
    return text


def titles(text):
    """the block title words of cfg.TITLE_AT ({word: (x, y) or (x, y, height)}) moved to their places (centre, Due mm); the rest of each record is kept"""
    import re
    for word, at in getattr(cfg, 'TITLE_AT', {}).items():
        i = text.index('\n\t(gr_text "%s"\n' % word)
        j = text.index('\n\t)', i)
        rec = text[i:j]
        rec = re.sub(r'(\(at )[-\d.]+ [-\d.]+', lambda m: m.group(1) + f'{at[0] + 50:g} {150 - at[1]:g}', rec, count=1)
        if len(at) > 2:
            rec = re.sub(r'\(size [\d.]+ [\d.]+\)', f'(size {at[2]:g} {at[2]:g})', rec, count=1)
        text = text[:i] + rec + text[j:]
    return text


def apply(text):
    place_identity.use_design('v1')
    text = place_identity.apply(text)
    text = bnc_labels(text)
    text = titles(text)
    return draw_union(text)


def _sides(rects):
    """the boundary of a block's rectangles (Due mm): each side less the parts that lie inside the union (where another rectangle abuts or overlaps it)"""
    out = []
    for i, (x0, y0, x1, y1) in enumerate(rects):
        others = [r for j, r in enumerate(rects) if j != i]
        for kind, line, lo, hi in (('h', y0, x0, x1), ('h', y1, x0, x1), ('v', x0, y0, y1), ('v', x1, y0, y1)):
            cut = []
            for a0, b0, a1, b1 in others:
                if kind == 'h' and b0 - 1e-6 <= line <= b1 + 1e-6 and (b0 < line - 1e-6 or line < b1 - 1e-6 or True):
                    # another rectangle spans this line: the stretch of it inside the span is interior unless the line is that rectangle's own edge on the same side
                    inside = b0 + 1e-6 < line < b1 - 1e-6
                    shared = abs(line - b0) < 1e-6 or abs(line - b1) < 1e-6
                    if inside or shared:
                        cut.append((a0, a1))
                elif kind == 'v' and a0 - 1e-6 <= line <= a1 + 1e-6:
                    inside = a0 + 1e-6 < line < a1 - 1e-6
                    shared = abs(line - a0) < 1e-6 or abs(line - a1) < 1e-6
                    if inside or shared:
                        cut.append((b0, b1))
            lo_, pieces = lo, []
            for c0, c1 in sorted(cut):
                if c1 <= lo_ or c0 >= hi:
                    continue
                if c0 > lo_:
                    pieces.append((lo_, c0))
                lo_ = max(lo_, c1)
            if lo_ < hi:
                pieces.append((lo_, hi))
            for u, v in pieces:
                if v - u > 1e-6:
                    out.append((u, line, v, line) if kind == 'h' else (line, u, line, v))
    return out


def draw_union(text):
    """the outlines of cfg.SILK_OUTLINE as 0.15 mm F.SilkS lines: each block's union boundary, less what the silk already draws"""
    import outlines_from_silk as ofs
    existing = ofs.silk_segments(text)
    added = []
    for rects in cfg.SILK_OUTLINE.values():
        for (x0, y0, x1, y1) in _sides(rects):
            seg = (x0 + 50, 150 - y0, x1 + 50, 150 - y1)
            if any(abs(e[0] - seg[0]) < 0.01 and abs(e[1] - seg[1]) < 0.01 and abs(e[2] - seg[2]) < 0.01 and abs(e[3] - seg[3]) < 0.01 for e in existing):
                continue
            added.append(draw_outlines.gr_line(seg))
            existing = list(existing) + [seg]
    if not added:
        return text, []
    i = text.rstrip().rfind(')')
    return text[:i] + ''.join(added) + text[i:], added


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('board', nargs='?', default=os.path.join(HERE, 'afe-proto.kicad_pcb'))
    ap.add_argument('--write')
    a = ap.parse_args()
    src = open(a.board).read()
    out, added = apply(src)
    print(f'{len(added)} outline rectangles drawn; the board text {"changes" if out != src else "is unchanged"}')
    if a.write:
        open(a.write, 'w').write(out)
