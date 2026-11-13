"""build.py: generate an unrouted board from a part list, a schematic and a placement: outline, every footprint placed with
its nets, the links to the schematic. Nothing here names a board.

    nets = schematic_nets(schematic_path)                       # (ref, pin) -> net name, from KiCad's own netlist export
    build_board(parts, cfg, place, nets, out_path)

parts  [dict]   ref, fp ('lib:name'), value, lcsc, mpn, fitted_by, note, dnp
place  {ref: (x, y, rot[, locked])}   Due mm, degrees; every part must be in it (a missing one raises)
cfg    object   PROJECT, NS, OUTLINE (x0, y0, x1, y1), KEEPOUTS [(name, (x0, y0, x1, y1))] rule areas (optional), REFERENCE_OUTLINE [(x, y)...] (drawn on User.1, optional), TITLE, REV,
                COMMENTS [str], FOOTPRINT_DIR (KiCad's .pretty libraries), PROJECT_LIB_DIR (the 'afe' library),
                MODEL_OVERRIDE {fpid: (file, sha256)} and MODELS_DIR (optional)

The old packer is gone (every part is placed by the layout). The old courtyard "legaliser" is kept as `legalise()`, a pure
function on arrays that reproduces its result move for move; build_board(..., legalise_overlaps=True) applies it, and any
overlap it cannot clear is returned in the report.
"""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile

import numpy as np

from . import boardio
from .schematic import make_uid
from .sexpr import find, first, parse


def nets_from_netlist(text):
    """(ref, pin) -> net name from a KiCad s-expression netlist (names as KiCad gives them: '/GND', 'unconnected-(...)')"""
    n = parse(text)
    res = {}
    for e in find(first(n, 'nets'), 'net'):
        name = first(e, 'name')[1]
        for x in find(e, 'node'):
            res[(first(x, 'ref')[1], first(x, 'pin')[1])] = name
    return res


def schematic_nets(sch_path):
    """run kicad-cli on the schematic and read the netlist back (the board follows the schematic exactly as 'Update PCB
    from schematic' would)"""
    tmp = tempfile.mkdtemp(prefix='pcbtools-net-')
    try:
        out = os.path.join(tmp, 'net.net')
        subprocess.run(['kicad-cli', 'sch', 'export', 'netlist', '--format', 'kicadsexpr', '-o', out, str(sch_path)],
                       check=True, capture_output=True)
        with open(out) as f:
            return nets_from_netlist(f.read())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def renumber_uuids(text, ns):
    """pcbnew gives every item but the footprints a random uuid: renumber them in file order so two builds of one tree are
    byte-identical (the footprint uuids, set explicitly, already fix the order)"""
    k = iter(range(10 ** 7))
    return re.sub(r'\(uuid "[0-9a-f-]{36}"\)', lambda m: f'(uuid "{make_uid(ns, "pcb", next(k))}")', text)


def overlaps(box_ref, boxes, clear=0.0):
    """pairs of courtyard boxes that overlap: boxes (N,4) = x0, y0, x1, y1; returns an (M,2) int array of index pairs i < j.
    Vectorised: one (N,N) comparison, chunked by rows so memory stays bounded."""
    b = np.asarray(boxes, np.float64)
    out = []
    step = 512
    for s in range(0, len(b), step):
        a = b[s:s + step, None, :]
        hit = (a[..., 0] < b[None, :, 2] - clear) & (b[None, :, 0] < a[..., 2] - clear) & \
              (a[..., 1] < b[None, :, 3] - clear) & (b[None, :, 1] < a[..., 3] - clear)
        i, j = np.nonzero(hit)
        i = i + s
        keep = i < j
        out.append(np.stack([i[keep], j[keep]], axis=1))
    return np.concatenate(out) if out else np.zeros((0, 2), np.int64)


