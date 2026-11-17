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
    ('read_board ignores the configuration frame', "    frame = frame_of(cfg)\n    import gc", "    frame = DEFAULT_FRAME\n    import gc"),
    ('a configuration without FRAME falls back to the default', "raise ValueError('the configuration has no FRAME", "return DEFAULT_FRAME; raise ValueError('the configuration has no FRAME"),
    ('retry child does not pass the frame', "repr(ox), repr(oy)]", "'0.0', '0.0']"),
]
RUNS = [('geom.py', GEOM, ['test_geom.py']), ('geom.py', COPPER, ['test_copper.py']), ('board.py', BOARD, ['test_board.py'])]


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
