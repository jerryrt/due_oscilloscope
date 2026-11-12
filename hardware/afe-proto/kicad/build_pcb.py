"""Generate the AFE shield board: outline, every footprint placed, nets on every pad.  No copper is routed.

    /usr/bin/python3.14 -I hardware/afe-proto/kicad/build_pcb.py

KiCad's pcbnew module is built against the system Python 3.14 (python3.13 crashes loading a board).
Coordinates below are the Due's (docs/due-header-table.md): origin at its lower-left corner, x right,
Yup up, mm.  The board is x 17..117, Yup 0..53.34 (bom.txt BOARD OUTLINE, PROPOSED).

What is placed and how:
  - the seven Due headers on the V03 pad centres (check.py P3 holds them to the table);
  - the M3 standoff hole on the Due hole (96.52, 2.54);
  - three right-angle BNCs on the right overhang, mouths facing +x;
  - every SMT part in its block's zone, packed in rows by courtyard, in design.py order.
Placement is a first, unrouted arrangement for the 3D check and the mechanical fit, not a layout.

Own work, CC BY-SA 4.0.
"""
import hashlib
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pcbnew as pcb   # noqa: E402
import design          # noqa: E402
import build_sch       # noqa: E402  (uuids, so the board links to the schematic)

FPDIR = os.environ.get('KICAD_FOOTPRINT_DIR', '/usr/share/kicad/footprints')
OX, OY = 50.0, 150.0               # where the Due origin sits on the KiCad page
X0, X1, Y0, Y1 = 17.0, 117.0, 0.0, 53.34


def at(x, yup):
    return pcb.VECTOR2I(pcb.FromMM(OX + x), pcb.FromMM(OY - yup))


def due(v):
    return pcb.ToMM(v.x) - OX, OY - pcb.ToMM(v.y)


# header: (pin-1 x, pin-1 Yup, direction of rising pin numbers) from due-header-table.md section 2
HEADERS = {'J4': (27.94, 2.54, '+x'), 'J5': (50.80, 2.54, '+x'), 'J6': (73.66, 2.54, '+x'),
           'J7': (63.50, 50.80, '-x'), 'J8': (68.58, 50.80, '+x'), 'J9': (41.656, 50.80, '-x')}
XIO = (93.98, 50.80)        # pin 1; odd pins at x 93.98, even at 96.52, rows step down 2.54
ROT = {'+x': 90.0, '-x': -90.0}
# Yup of each BNC centre pin, CH1, CH2, AWG: midway between two XIO0 rows of unused pins (AWG: under the last row),
# so each input enters straight through the header; 17.78 mm apart, clear of each other's courtyards
BNCS = {'J1': 41.91, 'J2': 24.13, 'J3': 7.4}    # J3: its legs (5.05 below, 2.6 mm pads) and body clear the bottom edge
BNC_X = 102.0               # centre pin x: the rear courtyard (2.25 mm back) clears XIO0 (x 98.3) and MH1 (x 99.6)
MH = (96.52, 2.54)

# zones per block (x0, x1, yup0, yup1), inside the headers' bodies; the SMT field is x 18..92, Yup 4.6..48.4
# Placement by signal flow (FR-02).  Each group fills its box in rows, in the order given (the signal's order), starting
# from the named corner: rows grow away from that edge and each row runs away from the named side.  Boxes are in Due
# coordinates (x0, x1, yup0, yup1).
def _r(a, b, pre='R'):
    return [f'{pre}{k}' for k in range(a, b + 1)]


