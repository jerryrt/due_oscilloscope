"""D30 option C: leave the dense blocks' leftover labels off the silk (the part is found through the BOM), by the config's rules.

    python3 -m pcbtools.silkbom BOARD.kicad_pcb --config v2_layout [--write OUT.kicad_pcb]      (in the PCB image)

A part silkread (with the config's SILK_BLOCKS and SILK_NEAR_OK) finds fault with is treated in two steps:
  1. a passive in SILK_NEAR_OK gets its label re-placed inside its own block, nearer its own courtyard than any other (pcbtools.silkplace, margin just
     above zero), where such a place exists;
  2. every part still found fault with, and every part the config's SILK_TO_BOM lists, has its Reference moved to F.Fab (silkruns.hide); the ones found are
     reported, for the SILK_TO_BOM table.
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
        must = set(getattr(cfg, 'SILK_MUST_LABEL', ()))
        if must & set(r for r in must):
            text = silkruns.show(text, sorted(must))                  # these keep a visible label: back on the silk before the placer looks
            b, f, refs = read(text)
        cand = {r for r in refs if r in cfg.SILK_NEAR_OK}
        if cand:
            vis = {b.fp_ref[int(b.r_fp[k])] for k in range(len(b.r_fp)) if b.r_on_silk[k] and int(b.r_layer[k]) == 0}
            keep = tuple(sorted(vis - cand))
            placed, _ = silkplace.place(b, cfg, MARGIN, keep, silkruns.silk_boxes(text, cfg), silkapply.FALLBACK_GAP_MAX)
            placed = {r: v for r, v in placed.items() if r in cand}
            text, replaced = silkapply.apply_moves(text, b, placed)
            b, f, refs = read(text)
        keep_as_is = set(getattr(cfg, 'SILK_KEEP', ()))
        left = sorted(r for r in refs if r in must)
        if left:                                                      # a must-label part with no place that meets the rule: the nearest free place at all inside its block, named
            vis = {b.fp_ref[int(b.r_fp[k])] for k in range(len(b.r_fp)) if b.r_on_silk[k] and int(b.r_layer[k]) == 0}
            placed, _ = silkplace.place(b, cfg, -9.0, tuple(sorted(vis - set(left))), silkruns.silk_boxes(text, cfg), silkapply.FALLBACK_GAP_MAX + 4.0)
            placed = {r: v for r, v in placed.items() if r in left}
            text, ch = silkapply.apply_moves(text, b, placed)
            replaced = sorted(set(replaced) | set(ch))
            b, f, refs = read(text)
        hid = {r: v for r, v in refs.items() if r not in exempt and r not in keep_as_is and r not in must}
        text = silkruns.hide(text, sorted(set(hid) | set(exempt)))          # the listed parts and the ones just found are off the top silk (idempotent)
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
