"""Measure pcbtools.cap against the frozen old cap.py on the integrated board: wall time and peak RSS per run, each its own
child process under CAPPED when set, one at a time, 3 repetitions (the first is recorded, flagged, and excluded from the median).

    [CAPPED=<capped.sh>] [PCB_IMAGE_ID=<id>] python tests/golden_capture/bench_cap.py [--out DIR | --into-golden]

Reads the committed tests/golden/v2-8a1f7ac/new_tools_bench.json (or the one already in the output folder) and writes it to the
output folder with this script's rows (`cap_*`) appended; its own earlier rows are replaced, everything else is kept.
Cases: the old tool (frozen, reads the .kicad_pcb through pcbnew), the new module from the cached arrays (.npz, no pcbnew) and
from the .kicad_pcb (pcbnew read in a child, then the solve).
"""
import json
import os
import statistics
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

NAME = 'v2-integrated-990d4b03'
PCB = os.path.join(C.FX, NAME + '.kicad_pcb')
NPZ = os.path.join(C.TESTS, 'fixtures', 'arrays', NAME + '.npz')


def cases():
    py = [C.PY, '-I', '-B']
    return [('cap_old_frozen', py + [os.path.join(C.FROZEN_TOOLS, 'cap.py'), PCB], None),
            ('cap_new_npz', [C.PY, '-B', '-m', 'pcbtools.cap', NPZ], C.ROOT),
            ('cap_new_kicad_pcb', [C.PY, '-B', '-m', 'pcbtools.cap', PCB], C.ROOT)]


def main(argv=None):
    out_dir, args = C.parse_out(__doc__, argv)
    out = os.path.join(out_dir, 'new_tools_bench.json')
    base = out if os.path.exists(out) else os.path.join(C.GOLDEN_V2, 'new_tools_bench.json')
    data = json.load(open(base))
    data['rows'] = [r for r in data['rows'] if not r['what'].startswith('cap_')]
    env = C.env_record()
    import scipy
    env['scipy'] = scipy.__version__
    stdout = {}
    for what, cmd, cwd in cases():
        runs = []
        for rep in range(1, 4):
            if cwd:
                os.chdir(cwd)
            rc, text, wall, rss, att = C.run(cmd, mem='3G', tmo=300)
            stdout.setdefault(what, text)
            row = dict(what=what, fixture=NAME, rep=rep, first_run_excluded_from_median=(rep == 1), env_label=env['label'],
                       wall_s=wall, peak_rss_kb=rss, exit_code=rc, outer_attempts=att, stdout_lines=len(text.splitlines()))
            runs.append(row)
            data['rows'].append(row)
            print(json.dumps(row), flush=True)
        warm = runs[1:]
        summ = dict(what=what + '_median_of_reps_2_3', fixture=NAME, wall_s=statistics.median(r['wall_s'] for r in warm),
                    peak_rss_kb=max(r['peak_rss_kb'] for r in warm), any_retry=any(r['outer_attempts'] > 1 for r in runs))
        data['rows'].append(summ)
        print(json.dumps(summ), flush=True)
    # the three printed outputs must agree (the new module's lines are the old tool's lines): recorded with the rows
    data['rows'].append(dict(what='cap_output_check', fixture=NAME, old_equals_new_npz=stdout['cap_old_frozen'] == stdout['cap_new_npz'],
                             old_equals_new_kicad_pcb=stdout['cap_old_frozen'] == stdout['cap_new_kicad_pcb']))
    data['cap_env'] = env
    json.dump(data, open(out, 'w'), indent=1)
    C.done(args)


if __name__ == '__main__':
    main()
