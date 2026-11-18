"""the automatic pass: re-route only the runs of segments track_geometry flags, from the nearest good vertex on each side, as an octilinear path of at most --max-legs legs that keeps
every net's pad connectivity (with and without the LR-6 / LR-8 cuts) and the INV_MAX nets' length.

usage: python3 cc_reroute.py IN OUT [--nets A,B] [--max-legs 4] [--iters N] [--narrow] [--gnd-delete] [--collapse] [--why] [--debug]
"""
import sys, os, math, collections, time, itertools
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
import numpy as np
from cc_state import State, key, write, KEY, MIN_LEG, BREAKOUT_LEG, FRAME, CFG, rules, geom
from cc_router import DIRS, candidates, turn_ok


def dir_index(p, q):
    a = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 360
    k = int(round(a / 45.0)) % 8
    return k if abs(a - 45 * round(a / 45.0)) < 0.6 else None


from pcbtools.boards import v2_layout as _L
PROTECTED = set(_L.INV_LEN_NODES) | set(_L.ADC_NETS) | set(_L.INV_NODES)        # the nets whose track length an LR row reads or limits: AWG_FB, CH1_OUT, CH2_OUT, A0, A1, the divider nodes


class Runner(State):
    def findings(self):
        return rules.track_geometry_parts(self.board(), CFG)

    def runs(self, ch, bad):
        """[(i, j)] maximal runs of consecutive bad segments of the chain (indices into its walk order)"""
        out, i = [], 0
        n = len(ch['segs'])
        while i < n:
            if bad[i]:
                j = i
                while j + 1 < n and bad[j + 1]:
                    j += 1
                out.append((i, j)); i = j + 1
            else:
                i += 1
        return out

    def pad_spec(self, h, fine_ok=True):
        """terminal spec of the pad row h of self.pa (a waypoint of a route)"""
        pa = self.pa
        sh = pa['shape'][h]
        rot = float(pa['rot'][h]) % 360
        if sh == 0:
            dirs = list(range(8))
        else:
            base = int(round(rot / 45.0)) % 8
            dirs = [(base + q) % 8 for q in (0, 2, 4, 6)] if abs(rot / 45.0 - round(rot / 45.0)) < 1e-6 else [0, 2, 4, 6]
        fine = self.fine.get(int(pa['fp'][h]), 9) <= 0.65 + 1e-9
        return dict(pos=(float(pa['cx'][h]), float(pa['cy'][h])), dirs=dirs, minleg=BREAKOUT_LEG if fine else MIN_LEG, skip={int(h)}, kind='pad', row=int(h), cap=self.pad_caps(h, dirs))

    def waypoints(self, net, layer, old, skip):
        """the net's own pads (not the terminals) that the old route runs over: [(distance along the route, pad row)]"""
        pa = self.pa
        out = []
        cu = self.cu_pads
        S = np.array([[old[i][0], old[i][1], old[i + 1][0], old[i + 1][1]] for i in range(len(old) - 1)])
        for h in range(len(pa['rows'])):
            if int(pa['net'][h]) != net or h in skip or not (pa['mask'][h] & (1 << layer)):
                continue
            rows = np.flatnonzero(cu.owner == h)
            D = geom.seg_seg_dist(cu.C[rows], S) - cu.r[rows][:, None] - 0.0
            if D.min() < 0.05:
                k = int(np.argmin(D.min(axis=0)))
                t = float(np.hypot(pa['cx'][h] - old[0][0], pa['cy'][h] - old[0][1]))
                out.append((t, h))
        return sorted(out)

    def route_pair(self, net, layer, width, sa, sb, old, max_legs, K=6):
        """a path between two terminal specs (dicts with pos, dirs, minleg, skip), or None"""
        A, B = sa['pos'], sb['pos']
        if math.hypot(A[0] - B[0], A[1] - B[1]) < 1e-6:
            return []
        xs = [p[0] for p in old] + [A[0], B[0]]; ys = [p[1] for p in old] + [A[1], B[1]]
        win = (min(xs) - 3.0, min(ys) - 3.0, max(xs) + 3.0, max(ys) + 3.0)
        skip_v = {sp['via'] for sp in (sa, sb) if 'via' in sp}
        obs = self.obstacles(net, layer, win, sa['skip'] | sb['skip'], old, width, skip_v)
        last_dirs = sb['lastdirs'] if 'lastdirs' in sb else [(d + 4) % 8 for d in sb['dirs']]
        self.last = (obs, A, B, sa['dirs'], last_dirs, sa['minleg'], sb['minleg'], width)

        def wfun(pts):
            n = len(pts) - 1
            ws = [width] * n
            d0 = dir_index(pts[0], pts[1]); dn = dir_index(pts[-2], pts[-1])
            if 'cap' in sa and d0 is not None:
                ws[0] = max(0.15, min(width, sa['cap'].get(d0, width)))
            if 'cap' in sb and dn is not None:
                ws[-1] = max(0.15, min(ws[-1], sb['cap'].get((dn + 4) % 8, width)))
            return ws
        self.wfun = wfun
        oldlen = sum(math.hypot(old[k + 1][0] - old[k][0], old[k + 1][1] - old[k][1]) for k in range(len(old) - 1))
        cap = oldlen + (1e-9 if self.b.nets[net] in PROTECTED else max(1.0, 0.3 * oldlen))      # a protected net never gets longer: not by 0.1 mm, not by anything over float noise
        got = []
        for legs in range(1, max_legs + 1):
            cands = [c for c in candidates(A, B, sa['dirs'], last_dirs, sa['minleg'], sb['minleg'], MIN_LEG, max_legs=legs) if len(c[1]) - 1 == legs]
            cands = [c for c in cands if sum(math.hypot(c[1][k + 1][0] - c[1][k][0], c[1][k + 1][1] - c[1][k][1]) for k in range(len(c[1]) - 1)) <= cap + 1e-9]
            for a0 in range(0, len(cands), 200):
                blk = cands[a0:a0 + 200]
                ok = self.valid(blk, obs, width, wfun=wfun)
                for k in np.flatnonzero(ok):
                    pp = blk[int(k)][1]
                    got.append((pp, wfun(pp)))
                    if len(got) >= K:
                        return got
            if got:
                return got
        return got


    def try_run(self, ch, pts, i, j, max_legs):
        """re-route the vertices i .. j+1 of the chain's polyline; extension levels 0.. add good neighbours on both sides. Returns (new points, lo, hi, ext, legs) or None"""
        n = len(ch['segs'])
        net, layer = ch['net'], ch['layer']
        width = float(self.W[ch['segs'][0]])
        for ext in range(0, 4):
            lo, hi = max(0, i - ext), min(n - 1, j + ext)            # segments lo..hi are replaced
            if lo == 0:
                sa = self.terminal_spec(ch['a'], net, layer, None)
            else:
                pd = dir_index(pts[lo - 1], pts[lo])
                if pd is None:
                    continue
                fd = [pd] + [(pd + t) % 8 for t in (1, 2, 6, 7)]
                sa = dict(pos=tuple(pts[lo]), dirs=fd, minleg={d: (0.05 if d == pd else MIN_LEG) for d in fd}, skip=set())
            if hi == n - 1:
                sb = self.terminal_spec(ch['b'], net, layer, None)
            else:
                nd = dir_index(pts[hi + 1], pts[hi + 2])
                if nd is None:
                    continue
                ld = [nd] + [(nd + t) % 8 for t in (1, 2, 6, 7)]
                sb = dict(pos=tuple(pts[hi + 1]), dirs=[(d + 4) % 8 for d in ld], lastdirs=ld, minleg={d: (0.05 if d == nd else MIN_LEG) for d in ld}, skip=set())
            old = [tuple(sa['pos'])] + [tuple(p) for p in pts[lo + 1:hi + 1]] + [tuple(sb['pos'])]
            wps = self.waypoints(net, layer, old, sa['skip'] | sb['skip'])
            specs = [sa] + [self.pad_spec(h) for _, h in wps] + [sb]
            opts = []
            for q in range(len(specs) - 1):
                got = self.route_pair(net, layer, width, dict(specs[q]), dict(specs[q + 1]), old, max_legs)
                if not got:
                    opts = None
                    break
                opts.append(got)
            if opts is None:
                continue
            tries = 0
            for combo in itertools.product(*opts):
                tries += 1
                if tries > 24:
                    break
                total, wsall, nl = [specs[0]['pos']], [], 0
                for p, ws in combo:
                    total += list(p[1:]); nl += len(p) - 1; wsall += ws
                plen = lambda P: sum(math.hypot(P[k + 1][0] - P[k][0], P[k + 1][1] - P[k][1]) for k in range(len(P) - 1))
                if self.b.nets[net] in PROTECTED and plen(total) > plen(old) + 1e-9:
                    continue                                              # a protected net never gets longer
                if self.keeps_connectivity(ch, lo, hi, total, wsall):
                    return total, lo, hi, ext, nl, wsall
                if getattr(self, 'debug', False):
                    print('   invariant rejects', np.round(total, 2).tolist())
        return None

    def collapse_junctions(self, only=None, maxlen=1.0):
        """a junction that sits a short stub away from a pad of its net is moved onto the pad (the pad becomes the hub): the stub goes, and the other
        branches start at the pad's centre. Connectivity is unchanged by construction. Returns how many were collapsed."""
        n = 0
        for net in sorted(set(self.N[self.alive & (self.L == 0)].tolist())):
            name = self.b.nets[net]
            if only and name not in only:
                continue
            chs = self.chains(net)
            deg = collections.Counter()
            for ch in chs:
                deg[ch['a']] += 1; deg[ch['b']] += 1
            for ch in chs:
                if not all(self.alive[s] for s in ch['segs']):
                    continue
                for end, other in (('a', 'b'), ('b', 'a')):
                    J = ch[end]; P = ch[other]
                    x, y = J[0] / KEY, J[1] / KEY
                    if deg[J] < 3 or len(self.pad_at(x, y, net, 0)) or self.via_at(x, y) >= 0:
                        continue
                    pads = self.pad_at(P[0] / KEY, P[1] / KEY, net, 0)
                    if not len(pads) or self.chain_length(ch) > maxlen:
                        continue
                    h = min(pads, key=lambda q: math.hypot(self.pa['cx'][q] - P[0] / KEY, self.pa['cy'][q] - P[1] / KEY))
                    c = (float(self.pa['cx'][h]), float(self.pa['cy'][h]))
                    # move every other segment end at J onto the pad centre, drop the stub
                    for s in ch['segs']:
                        self.alive[s] = False
                    for o in self.net_segments(net):
                        for e in (0, 1):
                            if key(*self.S[o, 2 * e:2 * e + 2]) == J:
                                self.S[o, 2 * e], self.S[o, 2 * e + 1] = c
                    deg[J] -= 1
                    n += 1
                    break
        return n

    def narrow_entries(self):
        """a segment that runs along a pad axis into the pad but is wider than the pad's span at that edge is narrowed to fit (0.15 mm at the least). Returns how many."""
        import math as m
        n = 0
        fnd = [f for f in self.findings() if f[0] == 'entry']
        pa = self.pa
        for f in fnd:
            x, y = f[2], f[3]
            for i in np.flatnonzero(self.alive & (self.L == 0)):
                for e in (0, 1):
                    if abs(self.S[i, 2 * e] - x) < 1e-3 and abs(self.S[i, 2 * e + 1] - y) < 1e-3:
                        hs = self.pad_at(x, y, int(self.N[i]), 0)
                        if not len(hs):
                            continue
                        h = hs[0]
                        a = m.degrees(m.atan2(self.S[i, 3] - self.S[i, 1], self.S[i, 2] - self.S[i, 0]))
                        rot = float(pa['rot'][h])
                        d = (a - rot) % 180; d = min(d, 180 - d)
                        e90 = abs(d - 90) < 0.5
                        if d < 0.5 or e90:
                            span = float(pa['sy'][h] if d < 0.5 else pa['sx'][h])
                            ar = m.radians(rot)
                            dx, dy = x - pa['cx'][h], y - pa['cy'][h]
                            u = dx * m.cos(ar) + dy * m.sin(ar); v = -dx * m.sin(ar) + dy * m.cos(ar)
                            off = abs(v) if d < 0.5 else abs(u)
                            wmax = 2 * (span / 2 + 0.0009 - off)
                            wnew = np.floor(wmax / 0.05 + 1e-9) * 0.05
                            if wnew >= 0.15 and wnew < self.W[i] - 1e-9:
                                self.W[i] = wnew; n += 1
        return n

    def via_stub(self, ch):
        """a short chain from a pad to a via nothing else uses: lay a straight perpendicular leg from the pad and put the via at its end (the via moves; connectivity and LR-1's 'own via' are kept, a pad keeps its own via).
        Returns (via index, new via xy, leg points, widths) or None."""
        net, layer = ch['net'], ch['layer']
        ta = self.terminal_spec(ch['a'], net, layer, None); tb = self.terminal_spec(ch['b'], net, layer, None)
        if ta['kind'] == 'via' and tb['kind'] == 'pad':
            ta, tb = tb, ta
        if not (ta['kind'] == 'pad' and tb['kind'] == 'via'):
            return None
        vi = tb['via']
        # nothing else may use this via
        for o in self.chains(net):
            if o is not ch and (o['a'] == ch['a'] and False):
                pass
        users = [o for o in self.chains(net) if (key(*self.vias[vi, :2]) in (o['a'], o['b'])) and o['segs'] != ch['segs']]
        if users:
            return None
        A = ta['pos']
        old = [tuple(A), tuple(tb['pos'])]
        win = (A[0] - 3, A[1] - 3, A[0] + 3, A[1] + 3)
        obs = self.obstacles(net, layer, win, ta['skip'], old, 0.2, {vi})
        pa = self.pa; h = ta['row']
        best = None
        for d in ta['dirs']:
            u = np.array(DIRS[d])
            w = max(0.15, min(0.2, ta['cap'].get(d, 0.2)))
            for l in np.arange(0.62, 2.0, 0.05):
                V = (round(A[0] + l * u[0], 4), round(A[1] + l * u[1], 4))
                c = [(0, [tuple(A), V])]
                if not self.valid(c, obs, w)[0]:
                    continue
                if not self.valid([(0, [V, V])], obs, 0.6)[0]:
                    continue
                cost = l + 0.5 * math.hypot(V[0] - tb['pos'][0], V[1] - tb['pos'][1])
                if best is None or cost < best[0]:
                    best = (cost, V, [tuple(A), V], [w])
        if best is None:
            return None
        return vi, best[1], best[2], best[3]

    def gnd_delete(self, ch):
        """a GND chain from a pad to a via nothing else uses is deleted when another GND via stays within 3 mm of the pad (LR-1: a via of its own, each via once)"""
        if not self.delete_stubs:
            return False
        net, layer = ch['net'], ch['layer']
        ta = self.terminal_spec(ch['a'], net, layer, None); tb = self.terminal_spec(ch['b'], net, layer, None)
        if ta['kind'] == 'via' and tb['kind'] == 'pad':
            ta, tb = tb, ta
        if not (ta['kind'] == 'pad' and tb['kind'] == 'via'):
            return False
        vi = tb['via']
        if [o for o in self.chains(net) if o['segs'] != ch['segs'] and key(*self.vias[vi, :2]) in (o['a'], o['b'])]:
            return False
        for s in ch['segs']:
            self.alive[s] = False
        return True

    def chain_length(self, ch):
        return float(sum(math.hypot(*(self.S[i, :2] - self.S[i, 2:])) for i in ch['segs']))

    def partitions(self, board, name):
        from pcbtools import rules as AR
        from pcbtools.boards import v2_layout as C
        cut = set(map(tuple, C.STAR.get(name, []))) if hasattr(C, 'STAR') else set()
        if name == C.VREF_NET:
            cut |= set(map(tuple, C.VREF_SOURCE))
        f = lambda cc: frozenset(frozenset(g) for g in AR.pieces_keys(board, C, name, cc))
        return f(()), f(cut)

    def keeps_connectivity(self, ch, lo, hi, newpts, ws):
        """the net's pads are connected exactly as before, with and without the LR-6 / LR-8 cuts"""
        name = self.b.nets[ch['net']]
        if not hasattr(self, 'part0'):
            self.part0 = {}
        if name not in self.part0:
            self.part0[name] = self.partitions(self.board(), name)
        saved_alive, saved_new = self.alive.copy(), list(self.new)
        self.replace(ch, lo, hi, newpts, ws)
        ok = self.partitions(self.board(), name) == self.part0[name]
        self.alive, self.new = saved_alive, saved_new
        return ok

    def replace(self, ch, lo, hi, newpts, ws):
        for s in ch['segs'][lo:hi + 1]:
            self.alive[s] = False
        for k in range(len(newpts) - 1):
            self.new.append((round(newpts[k][0], 4), round(newpts[k][1], 4), round(newpts[k + 1][0], 4), round(newpts[k + 1][1], 4), ws[k], ch['layer'], ch['net']))


