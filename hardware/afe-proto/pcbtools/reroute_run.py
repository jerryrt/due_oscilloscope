"""reroute_run.py BOARD [OUT] [--max N]: re-route the top-layer runs of track that fail pcbkit.rules.track_geometry with pcbkit.reroute, one run at a time, on the board's arrays, and report; with OUT, write the
board with the old segments removed and the new ones added (pcbtools.editor). Run in the PCB image from hardware/afe-proto.

The AFE's side: the net names and the frame are the AFE's, the limits are pcbkit's defaults (the owner's targets). Runs that cannot be re-routed are reported and left as they are."""
from __future__ import annotations

import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..', '..', 'pcbkit'), os.path.join(HERE, '..')]
from pcbkit import reroute, rules
from pcbkit import board as KB
from pcbtools import mutate
from pcbtools.frame import FRAME

def _cfg():
    from pcbtools.boards import v1_layout as mod
    names = [n.key for n in rules.TRACK_GEOMETRY_NAMES + rules.FILL_QUALITY_NAMES]
    return {k: getattr(mod, k) for k in names if hasattr(mod, k)}


CFG = _cfg()
FIX = ('angle', 'jog', 'entry', 'over_pad', 'detour')          # the findings a re-route can mend (a T stub, a wide track or a pad out of the pour it cannot)


NECKS = []                                           # (net, pad ref.pin, length mm) of every neck-down made


def route_w(b, c, **kw):
    """route, and the pieces with their widths: the run's width, narrowed to the minimum for the last mm into a pad the track is too wide for (a neck-down). Returns (polyline, pieces) or (None, None)"""
    poly = reroute.route(b, c, **kw)
    if poly is None and reroute.LAST_WHY[0] in ('no path in the window', 'search limit reached'):
        poly = reroute.route(b, c, margin=10.0, max_expand=4000000, **{k: v for k, v in kw.items() if k != 'margin'})       # a wider window, and more search
    if poly is None or len(poly) < 2:
        return None, None
    necks = list(reroute.LAST_NECKS)
    pieces = reroute.expand(poly, c.width, necks)
    pa = rules._pad_arrays(b)
    narrow = float(sum(np.hypot(q[0] - p[0], q[1] - p[1]) for p, q, w in pieces if w < c.width - 1e-9))
    for which, h in necks:
        NECKS.append((b.nets[c.net], '%s.%s' % (b.fp_ref[pa['fp'][h]], b.p_pin[pa['rows'][h]]), narrow / len(necks)))
    return poly, pieces


def _nearest(b, rows_by_net, x, y):
    best, hit = 1e9, None
    S = rules.segs(b)
    for i in range(len(S)):
        if b.s_layer[i] != 0:
            continue
        x0, y0, x1, y1 = S[i]
        dx, dy = x1 - x0, y1 - y0
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy)))
        d = float(np.hypot(x - (x0 + t * dx), y - (y0 + t * dy)))
        if d < best:
            best, hit = d, i
    return hit if best < 0.6 else None


def bad_chains(b):
    parts = rules.track_geometry_parts(b, CFG)
    ch = reroute.chains(b, 0)
    where = {}
    for k, ci in enumerate(ch):
        for s in ci.segs:
            where[s] = k
    bad = {}
    for kind, text, x, y in parts:
        if kind not in FIX:
            continue
        i = _nearest(b, None, x, y)
        if i is not None and i in where:
            bad.setdefault(where[i], []).append(kind)
    return parts, ch, bad


def drop_pad_stubs(b):
    """remove the segments whose two ends are in one pad of their own net: a stub the pad already is"""
    pa = rules._pad_arrays(b)
    S = rules.segs(b)
    if not len(S) or not len(pa['rows']):
        return b, 0
    a = rules._in_pads(S[:, :2], pa) & (pa['net'][None, :] == b.s_net[:, None]) & (b.s_layer[:, None] == 0)
    c = rules._in_pads(S[:, 2:], pa) & (pa['net'][None, :] == b.s_net[:, None])
    drop = (a & c).any(axis=1)
    return (mutate.drop_segments(b, drop), int(drop.sum())) if drop.any() else (b, 0)


