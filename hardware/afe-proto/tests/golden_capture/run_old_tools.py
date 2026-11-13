"""Run the FROZEN old tools (tests/fixtures/v2-8a1f7ac/tools) on the fixture boards and write their raw output.

    python tests/golden_capture/run_old_tools.py [--out DIR | --into-golden] [--only lr_check,fence_check,cap,mutate]

Per board and tool: <fixture>.<tool>.raw.txt (the tool's stdout, byte for byte) and a summary run_old_tools.json (exit code,
wall seconds, peak RSS, attempts). lr_check runs on the six non-BASE boards, `lr_check --mutate` and cap.py on the integrated
board, fence_check on the five block boards against BASE. This is what the container run uses to re-take the goldens of
record: capture_old.py parses the same output into the golden JSON, this script keeps the raw text so a diff is one `diff`.
--into-golden writes tests/golden/v2-8a1f7ac/ (then update the manifest). One job at a time, each under CAPPED when set.
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

BLOCK = {'v2-power3': 'POWER', 'v2-power': 'POWER', 'v2-refcal': 'REFCAL', 'v2-awg': 'AWG', 'v2-scope2east': 'SCOPE'}


def jobs(tools_dir):
    fx = {re.sub(r'-[0-9a-f]{8}$', '', os.path.basename(p)[:-10]): p for p in sorted(glob.glob(os.path.join(C.FX, '*.kicad_pcb')))}
    full = {k: os.path.basename(p)[:-10] for k, p in fx.items()}
    py = [C.PY, '-I', '-B']
    out = []
    for k in fx:
        if k != 'v2-BASE':
            out.append((full[k], 'lr_check', py + [f'{tools_dir}/lr_check.py', fx[k]], 300))
    out.append((full['v2-integrated'], 'lr_check_mutate', py + [f'{tools_dir}/lr_check.py', '--mutate', fx['v2-integrated']], 600))
    for k, blk in BLOCK.items():
        out.append((full[k], 'fence_check', py + [f'{tools_dir}/fence_check.py', blk, fx[k], fx['v2-BASE']], 300))
    out.append((full['v2-integrated'], 'cap', py + [f'{tools_dir}/cap.py', fx['v2-integrated']], 600))
    return out


def main(argv=None):
    out_dir, a = C.parse_out(__doc__, argv, extra=lambda ap: ap.add_argument('--only', default='', help='comma list of tool names'))
    only = {x for x in a.only.split(',') if x}
    tools = os.path.join(C.FROZEN_TOOLS)
    rows = []
    for fixture, tool, cmd, tmo in jobs(tools):
        if only and tool not in only and not (tool == 'lr_check_mutate' and 'mutate' in only):
            continue
        rc, text, wall, rss, att = C.run(cmd, mem='3G', tmo=tmo)
        with open(os.path.join(out_dir, f'{fixture}.{tool}.raw.txt'), 'w') as f:
            f.write(text)
        rows.append(dict(fixture=fixture, tool=tool, exit_code=rc, wall_s=wall, peak_rss_kb=rss, attempts=att))
        print(fixture, tool, rc, wall, rss, att, flush=True)
    with open(os.path.join(out_dir, 'run_old_tools.json'), 'w') as f:
        json.dump(dict(env=C.env_record(), tools_dir='tests/fixtures/v2-8a1f7ac/tools', rows=rows), f, indent=1)
    C.done(a)


if __name__ == '__main__':
    main()