def main():
    a = sys.argv[1:]
    inp, out = a[0], a[1]
    maxlegs = int(a[a.index('--max-legs') + 1]) if '--max-legs' in a else 3
    iters = int(a[a.index('--iters') + 1]) if '--iters' in a else 200
    only = set(a[a.index('--nets') + 1].split(',')) if '--nets' in a else None
    st = Runner(inp)
    st.last = None
    if '--narrow' in a:
        print('narrowed', st.narrow_entries())
    if '--collapse' in a:
        print('collapsed junctions', st.collapse_junctions(only))
    st.debug = '--debug' in a
    st.delete_stubs = '--gnd-delete' in a
    failed = set()
    for it in range(iters):
        fnd = st.findings()
        if not fnd:
            print('no findings left'); break
        P = np.array([[f[2], f[3]] for f in fnd])
        chs = []
        for net in sorted(set(st.N[st.alive & (st.L == 0)].tolist())):
            if only and st.b.nets[net] not in only:
                continue
            chs += st.chains(net)
        todo = []
        for ch in chs:
            pts = st.chain_polyline(ch)
            S = np.array([[pts[k][0], pts[k][1], pts[k + 1][0], pts[k + 1][1]] for k in range(len(pts) - 1)])
            D = geom.point_seg_dist(P, S)
            bad = (D < 0.03).any(axis=0)
            if bad.any():
                for (i, j) in st.runs(ch, bad):
                    fk = (ch['net'], round(pts[i][0], 3), round(pts[i][1], 3), round(pts[j + 1][0], 3), round(pts[j + 1][1], 3))
                    if fk in failed:
                        continue
                    fine = (i == 0 and st.terminal_spec(ch['a'], ch['net'], ch['layer'], None)['minleg'] == BREAKOUT_LEG) or \
                           (j == len(ch['segs']) - 1 and st.terminal_spec(ch['b'], ch['net'], ch['layer'], None)['minleg'] == BREAKOUT_LEG)
                    todo.append((0 if fine else 1, j - i + 1, fk, ch, pts, i, j))
        if not todo:
            print('nothing left to try'); break
        todo.sort(key=lambda t: (t[0], t[1], t[2]))
        _, _, fk, ch, pts, i, j = todo[0]
        name = st.b.nets[ch['net']]
        t0 = time.time()
        r = st.try_run(ch, pts, i, j, maxlegs)
        if r is None and name == '/GND' and i == 0 and j == len(ch['segs']) - 1 and st.gnd_delete(ch):
            print('del   %-10s stub %s deleted (the pad joins the pour; the via stays within reach)' % (name, np.round(np.array(ch['a']) / KEY, 2)))
            continue
        if r is None and name == '/GND' and i == 0 and j == len(ch['segs']) - 1:
            vs = st.via_stub(ch)
            if vs is not None:
                vi, V, leg, ws = vs
                for s_ in ch['segs']:
                    st.alive[s_] = False
                st.vias[vi, 0], st.vias[vi, 1] = V
                st.new.append((round(leg[0][0], 4), round(leg[0][1], 4), V[0], V[1], ws[0], ch['layer'], ch['net']))
                print('via   %-10s moved via %d to (%.2f,%.2f)' % (name, vi, *V))
                continue
        if r is None:
            failed.add(fk)
            print('FAIL  %-10s run %d..%d of %d  (%.2f,%.2f)-(%.2f,%.2f)' % (name, i, j, len(ch['segs']), *fk[1:]))
            if '--why' in a and st.last:
                obs, A, B, fd, ld, mf, ml, w = st.last
                cs = candidates(A, B, fd, ld, mf, ml, MIN_LEG, max_legs=3)[:3]
                for cost, pp in cs:
                    print('       cand', np.round(pp, 2).tolist(), st.blockers(pp, obs, w))
                if not cs:
                    print('       no candidate geometry (legs/dirs) between', A, B, fd, ld, mf, ml)
        else:
            newpts, lo, hi, ext, legs, wsall = r
            st.replace(ch, lo, hi, newpts, wsall)
            print('ok    %-10s run %d..%d ext %d -> %d legs  %.1fs   findings %d' % (name, i, j, ext, legs, time.time() - t0, len(fnd)))
    fnd = st.findings()
    print('left', dict(collections.Counter(f[0] for f in fnd)), 'failed runs', len(failed))
    write(inp, out, st)
    for fk in sorted(failed):
        print('  failed', st.b.nets[fk[0]], fk[1:])


if __name__ == '__main__':
    main()
