"""Measure `python -m pcbtools.check` on the integrated board: wall time and peak RSS per run, each its own child process
under CAPPED when set, one at a time, 3 repetitions (the first is recorded, flagged, and excluded from the medians).
Reads the committed tests/golden/v2-8a1f7ac/new_tools_bench.json (or the one already in the output folder) and writes it to the
output folder with this script's rows appended (stage 1's rows are kept; this script's own earlier rows are replaced), and
copies the old tool's figures from old_tools_bench.json next to them. The DRC child's seconds are separate
(`drc_child_s`), and the number of attempts a pcbnew start-up needed is recorded per row.

    [CAPPED=<capped.sh>] [PCB_IMAGE_ID=<id>] python tests/golden_capture/bench_rules.py [--out DIR | --into-golden]
"""
import json, os, re, statistics, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402
ROOT, CAPPED, PY = C.ROOT, C.CAPPED, C.PY
FX = os.path.join(ROOT, 'tests', 'fixtures')
OLD = os.path.join(C.GOLDEN_V2, 'old_tools_bench.json')
NAME = 'v2-integrated-990d4b03'
PCB = os.path.join(FX, 'v2-8a1f7ac', NAME + '.kicad_pcb')
NPZ = os.path.join(FX, 'arrays', NAME + '.npz')
CASES = [('check_npz', [NPZ], 'lr_check'), ('check_mutate_npz', [NPZ, '--mutate'], 'lr_check_mutate'),
         ('check_kicad_pcb', [PCB], 'lr_check'), ('check_kicad_pcb_with_drc', [PCB, '--drc'], None)]


def run(args, tmo=300):
    for attempt in range(1, 4):
        cmd = ([CAPPED, '-m', '3G', '-t', str(tmo)] if CAPPED else []) + ['/usr/bin/time', '-v', PY, '-m', 'pcbtools.check', *args, '--timing']
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        if p.returncode in (139, -11, 134, -6, 137):         # a start-up signal death outside the child retry: run again, count it
            continue
        break
    err = p.stderr
    m = re.search(r'Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (?:(\d+):)?(\d+):([\d.]+)', err)
    wall = (int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + float(m.group(3)))
    rss = int(re.search(r'Maximum resident set size \(kbytes\): (\d+)', err).group(1))
    t = re.search(r'# timing read_s=([\d.]+) rules_s=([\d.]+) drc_child_s=([\d.]+) read_attempts=(\d+)', err)
    return dict(wall_s=wall, peak_rss_kb=rss, exit_code=p.returncode, outer_attempts=attempt, read_s=float(t.group(1)), rules_s=float(t.group(2)),
                drc_child_s=float(t.group(3)), read_attempts=int(t.group(4)), stdout_lines=len(p.stdout.splitlines()))


def main(argv=None):
    out_dir, args = C.parse_out(__doc__, argv)
    OUT = os.path.join(out_dir, 'new_tools_bench.json')
    sys.path.insert(0, ROOT)
    import numpy, scipy, pcbnew
    env = dict(label='working reference, host .venv-pcb' if not C.IMAGE_ID else 'container', image_id=C.IMAGE_ID,
               interpreter=PY, python=sys.version.split()[0], numpy=numpy.__version__, scipy=scipy.__version__, kicad=pcbnew.GetBuildVersion())
    old = {r['tool']: r for r in json.load(open(OLD))['rows'] if r['fixture'] == NAME}
    data = json.load(open(OUT if os.path.exists(OUT) else os.path.join(C.GOLDEN_V2, 'new_tools_bench.json')))
    data['rows'] = [r for r in data['rows'] if not r['what'].startswith('check_')]
    for what, args, oldtool in CASES:
        runs = [run(args) for _ in range(3)]
        for i, r in enumerate(runs, 1):
            row = dict(what=what, fixture=NAME, rep=i, first_run_excluded_from_median=(i == 1), env_label=env['label'], **r)
            data['rows'].append(row)
            print(json.dumps(row), flush=True)
        warm = runs[1:]
        summ = dict(what=what + '_median_of_reps_2_3', fixture=NAME, wall_s=statistics.median(r['wall_s'] for r in warm),
                    peak_rss_kb=max(r['peak_rss_kb'] for r in warm), read_attempts_max=max(r['read_attempts'] for r in runs),
                    any_retry=any(r['read_attempts'] > 1 or r['outer_attempts'] > 1 for r in runs))
        if oldtool:
            summ.update(old_tool=oldtool, old_wall_s=old[oldtool]['wall_s'], old_peak_rss_kb=old[oldtool]['peak_rss_kb'])
        if any(r['drc_child_s'] for r in warm):
            summ['drc_child_s_median'] = statistics.median(r['drc_child_s'] for r in warm)
        data['rows'].append(summ)
        print(json.dumps(summ), flush=True)
    data['check_env'] = env
    json.dump(data, open(OUT, 'w'), indent=1)
    C.done(args)


if __name__ == '__main__':
    main()
