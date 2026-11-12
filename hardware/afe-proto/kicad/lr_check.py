"""The layout rules of docs/afe.md section 11.1 (LR-1 .. LR-11) that a program can decide, checked on the v1 board.

    /usr/bin/python3.14 -I lr_check.py [board.kicad_pcb]            every row; exit 0 only if all pass
    /usr/bin/python3.14 -I lr_check.py --mutate [board.kicad_pcb]   every row's broken-on-purpose arm: each must FAIL

Each rule is a function  lrN(model) -> (reasons, pass_text)  over a Model read from the board; no reasons = pass.
A mutation breaks the Model the way its rule forbids (a bottom track under the scope, a via on an inverting node, a join
between two consumers' copper, a part pushed out of its fence ...).  `--mutate` runs the rule on the clean model and on
the broken copy and demands a NEW reason that contains the arm's keyword: an arm only counts when the rule names the
defect that was put in, not when the board was already failing for another reason (the v1 baseline is not routed, so
most routing rows fail on it legitimately and a bare "the row failed" would certify nothing).  An arm may first run a
`prep` that brings the facet under test to a clean state (silk, test points), so the rule is not already failing it.
`--mutate` also runs REPAIR arms: a repair puts a rule's missing copper in and the named reason must disappear, which
shows the rule can pass.  An arm that does not behave exits 1.

The v1 board is read in Due coordinates (KiCad x = 50 + x, y = 150 - y up).  Blocks come from design.PARTS (power ch1 ch2
awg cal due -> POWER CH1 CH2 AWG REFCAL EDGE), fences from floorplan.FENCES.  Every other table is at the top of this file.

What each row looks at, so a pass is not read as more than it is:
  LR-1   two copper layers; one bottom GND zone, filled, one piece; every non-GND bottom run is a hop of at most
         HOP_MAX (3 mm) and 2 vias, no exception; no non-GND bottom segment lies under an analog part, inside the
         REFCAL / AWG / SCOPE fences, crosses (in plan view) any top segment of a sensitive net, or sits under a
         sensitive pad (those crossings are top bridges); every SMD GND pad has a via of its own within 3 mm.
  LR-2   per channel x falls from BNC through R1, Rnp, U101, Riso to the ADC pad; the ADC-side copper is longer than
         the channel's high-impedance copper; the generator is by the 5 V pad and far from every BNC; the reference
         and ladder are >= 10 mm from the generator; the channels' divider pads are >= 5 mm apart.
  LR-3   no via and at most 14 mm of track on the divider chain nets; no other non-GND top track within 0.6 mm.
  LR-4   inverting nodes (AWG_INV, CH1_N, CH2_N): no via, no bottom copper, at most INV_MAX of track, no top ground
         copper (track or pour) within 0.5 mm; A0 / A1: top only, no via; Riso at the output pin; a 100 nF within
         DECOUP_MAX of each op-amp supply pin.
  LR-5   no sensitive copper within 10 mm of the generator or its flying capacitor.
  LR-6   each rail (+3V3A, VNEG), with every pad of the generator's POWER-block parts cut out, falls into one piece per
         consumer (AWG, SCOPE, REF/ADS), each consumer's own pads being one piece.
  LR-7   DAC0 <= 12 mm; back-termination resistors near J301; the BNC shell pads are on ground.
  LR-8   VREF with the source pads cut out falls into one piece per named branch, each branch one piece.
  LR-9   SDA1 / SCL1 stay out of every analog part's courtyard but their own parts', and out of the SCOPE and AWG fences.
  LR-10  kicad-cli DRC: zero violations and nothing unconnected.
  LR-11  each fence holds exactly its blocks' parts (the six bridges excepted and placed at their floorplan points);
         every designator on silk at 0.8 mm or more; its hundreds digit names the part's block (1 CH1, 2 CH2, 3 AWG,
         4 POWER, 5 REFCAL, 6 edge); every block has a test point; the nine test points exist.
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict

sys.path.append('/usr/lib/python3/dist-packages')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pcbnew as pcb  # noqa: E402
import design  # noqa: E402
import floorplan  # noqa: E402

BOARD = os.path.join(HERE, 'afe-proto.kicad_pcb')

# ------------------------------------------------------------------------------------------------ tables (design values)
ZONE_PAD = 0.3            # mm round each analog courtyard
HOP_MAX = 3.0             # LR-1 (spec lead's ruling): a bottom run is at most this long and 2 vias
KEEPOUT = 10.0            # LR-5
INV_MAX = 5.0             # LR-4 (spec lead): the inverting node is the shortest trace of its stage, mm of track, AWG_INV, CH1_N and CH2_N
DECOUP_MAX = 3.0          # LR-4 (spec lead): each decoupling cap's supply pad to the IC supply pin, mm
POUR_CLR = 0.5            # LR-4: top ground copper kept back from an inverting node
GEN = ('U401', 'C402')    # LM27762 and its flying capacitor
BLOCK_NAME = {'power': 'POWER', 'ch1': 'CH1', 'ch2': 'CH2', 'awg': 'AWG', 'cal': 'REFCAL', 'due': 'EDGE'}
BLOCK_BY_BLOCK = dict(BLOCK_NAME)                       # design.PARTS blocks already carry the bridges' block:
BLOCK_OVERRIDE = {'R515': 'REFCAL', 'R516': 'REFCAL', 'R309': 'AWG', 'R310': 'AWG', 'R109': 'CH1', 'R110': 'CH1'}
BRIDGE_REFS = tuple(BLOCK_OVERRIDE)                     # the six 0603 bridges: they straddle the wall, outside every fence
BRIDGE_TOL = 3.0                                        # mm from the floorplan.BRIDGES point (*(check)*)
FENCE_BLOCKS = {'POWER': {'POWER'}, 'REFCAL': {'REFCAL'}, 'SCOPE': {'CH1', 'CH2'}, 'AWG': {'AWG'}}
ANALOG_BLOCKS = ('CH1', 'CH2', 'AWG', 'REFCAL')
NO_BOTTOM_FENCES = ('REFCAL', 'AWG', 'SCOPE')           # LR-1: the REF/CAL, AWG and channel zones
ANALOG_FENCES = ('SCOPE', 'AWG')                        # LR-9: the digital lines never enter these
BLOCK_HUNDREDS = {'1': 'CH1', '2': 'CH2', '3': 'AWG', '4': 'POWER', '5': 'REFCAL', '6': 'EDGE'}
# nets a bottom hop must never cross under, and that LR-5 keeps from the generator; prefix match on the net name
XSENS = ('/A0', '/A1', '/VREF', '/TAP', '/SNS', '/AWG_BNC', '/AWG_S', '/AWG_I', '/AWG_INV', '/AWG_BIN', '/AREF',
         '/CH1_', '/CH2_')
SENSITIVE = ('/A0', '/A1', '/VREF', '/TAP', '/SNS', '/AWG_BNC', '/CH1_N', '/CH2_N')
INV_NODES = ('/AWG_INV', '/CH1_N', '/CH2_N')
HIZ = ('CH1_N', 'CH1_NP', 'CH1_R1A', 'CH1_R2A', 'CH2_N', 'CH2_NP', 'CH2_R1A', 'CH2_R2A')   # LR-3 divider chain nets
DIGITAL = ('/SDA1', '/SCL1')
RAILS = ('/+3V3A', '/VNEG')                  # LR-6; consumers are the blocks AWG, SCOPE (ch1+ch2) and REFCAL
CONSUMER = {'AWG': 'AWG', 'CH1': 'SCOPE', 'CH2': 'SCOPE', 'REFCAL': 'REF/ADS'}
STAR_REQUIRED = {'/+3V3A': [('U401', '11'), ('C407', '1'), ('C408', '1')],      # OUT+ and its output capacitors
                 '/VNEG': [('U401', '6'), ('C409', '1'), ('C410', '1')]}        # OUT- and its output capacitors
KELVIN = {'/VREF': dict(                                           # LR-8 (floorplan rows 'VREF branch A..D2')
    source=[('U501', '2'), ('C504', '1')],
    branches={'A precision readers': {'J602', 'R508'}, 'B ADS AIN0': {'U502', 'C503'},
              'C AWG offset': {'R307'}, 'D1 CH1 leg + sense tie': {'R104', 'R512'}, 'D2 CH2 leg': {'R515'}})}
SUPPLY_PINS = (('U101', '8'), ('U301', '8'), ('U301', '4'))        # LR-4: op-amp supply pins that need a 100 nF
OUTPUT_RISO = (('R107', 'U101', '/CH1_OUT'), ('R207', 'U101', '/CH2_OUT'))
CHANNELS = ((1, 'J101', 'R102', 'R106', 'R107', '7'), (2, 'J201', 'R202', 'R206', 'R207', '8'))   # n, BNC, R1, Rnp, Riso, J602 pad
WANT_TP = [('/A1', 'CH1'), ('/A0', 'CH2'), ('/AWG_OUT', 'AWG'), ('/+5V_DUE', 'POWER'), ('/+5V_F', 'POWER'),
           ('/+3V3A', 'POWER'), ('/VNEG', 'POWER'), ('/VREF', 'REFCAL'), ('/GND', 'POWER')]
SILK_MIN = 1.0                                                    # mm: the board house minimum text height (docs/jlcpcb.md)
SILK_WORDS = ('CH1', 'CH2', 'AWG', 'POWER', 'REF/CAL', 'ON')       # block names, the BNC labels (CH1, CH2, AWG) and the CAL header's ON position


def mm(v):
    return pcb.ToMM(v)


def due(p):
    return (mm(p.x) - 50.0, 150.0 - mm(p.y))


class Model:
    """everything the rules read, in Due coordinates (y up), plain python so a mutation can edit it"""


def design_block(r):
    if r in BLOCK_OVERRIDE:
        return BLOCK_OVERRIDE[r]
    p = design.PARTS_BY_REF.get(r)
    return BLOCK_NAME[p['block']] if p else None


def load(path):
    b = pcb.LoadBoard(path)
    m = Model()
    m.board, m.path = b, path
    m.fps = {f.GetReference(): f for f in b.GetFootprints()}
    m.block = {r: design_block(r) for r in m.fps}
    m.pos = {r: due(f.GetPosition()) for r, f in m.fps.items()}
    m.box = {}
    for r, f in m.fps.items():
        f.BuildCourtyardCaches()
        c = f.GetCourtyard(pcb.F_CrtYd).BBox()
        if c.GetWidth():
            (x0, y1), (x1, y0) = due(pcb.VECTOR2I(c.GetLeft(), c.GetTop())), due(pcb.VECTOR2I(c.GetRight(), c.GetBottom()))
            m.box[r] = (x0, y0, x1, y1)
    m.segs, m.vias = [], []
    for t in b.GetTracks():
        if t.GetClass() == 'PCB_VIA':
            m.vias.append((str(t.GetNetname()), due(t.GetPosition())))
        else:
            m.segs.append((str(t.GetNetname()), 'F' if t.GetLayer() == pcb.F_Cu else 'B', due(t.GetStart()),
                           due(t.GetEnd()), mm(t.GetWidth())))
    m.pads = {}
    for r, f in m.fps.items():
        for p in f.Pads():
            key = (r, p.GetNumber())
            while key in m.pads:                  # a second pad of one number (BNC shell legs, thermal copies): '2#1'
                key = (r, key[1].split('#')[0] + '#' + str(int(key[1].split('#')[1]) + 1 if '#' in key[1] else 1))
            bb = p.GetBoundingBox()
            (x0, y1), (x1, y0) = due(pcb.VECTOR2I(bb.GetLeft(), bb.GetTop())), due(pcb.VECTOR2I(bb.GetRight(), bb.GetBottom()))
            m.pads[key] = dict(net=str(p.GetNetname()), c=due(p.GetPosition()), box=(x0, y0, x1, y1),
                                              smd=p.GetAttribute() == pcb.PAD_ATTRIB_SMD,
                                              layers=''.join(k for k, ly in (('F', pcb.F_Cu), ('B', pcb.B_Cu)) if p.IsOnLayer(ly)))
    m.zones = []
    for z in b.Zones():
        lay = z.GetLayer()
        m.zones.append(dict(layer='F' if lay == pcb.F_Cu else 'B', net=str(z.GetNetname()), z=z,
                            pieces=z.GetFilledPolysList(lay).OutlineCount() if z.IsFilled() else 0, filled=z.IsFilled()))
    m.layers = b.GetCopperLayerCount()
    m.silk = [(str(t.GetText()), due(t.GetPosition()), mm(t.GetTextHeight())) for t in b.Drawings()
              if t.GetClass() == 'PCB_TEXT' and t.GetLayer() == pcb.F_SilkS]
    m.refs = {r: (due(f.Reference().GetPosition()), mm(f.Reference().GetTextHeight()),
                  f.Reference().GetLayer() == pcb.F_SilkS and f.Reference().IsVisible()) for r, f in m.fps.items()}
    m.value = {r: str(f.GetValue()) for r, f in m.fps.items()}
    m.links = []                         # (net, padkey, padkey): joins a repair arm declares
    m.extra_top_gnd = []                 # a mutation can add top ground copper points here
    return m


_CACHE = {}


def fresh(path):
    """a private copy of the model: the board is read once (every LoadBoard prints wx noise), the plain data is copied"""
    import copy
    if path not in _CACHE:
        _CACHE[path] = load(path)
    base, m = _CACHE[path], Model()
    for k, v in vars(base).items():
        setattr(m, k, v if k in ('board', 'fps', 'zones', 'path') else copy.deepcopy(v))
    return m


# ------------------------------------------------------------------------------------------------ geometry
def seg_len(s):
    return math.dist(s[2], s[3])


def seg_pts(s, step=0.1):
    n = max(1, int(seg_len(s) / step))
    return [(s[2][0] + (s[3][0] - s[2][0]) * k / n, s[2][1] + (s[3][1] - s[2][1]) * k / n) for k in range(n + 1)]


def in_box(pt, box, pad=0.0):
    return box[0] - pad <= pt[0] <= box[2] + pad and box[1] - pad <= pt[1] <= box[3] + pad


def seg_in_box(s, box, pad=0.0):
    return any(in_box(p, box, pad + s[4] / 2) for p in seg_pts(s))


def dist_pt_box(pt, box):
    return math.hypot(max(box[0] - pt[0], 0, pt[0] - box[2]), max(box[1] - pt[1], 0, pt[1] - box[3]))


def dist_box_box(a, b):
    return math.hypot(max(a[0] - b[2], 0, b[0] - a[2]), max(a[1] - b[3], 0, b[1] - a[3]))


def pt_seg(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def _ccw(a, b, c):
    return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])


def seg_seg_dist(s, t):
    """centre-line distance of two segments, 0 when they cross (plan view)"""
    a, b, c, d = s[2], s[3], t[2], t[3]
    if _ccw(a, c, d) * _ccw(b, c, d) < 0 and _ccw(a, b, c) * _ccw(a, b, d) < 0:
        return 0.0
    return min(pt_seg(a, c, d), pt_seg(b, c, d), pt_seg(c, a, b), pt_seg(d, a, b))


def length_of(m, net, layer='F'):
    return sum(seg_len(s) for s in m.segs if s[0] == net and s[1] == layer)


def fences_of(names):
    return [rc for n in names for rc in floorplan.FENCES[n]]


def gnd_top_zone_hit(m, pt):
    return any(z['z'].HitTestFilledArea(pcb.F_Cu, pcb.VECTOR2I(pcb.FromMM(pt[0] + 50.0), pcb.FromMM(150.0 - pt[1])),
                                         pcb.FromMM(0.02)) for z in m.zones if z['layer'] == 'F' and z['net'] == '/GND')


def analog_refs(m):
    return {r for r in m.fps if m.block.get(r) in ANALOG_BLOCKS and not r.startswith(('J', 'TP', 'MH'))}


# ------------------------------------------------------------------------------------------------ LR-1
def bottom_runs(m):
    bs = [s for s in m.segs if s[1] == 'B' and s[0] != '/GND']
    runs, seen = [], [False] * len(bs)
    ar = analog_refs(m)
    for i in range(len(bs)):
        if seen[i]:
            continue
        stack, comp, seen[i] = [i], [], True
        while stack:
            k = stack.pop()
            comp.append(bs[k])
            for j in range(len(bs)):
                if not seen[j] and bs[j][0] == bs[k][0] and any(math.dist(p, q) < 0.01 for p in bs[k][2:4] for q in bs[j][2:4]):
                    seen[j] = True
                    stack.append(j)
        net = comp[0][0]
        ends = [p for s in comp for p in s[2:4]]
        nv = sum(1 for v in m.vias if v[0] == net and any(math.dist(v[1], p) < 0.05 for p in ends))
        under = sorted({r for r in ar if r in m.box and any(seg_in_box(s, m.box[r], ZONE_PAD) for s in comp)})
        runs.append((net, sum(seg_len(s) for s in comp), nv, under))
    return runs


def bottom_crossings(m):
    """no non-GND bottom segment lies in a REFCAL / AWG / SCOPE fence, crosses (plan view) any top segment of a sensitive
    net, or sits under a sensitive pad: those crossings are top bridges, never a hop under"""
    bad = []
    fz = fences_of(NO_BOTTOM_FENCES)
    top = [s for s in m.segs if s[1] == 'F' and s[0].startswith(XSENS)]
    pads = [(k, v) for k, v in m.pads.items() if v['net'].startswith(XSENS)]
    for s in (x for x in m.segs if x[1] == 'B' and x[0] != '/GND'):
        for rc in fz:
            if seg_in_box(s, rc):
                bad.append(f'{s[0]}: bottom segment inside the fence {tuple(round(v, 1) for v in rc)}')
                break
        for t in top:
            if seg_seg_dist(s, t) < (s[4] + t[4]) / 2:
                bad.append(f'{s[0]}: bottom segment crosses {t[0]} on top (bridge it on top)')
                break
        for k, v in pads:
            if seg_in_box(s, v['box'], 0.1):
                bad.append(f'{s[0]}: bottom segment under pad {k[0]}.{k[1]} of {v["net"]}')
                break
    return bad


def lr1(m):
    bad = []
    if m.layers != 2:
        bad.append(f'{m.layers} copper layers')
    bz = [z for z in m.zones if z['layer'] == 'B' and z['net'] == '/GND']
    if not bz:
        bad.append('no bottom GND zone')
    else:
        if not bz[0]['filled']:
            bad.append('bottom zone not filled')
        if bz[0]['pieces'] != 1:
            bad.append(f"bottom plane is {bz[0]['pieces']} pieces, not 1")
    runs = bottom_runs(m)
    for net, L, nv, under in runs:
        if under:
            bad.append(f'{net}: bottom copper under {under}')
        if L > HOP_MAX or nv > 2:
            bad.append(f'{net}: bottom run {L:.1f} mm, {nv} vias (limit {HOP_MAX} mm, 2)')
    bad += bottom_crossings(m)
    gv = [v[1] for v in m.vias if v[0] == '/GND']
    gp = [(k, v) for k, v in m.pads.items() if v['net'] == '/GND' and v['smd'] and '#' not in k[1]]
    used, nov = set(), []
    for k, v in sorted(gp):
        cand = sorted((math.dist(v['c'], g), i) for i, g in enumerate(gv) if i not in used)
        if cand and cand[0][0] <= 3.0:
            used.add(cand[0][1])
        else:
            nov.append(f'{k[0]}.{k[1]}')
    if nov:
        bad.append(f'{len(nov)} SMD ground pads without a via of their own: {nov[:6]}')
    return bad, f'2 layers, one bottom plane, {len(runs)} bottom runs, {len(gp)} GND pads each with its own via'


# ------------------------------------------------------------------------------------------------ LR-2
def lr2(m):
    bad = []
    for ch, bnc, r1, rnp, riso, adc in CHANNELS:
        seq = [m.pads[(bnc, '1')]['c'][0], m.pos[r1][0], m.pos[rnp][0], m.pos['U101'][0], m.pos[riso][0],
               m.pads[('J602', adc)]['c'][0]]
        if not all(a > b for a, b in zip(seq, seq[1:])):
            bad.append(f'CH{ch}: x does not fall BNC > R1 > Rnp > U101 > Riso > ADC pad: {[round(x, 1) for x in seq]}')
        outl = length_of(m, '/A1' if ch == 1 else '/A0') + length_of(m, f'/CH{ch}_OUT')
        hiz = sum(length_of(m, '/' + n) for n in HIZ if n.startswith(f'CH{ch}_'))
        if outl <= hiz:
            bad.append(f'CH{ch}: output run {outl:.1f} mm is not longer than the divider side {hiz:.1f} mm')
    g = m.pos['U401']
    d5 = math.dist(g, m.pads[('J601', '5')]['c'])
    if d5 > 15:
        bad.append(f'generator {d5:.1f} mm from the 5 V pad')
    for j in ('J101', 'J201', 'J301'):
        if math.dist(g, m.pos[j]) < 50:
            bad.append(f'generator {math.dist(g, m.pos[j]):.0f} mm from {j}')
    for r in ('U501', 'U502', 'R503', 'R504', 'R505', 'R506', 'R507', 'R508'):
        d = min(dist_box_box(m.box[r], m.box[x]) for x in GEN)
        if d < KEEPOUT:
            bad.append(f'{r} only {d:.1f} mm from the generator')
    a = [v['c'] for k, v in m.pads.items() if v['net'] in ('/CH1_N', '/CH1_NP', '/CH1_R1A', '/CH1_R2A') and not k[0].startswith('J')]
    b = [v['c'] for k, v in m.pads.items() if v['net'] in ('/CH2_N', '/CH2_NP', '/CH2_R1A', '/CH2_R2A') and not k[0].startswith('J')]
    gap = min(math.dist(p, q) for p in a for q in b)
    if gap < 5.0:
        bad.append(f"channels' divider pads only {gap:.1f} mm apart")
    return bad, f'flow, generator, quiet zone and channel separation hold (closest divider pads {gap:.1f} mm)'


# ------------------------------------------------------------------------------------------------ LR-3
def lr3(m):
    bad = []
    for n in HIZ:
        net = '/' + n
        if any(v[0] == net for v in m.vias):
            bad.append(f'{net}: a via')
        L = length_of(m, net)
        if L > 14:
            bad.append(f'{net}: {L:.1f} mm of track')
    hs = [s for s in m.segs if s[0][1:] in HIZ and s[1] == 'F']
    others = [t for t in m.segs if t[1] == 'F' and t[0] != '/GND' and t[0][1:] not in HIZ]
    others += [t for t in hs]
    for s in hs:
        for t in others:
            if t[0] != s[0] and seg_seg_dist(s, t) < 0.6 + (s[4] + t[4]) / 2:
                bad.append(f'{s[0]} track within 0.6 mm of {t[0]} track')
                break
    return bad, f'{len(HIZ)} divider nets: no via, short, no track beside'


# ------------------------------------------------------------------------------------------------ LR-4
def lr4(m):
    bad = []
    for net in ('/A0', '/A1'):
        if any(v[0] == net for v in m.vias):
            bad.append(f'{net}: a via')
        if any(s[0] == net and s[1] == 'B' for s in m.segs):
            bad.append(f'{net}: bottom copper')
    for riso, op, net in OUTPUT_RISO:
        d = min(math.dist(m.pads[(riso, '1')]['c'], v['c']) for k, v in m.pads.items() if k[0] == op and v['net'] == net)
        if d > 5:
            bad.append(f'{riso} {d:.1f} mm from the output pin')
    for ref, pin in SUPPLY_PINS:
        pc = m.pads[(ref, pin)]
        caps = [(math.dist(v['c'], pc['c']), k[0]) for k, v in m.pads.items()
                if k[0].startswith('C') and v['net'] == pc['net'] and m.value.get(k[0], '').startswith('100n')]
        if not caps or min(caps)[0] > DECOUP_MAX:
            bad.append(f'{ref}.{pin}: no 100 nF within {DECOUP_MAX:.0f} mm ' + (f'(nearest {min(caps)[1]} at {min(caps)[0]:.1f} mm)' if caps else '(none on the net)'))
    for net in INV_NODES:
        if any(v[0] == net for v in m.vias):
            bad.append(f'{net}: inverting node has a via')
        if any(s[0] == net and s[1] == 'B' for s in m.segs):
            bad.append(f'{net}: inverting node has bottom copper')
        L = length_of(m, net)
        if L > INV_MAX:
            bad.append(f'{net}: inverting node {L:.1f} mm of track (limit {INV_MAX})')
        pts = [p for s in m.segs if s[0] == net and s[1] == 'F' for p in seg_pts(s, 0.5)]
        pts += [v['c'] for v in m.pads.values() if v['net'] == net]
        near = set()
        for p in pts:
            if any(math.dist(p, q) < POUR_CLR for q in m.extra_top_gnd):
                near.add('added ground copper')
            for s in m.segs:
                if s[0] == '/GND' and s[1] == 'F' and pt_seg(p, s[2], s[3]) - s[4] / 2 < POUR_CLR:
                    near.add('GND track')
            if any(gnd_top_zone_hit(m, (p[0] + dx, p[1] + dy)) for dx, dy in ((POUR_CLR, 0), (-POUR_CLR, 0), (0, POUR_CLR), (0, -POUR_CLR))):
                near.add('top pour')
        if near:
            bad.append(f'{net}: top ground copper within {POUR_CLR} mm ({sorted(near)})')
    return bad, (f'A0/A1 top only, no via ({length_of(m, "/A0"):.0f}/{length_of(m, "/A1"):.0f} mm); inverting nodes clean '
                 f'(AWG_INV {length_of(m, "/AWG_INV"):.1f} mm); 100 nF at every supply pin')


# ------------------------------------------------------------------------------------------------ LR-5
def lr5(m):
    gen = [m.box[r] for r in GEN]
    near = []
    for s in m.segs:
        if s[1] == 'F' and s[0].startswith(SENSITIVE):
            d = min(min(dist_pt_box(p, g) for p in seg_pts(s, 0.5)) for g in gen)
            if d < KEEPOUT:
                near.append(f'{s[0]} {d:.1f} mm')
    for k, v in m.pads.items():
        if v['net'].startswith(SENSITIVE) and m.block.get(k[0]) != 'POWER':
            d = min(dist_pt_box(v['c'], g) for g in gen)
            if d < KEEPOUT:
                near.append(f'{v["net"]} pad {k[0]}.{k[1]} {d:.1f} mm')
    return sorted(set(near)), f'sensitive copper >= {KEEPOUT} mm from {"/".join(GEN)}'


# ------------------------------------------------------------------------------------------------ pieces of copper
def pieces(m, net, cut=(), with_pads=True):
    """connected pieces of one net's copper (tracks on both layers, vias, pads on their layers), the pads in `cut`
    removed.  Returns a list of sets of pad keys (ref, pad)"""
    nodes = [('s', s) for s in m.segs if s[0] == net]
    nodes += [('v', v) for v in m.vias if v[0] == net]
    nodes += [('p', (k, v)) for k, v in m.pads.items() if v['net'] == net and k not in cut]
    parent = list(range(len(nodes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def touches(a, b):
        ka, kb = a[0], b[0]
        if ka == 'p' and kb == 'p':
            return False
        if ka == 'p':
            return touches(b, a)
        if ka == 's':
            if kb == 's':
                return a[1][1] == b[1][1] and (any(math.dist(p, q) < 0.02 for p in a[1][2:4] for q in b[1][2:4]) or
                                               any(pt_seg(p, b[1][2], b[1][3]) < 0.02 for p in a[1][2:4]) or
                                               any(pt_seg(q, a[1][2], a[1][3]) < 0.02 for q in b[1][2:4]))
            if kb == 'v':
                return pt_seg(b[1][1], a[1][2], a[1][3]) < 0.05
            bx = b[1][1]
            return a[1][1] in bx['layers'] and any(in_box(p, bx['box'], 0.02) for p in seg_pts(a[1], 0.1))
        if ka == 'v':
            if kb == 'v':
                return math.dist(a[1][1], b[1][1]) < 0.05
            return in_box(a[1][1], b[1][1]['box'], 0.02)
        return False
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if touches(nodes[i], nodes[j]):
                parent[find(i)] = find(j)
    for (n, ka, kb) in m.links:                     # abstract joins a repair arm declares (no geometry to route)
        ia = [i for i, nd in enumerate(nodes) if n == net and nd[0] == 'p' and nd[1][0] == ka]
        ib = [i for i, nd in enumerate(nodes) if n == net and nd[0] == 'p' and nd[1][0] == kb]
        if ia and ib:
            parent[find(ia[0])] = find(ib[0])
    groups = defaultdict(set)
    for i, nd in enumerate(nodes):
        if nd[0] == 'p':
            groups[find(i)].add(nd[1][0])
        else:
            groups[find(i)]
    return [g for g in groups.values()]


def _split_check(m, net, cut, groups, label):
    """groups: name -> set of refs.  A piece serving two groups fails; so does a group whose own pads are not one piece"""
    bad = []
    pcs = pieces(m, net, cut)
    for pc in pcs:
        refs = {k[0] for k in pc}
        hit = sorted(g for g, rs in groups.items() if refs & rs)
        if len(hit) > 1:
            bad.append(f'{label}: one piece of copper serves {hit}')
    for g, rs in sorted(groups.items()):
        n = sum(1 for pc in pcs if {k[0] for k in pc} & rs)
        if n > 1:
            bad.append(f'{label}: {g} is not one piece ({n} pieces)')
    return bad


# ------------------------------------------------------------------------------------------------ LR-6
def rail_groups(m):
    groups = defaultdict(set)
    for r, b in m.block.items():
        if b in CONSUMER:
            groups[CONSUMER[b]].add(r)
    return groups


def lr6(m):
    bad = []
    groups = rail_groups(m)
    for net in RAILS:
        cut = set(STAR_REQUIRED[net])           # the named star: the generator's OUT pin and its output caps (spec lead)
        missing = [f'{k[0]}.{k[1]}' for k in STAR_REQUIRED[net] if k not in m.pads or m.pads[k]['net'] != net]
        if missing:
            bad.append(f'{net}: star pads {missing} are not on the net')
        have = {g for g, rs in groups.items() if any(v['net'] == net and k[0] in rs for k, v in m.pads.items())}
        bad += _split_check(m, net, cut, {g: rs for g, rs in groups.items() if g in have}, net)
    return bad, '+3V3A and VNEG: one piece per consumer (AWG, SCOPE, REF/ADS) after cutting the generator pads'


# ------------------------------------------------------------------------------------------------ LR-7
def lr7(m):
    bad = []
    L = length_of(m, '/DAC0')
    if L > 12:
        bad.append(f'DAC0 {L:.1f} mm of track')
    for r in ('R304', 'R306'):
        d = math.dist(m.pos[r], m.pos['J301'])
        if d > 16:
            bad.append(f'{r} {d:.0f} mm from J301')
    shell = [k for k, v in m.pads.items() if k[0] == 'J301' and k[1].split('#')[0] == '2' and v['net'] == '/GND']
    if len(shell) < 3:
        bad.append(f'{len(shell)} BNC shell pads on ground')
    return bad, f'DAC0 {L:.1f} mm; back-termination at the BNC; shell pads on ground'


# ------------------------------------------------------------------------------------------------ LR-8
def lr8(m):
    bad = []
    for net, k in KELVIN.items():
        cut = set(k['source'])
        missing = [f'{a}.{b}' for a, b in cut if (a, b) not in m.pads or m.pads[(a, b)]['net'] != net]
        if missing:
            bad.append(f'{net}: source pads {missing} are not on the net')
        bad += _split_check(m, net, cut, k['branches'], net.lstrip('/'))
    return bad, 'VREF: five branches each on its own copper'


# ------------------------------------------------------------------------------------------------ LR-9
def lr9(m):
    on = defaultdict(set)
    for k, v in m.pads.items():
        on[v['net']].add(k[0])
    bad = []
    ar = analog_refs(m)
    fz = fences_of(ANALOG_FENCES)
    for s in m.segs:
        if s[0] in DIGITAL:
            for r in ar:
                if r in on[s[0]] or r not in m.box:
                    continue
                if seg_in_box(s, m.box[r], ZONE_PAD):
                    bad.append(f'{s[0]} through {r}')
            if any(seg_in_box(s, rc) for rc in fz):
                bad.append(f'{s[0]} inside an analog fence')
    return sorted(set(bad)), 'SDA1 / SCL1 outside every analog courtyard but their own parts and outside the SCOPE and AWG fences'


# ------------------------------------------------------------------------------------------------ LR-10
def lr10(m):
    out = os.path.join(tempfile.mkdtemp(prefix='afe1-drc-'), 'drc.json')
    subprocess.run(['kicad-cli', 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', out, m.path], capture_output=True)
    if not os.path.exists(out):
        return ['kicad-cli produced no DRC report'], ''
    d = json.load(open(out))
    vio = [v for v in d.get('violations', []) if not v.get('excluded')]
    kinds = defaultdict(int)
    for v in vio:
        kinds[v['type']] += 1
    un = len(d.get('unconnected_items', []))
    bad = [f'DRC {dict(kinds)}'] if vio else []
    if un:
        bad.append(f'{un} unconnected items')
    return bad, 'DRC clean; unconnected 0'


# ------------------------------------------------------------------------------------------------ LR-11
def lr11(m):
    bad = []
    for fence, blocks in FENCE_BLOCKS.items():
        want = {r for r, b in m.block.items() if b in blocks and r not in BRIDGE_REFS}
        inside = {r for r in m.pos if m.block.get(r) is not None and r not in BRIDGE_REFS and
                  any(in_box(m.pos[r], rc) for rc in floorplan.FENCES[fence])}
        if inside != want:
            bad.append(f'{fence}: fence holds {sorted(inside - want)} extra, lacks {sorted(want - inside)}')
    for name, nets, at, crosses in floorplan.BRIDGES:
        r = name[name.index('(') + 1:name.index(')')]
        if r in m.pos and math.dist(m.pos[r], at) > BRIDGE_TOL:
            bad.append(f'bridge {r} is {math.dist(m.pos[r], at):.1f} mm from its floorplan point {at}')
    for r in m.fps:
        digits = ''.join(c for c in r if c.isdigit())
        want = BLOCK_HUNDREDS.get(digits[:1]) if len(digits) >= 3 else None
        if m.block.get(r) is None:
            bad.append(f'{r}: not in design.PARTS')
        elif want != m.block[r]:
            bad.append(f'{r}: designator number says {want}, the part is in {m.block[r]}')
    for net, blk in WANT_TP:
        if not any(k[0].startswith('TP') and v['net'] == net and m.block.get(k[0]) == blk for k, v in m.pads.items()):
            bad.append(f'no test point on {net} in block {blk}')
    for b in ('CH1', 'CH2', 'AWG', 'POWER', 'REFCAL'):
        if not any(k[0].startswith('TP') and m.block.get(k[0]) == b for k in m.pads):
            bad.append(f'block {b} has no test point')
    for r, (pos, h, vis) in sorted(m.refs.items()):
        if not vis or h < SILK_MIN - 0.01:
            bad.append(f'{r}: designator not on silk at 1.0 mm or more')
    names = {t for t, _, _ in m.silk}
    for w in SILK_WORDS:
        if w not in names:
            bad.append(f'silk word {w!r} missing')
    return bad, f'{len(floorplan.FENCES)} fences hold exactly their parts, {len(m.refs)} designators, 9 test points'


ROWS = [('LR-1', lr1), ('LR-2', lr2), ('LR-3', lr3), ('LR-4', lr4), ('LR-5', lr5), ('LR-6', lr6), ('LR-7', lr7),
        ('LR-8', lr8), ('LR-9', lr9), ('LR-10', lr10), ('LR-11', lr11)]


def summarise(bad, passmsg):
    """one line: a long run of per-part reasons collapses to a count"""
    if not bad:
        return passmsg
    if len(bad) > 6:
        kinds = defaultdict(list)
        for b in bad:
            kinds[b.split(':', 1)[-1].strip() if 'designator not on silk' in b else b].append(b)
        out = [v[0] if len(v) == 1 else f'{len(v)} x {k}' for k, v in kinds.items()]
        return f'{len(bad)} reasons: ' + '; '.join(out[:6]) + ('; ...' if len(out) > 6 else '')
    return '; '.join(bad)


# ------------------------------------------------------------------------------------------------ the broken arms
def clone_part(m, new, like, block, pos=None):
    m.fps[new], m.block[new] = m.fps[like], block
    m.pos[new] = pos or m.pos[like]
    m.refs[new] = m.refs[like]


def prep_silk(m):
    for r in m.refs:
        m.refs[r] = (m.refs[r][0], SILK_MIN, True)
    m.silk = [(w, (0, 0), 1.0) for w in SILK_WORDS]


def prep_tps(m):
    for ref, net, blk, like, at in (('TP101', '/A1', 'CH1', 'TP501', (70.0, 40.0)), ('TP201', '/A0', 'CH2', 'TP501', (70.0, 36.0)),
                                    ('TP301', '/AWG_OUT', 'AWG', 'TP501', (75.0, 8.0))):
        clone_part(m, ref, like, blk, at)
        m.pads[(ref, '1')] = dict(m.pads[('TP501', '1')], net=net)


def prep_silk_tps(m):
    prep_silk(m)
    prep_tps(m)


def prep_gnd_vias(m):
    for k, v in m.pads.items():
        if v['net'] == '/GND' and v['smd']:
            m.vias.append(('/GND', (v['c'][0] + 0.8, v['c'][1])))


def join(m, net, a, b, layer='F', w=0.2):
    m.segs.append((net, layer, m.pads[a]['c'], m.pads[b]['c'], w))


def connect_group(m, net, refs):
    keys = sorted(k for k, v in m.pads.items() if v['net'] == net and k[0] in refs)
    for a, b in zip(keys, keys[1:]):
        m.links.append((net, a, b))


def prep_connected_rails(m):
    for net in RAILS:
        for g, rs in rail_groups(m).items():
            connect_group(m, net, rs)


def prep_connected_vref(m):
    for g, rs in KELVIN['/VREF']['branches'].items():
        connect_group(m, '/VREF', rs)


OPEN = (20.0, 30.0)      # a spot clear of every fence and courtyard (west of REFCAL, above POWER)


def seg_at(net, layer, a, b, w=0.2):
    return (net, layer, a, b, w)


def mut1_under(m):
    c = m.pos['U101']
    m.segs.append(seg_at('/SCL1', 'B', (c[0] - 1, c[1]), (c[0] + 1, c[1])))


def mut1_hop(m):
    m.segs.append(seg_at('/SCL1', 'B', (OPEN[0], OPEN[1]), (OPEN[0] + 4, OPEN[1])))


def mut1_cross(m):                  # a short bottom hop that crosses an A0 top segment in the open: that is a hop under
    m.segs.append(seg_at('/A0', 'F', (OPEN[0], OPEN[1] - 3), (OPEN[0], OPEN[1] + 3)))
    m.segs.append(seg_at('/SCL1', 'B', (OPEN[0] - 1, OPEN[1]), (OPEN[0] + 1, OPEN[1])))


def mut1_fence(m):
    r = floorplan.FENCES['AWG'][0]
    m.segs.append(seg_at('/SCL1', 'B', (r[0] + 3, r[1] + 1), (r[0] + 4, r[1] + 1)))


def mut1_refcal_fence(m):
    r = floorplan.FENCES['REFCAL'][0]
    m.segs.append(seg_at('/SCL1', 'B', (r[0] + 12, r[1] + 20), (r[0] + 13, r[1] + 20)))


def mut1_pad(m):
    p = m.pads[('R303', '2')]['c']       # AWG_INV pad
    m.segs.append(seg_at('/SCL1', 'B', (p[0] - 0.5, p[1]), (p[0] + 0.5, p[1])))


def mut1_layers(m):
    m.layers = 4


def mut1_vias(m):
    for k in range(3):
        m.vias.append(('/SCL1', (OPEN[0] + k, OPEN[1])))
    m.segs.append(seg_at('/SCL1', 'B', OPEN, (OPEN[0] + 1, OPEN[1])))
    m.segs.append(seg_at('/SCL1', 'B', (OPEN[0] + 1, OPEN[1]), (OPEN[0] + 2, OPEN[1])))


def mut2_flow(m):
    m.pos['R107'] = (m.pos['U101'][0] + 5, m.pos['R107'][1])


def mut2_gen(m):
    m.pos['U401'] = (95.0, 10.0)


def mut2_quiet(m):
    m.box['U501'] = (m.box['U401'][2] + 2, m.box['U401'][1], m.box['U401'][2] + 4, m.box['U401'][3])


def mut2_gap(m):
    p = m.pads[('R106', '1')]['c']
    m.pads[('R206', '1')] = dict(m.pads[('R206', '1')], c=(p[0] + 1, p[1]))


def mut3_via(m):
    m.vias.append(('/CH1_N', m.pads[('R104', '1')]['c']))


def mut3_long(m):
    m.segs.append(seg_at('/CH2_N', 'F', (80, 20), (96, 20)))


def mut3_beside(m):
    c = m.pads[('R104', '1')]['c']
    m.segs.append(seg_at('/CH1_N', 'F', (c[0], c[1]), (c[0] + 1, c[1])))
    m.segs.append(seg_at('/SCL1', 'F', (c[0], c[1] + 0.5), (c[0] + 1, c[1] + 0.5)))


def mut4_via_a0(m):
    m.vias.append(('/A0', m.pads[('R207', '2')]['c']))


def mut4_bot_a1(m):
    m.segs.append(seg_at('/A1', 'B', (60, 40), (61, 40)))


def mut4_via_inv(m):
    m.vias.append(('/AWG_INV', m.pads[('R303', '2')]['c']))


def mut4_via_ch1n(m):
    m.vias.append(('/CH1_N', m.pads[('R105', '1')]['c']))


def mut4_bot_ch2n(m):
    m.segs.append(seg_at('/CH2_N', 'B', (3.0, 3.0), (4.0, 3.0)))


def mut4_long(m):
    m.segs.append(seg_at('/AWG_INV', 'F', (80, 30), (96, 30)))


def mut4_pour(m):
    p = m.pads[('R303', '2')]['c']
    m.extra_top_gnd.append((p[0] + 0.3, p[1]))


def mut4_gndtrack(m):
    p = m.pads[('R105', '1')]['c']
    m.segs.append(seg_at('/GND', 'F', (p[0] - 3, p[1] + 0.4), (p[0] + 3, p[1] + 0.4)))


def mut4_decoup(m):
    m.pads[('C302', '1')] = dict(m.pads[('C302', '1')], c=(0.0, 0.0))


def mut4_riso(m):
    m.pads[('R107', '1')] = dict(m.pads[('R107', '1')], c=(0.0, 0.0))


def mut5(m):
    c = m.pos['U401']
    m.segs.append(seg_at('/VREF', 'F', (c[0] + 4, c[1] + 4), (c[0] + 4, c[1] + 6)))


def mut5_pad(m):
    c = m.pos['U401']
    m.pads[('R508', '2')] = dict(m.pads[('R508', '2')], c=(c[0] + 4, c[1] + 4))


def mut6_join(m):
    join(m, '/+3V3A', ('U301', '8'), ('U502', '8'))


def mut6_star(m):
    m.pads[('C407', '1')] = dict(m.pads[('C407', '1')], net='/X')


def mut6_scope_join(m):
    join(m, '/+3V3A', ('R109', '1'), ('U301', '8'))


def mut7_dac0(m):
    m.segs.append(seg_at('/DAC0', 'F', (30.0, 30.0), (60.0, 30.0)))


def mut7_bt(m):
    m.pos['R304'] = (50.0, 30.0)


def mut7_shell(m):
    for k in [k for k in m.pads if k[0] == 'J301' and k[1].split('#')[0] == '2']:
        m.pads[k] = dict(m.pads[k], net='/X')


def mut8_join(m):
    join(m, '/VREF', ('R508', '2'), ('U502', '4'))


def mut8_join2(m):
    join(m, '/VREF', ('R307', '1'), ('R104', '2'))


def mut9_ana(m):
    c = m.pos['U101']
    m.segs.append(seg_at('/SDA1', 'F', (c[0] - 2, c[1]), (c[0] + 2, c[1])))


def mut9_fence(m):
    r = floorplan.FENCES['AWG'][0]
    m.segs.append(seg_at('/SCL1', 'F', (r[0] + 3, r[1] + 1), (r[0] + 4, r[1] + 1)))


def mut11_out(m):
    m.pos['R201'] = (30.0, 40.0)


def mut11_bridge(m):
    m.pos['R515'] = (30.0, 40.0)


def mut11_silk(m):
    m.refs['R101'] = (m.refs['R101'][0], 0.5, False)


def mut11_tp(m):
    del m.pads[('TP301', '1')]


def mut11_tpblock(m):
    m.block['TP301'] = 'CH1'


def mut11_num(m):
    clone_part(m, 'R399', 'R101', 'CH1')


def mut11_noblock(m):
    for r in [r for r in m.fps if r.startswith('TP') and m.block.get(r) == 'REFCAL']:
        del m.pads[(r, '1')]


def mut11_word(m):
    m.silk = [s for s in m.silk if s[0] != 'AWG']


# name, rule, prep, mutation, keyword that the NEW reason must contain
ARMS = [
    ('LR-1 bottom copper under U101', lr1, None, mut1_under, 'bottom copper under'),
    ('LR-1 4 mm hop', lr1, None, mut1_hop, 'bottom run'),
    ('LR-1 three vias on a hop', lr1, None, mut1_vias, '3 vias'),
    ('LR-1 hop crossing a sensitive top net', lr1, None, mut1_cross, 'crosses /A0'),
    ('LR-1 inside the AWG fence', lr1, None, mut1_fence, 'inside the fence'),
    ('LR-1 inside the REFCAL fence', lr1, None, mut1_refcal_fence, 'inside the fence'),
    ('LR-1 under an AWG_INV pad', lr1, None, mut1_pad, 'under pad R303'),
    ('LR-1 four copper layers', lr1, None, mut1_layers, '4 copper layers'),
    ('LR-2 flow reversed (Riso east of U101)', lr2, None, mut2_flow, 'x does not fall'),
    ('LR-2 generator by the BNC', lr2, None, mut2_gen, 'generator'),
    ('LR-2 reference under the generator', lr2, None, mut2_quiet, 'U501 only'),
    ('LR-2 divider pads of two channels 1 mm apart', lr2, None, mut2_gap, 'apart'),
    ('LR-3 via on CH1_N', lr3, None, mut3_via, 'a via'),
    ('LR-3 16 mm of CH2_N', lr3, None, mut3_long, 'mm of track'),
    ('LR-3 track 0.5 mm beside CH1_N', lr3, None, mut3_beside, 'within 0.6 mm'),
    ('LR-4 via in A0', lr4, None, mut4_via_a0, '/A0: a via'),
    ('LR-4 bottom copper on A1', lr4, None, mut4_bot_a1, '/A1: bottom copper'),
    ('LR-4 via on AWG_INV', lr4, None, mut4_via_inv, 'AWG_INV: inverting node has a via'),
    ('LR-4 via on CH1_N', lr4, None, mut4_via_ch1n, 'CH1_N: inverting node has a via'),
    ('LR-4 bottom copper on CH2_N', lr4, None, mut4_bot_ch2n, 'CH2_N: inverting node has bottom'),
    ('LR-4 AWG_INV 16 mm long', lr4, None, mut4_long, 'AWG_INV: inverting node'),
    ('LR-4 pour near AWG_INV', lr4, None, mut4_pour, 'AWG_INV: top ground'),
    ('LR-4 GND track near CH1_N', lr4, None, mut4_gndtrack, 'CH1_N: top ground'),
    ('LR-4 100 nF far from U301.8', lr4, None, mut4_decoup, 'U301.8'),
    ('LR-4 Riso far from the output pin', lr4, None, mut4_riso, 'R107'),
    ('LR-5 VREF track by the generator', lr5, None, mut5, '/VREF'),
    ('LR-5 VREF pad by the generator', lr5, None, mut5_pad, 'pad R508'),
    ('LR-6 AWG and REF/ADS on one +3V3A piece', lr6, prep_connected_rails, mut6_join, 'serves'),
    ('LR-6 SCOPE and AWG on one +3V3A piece', lr6, prep_connected_rails, mut6_scope_join, 'serves'),
    ('LR-6 star pad off the rail', lr6, None, mut6_star, 'star pads'),
    ('LR-7 DAC0 30 mm', lr7, None, mut7_dac0, 'DAC0'),
    ('LR-7 R304 far from the BNC', lr7, None, mut7_bt, 'R304'),
    ('LR-7 BNC shell not on ground', lr7, None, mut7_shell, 'shell'),
    ('LR-8 ladder and ADS share VREF copper', lr8, prep_connected_vref, mut8_join, 'serves'),
    ('LR-8 AWG offset and CH1 leg share copper', lr8, prep_connected_vref, mut8_join2, 'serves'),
    ('LR-9 SDA1 through U101', lr9, None, mut9_ana, 'through U101'),
    ('LR-9 SCL1 inside the AWG fence', lr9, None, mut9_fence, 'analog fence'),
    ('LR-11 part out of its fence', lr11, prep_silk_tps, mut11_out, "'R201'"),
    ('LR-11 bridge away from its floorplan point', lr11, prep_silk_tps, mut11_bridge, 'bridge R515'),
    ('LR-11 designator under 0.8 mm / not on silk', lr11, prep_silk_tps, mut11_silk, 'R101: designator'),
    ('LR-11 missing test point (AWG_OUT)', lr11, prep_silk_tps, mut11_tp, 'no test point on /AWG_OUT'),
    ('LR-11 test point in the wrong block', lr11, prep_silk_tps, mut11_tpblock, 'no test point on /AWG_OUT'),
    ('LR-11 wrong-numbered designator', lr11, prep_silk_tps, mut11_num, 'R399'),
    ('LR-11 block without a test point', lr11, prep_silk_tps, mut11_noblock, 'REFCAL has no test point'),
    ('LR-11 silk word missing', lr11, prep_silk_tps, mut11_word, "silk word 'AWG'"),
]
# name, rule, repair (adds the copper the rule asks for), keyword that must DISAPPEAR from the reasons
REPAIRS = [
    ('LR-1 every SMD GND pad gets a via', lr1, prep_gnd_vias, 'without a via'),
    ('LR-6 each consumer connected on its rail', lr6, prep_connected_rails, 'is not one piece'),
    ('LR-8 each branch connected', lr8, prep_connected_vref, 'is not one piece'),
    ('LR-11 silk and the three test points added', lr11, prep_silk_tps, 'designator not on silk'),
]


def lr10_arm(path):
    b = pcb.LoadBoard(path)
    t = pcb.PCB_TRACK(b)
    p = b.FindFootprintByReference('R101').Pads()[0].GetPosition()
    t.SetStart(pcb.VECTOR2I(p.x, p.y + pcb.FromMM(1.0)))
    t.SetEnd(pcb.VECTOR2I(p.x + pcb.FromMM(3.0), p.y + pcb.FromMM(1.0)))
    t.SetWidth(pcb.FromMM(0.1))
    t.SetLayer(pcb.F_Cu)
    t.SetNet(b.FindNet('/CH1_N'))
    b.Add(t)
    tmp = os.path.join(tempfile.mkdtemp(prefix='afe1-mut-'), 'afe-proto.kicad_pcb')
    b.Save(tmp)
    shutil.copy(os.path.join(HERE, 'afe-proto.kicad_pro'), tmp.replace('.kicad_pcb', '.kicad_pro'))
    return tmp


def main(argv):
    mutate = '--mutate' in argv
    args = [a for a in argv if not a.startswith('--')]
    path = args[0] if args else BOARD
    m = fresh(path)
    fails = []
    if not mutate:
        for name, fn in ROWS:
            bad, ok_text = fn(m)
            print(f'[{"FAIL" if bad else "PASS"}] {name}: {summarise(bad, ok_text)}', flush=True)
            if bad:
                fails.append(name)
        print('ALL PASS' if not fails else 'FAIL: ' + ', '.join(fails))
        return 1 if fails else 0
    for name, fn, prep, mut, key in ARMS:
        clean = fresh(path)
        if prep:
            prep(clean)
        before, _ = fn(clean)
        broken = fresh(path)
        if prep:
            prep(broken)
        mut(broken)
        after, _ = fn(broken)
        new = [x for x in after if x not in before and key in x]
        print(f'[{"FAILED AS REQUIRED" if new else "NOT CAUGHT"}] {name} (rule on the prepared board: '
              f'{"fail" if before else "pass"}): {new[0] if new else "no new reason containing " + repr(key)}', flush=True)
        if not new:
            fails.append(name)
    for name, fn, repair, key in REPAIRS:
        a = fresh(path)
        before, _ = fn(a)
        repair(a)
        after, _ = fn(a)
        had = any(key in x for x in before)
        gone = not any(key in x for x in after)
        ok = had and gone
        print(f'[{"REPAIR CLEARS IT" if ok else "REPAIR DID NOT"}] {name}: before {sum(key in x for x in before)} '
              f'reasons with {key!r}, after {sum(key in x for x in after)}', flush=True)
        if not ok:
            fails.append(name)
    before, _ = lr10(fresh(path))
    after, _ = lr10(load(lr10_arm(path)))
    new = [x for x in after if x not in before]
    print(f'[{"FAILED AS REQUIRED" if new else "NOT CAUGHT"}] LR-10 (a 0.1 mm track added): before {before}; after {after}', flush=True)
    if not new:
        fails.append('LR-10')
    print('every arm behaved' if not fails else 'NOT CAUGHT: ' + ', '.join(fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