def _free_tail(b, c):
    """re-route a run with one end free: the run leaves its other end and goes to each pad it lay across, nearest first, and stops at the last; with no such pad it was a stub and goes.
    Returns (arrays, ok, text)."""
    anchor = c.ends[1] if c.ends[0].kind == 'free' else c.ends[0]
    name = b.nets[c.net]
    pa = rules._pad_arrays(b)
    extras = reroute.overlapped_pads(b, c)
    mask = np.zeros(len(b.s_idx), bool)
    mask[c.segs] = True
    b2 = mutate.drop_segments(b, mask)
    if not extras:
        return b2, True, 'a stub, removed'
    extras.sort(key=lambda h: (pa['cx'][h] - anchor.x) ** 2 + (pa['cy'][h] - anchor.y) ** 2)
    terms = [anchor] + [reroute.End('pad', float(pa['cx'][h]), float(pa['cy'][h]), pad=h) for h in extras]
    for t0, t1 in zip(terms[:-1], terms[1:]):
        poly, pieces = route_w(b2, reroute.Chain(c.net, 0, [], (t0, t1), c.width))
        if poly is None:
            return b, False, reroute.LAST_WHY[0]
        for p, q, w in pieces:
            b2 = mutate.add_segment(b2, name, 'F', p, q, w)
    return b2, True, 'joined %d pads' % len(extras)


def run(b, limit=200, verbose=True):
    orig = set(b.s_idx.tolist())
    b, nstub = drop_pad_stubs(b)
    if verbose:
        print('removed %d stubs lying inside one pad' % nstub)
    tries = {}
    failed = set()
    done = []
    t0 = time.time()
    for it in range(limit):
        parts, ch, bad = bad_chains(b)
        todo = [(len(ch[k].segs), k) for k in bad if (tuple(ch[k].segs), ch[k].net) not in failed and tuple(sorted(int(b.s_idx[s]) for s in ch[k].segs)) not in failed]
        if verbose:
            print('pass %d: %d findings, %d runs to fix, %d failed so far, %.0f s' % (it, len(parts), len(bad), len(failed), time.time() - t0), flush=True)
        if not todo:
            break
        todo.sort()
        k = todo[0][1]
        c = ch[k]
        key = tuple(sorted(int(b.s_idx[s]) for s in c.segs))
        ek = (c.net,) + tuple(sorted((round(e.x, 2), round(e.y, 2)) for e in c.ends))
        tries[ek] = tries.get(ek, 0) + 1
        if tries[ek] > 2:
            failed.add(key)
            print('   GAVE UP %s run %s (the findings persist after two re-routes)' % (b.nets[c.net], ek[1:]), flush=True)
            continue
        if any(e.kind == 'free' for e in c.ends) and not all(e.kind == 'free' for e in c.ends):
            b2, ok, what = _free_tail(b, c)                      # a run that ends in nothing: its pads are joined from the end that is somewhere, the tail goes
            if ok:
                b = b2
                done.append((b.nets[c.net], len(c.segs), 0))
                print('   rerouted %s %d segments with a free end: %s (%s)' % (b.nets[c.net], len(c.segs), what, ','.join(bad[k])), flush=True)
            else:
                failed.add(key)
                print('   FAILED %s run of %d segments with a free end %s -> %s  (%s): %s' % (b.nets[c.net], len(c.segs), (round(c.ends[0].x, 2), round(c.ends[0].y, 2)), (round(c.ends[1].x, 2), round(c.ends[1].y, 2)), ','.join(bad[k]), what), flush=True)
            continue
        poly, pieces = route_w(b, c)
        name = b.nets[c.net]
        if poly is None:
            failed.add(key)
            print('   FAILED %s run of %d segments %s -> %s  (%s): %s' % (name, len(c.segs), (round(c.ends[0].x, 2), round(c.ends[0].y, 2)), (round(c.ends[1].x, 2), round(c.ends[1].y, 2)), ','.join(bad[k]), reroute.LAST_WHY[0]), flush=True)
            continue
        old_len = float(sum(np.hypot(b.s_x1[q] - b.s_x0[q], b.s_y1[q] - b.s_y0[q]) for q in c.segs))
        new_len = float(sum(np.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(poly[:-1], poly[1:])))
        if new_len > old_len * 1.2 + 0.4:
            failed.add(key)
            print('   LEFT %s run %s: the new track is %.1f mm against %.1f (a run is kept short)' % (name, ek[1:], new_len, old_len), flush=True)
            continue
        extras = reroute.overlapped_pads(b, c)
        b_before = b
        mask = np.zeros(len(b.s_idx), bool)
        mask[c.segs] = True
        b = mutate.drop_segments(b, mask)
        for p, q, w in pieces:
            b = mutate.add_segment(b, name, 'F', p, q, w)
        pa = rules._pad_arrays(b)
        ok = True
        nspur = 0
        for h in extras:                                          # the pads the old track ran across stay connected: a spur from each to the net
            sc = reroute.Chain(c.net, 0, [], (reroute.End('pad', float(pa['cx'][h]), float(pa['cy'][h]), pad=h), reroute.End('free', 0.0, 0.0)), c.width)
            sp, spieces = route_w(b, sc, goal=False)
            if sp is None:
                ok = False
                break
            for p, q, w in spieces:
                b = mutate.add_segment(b, name, 'F', p, q, w)
            nspur += 1
        if not ok:
            b = b_before
            failed.add(key)
            print('   FAILED %s run %s: no spur to a pad it ran across' % (name, ek[1:]), flush=True)
            continue
        done.append((name, len(c.segs), len(poly) - 1))
        print('   rerouted %s %d -> %d segments, %d spurs (%s)' % (name, len(c.segs), len(poly) - 1, nspur, ','.join(bad[k])), flush=True)
    return b, done, failed, orig


