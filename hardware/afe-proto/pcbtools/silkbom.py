"""D30 option C: leave the dense blocks' leftover labels off the silk (the part is found through the BOM), by the config's rules.

    python3 -m pcbtools.silkbom BOARD.kicad_pcb --config v2_layout [--write OUT.kicad_pcb]      (in the PCB image)

A part silkread (with the config's SILK_BLOCKS and SILK_NEAR_OK) finds fault with is treated in two steps:
  1. a passive in SILK_NEAR_OK gets its label re-placed inside its own block, nearer its own courtyard than any other (pcbtools.silkplace, margin just
     above zero), where such a place exists;
  2. every part still found fault with has its Reference moved to F.Fab (silkruns.hide) and is reported, for the config's SILK_TO_BOM table.
Text splices only: no part, track or zone moves. Idempotent: a board it has made reports nothing more to do.
"""
import argparse
import importlib
import os
import tempfile

from . import boardio, silkapply, silkplace, silkread, silkruns

MARGIN = 0.01            # mm: "nearer its own courtyard than any other"


def _find(path, cfg, exempt):
    b = boardio.read_board(path)
    f = silkread.findings(b, getattr(cfg, 'BNC_LABELS', None), exempt=exempt, blocks=cfg.SILK_BLOCKS, near_ok=cfg.SILK_NEAR_OK)
    refs = {}
    for x in f:
        refs.setdefault(x.split(':')[0], []).append(x.split(':', 1)[1].strip())
    return b, f, refs


def run(text, cfg):
    """(new text, [refs re-placed], {ref: [findings] it was hidden for})"""
    exempt = dict(getattr(cfg, 'SILK_TO_BOM', {}))
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'b.kicad_pcb')

        def read(t):
            with open(path, 'w') as fh:
                fh.write(t)
            return _find(path, cfg, exempt)
        b, f, refs = read(text)
        replaced = []
        cand = {r for r in refs if r in cfg.SILK_NEAR_OK and not r.startswith('J')}
        if cand:
            vis = {b.fp_ref[int(b.r_fp[k])] for k in range(len(b.r_fp)) if b.r_on_silk[k] and int(b.r_layer[k]) == 0}
            keep = tuple(sorted(vis - cand))
            placed, _ = silkplace.place(b, cfg, MARGIN, keep, silkruns.silk_boxes(text, cfg), silkapply.FALLBACK_GAP_MAX)
            placed = {r: v for r, v in placed.items() if r in cand}
            text, replaced = silkapply.apply_moves(text, b, placed)
            b, f, refs = read(text)
        hid = {r: v for r, v in refs.items() if r not in exempt}
        if hid:
            text = silkruns.hide(text, sorted(hid))
            b, f, refs = read(text)
        return text, sorted(replaced), hid, f


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python3 -m pcbtools.silkbom', description=__doc__.split('\n')[0])
    ap.add_argument('board')
    ap.add_argument('--config', default='v2_layout')
    ap.add_argument('--write')
    a = ap.parse_args(argv)
    cfg = importlib.import_module(f'pcbtools.boards.{a.config}')
    with open(a.board) as fh:
        text = fh.read()
    new, replaced, hid, left = run(text, cfg)
    print('re-placed', len(replaced), replaced)
    print('hidden', len(hid))
    for r in sorted(hid):
        print(' ', r, '|', '; '.join(hid[r])[:160])
    print('findings left', len(left), left[:5])
    if a.write:
        with open(a.write, 'w') as fh:
            fh.write(new)


if __name__ == '__main__':
    main()
