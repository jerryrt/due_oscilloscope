"""The connectors' labels, fixed by rule and not by the placer (LR-11, D30 (2)).

    apply(text, cfg) -> new text

* The BNCs: each one's designator and its function label ("CH1 IN") sit at the same offset in its own frame, which for BNCs turned alike is the
  same board offset from each one's origin. The designator is the first BNC's own (a board mm offset from each origin; J101's, the one the design was drawn with); the function label's offset is the config's BNC_LABEL_OFFSET (board mm), absolute, so a second pass moves nothing.
* DESIGNATOR_AT: {ref: (x, y)} designators held at a place (J605's, above its socket).

A text splice (the designators through silkapply.apply_moves, the labels by their gr_text), idempotent.
"""
import re

from . import silkapply


def _origin(text, ref):
    s, e = silkapply._span(text, ref)
    m = re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', text[s:e])
    return float(m.group(1)) - 50.0, 150.0 - float(m.group(2)), float(m.group(3) or 0.0)


def _designator_offset(text, ref):
    """the designator's centre, board mm (Due, y up) from the footprint's origin"""
    s, e = silkapply._span(text, ref)
    blk = text[s:e]
    fm = re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', blk)
    fa = float(fm.group(3) or 0)
    m = re.search(r'\(property "Reference" "%s"\n\t\t\t\(at ([-\d.]+) ([-\d.]+)' % ref, blk)
    lx, ly = float(m.group(1)), float(m.group(2))
    bx, by = silkapply._rot(fa, lx, ly)                                                          # footprint frame -> sheet offset
    return bx, -by


def _label(text, word):
    m = re.search(r'\n\t\(gr_text "%s"\n\t\t\(at ([-\d.]+) ([-\d.]+)( [-\d.]+)?\)' % re.escape(word), text)
    return m


def apply(text, cfg):
    labels = getattr(cfg, 'BNC_LABELS', {})
    if labels:
        refs = list(labels)
        first = refs[0]
        ox, oy, rot0 = _origin(text, first)
        off = getattr(cfg, 'BNC_LABEL_OFFSET')                                                      # board mm from each BNC's origin, the same for all three
        dx, dy = _designator_offset(text, first)                                                 # the first BNC's designator offset is every one's
        placed = {}
        for ref in refs:
            x, y, rot = _origin(text, ref)
            assert abs(rot - rot0) < 1e-6, f'{ref} is turned differently from {first}: the frame offset is not a board offset'
            placed[ref] = (round(x + dx, 3), round(y + dy, 3), getattr(cfg, 'BNC_DESIGNATOR_ANGLE', 0))
            lm = _label(text, labels[ref])
            nx, ny = x + off[0] + 50.0, 150.0 - (y + off[1])
            old = lm.group(0)
            new = old.replace(f'(at {lm.group(1)} {lm.group(2)}', f'(at {silkapply._fmt(nx)} {silkapply._fmt(ny)}', 1)
            text = text.replace(old, new, 1)
        text, _ = silkapply.apply_moves(text, None, placed)
    at = {r: (x, y, 0) for r, (x, y) in getattr(cfg, 'DESIGNATOR_AT', {}).items()}
    if at:
        text, _ = silkapply.apply_moves(text, None, at)
    return text


def main(argv=None):
    import argparse
    import importlib
    ap = argparse.ArgumentParser(prog='python3 -m pcbtools.bncframe', description=__doc__.split('\n')[0])
    ap.add_argument('board')
    ap.add_argument('--config', default='v2_layout')
    ap.add_argument('--write')
    a = ap.parse_args(argv)
    cfg = importlib.import_module(f'pcbtools.boards.{a.config}')
    with open(a.board) as fh:
        text = fh.read()
    new = apply(text, cfg)
    print('changed' if new != text else 'nothing to change')
    if a.write:
        with open(a.write, 'w') as fh:
            fh.write(new)


if __name__ == '__main__':
    main()
