"""Connector boxes: a box round each listed connector's own silk, with one margin on all sides, and the connector's designator and function text turned and set in the
left margin at offsets from the footprint origin, the same for every connector of the set.

    bnc_layout(lb, cfg) -> dict(margin, rects {ref: box}, labels {ref: (x, y, 90)}, texts {ref: (text, x, y_bottom, 90)}, fixed {'fn_REF': box})

`BNC` maps the connector references to their function text; the margin is (pitch - silk height) / 2, pitch being the distance between the first two connectors, so that two
neighbouring boxes share one line. Names: BNC, BNC_DES_DY, BNC_FN_DY, BNC_LINE (half the outline line width), BNC_MARGIN (None = derived)."""
from . import _g as G
from .placer import Cfg, NEEDS


def bnc_layout(lb, cfg):
    c = Cfg(cfg, NEEDS['bnc_layout'])
    refs = list(c.BNC)
    if not refs:
        return None
    silk = {r: lb.parts[r].silk for r in refs}
    if any(v is None for v in silk.values()):
        raise ValueError('a connector in BNC has no footprint silk to box: %s' % [r for r, v in silk.items() if v is None])
    h = silk[refs[0]][3] - silk[refs[0]][1]
    pitch = abs(lb.parts[refs[0]].y - lb.parts[refs[1]].y) if len(refs) > 1 else None
    m = c.BNC_MARGIN if c.BNC_MARGIN is not None else (pitch - h) / 2
    rects = {r: (round(b[0] - m, 3), round(b[1] - m, 3), round(b[2] + m, 3), round(b[3] + m, 3)) for r, b in silk.items()}
    bx = silk[refs[0]][0] - (m - c.BNC_LINE) / 2                       # the middle of the clear width between the box's west line and the silk
    labels, texts, fixed = {}, {}, {}
    for r in refs:
        oy = lb.parts[r].y
        labels[r] = (round(bx, 3), round(oy + c.BNC_DES_DY, 3), 90)
        t = c.BNC[r]
        yb = oy + c.BNC_FN_DY
        texts[r] = (t, round(bx, 3), round(yb, 3), 90)
        hh = c.DESIGNATOR_INK_H * c.DESIGNATOR_H
        fixed['fn_' + r] = (bx - hh / 2, yb, bx + hh / 2, yb + len(t) * c.DESIGNATOR_ADVANCE * c.DESIGNATOR_H)
    return dict(margin=m, rects=rects, labels=labels, texts=texts, fixed=fixed)
