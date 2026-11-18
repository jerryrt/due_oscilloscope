"""State of the top-layer tracks of a .kicad_pcb for the copper cleanup: the net graph (chains of segments between pads, vias and junctions), the copper a new track must keep clear of,
and the writer that splices changed segments and vias back into the board text. Used by cc_reroute.py, cc_edits.py and cc_gndvias.py; see README.md."""
import sys, os, re, math, uuid, collections, itertools, time
HERE = os.path.dirname(os.path.abspath(__file__))
AFE = os.path.normpath(os.path.join(HERE, '..', '..', '..'))                 # hardware/afe-proto
sys.path[:0] = [HERE, AFE, os.path.join(AFE, '..', 'pcbkit')]
import numpy as np
import pcbtools                                        # registers pcbkit
from pcbkit import board as KB, rules, geom
from cc_router import DIRS, candidates

from pcbtools.frame import FRAME
from pcbtools.boards import v2_layout as _L
CFG = {k: getattr(_L, k) for k in [n.key for n in rules.TRACK_GEOMETRY_NAMES + rules.FILL_QUALITY_NAMES] if hasattr(_L, k)}      # the AFE-2 configuration: the names the two rules declare, as pcbkit_regress/geometry.py reads them
MIN_LEG, BREAKOUT_LEG, FINE_PITCH = 0.62, 0.3, 0.65             # the rule needs 0.6: coordinates are rounded to 0.1 um
REQ_MAX, REQ_MIN, REQ_SAME = 0.3, 0.15, 0.12
KEY = 1000


def key(x, y):
    return (int(round(x * KEY)), int(round(y * KEY)))


