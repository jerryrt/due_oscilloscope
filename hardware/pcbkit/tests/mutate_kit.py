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
RUNS = [('geom.py', GEOM, ['test_geom.py']), ('geom.py', COPPER, ['test_copper.py']), ('board.py', BOARD, ['test_board.py']), ('board.py', SILK, ['test_board_silk.py']), ('board.py', REQUIRE, ['test_require.py'])]


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