PLAN = [
    # 5 V feed and the LM27762 by the 5V pin (x 38.1), bottom up
    ('power', (18.0, 31.4, 4.6, 48.6), 'bl', ['R70', 'C36', 'C37', 'C23', 'U7', 'C31', 'C38', 'C39', 'C40', 'C41',
                                              'C42', 'C43', 'R29', 'R5', 'R6', 'R25', 'R26', 'R27', 'R28', 'R65',
                                              'TP1', 'TP2', 'TP3', 'TP4', 'TP5']),
    # ladder and reference right above A2..A7 (x 50.8..63.5), bottom up
    ('ladder', (40.0, 64.2, 4.6, 13.8), 'bl', ['R43', 'R44', 'R45', 'R46', 'R47', 'R48', 'R49', 'R50', 'U8', 'C24',
                                               'C32', 'C26', 'C27', 'R81']),
    # precision ADC and the AWG-sense divider with its ratio switch
    ('ads', (32.0, 64.2, 14.4, 26.4), 'br', ['U9', 'C25', 'C33', 'R69', 'R7', 'R8', 'U12', 'C30', 'R68', 'R9', 'D7',
                                             'D8', 'TP6']),
    # scope Vmid: CH1's loop on top (next to CH1), the TLV9062 and divider, CH2's loop at the bottom (next to CH2)
    ('vmid', (32.0, 64.2, 27.2, 48.6), 'tr', _r(48, 53, 'C') + ['R73', 'R74', 'R75', 'R76', 'R63', 'C34', 'C16',
                                              'U6', 'C18', 'R20', 'R21', 'C47', 'R38', 'C46', 'C15',
                                              'R77', 'R78', 'R79', 'R80', 'R64', 'C35', 'C17'] + _r(54, 59, 'C')),
    # CH1: input at the top right (BNC at Yup 44.45), output at the bottom left (to A1 down the x 64.4..70 strip)
    ('ch1', (64.6, 91.8, 37.0, 48.8), 'tr', ['R10', 'R11', 'R1', 'C1', 'R14', 'R15', 'R3', 'R18', 'C9', 'C3', 'C4',
                                             'C10', 'R52', 'U10', 'R30', 'U1', 'R36', 'R71', 'C44', 'C13', 'C28',
                                             'R66', 'R55', 'D5']),
    # CH2: input at the bottom right (BNC at Yup 26.67), same order upward
    ('ch2', (64.6, 91.8, 24.8, 36.4), 'br', ['R12', 'R13', 'R2', 'C2', 'R16', 'R17', 'R4', 'R19', 'C11', 'C5', 'C6',
                                             'C12', 'R53', 'U11', 'R31', 'U2', 'R37', 'R72', 'C45', 'C14', 'C29',
                                             'R67', 'R56', 'D6']),

    # AWG: DAC0 (x 83.8) at the bottom, output to J3 (Yup 8.89) on the right
    ('awg', (64.6, 91.8, 4.6, 24.0), 'bl', ['R54', 'R22', 'U4', 'D3', 'C19', 'R32', 'R34', 'R39', 'R40', 'R57',
                                            'R33', 'C7', 'R35', 'R41', 'R42', 'R58', 'U3', 'D9', 'D10', 'D11', 'R51',
                                            'R59', 'R60', 'C21', 'D1', 'R61', 'R62', 'C22', 'D2',
                                            'R23', 'R24', 'C8', 'U5', 'D4', 'C20']),
]
GAP = 1.0
GROUP_GAP = {'ch1': 0.75, 'ch2': 0.75, 'awg': 0.7}     # boxes fixed by the BNCs and the DAC0 pin
# footprint -> (project model, sha256): models the KiCad library lacks (3d/SOURCES.md)
MODEL_OVERRIDE = {
    'Package_QFP:TQFP-32_5x5mm_P0.5mm': ('LQFP-32_5x5mm_P0.5mm.step',
                                         '9f2be83a713ff62d2355f91718245c4e93f9a75ac14a804dc68810514dd9a3a3'),
}


def xio_footprint():
    """PinSocket_2x18 with odd and even pad numbers exchanged: the stock socket puts pin 2 at -2.54 mm, the Due's XIO0
    has it at +2.54 (due-header-table.md 2.3).  The copper pattern is the same; only the numbering moves, so the
    origin goes on the even column.  Written as text into the project library (sexpr.py)."""
    from sexpr import parse, dump, Q, first
    src = os.path.join(FPDIR, 'Connector_PinSocket_2.54mm.pretty', 'PinSocket_2x18_P2.54mm_Vertical.kicad_mod')
    e = parse(open(src).read())
    name = 'PinSocket_2x18_P2.54mm_Vertical_DueXIO'
    e[1] = Q(name)
    for x in e:
        if isinstance(x, list) and x and x[0] == 'pad':
            n = int(x[1]); x[1] = Q(str(n + 1 if n % 2 else n - 1))
        if isinstance(x, list) and x and x[0] == 'descr':
            x[1] = Q('Stacking socket for the Due XIO0 2x18: PinSocket_2x18 with pin 2 at +2.54 mm (odd/even numbers '
                     'exchanged); the silkscreen pin-1 mark sits on pin 2 (cosmetic). Generated by build_pcb.py from '
                     'KiCad PinSocket_2x18_P2.54mm_Vertical')
    lib = os.path.join(HERE, 'lib', 'afe.pretty')
    os.makedirs(lib, exist_ok=True)
    with open(os.path.join(lib, name + '.kicad_mod'), 'w') as f:
        f.write(dump(e) + '\n')


