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


def _bottom_designator(text, ref, x, y):
    """the Reference of `ref` on B.SilkS, mirrored (it reads from the bottom), its centre at (x, y) Due mm, angle 0; idempotent"""
    s, e = silkapply._span(text, ref)
    blk = text[s:e]
    fm = re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', blk)
    fx, fy, fa = float(fm.group(1)), float(fm.group(2)), float(fm.group(3) or 0)
    lx, ly = silkapply._rot(-fa, (x + 50.0) - fx, (150.0 - y) - fy)
    i = blk.index('(property "Reference" "%s"' % ref)
    j = blk.index('\n\t\t)', i)                                                                   # the property's closing paren
    prop = blk[i:j]
    prop = re.sub(r'\(at [-\d.]+ [-\d.]+(?: [-\d.]+)?\)', f'(at {silkapply._fmt(lx)} {silkapply._fmt(ly)})', prop, count=1)
    prop = re.sub(r'\(layer "[^"]*"\)', '(layer "B.SilkS")', prop, count=1)
    if '(justify mirror)' not in prop:
        k = prop.rindex('\n\t\t\t)')                                                               # the effects block's closing paren
        prop = prop[:k] + '\n\t\t\t\t(justify mirror)' + prop[k:]
    return text[:s] + blk[:i] + prop + blk[j:] + text[e:]


def _centred(text, x, y, word):
    """the label's `(justify left)` taken off, so the position is the text's centre (the checker reads it as one)"""
    i = text.index('(gr_text "%s"' % word)
    j = text.index('\n\t)', i)
    blk = text[i:j].replace('\n\t\t\t(justify left)', '')
    return text[:i] + blk + text[j:]


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
        dx, dy = cfg.BNC_DESIGNATOR_OFFSET                                                       # board mm from each BNC's origin, the same for all three
        for ref in refs:
            x, y, rot = _origin(text, ref)
            assert abs(rot - rot0) < 1e-6, f'{ref} is turned differently from {first}: the frame offset is not a board offset'
            lm = _label(text, labels[ref])
            nx, ny = x + off[0] + 50.0, 150.0 - (y + off[1])
            old = lm.group(0)
            text = text.replace(old, old.replace(f'(at {lm.group(1)} {lm.group(2)}', f'(at {silkapply._fmt(nx)} {silkapply._fmt(ny)}', 1), 1)
            text = _centred(text, nx, ny, labels[ref])
            text = _bottom_designator(text, ref, x + dx, y + dy)
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
