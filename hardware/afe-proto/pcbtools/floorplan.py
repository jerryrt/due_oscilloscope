"""floorplan.py: ONE data set draws the floorplan picture and writes the interface-contract table, and can be validated.

Nothing here names a board. A board supplies a data object (a module or a SimpleNamespace) with:

    X0 X1 Y0 Y1        board outline, Due mm (x right, y up)
    FENCES             {block: [(x0, y0, x1, y1), ...]}
    CORRIDORS          {label: (x0, y0, x1, y1)}            copper a block owns outside its fence
    KEEPOUT, KEEP_R    [(x0, y0, x1, y1)] and the clearance round them (LR-5), mm
    FIXED              [(name, x, y, note)]                 parts that do not move (BNCs, holes)
    HEADERS            [(name, x_first, y, x_last)]
    COL                {block: '#rrggbb'}
    C                  [(net, from, to, edge_point, layer_width, bridge, owner, note)]   edge_point: (x, y), ('inside',) or 'plane'
    BRIDGES            [(ref, nets, (x, y) | (block,), crosses)]
    NOTES              [str]
    TITLE              picture caption

`table_md(d)`, `svg(d)` and `validate(d)` are pure functions of that object (no pcbnew, no files).
"""
import math

S = 12.0          # px per mm


def _numeric(pt):
    return len(pt) == 2 and not isinstance(pt[0], str)


def table_md(d):
    out = ['| # | net | from -> to | edge point (x, y) | layer / width | bridge | owner | note |',
           '|---|---|---|---|---|---|---|---|']
    for k, (net, frm, to, pt, lw, br, own, note) in enumerate(d.C, 1):
        p = 'plane' if pt == 'plane' else ('inside the fence' if len(pt) == 1 else f'({pt[0]}, {pt[1]})')
        out.append(f'| {k} | {net} | {frm} -> {to} | {p} | {lw} | {br} | {own} | {note} |')
    out += ['', '| bridge | nets split | at (x, y) | crosses |', '|---|---|---|---|']
    for ref, nets, at, crosses in d.BRIDGES:
        p = f'({at[0]}, {at[1]})' if _numeric(at) else f'in {at[0]}, to be placed'
        out.append(f'| {ref} | {nets} | {p} | {crosses} |')
    out += ['', 'Notes:'] + list(d.NOTES)
    return '\n'.join(out)