def load(fpid):
    libname, name = fpid.split(':')
    if libname == 'afe':
        return pcb.FootprintLoad(os.path.join(HERE, 'lib', 'afe.pretty'), name)
    f = pcb.FootprintLoad(os.path.join(FPDIR, libname + '.pretty'), name)
    if f is None:
        raise KeyError(fpid)
    return f


def courtyard(f):
    f.BuildCourtyardCaches()
    b = f.GetCourtyard(pcb.F_CrtYd).BBox()
    if b.GetWidth() == 0:
        b = f.GetBoundingBox(False)
    return b


def schematic_nets():
    """(ref, pin) -> net name, from KiCad's own netlist export of the schematic (names as KiCad gives them: '/GND',
    'unconnected-(D1-K-Pad2)'), so the board follows the schematic exactly as 'Update PCB from schematic' would."""
    from sexpr import parse, find, first
    tmp = tempfile.mkdtemp(prefix='afe-pcb-')
    out = os.path.join(tmp, 'net.net')
    subprocess.run(['kicad-cli', 'sch', 'export', 'netlist', '--format', 'kicadsexpr', '-o', out,
                    os.path.join(HERE, 'afe-proto.kicad_sch')], check=True, capture_output=True)
    n = parse(open(out).read())
    res = {}
    for e in find(first(n, 'nets'), 'net'):
        for x in find(e, 'node'):
            res[(first(x, 'ref')[1], first(x, 'pin')[1])] = first(e, 'name')[1]
    shutil.rmtree(tmp, ignore_errors=True)
    return res


def legalise(fps, fixed, order, clear=0.0, rounds=200):
    """Push overlapping courtyards apart, keeping the hand placement's arrangement: connectors, the hole and ICs stay;
    a passive in an overlap moves the shortest way out (plus clear), the later one in the placement order first.
    Everything also stays inside the SMT field."""
    import layout
    anchors = set(fixed) | {r for r in fps if r.startswith('U')}
    rank = {r: k for k, r in enumerate(order)}

    def box(f):
        b = courtyard(f)
        (ax, ay), (bx, by) = due(pcb.VECTOR2I(b.GetLeft(), b.GetBottom())), due(pcb.VECTOR2I(b.GetRight(), b.GetTop()))
        return ax, ay, bx, by

    def move(f, dx, dy):
        x, y = due(f.GetPosition())
        f.SetPosition(at(round((x + dx) / 0.05) * 0.05, round((y + dy) / 0.05) * 0.05))
    refs = [r for r in fps if r in layout.PLACE or r in anchors]
    for _ in range(rounds):
        moved = False
        boxes = {r: box(fps[r]) for r in refs}
        for i, a in enumerate(refs):
            for c in refs[i + 1:]:
                A, B = boxes[a], boxes[c]
                if not (A[0] < B[2] + clear and B[0] < A[2] + clear and A[1] < B[3] + clear and B[1] < A[3] + clear):
                    continue
                if a in anchors and c in anchors:
                    continue
                m = c if (a in anchors or (c not in anchors and rank.get(c, 0) >= rank.get(a, 0))) else a
                o = a if m == c else c
                M, O = boxes[m], boxes[o]
                # push m away from o along the axis of least penetration, in the direction of their centres
                px = min(M[2], O[2]) - max(M[0], O[0]) + clear
                py = min(M[3], O[3]) - max(M[1], O[1]) + clear
                cmx, cox = (M[0] + M[2]) / 2, (O[0] + O[2]) / 2
                cmy, coy = (M[1] + M[3]) / 2, (O[1] + O[3]) / 2
                if px <= py:
                    dx, dy = (px if cmx >= cox else -px), 0.0
                else:
                    dx, dy = 0.0, (py if cmy >= coy else -py)
                move(fps[m], dx + math.copysign(0.05, dx) if dx else 0, dy + math.copysign(0.05, dy) if dy else 0)
                boxes[m] = box(fps[m]); moved = True
        if not moved:
            return
    left = []
    boxes = {r: box(fps[r]) for r in refs}
    for i, a in enumerate(refs):
        for c in refs[i + 1:]:
            A, B = boxes[a], boxes[c]
            if A[0] < B[2] and B[0] < A[2] and A[1] < B[3] and B[1] < A[3] and not (a in anchors and c in anchors):
                left.append((a, c))
    if left:
        raise SystemExit(f'placement does not settle: {left[:10]}')


