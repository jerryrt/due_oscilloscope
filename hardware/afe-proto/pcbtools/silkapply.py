"""Apply a silk placement (pcbtools.silkplace) to a board TEXT, as a splice: only the (at x y [angle]) of each moved designator's Reference
field changes, in the footprint's own frame. No pcbnew rewrite (that reformats the file and reorders its zones), so the rest of the file stays
byte for byte, and the project file is not touched. Board-agnostic: the config is the placer's.

    python3 -m pcbtools.silkapply BOARD.kicad_pcb --config v2_layout [--keep REF ...] [--write OUT.kicad_pcb]      (in the PCB image)

    apply_moves(text, b, placed) -> new text        placed {ref: (x, y, angle)} in Due mm, the centre of the text and 0 or 90 degrees

The field's position is in the footprint's own frame (turned with it); its angle is the text's own board angle, 0 or 90 as the placer gives it
(boardio reads the field's angle as written). A part with a designator off the silk (a keyed part) is skipped. Idempotent: placing the placed board again moves nothing
(`main` reports how many moved, and a second run on its own output reports 0).
"""
import argparse
import importlib
import math
import re
import sys

from . import silkplace


def _rot(a, x, y):
    c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
    return x * c + y * s, -x * s + y * c


def _fmt(v):
    return ('%.4f' % v).rstrip('0').rstrip('.') or '0'


def _span(text, ref):
    for m in re.finditer(r'\n\t\(footprint "[^"]*"\n', text):
        end = text.find('\n\t(footprint ', m.end())
        end = len(text) if end < 0 else end
        if re.search(r'\(property "Reference" "%s"' % re.escape(ref), text[m.start():end]):
            return m.start(), end
    raise KeyError(ref)


def apply_moves(text, b, placed):
    """(new text, [refs whose text changed])"""
    changed = []
    for ref, (x, y, a) in sorted(placed.items()):
        s, e = _span(text, ref)
        blk = text[s:e]
        fm = re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', blk)
        fx, fy, fa = float(fm.group(1)), float(fm.group(2)), float(fm.group(3) or 0)
        lx, ly = _rot(-fa, (x + 50.0) - fx, (150.0 - y) - fy)                    # sheet mm -> the footprint's frame
        pat = re.compile(r'(\(property "Reference" "%s"\n\t\t\t\(at )([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?(\)\n\t\t\t\(layer ")([^"]*)(")' % re.escape(ref))
        m = pat.search(blk)
        if m is None or m.group(6) != 'F.SilkS':
            continue                                                              # off the silk (a keyed part): not ours to move
        want = float(a)                                                           # the field's angle is the text's own (board) angle, not relative
        new = f'{m.group(1)}{_fmt(lx)} {_fmt(ly)}' + (f' {_fmt(want)}' if want else '') + m.group(5) + m.group(6) + m.group(7)
        if (_fmt(float(m.group(2))), _fmt(float(m.group(3))), float(m.group(4) or 0)) != (_fmt(lx), _fmt(ly), want):
            blk = blk[:m.start()] + new + blk[m.end():]
            text = text[:s] + blk + text[e:]
            changed.append(ref)
    return text, changed


MAX_PASSES = 6


def settle(b, text, cfg, margin=0.25, keep=()):
    """the placer's result with the board's own silk lines and words as obstacles, and each part it could not place counted as staying where its
    text is for the others (run again until the unplaced set stops growing): a placed text then lies on no residue text either"""
    from . import keys
    silk = keys.silk_boxes(text, cfg)
    stay = set(keep)
    while True:
        placed, unplaced = silkplace.place(b, cfg, margin, tuple(stay), silk)
        if set(unplaced) <= stay:
            return placed, sorted(stay - set(keep) | set(unplaced))
        stay |= set(unplaced)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python3 -m pcbtools.silkapply', description=__doc__.split('\n')[0])
    ap.add_argument('board')
    ap.add_argument('--config', default='v2_layout')
    ap.add_argument('--margin', type=float, default=0.25, help='D30 asks 0.25 (the placer\'s own default is 0.30)')
    ap.add_argument('--keep', nargs='*', default=[])
    ap.add_argument('--write')
    a = ap.parse_args(argv)
    from . import boardio
    import os
    import tempfile
    cfg = importlib.import_module(f'pcbtools.boards.{a.config}')
    with open(a.board) as fh:
        text = fh.read()
    first = text
    moved = set()
    for _ in range(MAX_PASSES):                       # the placement of one pass is the start of the next, until it moves nothing
        with tempfile.TemporaryDirectory() as d:
            path = a.board if text == first else os.path.join(d, 'pass.kicad_pcb')
            if text != first:
                with open(path, 'w') as fh:
                    fh.write(text)
            b = boardio.read_board(path)
            placed, unplaced = settle(b, text, cfg, a.margin, a.keep)
        text, changed = apply_moves(text, b, placed)
        moved |= set(changed)
        if not changed:
            break
    new = text
    print(f'placed {len(placed)} ({len(moved)} moved), unplaced {len(unplaced)}: {" ".join(unplaced)}')
    if a.write:
        with open(a.write, 'w') as fh:
            fh.write(new)
    return 0


if __name__ == '__main__':
    sys.exit(main())
