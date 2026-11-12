"""Measure pcbtools: read_board wall time / peak RSS per fixture, and the geom kernels at 10 000 x 10 000 segments.
Each measurement is its own child process (peak RSS is per process), one at a time, under CAPPED when set.

    [PCB_PYTHON=...] [CAPPED=<capped.sh>] [PCB_IMAGE_ID=<id>] python tests/golden/bench_new.py   -> tests/golden/v2-8a1f7ac/new_tools_bench.json
"""
import glob, json, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))                  # hardware/afe-proto
FX = os.path.join(ROOT, 'tests', 'fixtures', 'v2-8a1f7ac')
OUT = os.path.join(HERE, 'v2-8a1f7ac', 'new_tools_bench.json')
CAPPED = os.environ.get('CAPPED', '')
PY = sys.executable

CHILD = r'''
import sys, time, json, resource
sys.path.insert(0, sys.argv[1])
import numpy as np
t0 = time.perf_counter()
what = sys.argv[2]
extra = {}
if what == 'read_board':
    from pcbtools import boardio
    b = boardio.read_board(sys.argv[3])
    extra = dict(segments=len(b.s_idx), pads=len(b.p_fp), footprints=len(b.fp_idx))
else:
    from pcbtools import geom
    rng = np.random.default_rng(1)
    n = 10000
    def mk(n):
        p = rng.uniform(0, [100, 50, 100, 50], (n, 4)); q = p[:, :2] + rng.uniform(-3, 3, (n, 2)); p[:, 2:] = q; return p
    A, B = mk(n), mk(n)
    t0 = time.perf_counter()
    if what == 'min_dist_10k_x_10k':
        r = geom.min_dist(A, B); extra = dict(pairs=n * n, mean_min=float(r.mean()))
    elif what == 'within_10k_x_10k_d0.3':
        i, j = geom.within(A, B, 0.3); extra = dict(pairs_found=int(len(i)))
    elif what == 'seg_seg_dist_3k_x_3k_matrix':
        r = geom.seg_seg_dist(A[:3000], B[:3000]); extra = dict(matrix_mb=r.nbytes / 2**20)
    elif what == 'points_in_polys_20k_pts_in_8.5k_vertex_polygon':
        th = np.linspace(0, 2 * np.pi, 8500, endpoint=False); poly = np.column_stack([50 + 40 * np.cos(th), 25 + 20 * np.sin(th)])
        r = geom.points_in_polys(rng.uniform(0, 100, (20000, 2)), [poly]); extra = dict(inside=int(r.sum()))
    elif what == 'connected_components_100k_items_100k_joins':
        k, lab = geom.connected_components(100000, rng.integers(0, 100000, (100000, 2))); extra = dict(components=k)
wall = time.perf_counter() - t0
print(json.dumps(dict(wall_s=wall, child_peak_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, **extra)))
'''


def env():
    import numpy, scipy, pcbnew
    return dict(label='working reference, host .venv-pcb' if not os.environ.get('PCB_IMAGE_ID') else 'container',
                image_id=os.environ.get('PCB_IMAGE_ID'), interpreter=PY, python=sys.version.split()[0],
                numpy=numpy.__version__, scipy=scipy.__version__, kicad=pcbnew.GetBuildVersion())


def run(*args, tmo=300):
    for attempt in range(1, 4):
        cmd = ([CAPPED, '-m', '3G', '-t', str(tmo)] if CAPPED else []) + ['/usr/bin/time', '-v', PY, '-c', CHILD, ROOT, *args]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode in (139, -11, 134, -6):
            continue
        rss = int(re.search(r'Maximum resident set size \(kbytes\): (\d+)', p.stderr).group(1))
        try:
            d = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:
            d = dict(error=p.stdout[-300:] + p.stderr[-300:])
        return dict(d, peak_rss_mb_time_v=round(rss / 1024, 1), exit_code=p.returncode, attempts=attempt)
    return dict(error='died with a signal 3 times')


def main():
    rows = []
    for f in sorted(glob.glob(os.path.join(FX, '*.kicad_pcb'))):
        n = os.path.basename(f)[:-10]
        for rep in range(3):             # first run discarded by index when the figures are read: keep all three
            rows.append(dict(what='read_board', fixture=n, rep=rep + 1, **run('read_board', f)))
            print(rows[-1], flush=True)
    for w in ('min_dist_10k_x_10k', 'within_10k_x_10k_d0.3', 'seg_seg_dist_3k_x_3k_matrix',
              'points_in_polys_20k_pts_in_8.5k_vertex_polygon', 'connected_components_100k_items_100k_joins'):
        for rep in range(2):
            rows.append(dict(what=w, rep=rep + 1, **run(w)))
            print(rows[-1], flush=True)
    json.dump(dict(env=env(), rows=rows), open(OUT, 'w'), indent=1)


main()
