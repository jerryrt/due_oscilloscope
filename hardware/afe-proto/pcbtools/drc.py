"""LR-10: kicad-cli DRC at the board's own rules (the project file next to the .kicad_pcb): zero violations and nothing
unconnected. The only rule that needs KiCad, so it is separate from pcbtools.rules, and slow (seconds per board); the
caller wraps the whole process in its memory cap, so the child inherits it. No pcbnew: the arm below edits the file text.

    lr10(b, cfg=None, outdir=None, cli='kicad-cli') -> Result      b is a BoardArrays whose .path is the board file
    drc_time()                                                     seconds the last DRC child took (for the benchmark)
    lr10_arm(b, outdir, cfg) -> path of a work copy (same libraries as lr10's) with a 0.1 mm track added
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections import defaultdict

from . import boardio
from .rules import Result

_LAST = {'s': 0.0}


def drc_time():
    return _LAST['s']


def _work_copy(path, d):
    """kicad-cli writes <board>.kicad_prl and lock files beside the board it opens, so DRC never runs on the caller's file: it runs
    on a copy in the scratch folder d together with what DRC reads from beside the board (the project file, the footprint library
    table and the lib/ folder, linked not copied). Returns the copy's path."""
    src = os.path.abspath(str(path))
    here = os.path.dirname(src)
    stem = os.path.splitext(os.path.basename(src))[0]
    w = os.path.join(d, 'work')
    os.makedirs(w, exist_ok=True)
    dst = os.path.join(w, os.path.basename(src))
    shutil.copyfile(src, dst)
    for name in (stem + '.kicad_pro', 'fp-lib-table', 'sym-lib-table'):
        if os.path.exists(os.path.join(here, name)):
            shutil.copyfile(os.path.join(here, name), os.path.join(w, name))
    if os.path.isdir(os.path.join(here, 'lib')):
        os.symlink(os.path.join(here, 'lib'), os.path.join(w, 'lib'))
    return dst


def lr10_path(path, outdir=None, cli='kicad-cli', timeout=300):
    own = outdir is None
    d = tempfile.mkdtemp(prefix='pcbtools-drc-') if own else outdir
    try:
        out = os.path.join(d, 'drc.json')
        work = _work_copy(path, d)
        t = time.perf_counter()
        p = subprocess.run([cli, 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', out, work], capture_output=True,
                           text=True, timeout=timeout)
        _LAST['s'] = time.perf_counter() - t
        if not os.path.exists(out):
            return Result(False, f'kicad-cli produced no report (rc {p.returncode}): {p.stderr[-200:]}', {})
        with open(out) as f:
            data = json.load(f)
    finally:
        if own:
            shutil.rmtree(d, ignore_errors=True)
    vio = [v for v in data.get('violations', []) if not v.get('excluded')]
    kinds = defaultdict(int)
    for v in vio:
        kinds[v['type']] += 1
    un = len(data.get('unconnected_items', []))
    return Result(not vio and not un, f'DRC {dict(kinds) or "clean"}; unconnected {un}',
                  dict(violations=float(len(vio)), unconnected=float(un), **{k: float(v) for k, v in kinds.items()}))


def lr10(b, cfg=None, outdir=None, cli='kicad-cli'):
    return lr10_path(b.path, outdir, cli)


def lr10_arm(b, outdir, cfg):
    """The arm's board: the original's work copy (`_work_copy`: board, project file, fp-lib-table and lib/, exactly what the base run
    gets) in outdir/arm, with a 0.1 mm top track one mm (KiCad +y) from a pad appended to its text, as the old arm: the pad and
    the net are `cfg.DRC_ARM` (ref, pin, net). The text is edited in the copy, so the arm runs with the same libraries as the base run and gains no
    lib_footprint_issues of its own (it used to be copied alone, without fp-lib-table and lib/). Returns the path of the edited copy."""
    arm_dir = os.path.join(outdir, 'arm')
    os.makedirs(arm_dir, exist_ok=True)
    dst = _work_copy(b.path, arm_dir)
    text = open(dst).read()
    arm = cfg.DRC_ARM
    r = int(b.pad_indices(arm['ref'], arm['pin'])[0])
    x, y = boardio.from_due(b.p_x[r], b.p_y[r])
    seg = (f'\t(segment (start {x:.6f} {y + 1.0:.6f}) (end {x + 3.0:.6f} {y + 1.0:.6f}) (width 0.1) (layer "F.Cu") '
           f'(net "{arm['net']}") (uuid "00000000-0000-4000-8000-000000000101"))\n')
    i = text.rstrip().rfind(')')
    with open(dst, 'w') as f:
        f.write(text[:i] + seg + text[i:])
    return dst
