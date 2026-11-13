"""Apply the owner's board-outline ruling to a v2 board: the outline overhangs the Due by 5 mm on the analog-header edge only (the
south edge, y 0), and that band is a copper keep-out. MC-1 amended, 2026-11-13; boards/v1.py does the same for v1.

    python3 v2/layout/outline_overhang.py BOARD.kicad_pcb [--pro BOARD.kicad_pro] [--write OUT.kicad_pcb] [--check]

The numbers are pcbtools/boards/v2_layout.py's (BOARD_RECT, KEEPOUTS, BOARD_SETUP), the one place they live. Pure text editing, no
KiCad needed, and only what the ruling touches is edited: the Edge.Cuts rectangle's south side moves 5 mm out and its two side
edges are extended with it (nothing else is moved: footprints, tracks, vias and zone fills stay byte for byte, so the pours are not
refilled); one rule area (no tracks, no vias, no pour, on F.Cu and B.Cu) is added over the band; and the project file takes the
board setup (min_copper_edge_clearance 0.45 ...). Idempotent: a board that already has all of it is written back unchanged.
Exit 0 on success; --check writes nothing and exits 1 when the board still needs the change.
"""
import json
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
from pcbtools.boards import v2_layout as cfg  # noqa: E402

SHEET_X, SHEET_Y = 50.0, 150.0           # Due mm -> KiCad sheet mm: x + 50, 150 - y


def sheet(x, y):
    return round(x + SHEET_X, 6), round(SHEET_Y - y, 6)


def fmt(v):
    return ('%.6f' % v).rstrip('0').rstrip('.')


def _edge_blocks(text):
    """[(start, end, text)] of the top-level gr_line blocks on Edge.Cuts"""
    out, i = [], 0
    while True:
        i = text.find('\n\t(gr_line\n', i)
        if i < 0:
            return out
        j = text.find('\n\t)\n', i)
        blk = text[i:j + 4]
        if '(layer "Edge.Cuts")' in blk:
            out.append((i, j + 4, blk))
        i = j


def _set_pts(blk, start, end):
    lines = blk.split('\n')
    for k, ln in enumerate(lines):
        if ln.strip().startswith('(start '):
            lines[k] = '\t\t(start %s %s)' % tuple(fmt(v) for v in start)
        elif ln.strip().startswith('(end '):
            lines[k] = '\t\t(end %s %s)' % tuple(fmt(v) for v in end)
    return '\n'.join(lines)


def _pts(blk):
    import re
    s = re.search(r'\(start ([-\d.]+) ([-\d.]+)\)', blk)
    e = re.search(r'\(end ([-\d.]+) ([-\d.]+)\)', blk)
    return (float(s[1]), float(s[2])), (float(e[1]), float(e[2]))


def zone_text(name, rect):
    x0, y0, x1, y1 = rect
    a, b = sheet(x0, y0), sheet(x1, y1)
    pts = ' '.join('(xy %s %s)' % (fmt(x), fmt(y)) for x, y in ((a[0], a[1]), (b[0], a[1]), (b[0], b[1]), (a[0], b[1])))
    u = uuid.uuid5(uuid.NAMESPACE_URL, 'afe-v2-integrated/rule-area/' + name)
    return f'''	(zone
		(layers "F.Cu" "B.Cu")
		(uuid "{u}")
		(name "{name}")
		(hatch edge 0.5)
		(connect_pads
			(clearance 0)
		)
		(min_thickness 0.25)
		(keepout
			(tracks not_allowed)
			(vias not_allowed)
			(pads allowed)
			(copperpour not_allowed)
			(footprints allowed)
		)
		(placement
			(enabled no)
			(sheetname "")
		)
		(fill
			(thermal_gap 0.5)
			(thermal_bridge_width 0.5)
			(island_removal_mode 0)
		)
		(polygon
			(pts
				{pts}
			)
		)
	)
'''


def apply_outline(text):
    """the board text with the overhang outline and the band's rule area; unchanged when it already has both"""
    x0, y0, x1, y1 = cfg.BOARD_RECT
    (ax, ay), (bx, by) = sheet(x0, y1), sheet(x1, y0)          # sheet: west x, north y / east x, south y
    blocks = _edge_blocks(text)
    if len(blocks) != 4:
        raise SystemExit(f'expected the four Edge.Cuts lines of a rectangle, found {len(blocks)}')
    new = []
    for s, e, blk in blocks:
        p, q = _pts(blk)
        fix = lambda pt: (pt[0], by) if abs(pt[1] - by) < 1e-6 or abs(pt[1] - (SHEET_Y - 0.0)) < 1e-6 else pt  # noqa: E731
        nb = _set_pts(blk, fix(p), fix(q))
        new.append((s, e, nb))
    for (s, e, nb), (_, _, blk) in zip(reversed(new), reversed(blocks)):
        text = text[:s] + nb + text[e:]
    for kname, rect in cfg.KEEPOUTS:
        if f'(name "{kname}")' not in text:
            at = text.index('\n\t(zone\n') + 1
            text = text[:at] + zone_text(kname, rect) + text[at:]
    return text


def apply_pro(pro):
    out = json.loads(json.dumps(pro))
    for k, v in json.loads(json.dumps(cfg.BOARD_SETUP)).items():
        if k == 'board':
            out.setdefault('board', {}).setdefault('design_settings', {}).setdefault('rules', {}).update(v['design_settings']['rules'])
        elif k == 'net_settings':                  # the named classes are updated in place (key order kept), nothing else is touched
            ns = out.setdefault('net_settings', {'classes': []})
            for c in v['classes']:
                old = [o for o in ns.setdefault('classes', []) if o.get('name') == c['name']]
                if old:
                    old[0].update(c)
                else:
                    ns['classes'].append(c)
            for kk, vv in v.items():
                ns.setdefault(kk, vv)
        else:
            out[k] = v
    return out


def main(argv):
    args = argv[1:]
    if not args or args[0].startswith('-'):
        raise SystemExit(__doc__)
    path = args[0]
    opt = lambda k: args[args.index(k) + 1] if k in args else None  # noqa: E731
    out = opt('--write') or path
    pro_path = opt('--pro') or os.path.splitext(path)[0] + '.kicad_pro'
    text = open(path).read()
    new = apply_outline(text)
    pro = json.load(open(pro_path)) if os.path.exists(pro_path) else None
    newpro = apply_pro(pro) if pro is not None else None
    todo = new != text or (pro is not None and newpro != pro)
    if '--check' in args:
        return 1 if todo else 0
    open(out, 'w').write(new)
    if newpro is not None:
        outpro = os.path.splitext(out)[0] + '.kicad_pro'
        if outpro == pro_path or '--write' not in args:
            open(pro_path, 'w').write(json.dumps(newpro, indent=2, ensure_ascii=False))
        else:
            open(outpro, 'w').write(json.dumps(newpro, indent=2, ensure_ascii=False))
    print('changed' if todo else 'already applied')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