def legalise(pos, rel, anchors, rank, clear=0.0, rounds=200, snap=0.05):
    """Push overlapping courtyards apart, keeping the arrangement: anchors (connectors, holes, ICs) stay; of two
    overlapping parts the later one in `rank` moves, the shortest way out (plus `clear`), to the `snap` grid.
    pos (N,2) part origins, rel (N,4) courtyard box minus origin (x0, y0, x1, y1), anchors (N,) bool, rank (N,) int.
    Returns (pos', leftover pairs (M,2)). The scan order is the old one (pairs i < j in index order, each judged on the
    boxes as they are after the earlier moves of the same round); the overlap test of one part against all later ones is a
    vector operation, so a round costs N numpy calls instead of N*N Python iterations."""
    pos = np.array(pos, np.float64)
    rel = np.asarray(rel, np.float64)
    anchors = np.asarray(anchors, bool)
    rank = np.asarray(rank)
    n = len(pos)

    def box(i):
        return pos[i, 0] + rel[i, 0], pos[i, 1] + rel[i, 1], pos[i, 0] + rel[i, 2], pos[i, 1] + rel[i, 3]

    def hits(i, start):
        """indices j >= start overlapping part i on the current boxes (clearance included), anchors pairs excluded"""
        if start >= n:
            return np.zeros(0, np.int64)
        a = box(i)
        bx0, by0 = pos[start:, 0] + rel[start:, 0], pos[start:, 1] + rel[start:, 1]
        bx1, by1 = pos[start:, 0] + rel[start:, 2], pos[start:, 1] + rel[start:, 3]
        h = (a[0] < bx1 + clear) & (bx0 < a[2] + clear) & (a[1] < by1 + clear) & (by0 < a[3] + clear)
        if anchors[i]:
            h &= ~anchors[start:]
        return np.nonzero(h)[0] + start

    for _ in range(rounds):
        moved = False
        for i in range(n):
            j = i + 1
            while True:
                h = hits(i, j)
                if not len(h):
                    break
                c = int(h[0])
                a, m_is_c = i, None
                if anchors[a] or (not anchors[c] and rank[c] >= rank[a]):
                    m, o = c, a
                else:
                    m, o = a, c
                M, O = box(m), box(o)
                px = min(M[2], O[2]) - max(M[0], O[0]) + clear
                py = min(M[3], O[3]) - max(M[1], O[1]) + clear
                cmx, cox = (M[0] + M[2]) / 2, (O[0] + O[2]) / 2
                cmy, coy = (M[1] + M[3]) / 2, (O[1] + O[3]) / 2
                if px <= py:
                    dx, dy = (px if cmx >= cox else -px), 0.0
                else:
                    dx, dy = 0.0, (py if cmy >= coy else -py)
                if dx:
                    dx += np.copysign(snap, dx)
                if dy:
                    dy += np.copysign(snap, dy)
                pos[m, 0] = round((pos[m, 0] + dx) / snap) * snap
                pos[m, 1] = round((pos[m, 1] + dy) / snap) * snap
                moved = True
                j = c + 1
        if not moved:
            return pos, np.zeros((0, 2), np.int64)
    boxes = np.stack([pos[:, 0] + rel[:, 0], pos[:, 1] + rel[:, 1], pos[:, 0] + rel[:, 2], pos[:, 1] + rel[:, 3]], axis=1)
    pairs = overlaps(None, boxes)
    keep = ~(anchors[pairs[:, 0]] & anchors[pairs[:, 1]]) if len(pairs) else np.zeros(0, bool)
    return pos, pairs[keep]


def _load_footprint(pcb, cfg, fpid):
    lib, name = fpid.split(':')
    d = cfg.PROJECT_LIB_DIR if lib == 'afe' else os.path.join(cfg.FOOTPRINT_DIR, lib + '.pretty')
    f = pcb.FootprintLoad(str(d), name)
    if f is None:
        raise KeyError(fpid)
    return f