def svg(d):
    def px(x, y):
        return (x - d.X0 + 2) * S, (d.Y1 - y + 2) * S
    w, h = (d.X1 - d.X0 + 4) * S, (d.Y1 - d.Y0 + 4) * S
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" font-family="sans-serif">',
         f'<rect width="{w:.0f}" height="{h:.0f}" fill="#ffffff"/>']

    def rect(x0, y0, x1, y1, **a):
        ax, ay = px(x0, y1)
        bx, by = px(x1, y0)
        at = ' '.join(f'{k.replace("_", "-")}="{v}"' for k, v in a.items())
        o.append(f'<rect x="{ax:.1f}" y="{ay:.1f}" width="{bx - ax:.1f}" height="{by - ay:.1f}" {at}/>')

    def text(x, y, t, size=11, fill='#000', weight='normal'):
        a, b = px(x, y)
        o.append(f'<text x="{a:.1f}" y="{b:.1f}" font-size="{size}" fill="{fill}" font-weight="{weight}">{t}</text>')

    rect(d.X0, d.Y0, d.X1, d.Y1, fill='#f4f4f0', stroke='#000', stroke_width=2)
    for (a, b, c, e) in d.KEEPOUT:
        rect(a - d.KEEP_R, b - d.KEEP_R, c + d.KEEP_R, e + d.KEEP_R, fill='#d9822b', fill_opacity='0.10', stroke='#d9822b',
             stroke_dasharray='6 4', rx=d.KEEP_R * S)
    for name, (a, b, c, e) in d.CORRIDORS.items():
        rect(a, b, c, e, fill='#999', fill_opacity='0.25', stroke='#777', stroke_dasharray='3 3')
    for blk, rs in d.FENCES.items():
        for (a, b, c, e) in rs:
            rect(a, b, c, e, fill=d.COL[blk], fill_opacity='0.12', stroke=d.COL[blk], stroke_width=2)
        text(rs[0][0] + 0.5, rs[0][3] - 3.2, blk, 14, d.COL[blk], 'bold')
    for name, a, y, b in d.HEADERS:
        rect(min(a, b) - 1.3, y - 1.3, max(a, b) + 1.3, y + 1.3, fill='#ddd', stroke='#444')
        text(min(a, b), y + (-2.0 if y < 10 else 2.8), name, 10)
    for name, x, y, note in d.FIXED:
        a, b = px(x, y)
        o.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="5" fill="#c00"/>')
        text(x + 0.8, y + 0.4, name, 10, '#c00')
    for k, row in enumerate(d.C, 1):
        pt = row[3]
        if _numeric(pt):
            a, b = px(*pt)
            o.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="7" fill="#fff" stroke="#000"/>')
            o.append(f'<text x="{a - 4.5:.1f}" y="{b + 3.5:.1f}" font-size="10">{k}</text>')
    for ref, nets, at, crosses in d.BRIDGES:
        if _numeric(at):
            a, b = px(*at)
            o.append(f'<rect x="{a - 4:.1f}" y="{b - 4:.1f}" width="8" height="8" fill="#e63946"/>')
            text(at[0] + 0.6, at[1] - 0.3, ref, 8, '#e63946')
    text(d.X0 + 0.5, d.Y1 + 1.2, d.TITLE, 11)
    o.append('</svg>')
    return '\n'.join(o)


def _overlap(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 1e-9 and min(a[3], b[3]) - max(a[1], b[1]) > 1e-9


def dist_to_rect_boundary(p, r):
    """0 on the boundary, positive outside or inside (distance to the nearest edge), as a number of mm"""
    x, y = p
    dx = max(r[0] - x, 0.0, x - r[2])
    dy = max(r[1] - y, 0.0, y - r[3])
    if dx > 0 or dy > 0:
        return math.hypot(dx, dy)
    return min(x - r[0], r[2] - x, y - r[1], r[3] - y)


def validate(d, tol=1.0):
    """problems in the data set, as strings (empty = consistent):
    a fence that is empty or leaves the board; two fences of different blocks that overlap; duplicate bridge refs;
    a contract edge point (numeric) farther than `tol` mm from the boundary of every fence of the blocks the row names
    (rows naming EDGE, 'all' or a block without fence are skipped)."""
    bad = []
    bx = (d.X0, d.Y0, d.X1, d.Y1)
    rects = [(b, r) for b, rs in d.FENCES.items() for r in rs]
    for b, r in rects:
        if not (r[0] < r[2] and r[1] < r[3]):
            bad.append(f'fence {b} {r}: empty')
        elif r[0] < bx[0] or r[1] < bx[1] or r[2] > bx[2] or r[3] > bx[3]:
            bad.append(f'fence {b} {r}: outside the board')
    for i, (b1, r1) in enumerate(rects):
        for b2, r2 in rects[i + 1:]:
            if b1 != b2 and _overlap(r1, r2):
                bad.append(f'fences {b1} {r1} and {b2} {r2} overlap')
    refs = [x[0] for x in d.BRIDGES]
    for r in sorted({x for x in refs if refs.count(x) > 1}):
        bad.append(f'bridge {r} listed twice')
    for k, (net, frm, to, pt, lw, br, own, note) in enumerate(d.C, 1):
        if not _numeric(pt):
            continue
        near = [dist_to_rect_boundary(pt, r) for b in (frm, to) if b in d.FENCES for r in d.FENCES[b]]
        if near and min(near) > tol:
            bad.append(f'row {k} {net}: edge point {pt} is {min(near):.2f} mm from the fences of {frm} / {to}')
    return bad
