"""Which board a set of renders was made from, by content. Replaces file modification times, which a checkout does not keep.

    python3 -m pcbtools.gate3.rendersum BOARD.kicad_pcb RENDER_DIR      # write RENDER_DIR/renders.sha256.json (render.sh runs this last)

The manifest holds the sha256 of the board the renders were made from, the sha256 of every PNG in the folder, and the 3D models of the board as pcbkit.render sees them
from the board's own directory ({checked, missing, unresolved}): a render set made with a model file missing says so, and tests/pcbtools/test_gate3_render_models.py
fails on it. A render is CURRENT
when the manifest names this board's hash and the PNG on disk still has the hash the manifest recorded for it; it is STALE when the
board changed since (board hash differs), when the PNG was replaced or altered (PNG hash differs), or when no manifest lists it.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

MANIFEST = 'renders.sha256.json'


def sha256_file(path):
    with open(path, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def models(board):
    """{checked, missing, unresolved} of the board's 3D models from its own directory (pcbkit.render.check_models; needs pcbnew, KICAD10_3DMODEL_DIR set as render.sh does)"""
    import pcbtools                                    # noqa: F401  (importing the package registers pcbkit)
    from pcbkit import render
    n, missing, unresolved = render.check_models(board)
    return dict(checked=n, missing=[list(m) for m in missing], unresolved=[list(m) for m in unresolved])


def write(board, folder):
    files = {n: sha256_file(os.path.join(folder, n)) for n in sorted(os.listdir(folder)) if n.endswith('.png')}
    m = models(board)                                  # before the file is opened: a failure here must not leave an empty manifest
    with open(os.path.join(folder, MANIFEST), 'w') as fh:
        json.dump(dict(board_sha256=sha256_file(board), models=m, files=files), fh, indent=1)
        fh.write('\n')
    return files


def status(board, folder, name):
    """(current, why): why is '' for a current render, otherwise what differs"""
    p = os.path.join(folder, name)
    mp = os.path.join(folder, MANIFEST)
    if not os.path.exists(p):
        return False, 'missing'
    if not os.path.exists(mp):
        return False, 'no manifest'
    with open(mp) as fh:
        m = json.load(fh)
    if name not in m.get('files', {}):
        return False, 'not in the manifest'
    if m['files'][name] != sha256_file(p):
        return False, 'image differs from the one recorded'
    if m.get('board_sha256') != sha256_file(board):
        return False, 'made from another board file'
    return True, ''


if __name__ == '__main__':
    files = write(sys.argv[1], sys.argv[2])
    print('wrote', os.path.join(sys.argv[2], MANIFEST), len(files), 'images')
