"""gndpads.py: SMD GND pads of the top layer that the pour does not touch get their via at the pad's edge (no visible stub).

  failing(board_path, clearance...) -> [(ref, pin, x, y)]    the SMD GND pads pcbkit.rules.fill_quality's 'gndpad' finds on a FILLED board
  relocate(src, dst, pads)          -> (done, skipped)         for each pad: the track run from the pad to its own via is removed with the via, and a via goes on the pad's edge instead
                                                               (0.25 mm out of the edge, so its annulus overlaps the pad by 0.05), at the side with the most room to other nets' copper

Only copper changes (tracks and a GND via); no part or pad moves. A pad whose via serves other pads or tracks too is skipped and reported."""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..', '..', 'pcbkit'), os.path.join(HERE, '..')]
sys.path.append('/usr/lib/python3/dist-packages')
from pcbkit import board as kb, rules, geom
from pcbtools.frame import FRAME

VIA_D, VIA_DRILL = 0.6, 0.3
EDGE_GAP = 0.05                                    # a via whose annulus is this near the pad edge is at the edge: FILL_GNDPAD_VIA_GAP's default
MIN_CLEAR = 0.2


def failing(path, gndpad_min=0.2, radius=3.0, shells=()):
    """(pads, trouble): the SMD GND pads the pour does not touch, and the SMD GND pads within `radius` of a place where the filled pour is rough or has a dead-end finger (their ring is what makes it so)"""
    b = kb.read_board(path, {'FRAME': FRAME})
    parts, _ = rules.fill_quality_parts(b, {'GND': '/GND', 'FILL_LAYERS': ('F',), 'FILL_ROUGH_LAYERS': ('F',), 'FILL_SHELL_PREFIXES': shells, 'FILL_GNDPAD_MIN': gndpad_min})
    out, spots, shell = [], [], []
    for kind, text, x, y in parts:
        if kind == 'shell':
            shell.append((x, y))
        if kind == 'gndpad':
            ref, _, rest = text.partition(' pin ')
            out.append((ref, rest.split(' ')[0], x, y))
        elif kind in ('rough', 'dead_end'):
            spots.append((x, y))
    near = []
    g = [i for i, n in enumerate(b.nets) if n.lstrip('/') == 'GND'][0]
    pins = list(b.p_pin)
    have = {(r, p) for r, p, *_ in out}
    for i in range(len(b.p_x)):
        if b.p_net[i] == g and b.p_smd[i] and (b.p_layer_mask[i] & 1) and any(math.hypot(b.p_x[i] - sx, b.p_y[i] - sy) <= radius for sx, sy in spots):
            key = (b.fp_ref[b.p_fp[i]], pins[i])
            if key not in have:
                near.append((key[0], key[1], float(b.p_x[i]), float(b.p_y[i])))
    failing.shell = shell                                      # the connector GND pins the pour does not touch (their strips are drawn by fill_clean)
    return out, near


def _chain(b, g, pad_row, via_xy_all):
    """(segment indices, via index) of the GND track run from the pad to a via, or None"""
    px, py = b.p_x[pad_row], b.p_y[pad_row]
    half = max(b.p_sx[pad_row], b.p_sy[pad_row]) / 2
    segs = [k for k in range(len(b.s_x0)) if b.s_net[k] == g and b.s_layer[k] == 0]
    cur = [k for k in segs if min(math.hypot(b.s_x0[k] - px, b.s_y0[k] - py), math.hypot(b.s_x1[k] - px, b.s_y1[k] - py)) <= half + 0.01]
    if not cur:
        return None
    run, frontier = list(cur), []
    for k in cur:
        for e in ((b.s_x0[k], b.s_y0[k]), (b.s_x1[k], b.s_y1[k])):
            if math.hypot(e[0] - px, e[1] - py) > half:
                frontier.append(e)
    for _ in range(6):
        for e in list(frontier):
            vi = [i for i in range(len(b.v_x)) if b.v_net[i] == g and math.hypot(b.v_x[i] - e[0], b.v_y[i] - e[1]) <= b.v_dia[i] / 2 + 0.01]
            if vi:
                return run, vi[0]
        nxt = []
        for k in segs:
            if k in run:
                continue
            for e in list(frontier):
                if min(math.hypot(b.s_x0[k] - e[0], b.s_y0[k] - e[1]), math.hypot(b.s_x1[k] - e[0], b.s_y1[k] - e[1])) <= 0.01:
                    run.append(k)
                    nxt += [(b.s_x0[k], b.s_y0[k]), (b.s_x1[k], b.s_y1[k])]
        frontier = nxt
        if not frontier:
            break
    return None


