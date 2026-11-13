"""LR-11: board-level silk carries no arrow (docs/afe-v2.md). An arrowhead is two short silk lines that meet at one end point and open at an
acute angle; a closed triangle contains one, so the single test finds both. Outline and block drawing lines are long, collinear or at right
angles, and none of them qualifies. Reads the .kicad_pcb text, no pcbnew."""
import math
import re

MAX_LEN = 2.0                    # mm: a head side is short; a block outline side is longer or a collinear dash
MIN_DEG, MAX_DEG = 10.0, 80.0    # the opening of the V; a dashed outline's corner is 90 degrees and a straight run 180


def silk_segments(txt):
    """[(x0, y0, x1, y1)] of the top-level gr_line items on F.SilkS or B.SilkS"""
    out = []
    for m in re.finditer(r'\n\t\(gr_line\n(.*?)\n\t\)', txt, re.S):
        b = m.group(1)
        lay = re.search(r'\(layer "([^"]+)"', b)
        s = re.search(r'\(start ([-\d.]+) ([-\d.]+)\)', b)
        e = re.search(r'\(end ([-\d.]+) ([-\d.]+)\)', b)
        if lay and lay.group(1) in ('F.SilkS', 'B.SilkS') and s and e:
            out.append((float(s.group(1)), float(s.group(2)), float(e.group(1)), float(e.group(2))))
    return out


def arrowheads(segs, tol=1e-3):
    """[(x, y, angle_deg)] of every point where two short segments meet at an acute angle"""
    short = [s for s in segs if 0 < math.hypot(s[2] - s[0], s[3] - s[1]) <= MAX_LEN]
    ends = []                                           # (point, direction away from the point)
    for x0, y0, x1, y1 in short:
        ends.append(((x0, y0), (x1 - x0, y1 - y0)))
        ends.append(((x1, y1), (x0 - x1, y0 - y1)))
    found = set()
    for i in range(len(ends)):
        for j in range(i + 1, len(ends)):
            (p, u), (q, v) = ends[i], ends[j]
            if abs(p[0] - q[0]) > tol or abs(p[1] - q[1]) > tol:
                continue
            c = (u[0] * v[0] + u[1] * v[1]) / (math.hypot(*u) * math.hypot(*v))
            a = math.degrees(math.acos(max(-1.0, min(1.0, c))))
            if MIN_DEG <= a <= MAX_DEG:
                found.add((round(p[0], 3), round(p[1], 3), round(a, 1)))
    return sorted(found)
