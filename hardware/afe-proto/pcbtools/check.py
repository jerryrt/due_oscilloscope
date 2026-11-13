"""Command line of the layout rules.

    python -m pcbtools.check BOARD.kicad_pcb|CACHE.npz --config v2 [--rows LR-1 LR-5 ...] [--drc]
    python -m pcbtools.check BOARD_OR_NPZ --config v2 --mutate [--drc]

Prints the lines the old lr_check.py printed ('[PASS] LR-1: ...', 'ALL PASS' / 'FAIL: ...'; with --mutate
'[FAILED AS REQUIRED] ...' per arm and 'every arm caught' / 'NOT CAUGHT: ...'). A .kicad_pcb is read once (pcbnew, in a
short child process retried on a start-up segfault, every retry printed); an .npz is a cache written by
`python -m pcbtools.boardio`. LR-10 (kicad-cli DRC) runs only with --drc and only from a .kicad_pcb; otherwise its row is
printed as [NOT RUN] and the run is not a pass ('LR-10 NOT RUN', exit 1) unless --no-drc says the skip is wanted. Exit 0 only if every row that ran passed (every arm was caught, and every arm was testable) and LR-10 either ran or was skipped by --no-drc, 1
otherwise, 2 on bad input.
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


def _drc_possible(b):
    return b.path.endswith('.kicad_pcb') and os.path.exists(b.path)


def run_rows(b, cfg, rows=None, want_drc=False, out=print, no_drc=False):
    """Print every row; returns the failed rows. LR-10 (DRC) is part of 'every row': when it is not run - no --drc, or an .npz
    cache with no board file to run it on - the summary says 'LR-10 NOT RUN' and `run_rows.not_run` is set, so a green line cannot
    be read as the whole check. `no_drc` (the command line's --no-drc) is the explicit request to skip it."""
    fails = []
    todo = [(n, f) for n, f in rules.ROWS if not rows or n in rows]
    for name, fn in todo:
        r = fn(b, cfg)
        out(f'[{"PASS" if r.ok else "FAIL"}] {name}: {r.detail}')
        if not r.ok:
            fails.append(name)
    not_run = False
    if not rows or 'LR-10' in rows:
        if want_drc and not no_drc and _drc_possible(b):
            r = drc.lr10(b, cfg)
            out(f'[{"PASS" if r.ok else "FAIL"}] LR-10: {r.detail}')
            if not r.ok:
                fails.append('LR-10')
        elif no_drc:
            out('[SKIP] LR-10: skipped by request (--no-drc)')
        else:
            out('[NOT RUN] LR-10: DRC not run (needs --drc and a .kicad_pcb that exists)')
            not_run = True
    skipped_by_request = bool(no_drc and (not rows or 'LR-10' in rows))
    if fails:
        out('FAIL: ' + ', '.join(fails) + ('; LR-10 NOT RUN' if not_run else ''))
    elif not_run:
        out('LR-10 NOT RUN')
    else:
        out('ALL PASS (LR-10 skipped by request)' if skipped_by_request else 'ALL PASS')
    run_rows.not_run = not_run
    return fails


run_rows.not_run = False


def run_arms(b, cfg, arms, want_drc=False, out=print, no_drc=False, lr10_arm=True):
    """Run every arm on the board. An arm is evidence only where its rule PASSES on the unmutated board and then FAILS on the
    mutated one (a flip). A rule that already fails on the clean board cannot show it: that arm is reported 'NOT TESTABLE on this
    board', never 'caught'. Returns the list of arms not caught; `run_arms.untestable` is the list of arms that could not test."""
    miss, untestable = [], []
    for name, fn, arm in arms:
        ok0 = fn(b, cfg).ok
        r = fn(arm(b, cfg), cfg)
        if not ok0:
            untestable.append(name)
            out(f'[NOT TESTABLE on this board] {name} (clean board: fail, so a failing mutant proves nothing): {r.detail}')
            continue
        out(f'[{"NOT CAUGHT" if r.ok else "FAILED AS REQUIRED"}] {name} (clean board: pass): {r.detail}')
        if r.ok:
            miss.append(name)
    drc_not_run = False
    if not lr10_arm:
        pass                                                     # --rows left the LR-10 arm out: it was not asked for
    elif want_drc and not no_drc and _drc_possible(b):
        with tempfile.TemporaryDirectory(prefix='pcbtools-arm-') as d:
            r = drc.lr10_path(drc.lr10_arm(b, d, cfg))
        out(f'[{"NOT CAUGHT" if r.ok else "FAILED AS REQUIRED"}] LR-10 (a 0.1 mm track added): {r.detail}')
        if r.ok:
            miss.append('LR-10')
    elif no_drc:
        out('[SKIP] LR-10 arm: skipped by request (--no-drc)')
    else:
        out('[NOT RUN] LR-10 arm: needs --drc and a .kicad_pcb that exists')
        drc_not_run = True
    parts = []
    if miss:
        parts.append('NOT CAUGHT: ' + ', '.join(miss))
    if untestable:
        parts.append('NOT TESTABLE on this board: ' + ', '.join(untestable))
    if drc_not_run:
        parts.append('LR-10 arm NOT RUN')
    out('; '.join(parts) if parts else ('every arm caught (LR-10 arm skipped by request)' if no_drc else 'every arm caught'))
    run_arms.untestable = untestable
    run_arms.not_run = drc_not_run
    return miss


run_arms.untestable = []
run_arms.not_run = False


def main(argv=None):
    ap = argparse.ArgumentParser(prog='pcbtools.check', description=__doc__.split('\n\n')[0])
    ap.add_argument('board')
    ap.add_argument('--config', default='v2')
    ap.add_argument('--mutate', action='store_true')
    ap.add_argument('--rows', nargs='*')
    ap.add_argument('--drc', action='store_true', help='also run LR-10 (kicad-cli) / its arm')
    ap.add_argument('--no-drc', action='store_true', help='skip LR-10 on purpose: the summary then says so and exits 0 on an otherwise clean run; '
                    'without it a run that did not do LR-10 prints "LR-10 NOT RUN" and exits 1')
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
        sel = [x for x in arms if not a.rows or x[1].__name__ in a.rows or x[0].split()[0] in a.rows]
        miss = run_arms(b, cfg, sel, a.drc, no_drc=a.no_drc, lr10_arm=not a.rows or 'LR-10' in a.rows)
        rc = 1 if (miss or run_arms.untestable or run_arms.not_run) else 0
    else:
        rc = 1 if (run_rows(b, cfg, a.rows, a.drc, no_drc=a.no_drc) or run_rows.not_run) else 0
    if a.timing:
        t2 = time.perf_counter()
        print(f'# timing read_s={t1 - t0:.3f} rules_s={t2 - t1:.3f} drc_child_s={drc.drc_time():.3f} read_attempts={boardio.LAST_ATTEMPTS["n"]}',
              file=sys.stderr)
    return rc


if __name__ == '__main__':
    sys.exit(main())