def build_board(parts, cfg, place, nets, out_path, legalise_overlaps=False, anchors=()):
    import pcbnew as pcb
    missing = [p['ref'] for p in parts if p['ref'] not in place]
    if missing:
        raise KeyError(f'not placed: {missing}')

    def at(x, y):
        kx, ky = boardio.from_due(x, y)
        return pcb.VECTOR2I(pcb.FromMM(float(kx)), pcb.FromMM(float(ky)))
    uid = lambda *k: make_uid(cfg.NS, *k)      # noqa: E731
    import uuid
    root = str(uuid.uuid5(uuid.UUID(cfg.NS), 'root'))

    board = pcb.BOARD()
    board.SetCopperLayerCount(2)
    tb = board.GetTitleBlock()
    tb.SetTitle(cfg.TITLE)
    tb.SetRevision(cfg.REV)
    for k, c in enumerate(cfg.COMMENTS):
        tb.SetComment(k, c)

    def poly(points, layer, width, close):
        pts = list(points) + ([points[0]] if close else [])
        for a, b in zip(pts, pts[1:]):
            s = pcb.PCB_SHAPE(board)
            s.SetShape(pcb.SHAPE_T_SEGMENT)
            s.SetStart(at(*a))
            s.SetEnd(at(*b))
            s.SetLayer(layer)
            s.SetWidth(pcb.FromMM(width))
            board.Add(s)
    x0, y0, x1, y1 = cfg.OUTLINE
    poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], pcb.Edge_Cuts, 0.1, True)
    if getattr(cfg, 'REFERENCE_OUTLINE', None):
        poly(cfg.REFERENCE_OUTLINE, pcb.User_1, 0.15, False)
    for kname, (kx0, ky0, kx1, ky1) in getattr(cfg, 'KEEPOUTS', ()):         # rule areas: no tracks, vias or copper pour, on every copper layer
        z = pcb.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetLayerSet(pcb.LSET.AllCuMask())
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(True)
        z.SetDoNotAllowZoneFills(True)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        z.SetZoneName(kname)
        for px, py in ((kx0, ky0), (kx1, ky0), (kx1, ky1), (kx0, ky1)):
            z.AppendCorner(at(px, py), -1)
        board.Add(z)

    net_items = {}

    def net(name):
        if name not in net_items:
            net_items[name] = pcb.NETINFO_ITEM(board, name)
            board.Add(net_items[name])
        return net_items[name]

    models = getattr(cfg, 'MODEL_OVERRIDE', {})
    fps = {}
    for p in parts:
        f = _load_footprint(pcb, cfg, p['fp'])
        f.SetFPID(pcb.LIB_ID(*p['fp'].split(':')))
        if p['fp'] in models:
            name, sha = models[p['fp']]
            got = hashlib.sha256(open(os.path.join(cfg.MODELS_DIR, name), 'rb').read()).hexdigest()
            if got != sha:
                raise ValueError(f'{name}: sha256 {got} != {sha}')
            ms = f.Models()                   # iterating yields copies; index to edit in place
            for i in range(len(ms)):
                ms[i].m_Filename = '${KIPRJMOD}/3d/' + name
        f.SetReference(p['ref'])
        f.SetValue(p['value'])
        path = pcb.KIID_PATH()
        path.push_back(pcb.KIID(root))
        path.push_back(pcb.KIID(uid('sym', p['ref'], 1)))
        f.SetPath(path)
        f.SetSheetname('Root')
        f.SetSheetfile(cfg.PROJECT + '.kicad_sch')
        for k, name in (('lcsc', 'LCSC'), ('mpn', 'MPN'), ('fitted_by', 'Fitted by'), ('note', 'Note')):
            fld = pcb.PCB_FIELD(f, f.GetNextFieldOrdinal(), name)
            fld.SetText(p[k])
            fld.SetVisible(False)
            fld.SetLayer(pcb.F_Fab)
            f.Add(fld)
        f.SetDNP(p['dnp'])
        if p['fitted_by'] != 'JLC':
            f.SetExcludedFromPosFiles(True)       # JLC's placement file carries only what JLC assembles
        if p['fitted_by'] == 'none':
            f.SetExcludedFromBOM(True)
        if p['dnp']:
            f.SetExcludedFromPosFiles(True)
        f.Reference().SetLayer(pcb.F_Fab)         # a dense placement gives silk nothing but outlines
        f.Reference().SetTextSize(pcb.VECTOR2I(pcb.FromMM(0.5), pcb.FromMM(0.5)))
        f.Reference().SetTextThickness(pcb.FromMM(0.08))
        f.Value().SetVisible(False)
        if p['fitted_by'] != 'none':
            f.SetExcludedFromBOM(False)
        for pad in f.Pads():
            n = nets.get((p['ref'], pad.GetNumber()))
            if n:
                pad.SetNet(net(n))
        board.Add(f)
        fps[p['ref']] = f

    for ref, spec in place.items():
        if ref not in fps:
            continue
        x, y, rot = spec[:3]
        f = fps[ref]
        f.SetOrientationDegrees(rot)
        f.SetPosition(at(x, y))
        if len(spec) > 3 and spec[3]:
            f.SetLocked(True)
    leftover = []
    if legalise_overlaps:
        refs = [p['ref'] for p in parts if p['ref'] in place]          # scan in part order, as the old builder did
        order = {r: k for k, r in enumerate(place)}                      # the later in the placement, the later it moves
        anc = set(anchors) | {r for r in refs if r.startswith('U')}
        pos, rel = np.zeros((len(refs), 2)), np.zeros((len(refs), 4))
        for k, r in enumerate(refs):
            f = fps[r]
            f.BuildCourtyardCaches()
            bb = f.GetCourtyard(pcb.F_CrtYd).BBox()
            if bb.GetWidth() == 0:
                bb = f.GetBoundingBox(False)
            (ax, ay), (bx, by) = (boardio.to_due(pcb.ToMM(bb.GetLeft()), pcb.ToMM(bb.GetBottom())),
                                  boardio.to_due(pcb.ToMM(bb.GetRight()), pcb.ToMM(bb.GetTop())))
            px, py = boardio.to_due(pcb.ToMM(f.GetPosition().x), pcb.ToMM(f.GetPosition().y))
            pos[k] = (float(px), float(py))
            rel[k] = (float(ax) - float(px), float(ay) - float(py), float(bx) - float(px), float(by) - float(py))
        new, pairs = legalise(pos, rel, np.array([r in anc for r in refs]), np.array([order[r] for r in refs]))
        for k, r in enumerate(refs):
            if abs(new[k, 0] - pos[k, 0]) > 1e-9 or abs(new[k, 1] - pos[k, 1]) > 1e-9:
                fps[r].SetPosition(at(new[k, 0], new[k, 1]))
        leftover = [(refs[i], refs[j]) for i, j in pairs]
    for ref, f in fps.items():
        f.SetUuidDirect(pcb.KIID(uid('fp', ref)))
    board.Save(str(out_path))
    with open(out_path) as fh:
        text = fh.read()
    with open(out_path, 'w') as fh:
        fh.write(renumber_uuids(text, cfg.NS))
    return dict(footprints=len(fps), nets=len(net_items), overlaps_left=leftover)
