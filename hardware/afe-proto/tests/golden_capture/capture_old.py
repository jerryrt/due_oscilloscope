"""Capture goldens from the OLD reference tools. One heavy job at a time, each under CAPPED when set.

    python tests/golden_capture/capture_old.py [--out DIR | --into-golden]

Default output pcbtools/.scratch/golden_out/; --into-golden writes tests/golden/v2-8a1f7ac/ and prints the manifest reminder.
The tools run are OLD_TOOLS_DIR (when set) or the frozen copy in tests/fixtures/v2-8a1f7ac/tools.
Writes <fixture>.<tool>.json and old_tools_bench.json. Retries a start-up segfault up to 3 times.
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

BLOCK = {'v2-power3': 'POWER', 'v2-power': 'POWER', 'v2-refcal': 'REFCAL', 'v2-awg': 'AWG', 'v2-scope2east': 'SCOPE'}


def env():
    return C.env_record()


run = C.run


# One number or a slash group sharing one unit ('(46/58 mm)' -> 46 and 58), optionally preceded by a label word; plus the
# unitless 'cap>ic.pin value' pairs LR-12 prints. Used only to read the OLD tools' text: the new Result.figures holds floats.
_N = r'-?\d+(?:\.\d+)?'
NUM = re.compile(r'(?:(?P<label>[A-Za-z_][\w.>+/-]*)\s+)?(?P<v>' + _N + r'(?:/' + _N + r')*)\s*(?P<u>mm|pF|fF|um)\b')
PAIR = re.compile(r'(?P<label>[A-Za-z_]\w*>[\w.]+)\s+(?P<v>' + _N + r')(?![\d./]|\s*(?:mm|pF|fF|um)\b)')


def figures(detail):
    out = []
    for m in NUM.finditer(detail):
        for k, v in enumerate(m.group('v').split('/')):
            out.append(dict(label=m.group('label') if k == 0 else None, value=float(v), unit=m.group('u')))
    for m in PAIR.finditer(detail):
        out.append(dict(label=m.group('label'), value=float(m.group('v')), unit=None))
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


def save(out, name, tool, data):
    data['env'] = env()
    with open(os.path.join(out, f'{name}.{tool}.json'), 'w') as f:
        json.dump(data, f, indent=1, sort_keys=True)


def main(argv=None):
    out_dir, args = C.parse_out(__doc__, argv)
    V2, PY = C.old_tools_dir(), C.PY
    bench = []
    fx = {re.sub(r'-[0-9a-f]{8}$', '', os.path.basename(p)[:-10]): p for p in sorted(glob.glob(os.path.join(C.FX, '*.kicad_pcb')))}
    full = {k: os.path.basename(p)[:-10] for k, p in fx.items()}
    base = fx['v2-BASE']
    here = os.path.dirname(os.path.abspath(__file__))
    jobs = []
    for k in fx:
        jobs.append((k, 'counts', [PY, '-I', '-B', os.path.join(here, 'old_counts.py'), fx[k]]))
    for k in fx:
        if k != 'v2-BASE':
            jobs.append((k, 'lr_check', [PY, '-I', '-B', f'{V2}/lr_check.py', fx[k]]))
    jobs.append(('v2-integrated', 'lr_check_mutate', [PY, '-I', '-B', f'{V2}/lr_check.py', '--mutate', fx['v2-integrated']]))
    for k, blk in BLOCK.items():
        jobs.append((k, 'fence_check', [PY, '-I', '-B', f'{V2}/fence_check.py', blk, fx[k], base]))
    jobs.append(('v2-integrated', 'cap', [PY, '-I', '-B', f'{V2}/cap.py', fx['v2-integrated']]))
    for k, tool, cmd in jobs:
        rc, out, wall, rss, att = run(cmd, mem='3G', tmo=600 if tool in ('cap', 'lr_check_mutate') else 300,
                                      env={'OLD_TOOLS_DIR': V2} if tool == 'counts' else None)
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
        save(out_dir, full[k], tool, rec)
        bench.append(dict(fixture=full[k], tool=tool, wall_s=wall, peak_rss_kb=rss, exit_code=rc, attempts=att))
        print(full[k], tool, rc, wall, rss, att, flush=True)
    with open(os.path.join(out_dir, 'old_tools_bench.json'), 'w') as f:
        json.dump(dict(env=env(), rows=bench), f, indent=1)
    C.done(args)


if __name__ == '__main__':
    main()