class State:
    def __init__(self, path):
        self.path = path
        self.b = KB.read_board(path, FRAME)
        b = self.b
        self.S = np.column_stack([b.s_x0, b.s_y0, b.s_x1, b.s_y1]).copy()
        self.S0 = self.S.copy()
        self.W = b.s_w.copy()
        self.W0 = self.W.copy()
        self.L = b.s_layer.astype(int).copy()
        self.N = b.s_net.astype(int).copy()
        self.alive = np.ones(len(self.S), bool)
        self.pt = rules.pads(b)
        allrows = np.arange(len(b.p_x))
        self.pa = dict(rows=allrows, cx=b.p_x, cy=b.p_y, sx=b.p_sx, sy=b.p_sy, rot=b.p_rot, shape=b.p_shape, fp=b.p_fp, net=b.p_net, mask=b.p_layer_mask)       # every pad row: the rule's table keeps one per ref.pin and drops the exposed pad's rectangle
        self.fine = rules._fp_pitch(b)
        self.new = []                               # [(x0, y0, x1, y1, w, layer, net)]
        self.vias = np.column_stack([b.v_x, b.v_y, b.v_dia, b.v_net]).copy()
        self.cu_pads = geom.pad_copper(b, self.pa['rows'])

    # --- the net graph
    def net_segments(self, net, layer=0):
        return [i for i in np.flatnonzero(self.alive & (self.N == net) & (self.L == layer))]

    def pad_at(self, x, y, net, layer):
        """rows (into pa) of the net's pads on `layer` whose copper holds the point"""
        pa = self.pa
        hit = np.flatnonzero(rules._in_pads(np.array([[x, y]]), pa)[0] & (pa['net'] == net) & ((pa['mask'] & (1 << layer)) > 0))
        return hit

    def via_at(self, x, y):
        if not len(self.vias):
            return -1
        d = np.hypot(self.vias[:, 0] - x, self.vias[:, 1] - y)
        k = int(np.argmin(d))
        return k if d[k] <= self.vias[k, 2] / 2 + 1e-3 else -1

    def chains(self, net, layer=0):
        """[Chain]: maximal runs of segments through plain two-segment joints, between terminals (pads of the net, vias, junctions, loose ends)"""
        segs = self.net_segments(net, layer)
        at = collections.defaultdict(list)
        for i in segs:
            for e in (0, 1):
                at[key(*self.S[i, 2 * e:2 * e + 2])].append((i, e))
        def terminal(k):
            lst = at[k]
            x, y = k[0] / KEY, k[1] / KEY
            return len(lst) != 2 or len(self.pad_at(x, y, net, layer)) > 0 or self.via_at(x, y) >= 0
        out, used = [], set()
        for k, lst in at.items():
            if not terminal(k):
                continue
            for i, e in lst:
                if i in used:
                    continue
                run, cur_i, cur_e = [], i, e                      # walk away from k through segment i
                kk = k
                while True:
                    run.append((cur_i, cur_e))                    # cur_e = the end of cur_i that touches the node we came from
                    used.add(cur_i)
                    far = 1 - cur_e
                    k2 = key(*self.S[cur_i, 2 * far:2 * far + 2])
                    if terminal(k2):
                        break
                    nxt = [(j, f) for j, f in at[k2] if j != cur_i]
                    cur_i, cur_e = nxt[0]
                kend = k2
                out.append(dict(net=net, layer=layer, segs=[r[0] for r in run], a=kk, b=kend))
        return out

    def chain_polyline(self, ch):
        pts = [np.array(ch['a']) / KEY]
        for i in ch['segs']:
            p0, p1 = self.S[i, :2], self.S[i, 2:]
            cur = pts[-1]
            pts.append(p1 if np.hypot(*(p0 - cur)) < 2e-3 else p0)
        return pts

    # --- the rule, per chain
    def dirty_chains(self):
        """chains with a finding of the real rule on any of their segments"""
        b = self.b
        findings = rules.track_geometry_parts(self.board(), CFG)
        res = collections.defaultdict(list)
        chs = []
        for net in sorted(set(self.N[self.alive & (self.L == 0)].tolist())):
            chs += self.chains(net)
        if not findings:
            return [], chs
        pts = np.array([[f[2], f[3]] for f in findings])
        S = self.S
        dirty = []
        for ch in chs:
            segs = ch['segs']
            D = geom.point_seg_dist(pts, S[segs])
            hit = np.flatnonzero((D < 0.03).any(axis=1))
            if len(hit):
                ch['why'] = sorted({findings[h][0] for h in hit})
                dirty.append(ch)
        return dirty, chs

    def board(self):
        """BoardArrays with the current segments (the rule reads these)"""
        b = self.b
        idx = np.flatnonzero(self.alive)
        S = np.vstack([self.S[idx]] + ([np.array([[n[0], n[1], n[2], n[3]] for n in self.new])] if self.new else []))
        W = np.concatenate([self.W[idx]] + ([np.array([n[4] for n in self.new])] if self.new else []))
        Ly = np.concatenate([self.L[idx]] + ([np.array([n[5] for n in self.new])] if self.new else [])).astype(np.int8)
        Nn = np.concatenate([self.N[idx]] + ([np.array([n[6] for n in self.new])] if self.new else [])).astype(np.int32)
        # arcs and vias keep their indices; segments are renumbered after them (the rule reads positions, not indices)
        s_idx = np.arange(len(S), dtype=np.int32)
        return b.replace(s_idx=s_idx, s_x0=S[:, 0], s_y0=S[:, 1], s_x1=S[:, 2], s_y1=S[:, 3], s_w=W, s_layer=Ly, s_net=Nn)

    # --- obstacles
    def obstacles(self, net, layer, win, skip_pads, old_polyline, width, skip_vias=()):
        """(C (k,4), r (k,), owner (k,), req per owner) of the copper a new chain of `net` must keep clear of, inside the window"""
        b = self.b
        x0, y0, x1, y1 = win
        C, R, O, REQ, kind = [], [], [], [], []
        self.names = []
        n_owner = 0
        old = np.array([[old_polyline[i][0], old_polyline[i][1], old_polyline[i + 1][0], old_polyline[i + 1][1]] for i in range(len(old_polyline) - 1)])
        # other-net tracks on the layer
        idx = np.flatnonzero(self.alive & (self.L == layer) & (self.N != net))
        for i in idx:
            s = self.S[i]
            if max(s[0], s[2]) < x0 or min(s[0], s[2]) > x1 or max(s[1], s[3]) < y0 or min(s[1], s[3]) > y1:
                continue
            g = float(geom.seg_seg_dist(old, s[None, :]).min()) - width / 2 - self.W[i] / 2
            C.append(s); R.append(self.W[i] / 2); O.append(n_owner); REQ.append(self.req(net, int(self.N[i]), g)); self.names.append('seg %s %s' % (b.nets[self.N[i]], np.round(s, 2).tolist())); n_owner += 1
        for (a0, a1, a2, a3, w, ly, nn) in self.new:
            if ly == layer and nn != net:
                s = np.array([a0, a1, a2, a3])
                if max(s[0], s[2]) < x0 or min(s[0], s[2]) > x1 or max(s[1], s[3]) < y0 or min(s[1], s[3]) > y1:
                    continue
                C.append(s); R.append(w / 2); O.append(n_owner); REQ.append(REQ_MAX); self.names.append('new seg %s' % b.nets[nn]); n_owner += 1
        # vias (through: every layer)
        for vk, v in enumerate(self.vias):
            if vk in skip_vias:
                continue
            if x0 <= v[0] <= x1 and y0 <= v[1] <= y1:
                same = int(v[3]) == net
                g = float(geom.point_seg_dist(np.array([[v[0], v[1]]]), old).min()) - width / 2 - v[2] / 2
                C.append(np.array([v[0], v[1], v[0], v[1]])); R.append(v[2] / 2); O.append(n_owner)
                REQ.append(REQ_SAME if same else self.req(net, int(v[3]), g)); self.names.append('via %s' % b.nets[int(v[3])]); n_owner += 1
        # pads on the layer, every pad but the chain's own ends
        cu = self.cu_pads
        pa = self.pa
        for h in range(len(pa['rows'])):
            if h in skip_pads or not (pa['mask'][h] & (1 << layer)):
                continue
            if not (x0 - 1 <= pa['cx'][h] <= x1 + 1 and y0 - 1 <= pa['cy'][h] <= y1 + 1):
                continue
            rows = np.flatnonzero(cu.owner == h)
            same = int(pa['net'][h]) == net
            cs = cu.C[rows]
            g = float((geom.seg_seg_dist(old, cs) - cu.r[rows][None, :] - width / 2).min())
            for r_ in rows:
                C.append(cu.C[r_]); R.append(cu.r[r_]); O.append(n_owner)
            REQ.append(REQ_SAME if same else self.req(net, int(pa['net'][h]), g)); self.names.append('pad %s.%s %s' % (b.fp_ref[pa['fp'][h]], b.p_pin[pa['rows'][h]], b.nets[int(pa['net'][h])])); n_owner += 1
        if not C:
            return np.zeros((0, 4)), np.zeros(0), np.zeros(0, int), np.zeros(0)
        return np.array(C), np.array(R), np.array(O, int), np.array(REQ)

    SENS = ('/A0', '/A1', '/VREF', '/TAP', '/SNS', '/AWG_BNC', '/ADS_', '/AREF', '/AWG_FB', '/AWG_BIN', '/CH1_N', '/CH2_N', '/CH1_M', '/CH2_M', '/CH1_NP', '/CH2_NP')

    def req(self, na, nb, g):
        """the clearance a new track must keep from an object: 0.2 mm; where the old track was nearer, no less than it was (never under the DRC's 0.15); and around the
        sensitive nets no less than the old gap up to 0.5 mm"""
        names = (self.b.nets[na], self.b.nets[nb] if 0 <= nb < len(self.b.nets) else '')
        if any(n.startswith(self.SENS) for n in names):
            return max(0.2, min(0.5, g))
        return 0.2 if g >= 0.2 else max(0.15, g)

    def valid(self, cands, obs, width, edge=0.5, wfun=None):
        """boolean per candidate path (list of points): clear of every obstacle by its requirement"""
        C, R, O, REQ = obs
        ok = np.ones(len(cands), bool)
        segs, owner, wid = [], [], []
        for ci, (_, pts) in enumerate(cands):
            ws = wfun(pts) if wfun else [width] * (len(pts) - 1)
            for i in range(len(pts) - 1):
                segs.append([pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]]); owner.append(ci); wid.append(ws[i])
        if not segs:
            return ok
        segs = np.array(segs); owner = np.array(owner); wid = np.array(wid)
        bad = np.zeros(len(cands), bool)
        if len(C):
            for a0 in range(0, len(segs), 256):
                blk = slice(a0, a0 + 256)
                D = geom.seg_seg_dist(C, segs[blk]) - R[:, None] - (wid[blk] / 2)[None, :]                  # (k, m)
                M = np.full((int(O.max()) + 1, D.shape[1]), np.inf)
                np.minimum.at(M, O, D)
                viol = (M < REQ[:, None] - 1e-9).any(axis=0)
                for j in np.flatnonzero(viol):
                    bad[owner[a0 + j]] = True
        # board area
        x0, y0, x1, y1 = self.area
        for ci, (_, pts) in enumerate(cands):
            P = np.array(pts)
            if (P[:, 0] < x0 + edge).any() or (P[:, 0] > x1 - edge).any() or (P[:, 1] < y0 + edge).any() or (P[:, 1] > y1 - edge).any():
                bad[ci] = True
        return ~bad

    area = (17.0, -4.5, 117.0, 57.84)                  # BOARD_RECT

    def blockers(self, pts, obs, width):
        C, R, O, REQ = obs
        segs = np.array([[pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]] for i in range(len(pts) - 1)])
        D = geom.seg_seg_dist(C, segs) - R[:, None] - width / 2
        M = np.full(int(O.max()) + 1, np.inf)
        np.minimum.at(M, O, D.min(axis=1))
        return [(self.names[k], round(float(M[k]), 3), round(float(REQ[k]), 3)) for k in np.flatnonzero(M < REQ - 1e-9)]

    # --- routing one chain
    def terminal_spec(self, k, net, layer, other_pos):
        """position, allowed first directions, minimum first leg, the pad rows to skip as obstacles"""
        x, y = k[0] / KEY, k[1] / KEY
        pads = self.pad_at(x, y, net, layer)
        v = self.via_at(x, y)
        if len(pads):
            # the pad whose centre is nearest
            pa = self.pa
            h = min(pads, key=lambda q: math.hypot(pa['cx'][q] - x, pa['cy'][q] - y))
            sh = pa['shape'][h]
            cx, cy = float(pa['cx'][h]), float(pa['cy'][h])
            rot = float(pa['rot'][h]) % 360
            if sh == 0:                                                    # a round pad: any octilinear direction
                dirs = list(range(8)); pos = (cx, cy)
            else:
                base = int(round(rot / 45.0)) % 8
                dirs = [(base + q) % 8 for q in (0, 2, 4, 6)] if abs(rot / 45.0 - round(rot / 45.0)) < 1e-6 else [0, 2, 4, 6]
                pos = (cx, cy)
            fine = self.fine.get(int(pa['fp'][h]), 9) <= FINE_PITCH + 1e-9
            return dict(pos=pos, dirs=dirs, minleg=BREAKOUT_LEG if fine else MIN_LEG, skip={int(q) for q in pads}, kind='pad', row=int(h), cap=self.pad_caps(h, dirs))
        if v >= 0:
            return dict(pos=(float(self.vias[v, 0]), float(self.vias[v, 1])), dirs=list(range(8)), minleg=MIN_LEG, skip=set(), kind='via', row=v, via=v)
        return dict(pos=(x, y), dirs=list(range(8)), minleg=MIN_LEG, skip=set(), kind='free', row=-1)

    def pad_caps(self, h, dirs):
        """{direction index: the widest track that enters the pad along it through the edge}: the pad's span across that direction"""
        pa = self.pa
        rot = float(pa['rot'][h]) % 360
        out = {}
        for d in dirs:
            ang = (45 * d - rot) % 180
            along_x = min(ang, 180 - ang) < 1e-6
            out[d] = float(pa['sy'][h] if along_x else pa['sx'][h]) if pa['shape'][h] != 0 else float(min(pa['sx'][h], pa['sy'][h]))
        return out

    def route(self, ch, max_legs=3, verbose=False):
        net, layer = ch['net'], ch['layer']
        old = self.chain_polyline(ch)
        sa = self.terminal_spec(ch['a'], net, layer, None)
        sb = self.terminal_spec(ch['b'], net, layer, None)
        width = float(self.W[ch['segs'][0]])
        A, B = sa['pos'], sb['pos']
        xs = [A[0], B[0]] + [p[0] for p in old]; ys = [A[1], B[1]] + [p[1] for p in old]
        win = (min(xs) - 3.0, min(ys) - 3.0, max(xs) + 3.0, max(ys) + 3.0)
        obs = self.obstacles(net, layer, win, sa['skip'] | sb['skip'], old, width)
        # the chain's own old segments are not obstacles (other nets only), so nothing to exclude
        last_dirs = [(d + 4) % 8 for d in sb['dirs']]                          # arriving along d means leaving B along d + 4
        for legs in range(1, max_legs + 1):
            cands = candidates(A, B, sa['dirs'], last_dirs, sa['minleg'], sb['minleg'], MIN_LEG, max_legs=legs)
            cands = [c for c in cands if len(c[1]) - 1 == legs]
            for a0 in range(0, len(cands), 200):
                blk = cands[a0:a0 + 200]
                ok = self.valid(blk, obs, width)
                if ok.any():
                    return blk[int(np.argmax(ok))][1], legs
        return None, None

    def apply(self, ch, pts):
        for i in ch['segs']:
            self.alive[i] = False
        w = float(self.W[ch['segs'][0]])
        for i in range(len(pts) - 1):
            self.new.append((round(pts[i][0], 4), round(pts[i][1], 4), round(pts[i + 1][0], 4), round(pts[i + 1][1], 4), w, ch['layer'], ch['net']))


