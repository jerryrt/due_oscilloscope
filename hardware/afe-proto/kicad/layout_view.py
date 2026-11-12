"""Draw a block of the placed board for review: courtyards (red where two overlap), pads coloured by net, references,
and each net's ratsnest (minimum spanning tree over its pads).  Due coordinates.

    python3 -I layout_view.py out.svg [x0 x1 y0 y1]
"""
import math
import sys

sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew as pcb  # noqa: E402

OX, OY = 50.0, 150.0
S = 20.0     # px per mm


def due(v):
    return pcb.ToMM(v.x) - OX, OY - pcb.ToMM(v.y)


def main(out, box=(17, 117, 0, 53.34)):
    x0, x1, y0, y1 = box
    b = pcb.LoadBoard(sys.argv[3] if False else '/home/jerry/EE.Projects/due_oscilloscope/hardware/afe-proto/kicad/afe-proto.kicad_pcb')
    W, H = (x1 - x0) * S, (y1 - y0) * S
    X = lambda x: (x - x0) * S
    Y = lambda y: (y1 - y) * S
    el = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" style="background:#fff">']
    rects = []
    for f in b.GetFootprints():
        f.BuildCourtyardCaches()
        c = f.GetCourtyard(pcb.F_CrtYd).BBox()
        if c.GetWidth() == 0:
            continue
        ax, ay = due(pcb.VECTOR2I(c.GetLeft(), c.GetBottom())); bx, by = due(pcb.VECTOR2I(c.GetRight(), c.GetTop()))
        rects.append((f.GetReference(), ax, ay, bx, by))
    over = set()
    for i, a in enumerate(rects):
        for bb in rects[i + 1:]:
            if a[1] < bb[3] and bb[1] < a[3] and a[2] < bb[4] and bb[2] < a[4]:
                over.add(a[0]); over.add(bb[0])
    for ref, ax, ay, bx, by in rects:
        col = '#e00' if ref in over else '#999'
        el.append(f'<rect x="{X(ax):.1f}" y="{Y(by):.1f}" width="{(bx - ax) * S:.1f}" height="{(by - ay) * S:.1f}" '
                  f'fill="none" stroke="{col}" stroke-width="{2 if ref in over else 1}"/>')
    nets = {}
    pal = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#17becf', '#bcbd22']
    for f in b.GetFootprints():
        for p in f.Pads():
            px, py = due(p.GetPosition())
            bb = p.GetBoundingBox()
            ax, ay = due(pcb.VECTOR2I(bb.GetLeft(), bb.GetBottom())); bx, by = due(pcb.VECTOR2I(bb.GetRight(), bb.GetTop()))
            n = p.GetNetname().lstrip('/')
            col = '#bbb' if (not n or n.startswith('unconnected')) else ('#444' if n == 'GND' else pal[hash(n) % len(pal)])
            el.append(f'<rect x="{X(ax):.1f}" y="{Y(by):.1f}" width="{(bx - ax) * S:.1f}" height="{(by - ay) * S:.1f}" '
                      f'fill="{col}" opacity="0.55"/>')
            if n and not n.startswith('unconnected') and n != 'GND':
                nets.setdefault(n, []).append((px, py))
        cx, cy = due(f.GetPosition())
        el.append(f'<text x="{X(cx):.1f}" y="{Y(cy):.1f}" font-size="13" text-anchor="middle" fill="#000" '
                  f'font-family="sans-serif" font-weight="bold">{f.GetReference()}</text>')
    routed = len(b.GetTracks()) > 0
    for n, pts in nets.items():
        if routed:
            break
        col = pal[hash(n) % len(pal)]
        inn = [pts[0]]; rest = pts[1:]
        while rest:
            best = min(((math.dist(a, b), a, b) for a in inn for b in rest))
            _, a, bpt = best
            el.append(f'<line x1="{X(a[0]):.1f}" y1="{Y(a[1]):.1f}" x2="{X(bpt[0]):.1f}" y2="{Y(bpt[1]):.1f}" '
                      f'stroke="{col}" stroke-width="1.2"/>')
            inn.append(bpt); rest.remove(bpt)
        mx = sum(p[0] for p in pts) / len(pts); my = sum(p[1] for p in pts) / len(pts)
        if x0 <= mx <= x1 and y0 <= my <= y1 and len(pts) > 1:
            el.append(f'<text x="{X(mx):.1f}" y="{Y(my) - 4:.1f}" font-size="10" fill="{col}" '
                      f'font-family="sans-serif">{n}</text>')
    for t in b.GetTracks():
        if t.GetClass() == 'PCB_VIA':
            x, y = due(t.GetPosition())
            el.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="{0.3 * S:.1f}" fill="#0a0" opacity="0.8"/>')
            continue
        (xa, ya), (xb, yb) = due(t.GetStart()), due(t.GetEnd())
        col = '#c00' if t.GetLayer() == pcb.F_Cu else '#06c'
        el.append(f'<line x1="{X(xa):.1f}" y1="{Y(ya):.1f}" x2="{X(xb):.1f}" y2="{Y(yb):.1f}" stroke="{col}" '
                  f'stroke-width="{pcb.ToMM(t.GetWidth()) * S:.1f}" stroke-linecap="round" opacity="0.75"/>')
    el.append('</svg>')
    open(out, 'w').write('\n'.join(el))
    print(f'{len(over)} footprints in overlaps: {sorted(over)}')


if __name__ == '__main__':
    box = tuple(float(v) for v in sys.argv[2:6]) if len(sys.argv) >= 6 else (17, 117, 0, 53.34)
    main(sys.argv[1], box)
