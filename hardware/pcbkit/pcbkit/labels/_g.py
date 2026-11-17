"""Box kernels the label placer uses. Boxes are (x0, y0, x1, y1) in the board frame, y up, mm.
Moves to `pcbkit.geom` when step 1 lands; nothing else in `labels` computes a distance."""
import math


def box(x0, y0, x1, y1):
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def gap(a, c):
    """distance between two boxes, 0 when they touch or overlap"""
    return math.hypot(max(c[0] - a[2], 0.0, a[0] - c[2]), max(c[1] - a[3], 0.0, a[1] - c[3]))


def overlap(a, c):
    """true overlap of areas (touching is not overlap)"""
    return a[0] < c[2] and c[0] < a[2] and a[1] < c[3] and c[1] < a[3]


def near(a, c, m):
    """boxes closer than m on both axes (the clearance test: overlap after growing one by m)"""
    return a[0] - m < c[2] and c[0] < a[2] + m and a[1] - m < c[3] and c[1] < a[3] + m


def grow(a, m):
    return (a[0] - m, a[1] - m, a[2] + m, a[3] + m)


def centre(a):
    return ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2)


def in_box(p, a):
    return a[0] <= p[0] <= a[2] and a[1] <= p[1] <= a[3]


from ..outlines import covered      # noqa: E402,F401  (one implementation: pcbkit.outlines)