def write(inp, out, st):
    text = open(inp).read()
    b = st.b
    # remove old segment blocks of killed segments (matched by their coordinates), add the new ones after the last segment block
    pat = re.compile(r'\n\t\(segment\n\t\t\(start ([-\d.]+) ([-\d.]+)\)\n\t\t\(end ([-\d.]+) ([-\d.]+)\)\n\t\t\(width ([-\d.]+)\)\n\t\t\(layer "([^"]+)"\)\n\t\t\(net "([^"]*)"\)\n\t\t\(uuid "([^"]+)"\)\n\t\)')
    ms = list(pat.finditer(text))
    assert len(ms) == len(st.S), (len(ms), len(st.S))
    # the arrays enumerate GetTracks(): arcs and vias are interleaved, so match by value
    def k4(x0, y0, x1, y1):
        return tuple(int(round(v * 10000)) for v in (x0, y0, x1, y1))
    old_by = collections.defaultdict(list)
    moved = [i for i in range(len(st.S)) if st.alive[i] and (np.abs(st.S[i] - st.S0[i]).max() > 1e-9 or abs(st.W[i] - st.W0[i]) > 1e-9)]
    for i in range(len(st.S)):
        s = st.S0[i]
        ax, ay = FRAME[0] + s[0], FRAME[1] - s[1]
        bx, by = FRAME[0] + s[2], FRAME[1] - s[3]
        old_by[(k4(ax, ay, bx, by), b.nets[st.N[i]])].append(i)
    kill = set()
    for m in ms:
        kk = (k4(*(float(m.group(j)) for j in (1, 2, 3, 4))), m.group(7))
        lst = old_by.get(kk)
        if lst:
            i = lst.pop()
            if not st.alive[i] or i in moved:
                kill.add(m.start())
    parts, last = [], 0
    for m in ms:
        if m.start() in kill:
            parts.append(text[last:m.start()]); last = m.end()
    parts.append(text[last:])
    text = ''.join(parts)
    # new segments. A run keeps the direction the board of record drew it in: a track that started at a pad still starts there (the segment direction carries no meaning in KiCad, but
    # test_v2_bnc_pitch reads "a track starts at the BNC pin's centre", and the first version of this pass wrote the run from its other end)
    starts = collections.defaultdict(int)
    for i in range(len(st.S0)):
        if st.alive[i] and i not in moved: continue               # only the segments this pass replaced say which way the run went
        starts[(int(st.N[i]), int(st.L[i]), int(round(st.S0[i][0] * 10000)), int(round(st.S0[i][1] * 10000)))] += 1
    def sk(p, r):
        return (int(r[6]), int(r[5]), int(round(p[0] * 10000)), int(round(p[1] * 10000)))
    runs, cur = [], []
    for r in st.new:
        if cur and cur[-1][5:7] == r[5:7] and abs(cur[-1][2] - r[0]) < 1e-6 and abs(cur[-1][3] - r[1]) < 1e-6:
            cur.append(r)
        else:
            if cur: runs.append(cur)
            cur = [r]
    if cur: runs.append(cur)
    fixed = []
    for run in runs:
        head = starts[sk(run[0][:2], run[0])]
        tail = starts[sk(run[-1][2:4], run[-1])]
        if tail > head:
            run = [(r[2], r[3], r[0], r[1]) + tuple(r[4:]) for r in reversed(run)]
        fixed += run
    st.new = fixed
    blocks = []
    extra = [(*st.S[i], st.W[i], st.L[i], st.N[i]) for i in moved]
    for (x0, y0, x1, y1, w, ly, nn) in list(st.new) + extra:
        u = uuid.uuid5(uuid.NAMESPACE_URL, 'afe2-cc/%s/%.4f,%.4f,%.4f,%.4f' % (b.nets[nn], x0, y0, x1, y1))
        blocks.append('\n\t(segment\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(width %s)\n\t\t(layer "%s")\n\t\t(net "%s")\n\t\t(uuid "%s")\n\t)' % (
            fmt(FRAME[0] + x0), fmt(FRAME[1] - y0), fmt(FRAME[0] + x1), fmt(FRAME[1] - y1), fmt(w), 'F.Cu' if ly == 0 else 'B.Cu', b.nets[nn], u))
    ms2 = list(pat.finditer(text))
    pos = ms2[-1].end()
    text = text[:pos] + ''.join(blocks) + text[pos:]
    text = move_vias(text, st)
    text = drop_vias(text, st)
    text = add_vias(text, st)
    open(out, 'w').write(text)
    print('wrote', out, 'killed', len(kill), 'added', len(blocks))