def write(path, out, b_new, orig):
    from pcbtools.editor import edit
    keep = set(b_new.s_idx.tolist())
    b0 = KB.read_board(path, FRAME)
    gone = np.array([i in set(b0.s_idx.tolist()) - keep for i in b0.s_idx.tolist()], bool)
    new = [i for i in range(len(b_new.s_idx)) if int(b_new.s_idx[i]) not in orig]
    with edit(path, out) as e:
        e.remove_tracks(b0.s_idx[gone])
        for i in new:
            e.add_tracks(b_new.nets[b_new.s_net[i]], 'F', b_new.s_x0[i], b_new.s_y0[i], b_new.s_x1[i], b_new.s_y1[i], b_new.s_w[i])
        e.fill_zones()                                       # the fills follow the new tracks


if __name__ == '__main__':
    lim = int(sys.argv[sys.argv.index('--max') + 1]) if '--max' in sys.argv else 200
    args = [a for k, a in enumerate(sys.argv[1:], 1) if not a.startswith('--') and not (k > 1 and sys.argv[k - 1] == '--max')]
    path = args[0]
    b = KB.read_board(path, FRAME)
    b2, done, failed, orig = run(b, lim)
    parts = rules.track_geometry_parts(b2, CFG)
    import collections
    print('after: %s' % dict(sorted(collections.Counter(k for k, *_ in parts).items())), 'rerouted', len(done), 'failed', len(failed))
    for n_, pad_, ln_ in NECKS:
        print('   neck-down %s into %s, %.2f mm at 0.2 mm' % (n_, pad_, ln_))
    if len(args) > 1:
        write(path, args[1], b2, orig)
        print('wrote', args[1])
