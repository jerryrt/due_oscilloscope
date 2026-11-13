"""Write the grid-converged capacitance record of a board (pcbtools/cap_converged_v2_integrated.json) from the cap tool's own result.

    python3 -m pcbtools.cap_record BOARD.kicad_pcb OUT.json [--config v2] [--commit SHA] [--image ID] [--runner TEXT]

Runs `pcbtools.cap.report(converge=True)` once, in this process, and writes every converged figure as the tool returned it, with the board's
sha256, the wall time and the peak RSS this process measured, and the commit and image the caller names (the image has no git). No figure is typed
here. Needs the PCB image (pcbnew reads the board)."""
import argparse
import hashlib
import importlib
import json
import resource
import sys
import time

from . import cap, check


def main(argv=None):
    ap = argparse.ArgumentParser(prog='pcbtools.cap_record', description=__doc__.split('\n\n')[0])
    ap.add_argument('board')
    ap.add_argument('out')
    ap.add_argument('--config', default='v2')
    ap.add_argument('--commit', default='unknown')
    ap.add_argument('--image', default='unknown')
    ap.add_argument('--runner', default='docker/pcb/run.sh')
    a = ap.parse_args(argv)
    cfg = importlib.import_module(f'pcbtools.boards.{a.config}')
    t0 = time.time()
    rep = cap.report(check.load(a.board), cfg, converge=True)
    wall = round(time.time() - t0, 2)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    figs = []
    for (name, pour), r in rep.converged.items():
        kind = 'pair' if name in {p[0] for p in cfg.CAP_PAIRS} else 'self'
        figs.append(dict(figure=name, kind=kind, pour=pour, **r))
    doc = dict(
        description='Grid convergence of the v2 integrated board capacitance figures, pcbtools.cap.report(converge=True): cell sizes 0.2, 0.1, 0.05 mm, '
                    'Richardson extrapolation (observed order must be 0.5-2.5 and the sequence monotone, else the finest value with the full spread). '
                    'Pair values are mutual capacitances in pF; self values are capacitances to everything else in pF. '
                    'SELF CAPACITANCE IS NOT VALIDATED AGAINST A FIELD SOLVER.',
        board=a.board, board_sha256=hashlib.sha256(open(a.board, 'rb').read()).hexdigest(), commit=a.commit,
        config=f'pcbtools/boards/{a.config}.py (CAP_PAIRS, CAP_SELF)', tol=1e-6, max_cells=cap.MAX_CELLS, cell_sizes_mm=list(cap.CONVERGE_H),
        env=dict(image=a.image, runner=a.runner, wall_s=wall, peak_rss_kb=peak, run='one process solves every figure'),
        figures=figs)
    json.dump(doc, open(a.out, 'w'), indent=1)
    print(f'wrote {a.out}: {len(figs)} figures, {wall} s, peak {peak} kB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
