"""CLI of the gate-3 package generator (pcbtools.gate3)."""
import argparse
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python3 -B -m pcbtools.gate3', description=__doc__)
    ap.add_argument('--config', required=True, help='board config (pcbtools/boards/<name>.py), e.g. v2_layout')
    ap.add_argument('--table', required=True, help='gate-3 table (pcbtools/boards/<name>.py), e.g. gate3_v2, or a path to a .py file')
    ap.add_argument('--out', required=True, help='output folder: GATE3.md and data/ are written there')
    ap.add_argument('--stamp', default=os.environ.get('GATE3_STAMP'), help='text of the generated-at time (default: now; env GATE3_STAMP)')
    ap.add_argument('--check-table', action='store_true', help='only check the table (missing and TODO fields) and exit')
    a = ap.parse_args(argv)
    from . import table
    T = table.load_module(a.table)
    problems = table.check_table(T)
    if problems:
        print('gate-3 table %s is not complete:' % a.table, file=sys.stderr)
        for p in problems:
            print('  ' + p, file=sys.stderr)
        return 2
    if a.check_table:
        print('table %s: every required field present, no TODO markers' % a.table)
        return 0
    cfg = table.load_module(a.config)
    problems = table.check_config(cfg, T)
    if problems:
        print('board config %s does not carry what table %s reads:' % (a.config, a.table), file=sys.stderr)
        for p in problems:
            print('  ' + p, file=sys.stderr)
        return 2
    from . import engine
    doc = engine.generate(cfg, T, os.path.abspath(a.out), a.config, stamp=a.stamp)
    print('wrote', os.path.join(a.out, 'GATE3.md'), len(doc), 'bytes')
    return 0


if __name__ == '__main__':
    sys.exit(main())