def _room(b, g, x, y):
    """the smallest clearance of a via at (x, y) to copper of other nets (negative: it would not fit); board edge excluded (the DRC judges it)"""
    r = VIA_D / 2
    best = 9.0
    for i in range(len(b.p_x)):
        if b.p_net[i] == g or not (b.p_layer_mask[i] & 1):
            continue
        dx = max(b.p_bx0[i] - x, x - b.p_bx1[i], 0.0)
        dy = max(b.p_by0[i] - y, y - b.p_by1[i], 0.0)
        best = min(best, math.hypot(dx, dy) - r)
    S = np.column_stack([b.s_x0, b.s_y0, b.s_x1, b.s_y1])
    other = np.flatnonzero(b.s_net != g)
    if len(other):
        d = geom.seg_seg_dist(S[other], np.array([[x, y, x, y]]))[:, 0] - b.s_w[other] / 2 - r
        best = min(best, float(d.min()))
    for i in range(len(b.v_x)):
        if b.v_net[i] != g:
            best = min(best, math.hypot(b.v_x[i] - x, b.v_y[i] - y) - b.v_dia[i] / 2 - r)
    return best


def relocate(src, dst, pads):
    from pcbtools.editor import edit
    b = kb.read_board(src, {'FRAME': FRAME})
    g = [i for i, n in enumerate(b.nets) if n.lstrip('/') == 'GND'][0]
    pins = list(b.p_pin)
    remove_t, remove_v, new, done, skipped = [], [], [], [], []
    for ref, pin, x, y in pads:
        rows = [i for i in range(len(b.p_x)) if b.fp_ref[b.p_fp[i]] == ref and pins[i] == pin and (b.p_layer_mask[i] & 1) and abs(b.p_x[i] - x) < 0.01 and abs(b.p_y[i] - y) < 0.01]
        if not rows:
            skipped.append((ref, pin, 'pad not found'))
            continue
        h = rows[0]
        if len(b.v_x) and any(b.v_net[i] == g and math.hypot(max(b.p_bx0[h] - b.v_x[i], b.v_x[i] - b.p_bx1[h], 0), max(b.p_by0[h] - b.v_y[i], b.v_y[i] - b.p_by1[h], 0)) - b.v_dia[i] / 2 <= EDGE_GAP for i in range(len(b.v_x))):
            continue                                                       # a via is at its edge already: nothing to move
        ch = _chain(b, g, h, None)
        if ch is None:
            skipped.append((ref, pin, 'no track run to a via of its own'))
            continue
        run, vi = ch
        users = [k for k in range(len(b.s_x0)) if b.s_net[k] == g and k not in run and b.s_layer[k] == 0 and min(math.hypot(b.s_x0[k] - b.v_x[vi], b.s_y0[k] - b.v_y[vi]), math.hypot(b.s_x1[k] - b.v_x[vi], b.s_y1[k] - b.v_y[vi])) <= b.v_dia[vi] / 2 + 0.01]
        users += [i for i in range(len(b.p_x)) if i != h and b.p_net[i] == g and (b.p_layer_mask[i] & 1) and math.hypot(max(b.p_bx0[i] - b.v_x[vi], b.v_x[vi] - b.p_bx1[i], 0), max(b.p_by0[i] - b.v_y[vi], b.v_y[vi] - b.p_by1[i], 0)) <= b.v_dia[vi] / 2 + 0.01]
        if users:
            skipped.append((ref, pin, 'its via serves other copper'))
            continue
        out = VIA_D / 2 - 0.05
        cands = [(b.p_x[h], b.p_by1[h] + out), (b.p_x[h], b.p_by0[h] - out), (b.p_bx1[h] + out, b.p_y[h]), (b.p_bx0[h] - out, b.p_y[h])]
        removed_t = set(int(b.s_idx[k]) for k in run)
        # the room is judged without the pad's own run and via
        rooms = [(_room(b, g, cx, cy), cx, cy) for cx, cy in cands]
        room, cx, cy = max(rooms)
        if room < MIN_CLEAR - 1e-9:
            skipped.append((ref, pin, 'no side of the pad has room for a via (best %.2f mm)' % room))
            continue
        remove_t += sorted(removed_t)
        remove_v.append(int(b.v_idx[vi]))
        new.append((cx, cy))
        done.append((ref, pin, round(float(cx), 3), round(float(cy), 3), len(run)))
    with edit(src, dst) as e:
        e.remove_tracks(remove_t)
        e.remove_vias(remove_v)
        if new:
            e.add_vias('GND', [p[0] for p in new], [p[1] for p in new], VIA_D, VIA_DRILL)
    return done, skipped


BOARD = (17.0, -4.5, 117.0, 57.84)


def strip_rects(pins, length=3.0, half=1.0, board=BOARD):
    """for each connector GND pin the pour does not touch (Due mm): a rectangle from just behind the pin to `length` mm towards the board interior (away from its nearest edge), 2 x `half` wide.
    A GND strip zone of its own (a narrower minimum width than the top pour's) fills it, so the pin sits in copper the 1.0 mm rule would not allow between the pins of a 2.54 mm row."""
    out = []
    for x, y in pins:
        d = {'s': y - board[1], 'n': board[3] - y, 'w': x - board[0], 'e': board[2] - x}
        edge = min(d, key=d.get)
        if edge == 's':
            out.append((x - half, y - 0.6, x + half, y + length))
        elif edge == 'n':
            out.append((x - half, y - length, x + half, y + 0.6))
        elif edge == 'w':
            out.append((x - 0.6, y - half, x + length, y + half))
        else:
            out.append((x - length, y - half, x + 0.6, y + half))
    return out
