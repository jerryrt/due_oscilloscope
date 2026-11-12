"""Capture goldens from the OLD reference tools (v2 tree, not modified). One heavy job at a time, each under capped.sh.

    OLD_TOOLS_DIR=<v2/kicad> [CAPPED=<capped.sh>] [PCB_IMAGE_ID=<id>] python tests/golden/capture_old.py   (writes into tests/golden/v2-8a1f7ac/)

Writes tests/golden/<fixture>.<tool>.json and tests/golden/old_tools_bench.json. Retries a start-up segfault up to 3 times.
"""
import glob, json, os, re, subprocess, sys
HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v2-8a1f7ac')
FX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'fixtures', 'v2-8a1f7ac')
# the reference tools (v2-layout-wip 8a1f7ac, v2/kicad) and the memory cap wrapper are outside this repo: say where
V2 = os.environ['OLD_TOOLS_DIR']                       # e.g. <v2 worktree>/hardware/afe-proto/v2/kicad
CAPPED = os.environ.get('CAPPED', '')                  # capped.sh path; empty = run uncapped (the container caps itself)
IMAGE_ID = os.environ.get('PCB_IMAGE_ID')              # null until the pinned container exists
PY = sys.executable
BLOCK = {'v2-power3': 'POWER', 'v2-power': 'POWER', 'v2-refcal': 'REFCAL', 'v2-awg': 'AWG', 'v2-scope2east': 'SCOPE'}


def env():
    import numpy, pcbnew
    return dict(label='working reference, host .venv-pcb' if not IMAGE_ID else 'container', image_id=IMAGE_ID, interpreter=PY, python=sys.version.split()[0], numpy=numpy.__version__, kicad=pcbnew.GetBuildVersion())


def run(cmd, mem='3G', tmo=300):
    """-> (rc, stdout, wall_s, rss_kb, attempts); retries on a signal death (segfault at start-up)"""
    for attempt in range(1, 4):
        p = subprocess.run(([CAPPED, '-m', mem, '-t', str(tmo)] if CAPPED else []) + ['/usr/bin/time', '-v'] + cmd, capture_output=True, text=True)
        err = p.stderr
        if p.returncode in (139, -11, 134, -6) or 'Command terminated by signal' in err:
            continue
        wall = re.search(r'Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (\S+)', err).group(1)
        parts = [float(x) for x in wall.split(':')]
        w = 0.0
        for x in parts:
            w = w * 60 + x
        rss = int(re.search(r'Maximum resident set size \(kbytes\): (\d+)', err).group(1))
        return p.returncode, p.stdout, w, rss, attempt
    return p.returncode, p.stdout, None, None, 3


NUM = re.compile(r'(?:(?P<label>[A-Za-z_][\w.>+/-]*)\s+)?(?P<v>-?\d+(?:\.\d+)?)\s*(?P<u>mm|pF|fF|um)\b')


def figures(detail):
    out = []
    for m in NUM.finditer(detail):
        out.append(dict(label=m.group('label'), value=float(m.group('v')), unit=m.group('u')))
    return out


ROW = re.compile(r'^\[(?P<verdict>[A-Z ]+)\] (?P<name>[^:]+?)(?: \(clean board: (?P<clean>pass|fail)\))?: (?P<detail>.*)$')


def parse_rows(text):
    rows = []
    for ln in text.splitlines():
        m = ROW.match(ln)
        if m:
            d = m.group('detail')
            rows.append(dict(name=m.group('name'), verdict=m.group('verdict'), clean_board=m.group('clean'), detail=d, figures=figures(d)))
    return rows


def save(name, tool, data):
    data['env'] = env()
    with open(os.path.join(HERE, f'{name}.{tool}.json'), 'w') as f:
        json.dump(data, f, indent=1, sort_keys=True)


def main():
    bench = []
    fx = {re.sub(r'-[0-9a-f]{8}$', '', os.path.basename(p)[:-10]): p for p in sorted(glob.glob(os.path.join(FX, '*.kicad_pcb')))}
    full = {k: os.path.basename(p)[:-10] for k, p in fx.items()}
    base = fx['v2-BASE']
    jobs = []
    for k in fx:
        jobs.append((k, 'counts', [PY, '-I', '-B', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'old_counts.py'), fx[k]]))
    for k in fx:
        if k != 'v2-BASE':
            jobs.append((k, 'lr_check', [PY, '-I', '-B', f'{V2}/lr_check.py', fx[k]]))
    jobs.append(('v2-integrated', 'lr_check_mutate', [PY, '-I', '-B', f'{V2}/lr_check.py', '--mutate', fx['v2-integrated']]))
    for k, blk in BLOCK.items():
        jobs.append((k, 'fence_check', [PY, '-I', '-B', f'{V2}/fence_check.py', blk, fx[k], base]))
    jobs.append(('v2-integrated', 'cap', [PY, '-I', '-B', f'{V2}/cap.py', fx['v2-integrated']]))
    for k, tool, cmd in jobs:
        rc, out, wall, rss, att = run(cmd, mem='3G', tmo=600 if tool in ('cap', 'lr_check_mutate') else 300)
        rec = dict(fixture=full[k], tool=tool, cmd=' '.join(cmd[2:]), exit_code=rc, raw=out, wall_s=wall, peak_rss_kb=rss, attempts=att)
        if tool == 'counts':
            try:
                rec['counts'] = json.loads(out.strip().splitlines()[-1])
            except Exception as e:  # recorded, not hidden
                rec['counts_error'] = repr(e)
        elif tool == 'cap':
            rec['rows'] = [dict(line=l, figures=figures(l)) for l in out.splitlines() if l.strip()]
        elif tool == 'fence_check':
            rec['violations'] = [l[5:] for l in out.splitlines() if l.startswith('FAIL ')]
            rec['clean'] = rc == 0
        else:
            rec['rows'] = parse_rows(out)
        save(full[k], tool, rec)
        bench.append(dict(fixture=full[k], tool=tool, wall_s=wall, peak_rss_kb=rss, exit_code=rc, attempts=att))
        print(full[k], tool, rc, wall, rss, att, flush=True)
    with open(os.path.join(HERE, 'old_tools_bench.json'), 'w') as f:
        json.dump(dict(env=env(), rows=bench), f, indent=1)


main()
