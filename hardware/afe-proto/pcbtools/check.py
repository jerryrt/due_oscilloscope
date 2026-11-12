"""Command line of the layout rules.

    python -m pcbtools.check BOARD.kicad_pcb|CACHE.npz --config v2 [--rows LR-1 LR-5 ...] [--drc]
    python -m pcbtools.check BOARD_OR_NPZ --config v2 --mutate [--drc]

Prints the lines the old lr_check.py printed ('[PASS] LR-1: ...', 'ALL PASS' / 'FAIL: ...'; with --mutate
'[FAILED AS REQUIRED] ...' per arm and 'every arm caught' / 'NOT CAUGHT: ...'). A .kicad_pcb is read once (pcbnew, in a
short child process retried on a start-up segfault, every retry printed); an .npz is a cache written by
`python -m pcbtools.boardio`. LR-10 (kicad-cli DRC) runs only with --drc and only from a .kicad_pcb; otherwise its row is
printed as [SKIP]. Exit 0 only if every row that ran passed (every arm was caught), 1 otherwise, 2 on bad input.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
import tempfile
import time

from . import boardio, drc, rules


def load(path):
    if str(path).endswith('.npz'):
        return boardio.load_npz(path)
    return boardio.read_board_retry(path)


def run_rows(b, cfg, rows=None, want_drc=False, out=print):
    fails = []
    todo = [(n, f) for n, f in rules.ROWS if not rows or n in rows]
    for name, fn in todo:
        r = fn(b, cfg)
        out(f'[{"PASS" if r.ok else "FAIL"}] {name}: {r.detail}')
        if not r.ok:
            fails.append(name)
    if not rows or 'LR-10' in rows:
        if want_drc and b.path.endswith('.kicad_pcb') and os.path.exists(b.path):
            r = drc.lr10(b, cfg)
            out(f'[{"PASS" if r.ok else "FAIL"}] LR-10: {r.detail}')
            if not r.ok:
                fails.append('LR-10')
        else:
            out('[SKIP] LR-10: DRC not run (needs --drc and a .kicad_pcb that exists)')
    out('ALL PASS' if not fails else 'FAIL: ' + ', '.join(fails))
    return fails


def run_arms(b, cfg, arms, want_drc=False, out=print):
    miss = []
    for name, fn, arm in arms:
        ok0 = fn(b, cfg).ok
        r = fn(arm(b, cfg), cfg)
        out(f'[{"NOT CAUGHT" if r.ok else "FAILED AS REQUIRED"}] {name} (clean board: {"pass" if ok0 else "fail"}): {r.detail}')
        if r.ok:
            miss.append(name)
    if want_drc and b.path.endswith('.kicad_pcb') and os.path.exists(b.path):
        with tempfile.TemporaryDirectory(prefix='pcbtools-arm-') as d:
            r = drc.lr10_path(drc.lr10_arm(b, d))
        out(f'[{"NOT CAUGHT" if r.ok else "FAILED AS REQUIRED"}] LR-10 (a 0.1 mm track added): {r.detail}')
        if r.ok:
            miss.append('LR-10')
    out('every arm caught' if not miss else 'NOT CAUGHT: ' + ', '.join(miss))
    return miss


def main(argv=None):
    ap = argparse.ArgumentParser(prog='pcbtools.check', description=__doc__.split('\n\n')[0])
    ap.add_argument('board')
    ap.add_argument('--config', default='v2')
    ap.add_argument('--mutate', action='store_true')
    ap.add_argument('--rows', nargs='*')
    ap.add_argument('--drc', action='store_true', help='also run LR-10 (kicad-cli) / its arm')
    ap.add_argument('--timing', action='store_true', help='print read / rules / DRC-child seconds and read attempts to stderr')
    a = ap.parse_args(argv)
    if not os.path.exists(a.board):
        print(f'no such board: {a.board}')
        return 2
    try:
        cfg = importlib.import_module(f'pcbtools.boards.{a.config}')
        arms = importlib.import_module(f'pcbtools.boards.{a.config}_arms').ARMS if a.mutate else None
    except ImportError as e:
        print(f'unknown config {a.config!r}: {e}')
        return 2
    t0 = time.perf_counter()
    b = load(a.board)
    t1 = time.perf_counter()
    if a.mutate:
        rc = 1 if run_arms(b, cfg, [x for x in arms if not a.rows or x[1].__name__ in a.rows or x[0].split()[0] in a.rows], a.drc) else 0
    else:
        rc = 1 if run_rows(b, cfg, a.rows, a.drc) else 0
    if a.timing:
        t2 = time.perf_counter()
        print(f'# timing read_s={t1 - t0:.3f} rules_s={t2 - t1:.3f} drc_child_s={drc.drc_time():.3f} read_attempts={boardio.LAST_ATTEMPTS["n"]}',
              file=sys.stderr)
    return rc


if __name__ == '__main__':
    sys.exit(main())