def move_vias(text, st):
    b = st.b
    n = 0
    for k in range(len(b.v_x)):
        if abs(st.vias[k, 0] - b.v_x[k]) > 1e-9 or abs(st.vias[k, 1] - b.v_y[k]) > 1e-9:
            ox, oy = FRAME[0] + b.v_x[k], FRAME[1] - b.v_y[k]
            nx, ny = FRAME[0] + st.vias[k, 0], FRAME[1] - st.vias[k, 1]
            pat = re.compile(r'(\n\t\(via\n\t\t\(at )%s %s(\))' % (re.escape(fmt(ox)), re.escape(fmt(oy))))
            text, c = pat.subn(lambda m: m.group(1) + '%s %s' % (fmt(nx), fmt(ny)) + m.group(2), text, count=1)
            assert c == 1, ('via not found', ox, oy)
            n += 1
    print('moved vias', n)
    return text


def drop_vias(text, st):
    b = st.b
    n = 0
    for k in sorted(getattr(st, 'via_dead', ())):
        ox, oy = FRAME[0] + b.v_x[k], FRAME[1] - b.v_y[k]
        pat = re.compile(r'\n\t\(via\n\t\t\(at %s %s\)\n(?:\t\t[^\n]*\n)*?\t\)(?=\n)' % (re.escape(fmt(ox)), re.escape(fmt(oy))))
        text, c = pat.subn('', text, count=1)
        assert c == 1, ('via block not found', ox, oy)
        n += 1
    print('dropped vias', n)
    return text


def add_vias(text, st):
    b = st.b
    new = st.vias[len(b.v_x):]
    if not len(new):
        return text
    blocks = ''
    for v in new:
        u = uuid.uuid5(uuid.NAMESPACE_URL, 'afe2-cc-via/%.4f,%.4f' % (v[0], v[1]))
        blocks += '\n\t(via\n\t\t(at %s %s)\n\t\t(size 0.6)\n\t\t(drill 0.3)\n\t\t(layers "F.Cu" "B.Cu")\n\t\t(net "%s")\n\t\t(uuid "%s")\n\t)' % (fmt(FRAME[0] + v[0]), fmt(FRAME[1] - v[1]), b.nets[int(v[3])], u)
    last = list(re.finditer(r'\n\t\(via\n(?:\t\t[^\n]*\n)*?\t\)(?=\n)', text))[-1]
    print('added vias', len(new))
    return text[:last.end()] + blocks + text[last.end():]


def fmt(v):
    s = ('%.6f' % v).rstrip('0').rstrip('.')
    return s if s not in ('', '-0') else '0'


if __name__ == '__main__':
    main()
