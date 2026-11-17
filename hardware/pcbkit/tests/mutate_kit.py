"""Mutation proof for pcbkit.geom and pcbkit.board: copy the package to a scratch dir, break one thing at a time with a text
edit, run the module's tests against the broken copy (PCBKIT_ROOT points the suite at it) and require them to FAIL. The
unmutated copy must pass first. Run in the image from the repository root:

    docker/pcb/run.sh env PCBKIT_REQUIRE_PCBNEW=1 python3 hardware/pcbkit/tests/mutate_kit.py        (exit 1 if a mutant survives)
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                                 # hardware/pcbkit
SCR = os.path.join(ROOT, '.scratch', 'mut')

GEOM = [
    ('point-seg distance returns the square', "return np.hypot(px - (x0 + t * dx), py - (y0 + t * dy))",
     "return (px - (x0 + t * dx)) ** 2 + (py - (y0 + t * dy)) ** 2"),
    ('point-seg: no clamp to the segment', "t = np.clip(t, 0.0, 1.0)", "t = t"),
    ('point-seg: zero-length guard removed', "where=l2 > 0)", "where=l2 >= 0)"),
    ('seg-seg: crossing test dropped', "return np.where(crossing, 0.0, d)", "return d"),
    ('seg-seg: one endpoint distance dropped', "np.minimum(_pt_seg(bx0, by0, ax0, ay0, ax1, ay1), _pt_seg(bx1, by1, ax0, ay0, ax1, ay1)))",
     "_pt_seg(bx0, by0, ax0, ay0, ax1, ay1))"),
    ('tiles: last row of every tile dropped', "yield a, min(a + an, n), b, min(b + bm, m)", "yield a, min(a + an, n) - 1, b, min(b + bm, m)"),
    ('tiles: last column of every tile dropped', "yield a, min(a + an, n), b, min(b + bm, m)", "yield a, min(a + an, n), b, min(b + bm, m) - 1"),
    ('within: <= instead of <', "r, c = np.nonzero(dist < d)", "r, c = np.nonzero(dist <= d)"),
    ('within: x prune too tight', "np.searchsorted(sbx, axhi[ia].max() + d, side='left')", "np.searchsorted(sbx, axhi[ia].max(), side='left')"),
    ('within: y prune wrong sign', "(bylo[cand] < ayhi[ia].max() + d)", "(bylo[cand] < ayhi[ia].max() - d)"),
    ('within: result order not sorted', "o = np.lexsort((J, I))", "o = np.arange(len(I))[::-1]"),
    ('min_dist: min replaced by max', "_rows(A, B, a0, a1, b0, b1).min(axis=1)", "_rows(A, B, a0, a1, b0, b1).max(axis=1)"),
    ('box_overlap: strict counts touching', "return (ox > 0) & (oy > 0) if strict else (ox >= 0) & (oy >= 0)",
     "return (ox >= 0) & (oy >= 0) if strict else (ox >= 0) & (oy >= 0)"),
    ('box_dist: manhattan instead of euclid', "return np.hypot(gx, gy)", "return gx + gy"),
    ('seg_in_box: pad ignored on the high side', "box[None, :, 2] + pad)", "box[None, :, 2])"),
    ('seg_in_box: parallel case not range-checked', "ok &= ~par | ((o >= lo) & (o <= hi))", "ok &= True"),
    ('points_in_polys: parity test off', "% 2) == 1", "% 2) >= 1 if False else (np.abs(straddle & (px < xi)).sum(axis=1) > 0)"),
    ('points_in_polys: holes ignored', "res[:, owner[j]] &= ~out[:, j]", "res[:, owner[j]] &= True"),
    ('points_in_polys: hole cuts the wrong outline', "owner = np.cumsum(hole == 0) - 1", "owner = np.cumsum(hole == 0) * 0"),
    ('connected_components: directed strong', "_cc(g, directed=False)", "_cc(g, directed=True, connection='strong')"),
    ('seg_len: manhattan', "return np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1])", "return np.abs(S[:, 2] - S[:, 0]) + np.abs(S[:, 3] - S[:, 1])"),
    ('matrix guard removed', "if n * m * 8 > MAX_MATRIX_BYTES:", "if False:"),
]
COPPER = [
    ('copper: radius not subtracted', "np.maximum(min_dist(self.C, E) - self.r, 0.0)", "np.maximum(min_dist(self.C, E), 0.0)"),
    ('copper: track radius is the full width', "b.s_w[rows] / 2", "b.s_w[rows]"),
    ('copper: box with an end inside is not zero', "d[np.unique(own[inb])] = 0.0", "pass"),
    ('copper: fill inside test dropped', "d[np.unique(own[inside])] = 0.0", "pass"),
    ('copper: pad rotation ignored', "a = np.radians(rot)[:, None]", "a = np.radians(rot * 0)[:, None]"),
    ('copper: join does not offset owners', "O.append(p.owner + n)", "O.append(p.owner)"),
]
BOARD = [
    ('frame: y not flipped', "return np.asarray(x, np.float64) - frame[0], frame[1] - np.asarray(y, np.float64)",
     "return np.asarray(x, np.float64) - frame[0], np.asarray(y, np.float64) - frame[1]"),
    ('frame: x offset dropped', "return np.asarray(x, np.float64) - frame[0], frame[1]", "return np.asarray(x, np.float64), frame[1]"),
    ('frame: inverse forgets the offset', "return np.asarray(x, np.float64) + frame[0], frame[1] - np.asarray(y, np.float64)",
     "return np.asarray(x, np.float64), frame[1] - np.asarray(y, np.float64)"),
    ('read_board ignores the configuration frame', "    frame = frame_of(cfg)\n    import gc", "    frame = KICAD_FRAME\n    import gc"),
    ('a configuration without FRAME falls back to the KiCad frame', "raise ValueError('no FRAME = (OX, OY)", "return KICAD_FRAME; raise ValueError('no FRAME = (OX, OY)"),
    ('no configuration at all is accepted', "    if cfg is None:\n        fr = None\n    elif", "    if cfg is None:\n        return KICAD_FRAME\n    elif"),
    ('to_frame gets a default frame back', "def to_frame(x, y, frame):", "def to_frame(x, y, frame=KICAD_FRAME):"),
    ('read_board gets a default config back', "def read_board(path, cfg):", "def read_board(path, cfg=KICAD_FRAME):"),
    ('retry child does not pass the frame', "repr(ox), repr(oy)]", "'0.0', '0.0']"),
]
SILK = [
    ('fab box reads the silk layer', "if lay_ == pcb.F_Fab and g.GetClass() == 'PCB_SHAPE':", "if lay_ == pcb.F_SilkS and g.GetClass() == 'PCB_SHAPE':"),
    ('fab box of a footprint without one is 0, not NaN', "else (np.nan,) * 4)\n", "else (0.0,) * 4)\n"),
    ('fab box top edge taken from the wrong corner', "fx1, fy0 = to_f(fb[:, 2], fb[:, 3])", "fx1, fy0 = to_f(fb[:, 2], fb[:, 1])"),
    ('footprint silk reads the fab layer', "elif lay_ == pcb.F_SilkS:", "elif lay_ == pcb.F_Fab:"),
    ('footprint silk owner always row 0', "FS.append((i, ", "FS.append((0, "),
    ('segment kind named rect', "pcb.SHAPE_T_SEGMENT: 'segment'", "pcb.SHAPE_T_SEGMENT: 'rect'"),
    ('board silk graphics from every layer', "d.GetClass() == 'PCB_SHAPE' and d.GetLayer() == pcb.F_SilkS]", "d.GetClass() == 'PCB_SHAPE']"),
    ('board silk graphics: y edges swapped', "g_y0=_r(y0), g_x1=_r(x1), g_y1=_r(y1)", "g_y0=_r(y1), g_x1=_r(x1), g_y1=_r(y0)"),
    ('board texts from every layer', "if d.GetClass() == 'PCB_TEXT' and d.GetLayer() == pcb.F_SilkS]", "if d.GetClass() == 'PCB_TEXT']"),
    ('text angle dropped', "t_ang=_r([t[4] for t in T])", "t_ang=_r([0.0 for t in T])"),
    ('text stroke is its height', "t_stroke=_r(np.array([t[5] for t in T]) * U)", "t_stroke=_r(np.array([t[3] for t in T]) * U)"),
    ('text justification always centre', "t_just=[t[7] for t in T]", "t_just=['center' for t in T]"),
    ('text box x edges swapped', "t_x0=_r(x0), t_y0=_r(y0), t_x1=_r(x1), t_y1=_r(y1))", "t_x0=_r(x1), t_y0=_r(y0), t_x1=_r(x0), t_y1=_r(y1))"),
    ('reference hide flag dropped', "not r.IsVisible(), _just(pcb, r)))", "False, _just(pcb, r)))"),
    ('justification left reads as right', "pcb.GR_TEXT_H_ALIGN_LEFT: 'left'", "pcb.GR_TEXT_H_ALIGN_LEFT: 'right'"),
    ('pad box right edge is its left edge', "bb.GetRight(), bb.GetBottom(), pd.GetNetCode()", "bb.GetLeft(), bb.GetBottom(), pd.GetNetCode()"),
    ('an added field of the wrong length is let through', "if not (n in _ADDED and len(getattr(self, n)) == 0)}\n        if len(ns) > 1:", "if not (n in _ADDED)}\n        if len(ns) > 1:"),
]
REQUIRE = [
    ('require never raises', "if f in LATER_FIELDS and f not in b.read_fields:", "if False:"),
    ('fab_boxes forgets require', "require(b, 'fp_fab_x0', 'fp_fab_y0', 'fp_fab_x1', 'fp_fab_y1')\n", "pass\n"),
    ('text_boxes forgets require', "require(b, 't_x0', 't_y0', 't_x1', 't_y1')\n", "pass\n"),
    ('footprint_silk forgets require', "require(b, 'fs_fp', 'fs_x0', 'fs_y0', 'fs_x1', 'fs_y1', 'fs_kind')\n", "pass\n"),
    ('board_silk_graphics forgets require', "require(b, 'g_x0', 'g_y0', 'g_x1', 'g_y1', 'g_kind')\n", "pass\n"),
    ('a hand-built board claims every later field read', "dataclasses.field(default=frozenset()))]      # which LATER_FIELDS", "dataclasses.field(default=LATER_FIELDS))]      # which LATER_FIELDS"),
    ('read_board does not record what it filled', "read_fields=frozenset(LATER_FIELDS), **kw)", "**kw)"),
    ('the npz cache forgets read_fields', "'__read_fields': np.array(sorted(b.read_fields), dtype=str)}", "'__read_fields': np.array([], dtype=str)}"),
    ('an unknown field name is accepted', "if f not in KIND:", "if False:"),
]
GROUND_PLANE = [
    ('ground_plane: layer count not checked', "if b.copper_layers != c.COPPER_LAYERS:", "if False:"),
    ('ground_plane: another net\'s zone not reported', "for zi in bot[b.z_net[bot] != gnd]:", "for zi in []:"),
    ('ground_plane: a second GND zone not reported', "if len(bz) > 1:", "if False:"),
    ('ground_plane: an unfilled zone passes', "if not b.z_filled[z]:", "if False:"),
    ('ground_plane: pieces not counted', "if pieces_n != 1:", "if False:"),
    ('ground_plane: a keep-out area counts as a zone', "(b.z_layer == L) & ~b.z_keepout)", "(b.z_layer == L))"),
    ('ground_plane: no zone at all passes', "bad.append(f'no {side} GND zone')", "pass"),
    ('ground_plane: the plane layer is always the bottom', "L = _layer_code(c.PLANE_LAYER)\n    side = 'bottom' if L == 1 else 'top'\n    bad = []", "L = 1\n    side = 'bottom' if L == 1 else 'top'\n    bad = []"),
    ('ground_plane: a hole counts as a piece', "(b.z_ring_hole[b.z_ring_off[z]:b.z_ring_off[z + 1]] == 0).sum()", "(b.z_ring_hole[b.z_ring_off[z]:b.z_ring_off[z + 1]] >= 0).sum()"),
    ('ground_plane: via reach <= becomes <', "if i >= 0 and d[i] <= c.GND_VIA_REACH:", "if i >= 0 and d[i] < c.GND_VIA_REACH:"),
    ('ground_plane: one via serves several pads', "d = np.where(used, np.inf, d)", "d = d"),
    ('ground_plane: a through-hole pad needs a via', "pt.net[j] == gnd and b.p_smd[pt.rows[j]]", "pt.net[j] == gnd"),
    ('ground_plane: a via of another net serves', "gv = np.column_stack([b.v_x, b.v_y])[b.v_net == gnd]", "gv = np.column_stack([b.v_x, b.v_y])"),
]
BOTTOM_HOPS = [
    ('bottom_hops: length > becomes >=', "if Ln > c.HOP_MAX or nv > c.HOP_MAX_VIAS:", "if Ln >= c.HOP_MAX or nv > c.HOP_MAX_VIAS:"),
    ('bottom_hops: vias > becomes >=', "or nv > c.HOP_MAX_VIAS:", "or nv >= c.HOP_MAX_VIAS:"),
    ('bottom_hops: ground copper counts as a hop', "    rows = np.flatnonzero((b.s_layer == L) & (b.s_net != gnd))\n    n = len(rows)", "    rows = np.flatnonzero((b.s_layer == L))\n    n = len(rows)"),
    ('bottom_hops: segments never join', "i, j = geom.within(S, S, c.HOP_JOIN_TOL)", "i, j = geom.within(S, S, 0.0)"),
    ('bottom_hops: segments of different nets join', "keep = (i < j) & (net[i] == net[j])", "keep = (i < j)"),
    ('bottom_hops: a via of another net counts', "m = (d['v'] < c.HOP_VIA_TOL) & (b.v_net[vi] == net[ei % n])", "m = (d['v'] < c.HOP_VIA_TOL)"),
    ('bottom_hops: keep-out margin drops the track width', "pad=c.HOP_KEEPOUT_PAD + b.s_w[rows] / 2)", "pad=c.HOP_KEEPOUT_PAD)"),
    ('bottom_hops: a part without courtyard is not skipped', "refs = sorted(r for r in c.HOP_KEEPOUT_PARTS if has_box(b, r))", "refs = sorted(r for r in c.HOP_KEEPOUT_PARTS)"),
    ('bottom_hops: fence test ignores the track width', "hit = geom.seg_in_box(S, fz, pad=w / 2)", "hit = geom.seg_in_box(S, fz, pad=0.0)"),
    ('bottom_hops: sensitive tracks taken from the plane layer', "trows = np.flatnonzero((b.s_layer == 1 - L) & sens[b.s_net])", "trows = np.flatnonzero((b.s_layer == L) & sens[b.s_net])"),
    ('bottom_hops: sensitive clearance dropped', "close = D < (w[:, None] + b.s_w[trows][None, :]) / 2 + c.HOP_SENSITIVE_CLEAR", "close = D < (w[:, None] + b.s_w[trows][None, :]) / 2"),
    ('bottom_hops: sensitive pad clearance dropped', "pad=c.HOP_SENSITIVE_CLEAR + w / 2)", "pad=w / 2)"),
]
CONFIG = [
    ('config: a missing project name does not raise', "if n.kind == 'project':", "if False:"),
    ('config: a default is reported as the project\'s', "v, src = n.default, 'default'", "v, src = n.default, 'project'"),
]
GUARD = [
    ('guard: nothing is ever near', "return a != b and ((m >= 6 and distance(a, b) <= 2) or (4 <= m < 6 and distance(a, b) <= 1))", "return False"),
    ('guard: distance 2 allowed for short names', "(m >= 6 and distance(a, b) <= 2)", "(m >= 3 and distance(a, b) <= 2)"),
    ('guard: a declared name is tested like any other', "if k in DECLARED:\n            continue", "pass"),
    ('guard: an unrecognised name is not listed', "unknown.append(k)", "pass"),
    ('guard: a near miss does not raise', "if hit:\n            raise ConfigError", "if False:\n            raise ConfigError"),
    ('guard: the message does not name the declared name', 'near {", ".join(hit)}', "near it"),
    ('guard: resolve does not run it', "    out = {}\n    check_names(cfg)\n", "    out = {}\n"),
    ('guard: lower-case names are configuration names', "isinstance(k, str) and k.isupper()", "isinstance(k, str)"),
    ('guard: the edit distance counts substitutions as free', "prev[j - 1] + (ca != cb)", "prev[j - 1]"),
]
SENSITIVE = [
    ('sensitive_nets: no_via False ignored', "if e['no_via'] and (b.v_net == nid(b, n)).any():", "if (b.v_net == nid(b, n)).any():"),
    ('sensitive_nets: no_bottom False ignored', "if e['no_bottom'] and ((b.s_net == nid(b, n)) & (b.s_layer == 1)).any():", "if ((b.s_net == nid(b, n)) & (b.s_layer == 1)).any():"),
    ('sensitive_nets: length > becomes >=', "if e['max_length'] is not None and L > e['max_length']:", "if e['max_length'] is not None and L >= e['max_length']:"),
    ('sensitive_nets: length counts both layers', "        L = length_of(b, n)\n        if e['max_length']", "        L = length_of(b, n, top_only=False)\n        if e['max_length']"),
    ('sensitive_nets: widths not added to the gap', "lim = g[:, None] + (b.s_w[ia][:, None] + b.s_w[ot][None, :]) / 2", "lim = g[:, None]"),
    ('sensitive_nets: the plane net is a foreign track', "ot = np.flatnonzero((b.s_layer == 0) & (b.s_net != gnd))", "ot = np.flatnonzero((b.s_layer == 0))"),
    ('sensitive_nets: a net is its own neighbour', "close = (D < lim) & (b.s_net[ia][:, None] != b.s_net[ot][None, :])", "close = (D < lim)"),
    ('sensitive_nets: every net uses one gap', "g = np.array([gap_of[int(n)] for n in b.s_net[ia]])", "g = np.full(len(ia), 0.6)"),
    ('sensitive_nets: unknown entry keys accepted', "if bad or 'net' not in e:", "if False:"),
]
POUR = [
    ('pour_gap: track keep-back halved', "if g_trk < c.POUR_KEEP_BACK:", "if g_trk < c.POUR_KEEP_BACK / 2:"),
    ('pour_gap: pour keep-back halved', "if g_pour < c.POUR_KEEP_BACK:", "if g_pour < c.POUR_KEEP_BACK / 2:"),
    ('pour_gap: info nodes are judged', "if net not in c.POUR_NODES:\n            continue", "if False:\n            continue"),
    ('pour_gap: ground track half width dropped', "D = geom.seg_seg_dist(cu.C, G[a:a + 1024]) - cu.r[:, None] - wg[None, a:a + 1024]", "D = geom.seg_seg_dist(cu.C, G[a:a + 1024]) - cu.r[:, None]"),
    ('pour_gap: node copper radius dropped', "D = geom.seg_seg_dist(cu.C, G[a:a + 1024]) - cu.r[:, None] - wg[None, a:a + 1024]", "D = geom.seg_seg_dist(cu.C, G[a:a + 1024]) - wg[None, a:a + 1024]"),
    ('pour_gap: an unfilled zone is a pour', "b.z_net[z] == gnd and b.z_filled[z] and not b.z_keepout[z]]", "b.z_net[z] == gnd and not b.z_keepout[z]]"),
    ('pour_gap: a keep-out area is a pour', "b.z_net[z] == gnd and b.z_filled[z] and not b.z_keepout[z]]", "b.z_net[z] == gnd and b.z_filled[z]]"),
    ('pour_gap: a bottom zone is a pour', "b.z_layer[z] == 0 and b.z_net[z] == gnd", "b.z_net[z] == gnd"),
    ('pour_gap: a bottom ground track counts', "gt = np.flatnonzero((b.s_net == gnd) & (b.s_layer == 0))", "gt = np.flatnonzero((b.s_net == gnd))"),
    ('pour_gap: the info nodes are not measured', "for net in tuple(c.POUR_NODES) + tuple(c.POUR_INFO_NODES):", "for net in tuple(c.POUR_NODES):"),
]
KEEPOUT = [
    ('keepout_ring: a bottom track counts', "rows = np.flatnonzero((b.s_layer == 0) & sens[b.s_net])", "rows = np.flatnonzero(sens[b.s_net])"),
    ('keepout_ring: exempt parts are judged', "if pt.keys[j][0] not in c.KEEPOUT_EXEMPT_PARTS]", "if True]"),
    ('keepout_ring: the farthest part counts for a track', "d = np.min([cu.gap_to_box(g) for g in gen], axis=0)\n        dmin = min(dmin, float(d.min()))\n        for i in np.flatnonzero(d < c.KEEPOUT_DIST):\n            near.append(f'{b.nets[b.s_net[rows[i]]]}", "d = np.max([cu.gap_to_box(g) for g in gen], axis=0)\n        dmin = min(dmin, float(d.min()))\n        for i in np.flatnonzero(d < c.KEEPOUT_DIST):\n            near.append(f'{b.nets[b.s_net[rows[i]]]}"),
    ('keepout_ring: the farthest part counts for a pad', "d = np.min([cu.gap_to_box(g) for g in gen], axis=0)\n        dmin = min(dmin, float(d.min()))\n        for i in np.flatnonzero(d < c.KEEPOUT_DIST):\n            k = pt.keys[js[i]]", "d = np.max([cu.gap_to_box(g) for g in gen], axis=0)\n        dmin = min(dmin, float(d.min()))\n        for i in np.flatnonzero(d < c.KEEPOUT_DIST):\n            k = pt.keys[js[i]]"),
    ('keepout_ring: the track radius is not subtracted', "cu = geom.track_copper(b, rows)", "cu = geom.join(geom.track_copper(b, rows))\n        cu.r[:] = 0.0"),
    ('keepout_ring: the distance is not enforced for pads', "        for i in np.flatnonzero(d < c.KEEPOUT_DIST):\n            k = pt.keys[js[i]]", "        for i in np.flatnonzero(d < 0):\n            k = pt.keys[js[i]]"),
]
DECOUP = [
    ('decoupling: limit > becomes >=', "if d > c.DECOUPLING_MAX:", "if d >= c.DECOUPLING_MAX:"),
    ('decoupling: always pad 1', "ks = [k for k in ('1', '2') if pad_net(b, cap, k) == net] or ['1']", "ks = ['1']"),
    ('decoupling: the farther pad on the net counts', "return min(float(np.hypot(*(pad_c(b, cap, k) - pad_c(b, ic, pin)))) for k in ks)", "return max(float(np.hypot(*(pad_c(b, cap, k) - pad_c(b, ic, pin)))) for k in ks)"),
    ('decoupling: capacitors judged one short', "    for cap, ic, pin in c.DECOUPLING:\n        d = decoup_dist", "    for cap, ic, pin in list(c.DECOUPLING)[:1]:\n        d = decoup_dist"),
]
GUARD_RULES = [
    ('guard: effective_config does not list the unrecognised', "if unknown:\n        text +=", "if False:\n        text +="),
]
RUNS = [('geom.py', GEOM, ['test_geom.py']), ('geom.py', COPPER, ['test_copper.py']), ('board.py', BOARD, ['test_board.py']),
        ('board.py', SILK, ['test_board_silk.py']), ('board.py', REQUIRE, ['test_require.py']),
        ('rules.py', GROUND_PLANE, ['test_ground_plane.py']), ('rules.py', BOTTOM_HOPS, ['test_bottom_hops.py']),
        ('config.py', CONFIG, ['test_ground_plane.py', 'test_bottom_hops.py']),
        ('config.py', GUARD, ['test_config_guard.py']), ('rules.py', GUARD_RULES, ['test_config_guard.py']),
        ('rules.py', SENSITIVE, ['test_sensitive_nets.py']), ('rules.py', POUR, ['test_pour_gap.py']), ('rules.py', KEEPOUT, ['test_keepout_ring.py']),
        ('rules.py', DECOUP, ['test_decoupling.py'])]


def _limit():
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (2 << 30, 2 << 30))


def run(tag, mod, edit, tests):
    d = os.path.join(SCR, tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    shutil.copytree(os.path.join(ROOT, 'pcbkit'), os.path.join(d, 'pcbkit'), ignore=shutil.ignore_patterns('.scratch', '__pycache__'))
    g = os.path.join(d, 'pcbkit', mod)
    s = open(g).read()
    if edit:
        old, new = edit
        if s.count(old) != 1:
            return 'BAD-MUTANT (pattern found %d times)' % s.count(old)
        open(g, 'w').write(s.replace(old, new))
    p = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-x', '-p', 'no:cacheprovider', '-c', os.path.join(HERE, 'pytest.ini')]
                       + [os.path.join(HERE, t) for t in tests], capture_output=True, text=True, cwd=ROOT, timeout=300,
                       preexec_fn=_limit, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PCBKIT_ROOT=d))
    tail = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr[-200:]
    return ('PASSED' if p.returncode == 0 else 'FAILED') + ' | ' + tail


def main():
    bad = []
    for k, (mod, muts, tests) in enumerate(RUNS):
        r = run('clean%d' % k, mod, None, tests)
        print('unmutated copy (%s):' % ' '.join(tests), r)
        if not r.startswith('PASSED'):
            return 2
        for i, (name, old, new) in enumerate(muts):
            r = run(f'm{k}_{i}', mod, (old, new), tests)
            ok = r.startswith('FAILED')
            print(('caught   ' if ok else 'SURVIVED ') + name + '  [' + r + ']')
            if not ok:
                bad.append(name)
    print('every mutant caught' if not bad else 'SURVIVORS: ' + '; '.join(bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