def build():
    global SCH_NETS
    SCH_NETS = schematic_nets()
    xio_footprint()
    board = pcb.BOARD()
    board.SetCopperLayerCount(2)
    tb = board.GetTitleBlock()
    tb.SetTitle('AFE full range design 01: AFE shield for the Arduino Due, placement')
    tb.SetRevision('FR-01')
    tb.SetComment(0, 'Generated by hardware/afe-proto/kicad/build_pcb.py from design.py; not routed')
    tb.SetComment(1, 'Own work, CC BY-SA 4.0')
    # outline
    for (a, b) in (((X0, Y0), (X1, Y0)), ((X1, Y0), (X1, Y1)), ((X1, Y1), (X0, Y1)), ((X0, Y1), (X0, Y0))):
        s = pcb.PCB_SHAPE(board)
        s.SetShape(pcb.SHAPE_T_SEGMENT); s.SetStart(at(*a)); s.SetEnd(at(*b))
        s.SetLayer(pcb.Edge_Cuts); s.SetWidth(pcb.FromMM(0.1))
        board.Add(s)
    # the Due's outline on User.1, for reference (due-header-table.md section 1)
    due_pts = [(1, 0), (98.06, 0), (99.06, 1), (99.06, 2.54), (101.6, 5.08), (101.6, 37.846), (99.06, 40.386),
               (99.06, 51.816), (97.536, 53.34), (1, 53.34), (0, 52.34), (0, 1), (1, 0)]
    for a, b in zip(due_pts, due_pts[1:]):
        s = pcb.PCB_SHAPE(board)
        s.SetShape(pcb.SHAPE_T_SEGMENT); s.SetStart(at(*a)); s.SetEnd(at(*b))
        s.SetLayer(pcb.User_1); s.SetWidth(pcb.FromMM(0.15))
        board.Add(s)

    nets = {}

    def net(name):
        if name not in nets:
            nets[name] = pcb.NETINFO_ITEM(board, name)
            board.Add(nets[name])
        return nets[name]

    fps = {}
    for p in design.PARTS:
        f = load(p['fp'])
        f.SetFPID(pcb.LIB_ID(*p['fp'].split(':')))
        if p['fp'] in MODEL_OVERRIDE:
            name, sha = MODEL_OVERRIDE[p['fp']]
            got = hashlib.sha256(open(os.path.join(HERE, '3d', name), 'rb').read()).hexdigest()
            if got != sha:
                raise SystemExit(f'3d/{name}: sha256 {got} != {sha} (3d/SOURCES.md)')
            ms = f.Models()                   # iterating yields copies; index to edit in place
            for i in range(len(ms)):
                ms[i].m_Filename = '${KIPRJMOD}/3d/' + name
        f.SetReference(p['ref']); f.SetValue(p['value'])
        path = pcb.KIID_PATH()
        path.push_back(pcb.KIID(build_sch.ROOT_UUID))
        path.push_back(pcb.KIID(build_sch.uid('sym', p['ref'], 1)))
        f.SetPath(path)
        f.SetSheetname('Root'); f.SetSheetfile('afe-proto.kicad_sch')
        for k, name in (('lcsc', 'LCSC'), ('mpn', 'MPN'), ('fitted_by', 'Fitted by'), ('note', 'Note')):
            fld = pcb.PCB_FIELD(f, f.GetNextFieldOrdinal(), name)
            fld.SetText(p[k]); fld.SetVisible(False); fld.SetLayer(pcb.F_Fab)
            f.Add(fld)
        f.SetDNP(p['dnp'])
        if p['fitted_by'] != 'JLC':
            f.SetExcludedFromPosFiles(True)       # JLC's placement file carries only what JLC assembles
        if p['fitted_by'] == 'none':
            f.SetExcludedFromBOM(True)
        if p['dnp']:
            f.SetExcludedFromPosFiles(True)
        # reference on the fabrication layer: a dense placement gives silk nothing but outlines
        f.Reference().SetLayer(pcb.F_Fab)
        f.Reference().SetTextSize(pcb.VECTOR2I(pcb.FromMM(0.5), pcb.FromMM(0.5)))
        f.Reference().SetTextThickness(pcb.FromMM(0.08))
        f.Value().SetVisible(False)
        if p['fitted_by'] != 'none':
            f.SetExcludedFromBOM(False)           # owner-fitted parts are BOM lines too (MH1's library default excludes it)
        for pad in f.Pads():
            n = SCH_NETS.get((p['ref'], pad.GetNumber()))
            if n:
                pad.SetNet(net(n))
        board.Add(f)
        fps[p['ref']] = f

    # fixed parts
    fixed = set(HEADERS) | set(BNCS) | {'J10', 'MH1'}
    for ref, (x, y, d) in HEADERS.items():
        f = fps[ref]; f.SetOrientationDegrees(ROT[d]); f.SetPosition(at(x, y)); f.SetLocked(True)
    f = fps['J10']; f.SetOrientationDegrees(0); f.SetPosition(at(XIO[0] + 2.54, XIO[1])); f.SetLocked(True)
    for ref, y in BNCS.items():
        f = fps[ref]; f.SetOrientationDegrees(-90); f.SetPosition(at(BNC_X, y))
    f = fps['MH1']; f.SetPosition(at(*MH)); f.SetLocked(True)

    # placement by PLAN: each part, in order, takes the first free spot scanning rows from the named corner (0.2 mm
    # steps), its courtyard GAP clear of every courtyard already in the box
    placed = []
    import layout
    for ref, (x, y, rot) in layout.PLACE.items():
        f = fps[ref]
        f.SetOrientationDegrees(rot); f.SetPosition(at(x, y))
        placed.append(ref)
    for name, (x0, x1, y0, y1), corner, refs in PLAN:
        refs = [r for r in refs if r not in layout.PLACE]
        vert, horiz = corner[0], corner[1]
        gap = GROUP_GAP.get(name, GAP)
        rects = []
        for ref in refs:
            f = fps[ref]
            f.SetOrientationDegrees(0); f.SetPosition(at(0, 0))
            b = courtyard(f)
            w, h = pcb.ToMM(b.GetWidth()), pcb.ToMM(b.GetHeight())
            ys = [round(y0 + 0.2 * k, 3) for k in range(int((y1 - y0 - h) / 0.2) + 1)]
            xs = [round(x0 + 0.2 * k, 3) for k in range(int((x1 - x0 - w) / 0.2) + 1)]
            if vert == 't':
                ys.reverse()
            if horiz == 'r':
                xs.reverse()
            spot = None
            for yb in ys:
                for xl in xs:
                    if all(xl + w + gap <= a or xl >= c + gap or yb + h + gap <= bb or yb >= d + gap
                           for (a, bb, c, d) in rects):
                        spot = (xl, yb); break
                if spot:
                    break
            if spot is None:
                raise SystemExit(f'group {name} full at {ref}: enlarge its box')
            xl, yb = spot
            rects.append((xl, yb, xl + w, yb + h))
            cx, cy = due(pcb.VECTOR2I(b.GetLeft(), b.GetTop()))
            # on the router's 0.05 mm grid, so fine-pitch pad centre lines fall on grid lines (route.py)
            f.SetPosition(at(round((xl - cx) / 0.05) * 0.05, round((yb + h - cy) / 0.05) * 0.05))
            placed.append(ref)
    legalise(fps, fixed, list(layout.PLACE))
    missing = [p['ref'] for p in design.PARTS if p['ref'] not in placed and p['ref'] not in fixed]
    if missing:
        raise SystemExit(f'not in PLAN: {missing}')
    for ref, f in fps.items():
        f.SetUuidDirect(pcb.KIID(build_sch.uid('fp', ref)))
    out = os.path.join(HERE, 'afe-proto.kicad_pcb')
    board.Save(out)
    # pcbnew gives every other item (pads, fields, outline, nets) a random uuid: renumber them in file order so two
    # builds of one tree are byte-identical (footprint uuids, set above, already fix the order)
    text = open(out).read()
    k = iter(range(10 ** 6))
    text = re.sub(r'\(uuid "[0-9a-f-]{36}"\)', lambda m: f'(uuid "{build_sch.uid("pcb", next(k))}")', text)
    with open(out, 'w') as fh:
        fh.write(text)
    print(f'{len(fps)} footprints, {len(placed)} packed, {len(nets)} nets -> {out}')


if __name__ == '__main__':
    build()
