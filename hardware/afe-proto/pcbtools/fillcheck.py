"""fillcheck.py BOARD [--config NAME]: the stored pour of a board is the pour KiCad fills with the board's own project file beside it.

    python3 -m pcbtools.fillcheck kicad/afe-proto.kicad_pcb --config v1_layout          (PCB image, from hardware/afe-proto)

Refills every zone of a copy of the board (pcbnew loads <board>.kicad_pro from beside it, and the copy keeps the project) and compares, on each copper layer with a filled GND zone, the stored
pour with the refilled one: the outline length of its filled polygons (equal to 1e-6 mm) and the area of the symmetric difference of the two pours at 40 px/mm (0). Exit 0 when both hold on every
layer, 1 with the figures when not, 2 when the project file is missing. A pour stored from a fill made at other rules (a project edge clearance of 0.45 mm against KiCad's default 0.5 mm, say) changes
the next time anyone refills the board in KiCad: that is what it finds."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..', '..', 'pcbkit'), os.path.join(HERE, '..')]
sys.path.append('/usr/lib/python3/dist-packages')
from pcbkit import board as kb, fills
from pcbtools.frame import FRAME

TOL_MM = 1e-6


class ProjectMissing(Exception):
    pass


def _outline(b, layer_code, gnd):
    z = [i for i in range(len(b.z_layer)) if b.z_layer[i] == layer_code and b.z_net[i] == gnd and b.z_filled[i] and not b.z_keepout[i]]
    return float(sum(np.hypot(*(np.roll(b.z_xy[b.z_vert_off[j]:b.z_vert_off[j + 1]], -1, axis=0) - b.z_xy[b.z_vert_off[j]:b.z_vert_off[j + 1]]).T).sum()
                     for k in z for j in range(b.z_ring_off[k], b.z_ring_off[k + 1])))


def compare(path, frame=None, refilled_out=None):
    """[(layer, stored outline mm, refilled outline mm, xor mm2)] for the GND pour of each copper layer that has one. Raises ProjectMissing when <board>.kicad_pro is not beside `path`."""
    from pcbtools.editor import edit
    path = os.path.abspath(str(path))
    pro = os.path.splitext(path)[0] + '.kicad_pro'
    if not os.path.exists(pro):
        raise ProjectMissing(pro)
    d = tempfile.mkdtemp(prefix='fillcheck-')
    try:
        work = os.path.join(d, os.path.basename(path))
        shutil.copyfile(path, work)
        shutil.copyfile(pro, os.path.splitext(work)[0] + '.kicad_pro')
        for name in ('fp-lib-table', 'sym-lib-table'):
            if os.path.exists(os.path.join(os.path.dirname(path), name)):
                shutil.copyfile(os.path.join(os.path.dirname(path), name), os.path.join(d, name))
        if os.path.isdir(os.path.join(os.path.dirname(path), 'lib')):
            os.symlink(os.path.join(os.path.dirname(path), 'lib'), os.path.join(d, 'lib'))
        out = os.path.join(d, 'refilled.kicad_pcb')
        shutil.copyfile(os.path.splitext(work)[0] + '.kicad_pro', os.path.splitext(out)[0] + '.kicad_pro')
        with edit(work, out) as e:
            e.fill_zones()
        a = kb.read_board(path, {'FRAME': frame or FRAME})
        b = kb.read_board(out, {'FRAME': frame or FRAME})
        gnd = [i for i, n in enumerate(a.nets) if n.lstrip('/') == 'GND'][0]
        rows = []
        fr = (float(min(a.z_xy[:, 0])) - 1.0, float(min(a.z_xy[:, 1])) - 1.0, float(max(a.z_xy[:, 0])) + 1.0, float(max(a.z_xy[:, 1])) + 1.0)
        for code, name in ((0, 'F'), (1, 'B')):
            if not any(a.z_layer[i] == code and a.z_net[i] == gnd and a.z_filled[i] and not a.z_keepout[i] for i in range(len(a.z_layer))):
                continue
            ra = fills.net_copper(a, code, gnd, 40.0, with_net_items=False, frame=fr)
            rb = fills.net_copper(b, code, gnd, 40.0, with_net_items=False, frame=fr)
            rows.append((name, _outline(a, code, gnd), _outline(b, code, gnd), float((ra.mask ^ rb.mask).sum()) / 1600.0))
        return rows
    finally:
        shutil.rmtree(d, ignore_errors=True)


def ok(rows):
    return all(abs(s - r) <= TOL_MM and x == 0.0 for _, s, r, x in rows)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        sys.exit(__doc__)
    cfg = argv[argv.index('--config') + 1] if '--config' in argv else None
    board = [a for k, a in enumerate(argv) if not a.startswith('--') and (k == 0 or argv[k - 1] != '--config')][0]
    frame = None
    if cfg:
        import importlib
        frame = getattr(importlib.import_module('pcbtools.boards.' + cfg), 'FRAME', None)
    try:
        rows = compare(board, frame)
    except ProjectMissing as e:
        print('fillcheck: the project file %s is missing: the stored pour cannot be compared with the fill KiCad makes with it' % e)
        return 2
    for name, s, r, x in rows:
        print('%s.Cu stored %.6f mm, refilled %.6f mm (diff %+.6f), xor %.4f mm2 %s' % (name, s, r, r - s, x, 'ok' if abs(s - r) <= TOL_MM and x == 0.0 else 'DIFFERS'))
    print('fillcheck: %s' % ('the stored pour is the fill KiCad makes with the project' if ok(rows) else 'the stored pour is NOT the fill KiCad makes with the project'))
    return 0 if ok(rows) else 1


if __name__ == '__main__':
    sys.exit(main())
