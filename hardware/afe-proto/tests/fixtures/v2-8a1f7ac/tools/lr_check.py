"""The layout rules of docs/afe.md section 11.1 (LR-1 .. LR-11) that a program can decide, checked on the v2 board.

    python3.14 -I lr_check.py [board.kicad_pcb]            every row; exit 0 only if all pass
    python3.14 -I lr_check.py --mutate [board.kicad_pcb]   every row's broken-on-purpose arm: each must FAIL

Each rule is a function  lrN(model) -> (ok, detail)  over a Model read from the board.  A mutation is a function that
breaks the Model in the way its rule forbids (a bottom track under the scope, a via on N, a join between two rails'
branches, a part pushed out of its block outline ...); `--mutate` runs the rule on the broken copy and reports FAILED
AS REQUIRED, or exits 1 when a rule passes a layout it should refuse.  LR-10 (DRC) is run by kicad-cli on the file; its
arm writes a copy with a 0.1 mm track and expects DRC to object.
What each row looks at, so a pass is not read as more than it is:
  LR-1   two copper layers; one bottom GND zone, filled, one piece; every non-GND bottom run is a hop of at most
         3 mm and 2 vias (no exception for the generator); no non-GND bottom segment lies under an analog part,
         inside an analog fence (layout.OUTLINE of CH1, CH2, AWG), or under a sensitive top net or pad (A0/A1, VREF*,
         TAP*, SNS*, ADS_*, AWG_BNC*, AWG_FB, AWG_BIN, CH*_NP, CH*_N, CH*_M*, CH*_IN: those crossings are top bridges);
         every SMD GND pad has a via of its own within 3 mm.
  LR-2   per channel x falls from BNC through R1, Rnp, U101, Riso to the ADC pad; the ADC trace is longer than
         the channel's high-impedance copper; the generator is by the 5 V pad and far from every BNC; the reference
         block is >= 10 mm from the generator; the channels' divider pads are >= 5 mm apart.
  LR-3   no via and at most 14 mm of track on the divider nets; no other non-GND track within 0.6 mm of them.
  LR-4   inverting nodes (AWG_FB, CH1_N, CH2_N): no via, no bottom copper;  A0 / A1: top only, no via; Riso at the output pin; a 100 nF near each op-amp supply pin; the AWG
         inverting node is <= FB_MAX long; no top GND copper within 0.5 mm of that node.
  LR-4b  (row 'LR-4 INV_MAX') the summed track length of each of AWG_FB, CH1_N, CH2_N is <= INV_MAX (5 mm).
  LR-12  (row 'LR-12 DECOUP_MAX') each cap of the DECOUP table (cap -> IC supply pin) has its supply pad within
         DECOUP_MAX (3 mm) of that pin, pad centre to pin centre.
  LR-5   no sensitive copper within 10 mm of the generator or its flying capacitor.
  LR-6   each rail, with the generator's pads cut out, falls into pieces that each serve one consumer group.
  LR-7   DAC0 <= 12 mm; R301/R302 near J301; the BNC shells are on ground.
  LR-8   VREF with the source pads cut out falls into one piece per named branch (the groups of route.KELVIN).
  LR-9   Due digital nets (SDA, SCL) stay out of every analog part's courtyard other than their own parts'.
  LR-10  kicad-cli DRC at 0.15 / 0.3 mm: zero violations and nothing unconnected.
  LR-11  each block outline holds exactly its block's parts (design.py's block, with layout.BLOCK_OVERRIDE), every
         part has a 0.8 mm designator on silk, its designator's hundreds digit names its block
         (1 CH1, 2 CH2, 3 AWG, 4 POWER, 5 REFCAL, 6 edge), every block has a test point, the eight test points exist.
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
import layout  # noqa: E402

BOARD = os.path.join(HERE, 'afe-v2.kicad_pcb')
ZONE_PAD = 0.3
HOP_MAX = 3.0
# LR-1 / D24: a bottom hop is at most 3 mm and two vias, with no exception for the generator (the old 8 mm
# GEN_HOP_MAX for the EN hop was a deviation from the rule text and is gone; a longer hop now fails).
KEEPOUT = 10.0
FB_MAX = 14.0
GEN = ('U401', 'C409')
# LR-4 / LR-12: the inverting (and follower-critical) nodes are each the stage's shortest trace: Rf/Cf and Rg sit at the
# pin.  Track length summed over every layer of the net, in mm.
INV_MAX = 5.0
# LR-12: a supply decoupling cap's pad (the one on the supply net) lies within DECOUP_MAX mm, pad centre to the IC's
# supply pin centre, of the pin it decouples.
DECOUP_MAX = 3.0
# cap ref -> (IC ref, supply pin of that IC, from design.py's pin tables).  Spec lead's scope: the 100 nF at each op-amp,
# ADS1115 and REF3030E supply pin only.  Not the LM27762's caps C401..C408 (LR-5: the datasheet's layout at its pins) nor
# bulk filter caps (LR-6) nor the flying cap C409.
DECOUP = {'C104': ('U101', '8'), 'C105': ('U101', '8'),          # TPH2502 V+ (+3.3 V_A_U)
          'C305': ('U301', '8'), 'C306': ('U301', '4'),          # awg dual: V+ and V-
          'C502': ('U501', '1'), 'C501': ('U501', '2'),          # REF3030E VIN, VOUT
          'C503': ('U502', '8')}                                 # ADS1115 VDD
ANALOG_REFS = {p['ref'] for p in design.PARTS if p['block'] in ('CH1', 'CH2', 'AWG', 'REFCAL')
               and not p['ref'].startswith(('J', 'TP', 'MH'))}
ANALOG_REFS |= {r for r, v in layout.EXTRA.items() if v[2] in ('CH1', 'CH2', 'AWG', 'REFCAL')}
GENERATOR_BLOCK = {p['ref'] for p in design.PARTS if p['block'] == 'POWER'}
ANALOG_FENCE = ('CH1', 'CH2', 'AWG')          # LR-1 "analog zones": layout.OUTLINE rectangles of these blocks
# nets a bottom hop must never cross under (LR-1: ADC traces, follower +IN nodes, anything in an analog zone are
# bridged on top instead): A0/A1 (ADC traces), the reference, the taps and sense nodes, the AWG output, the AWG's
# inverting node and +IN, the scope channels' +IN pins and divider nodes
XSENS = ('/A0', '/A1', '/VREF', '/TAP', '/SNS', '/AWG_BNC', '/ADS_', '/AREF', '/AWG_FB', '/AWG_BIN', '/CH1_NP', '/CH2_NP',
         '/CH1_N', '/CH2_N', '/CH1_M', '/CH2_M', '/CH1_IN', '/CH2_IN')
INV_NODES = ('/AWG_FB', '/CH1_N', '/CH2_N')   # LR-4 / LR-3: no via, no bottom copper
# INV_MAX scope (spec lead): op-amp inverting inputs only: AWG_FB, and each scope follower's -IN tie (-IN is tied to OUT, so the
# net CHx_OUT).  The divider nodes CH1_N/CH2_N are LR-3's (no via, nothing beside, smallest copper, extracted budget).
INV_LEN_NODES = ('/AWG_FB', '/CH1_OUT', '/CH2_OUT')
BLOCK_HUNDREDS = {'1': 'CH1', '2': 'CH2', '3': 'AWG', '4': 'POWER', '5': 'REFCAL', '6': 'EDGE'}
SENSITIVE = ('/A0', '/A1', '/VREF', '/TAP', '/SNS', '/AWG_BNC', '/ADS_', '/CH1_N', '/CH2_N')
HIZ = ('CH1_N', 'CH1_M1', 'CH1_M2', 'CH1_M3', 'CH1_NP', 'CH2_N', 'CH2_M1', 'CH2_M2', 'CH2_M3', 'CH2_NP')
GROUPS_3V3 = {'scope': {'U101', 'C104', 'C105', 'BR101', 'BR102', 'D201', 'D101'},
              'awg': {'U301', 'C305'}, 'adc': {'U501', 'C502', 'U502', 'C503', 'R512', 'R513', 'BR507'}}
GROUPS_VNEG = {'awg': {'U301', 'C306', 'BR401'}}
STAR = {'/+3V3A': [('U401', '11'), ('C405', '1'), ('C406', '1'), ('R401', '1'), ('TP401', '1'), ('R407', '1')],
        '/VNEG_G': [('U401', '6'), ('C407', '1'), ('C408', '1'), ('R403', '1')]}


def mm(v):
    return pcb.ToMM(v)


def due(p):
    return (mm(p.x) - 50.0, 150.0 - mm(p.y))


class Model:
    """everything the rules read, in Due coordinates (y up), plain python so a mutation can edit it"""


def load(path):
    b = pcb.LoadBoard(path)
    m = Model()
    m.board, m.path = b, path
    m.fps = {f.GetReference(): f for f in b.GetFootprints()}
    m.block = {p['ref']: layout.BLOCK_OVERRIDE.get(p['ref'], p['block']) for p in design.PARTS}
    m.block.update({r: v[2] for r, v in layout.EXTRA.items()})
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
            bb = p.GetBoundingBox()
            (x0, y1), (x1, y0) = due(pcb.VECTOR2I(bb.GetLeft(), bb.GetTop())), due(pcb.VECTOR2I(bb.GetRight(), bb.GetBottom()))
            m.pads[(r, p.GetNumber())] = dict(net=str(p.GetNetname()), c=due(p.GetPosition()), box=(x0, y0, x1, y1),
                                              smd=p.GetAttribute() == pcb.PAD_ATTRIB_SMD)
    m.zones = []
    for z in b.Zones():
        lay = z.GetLayer()
        m.zones.append(dict(layer='F' if lay == pcb.F_Cu else 'B', net=str(z.GetNetname()), z=z,
                            pieces=z.GetFilledPolysList(lay).OutlineCount() if z.IsFilled() else 0, filled=z.IsFilled()))
    m.layers = b.GetCopperLayerCount()
    m.shell_ok = True
    m.silk = [(str(t.GetText()), due(t.GetPosition()), mm(t.GetTextHeight())) for t in b.Drawings()
              if t.GetClass() == 'PCB_TEXT' and t.GetLayer() == pcb.F_SilkS]
    m.refs = {r: (due(f.Reference().GetPosition()), mm(f.Reference().GetTextHeight()),
                  f.Reference().GetLayer() == pcb.F_SilkS and f.Reference().IsVisible()) for r, f in m.fps.items()}
    m.extra_top_gnd = []                 # a mutation can add top ground copper points here
    return m


def gnd_top_zone_hit(m, pt):
    return any(z['z'].HitTestFilledArea(pcb.F_Cu, pcb.VECTOR2I(pcb.FromMM(pt[0] + 50.0), pcb.FromMM(150.0 - pt[1])),
                                         pcb.FromMM(0.02)) for z in m.zones if z['layer'] == 'F' and z['net'] == '/GND')


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


def length_of(m, net):
    return sum(seg_len(s) for s in m.segs if s[0] == net and s[1] == 'F')


# --------------------------------------------------------------------------------------------------- LR-1
def bottom_runs(m):
    bs = [s for s in m.segs if s[1] == 'B' and s[0] != '/GND']
    runs, seen = [], [False] * len(bs)
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
        under = sorted({r for r in ANALOG_REFS if r in m.box and any(seg_in_box(s, m.box[r], ZONE_PAD) for s in comp)})
        runs.append((net, sum(seg_len(s) for s in comp), nv, under))
    return runs


def fences(m):
    return [rc for b in ANALOG_FENCE for rc in layout.OUTLINE.get(b, [])]


def seg_seg_dist(s, t):
    return min(math.dist(p, q) for p in seg_pts(s, 0.1) for q in seg_pts(t, 0.1))


def bottom_crossings(m):
    """LR-1: no non-GND bottom segment lies under a sensitive top net (track or pad) or inside an analog fence;
    those crossings are top-layer bridges, never a hop under"""
    bad = []
    fz = fences(m)
    top = [s for s in m.segs if s[1] == 'F' and s[0].startswith(XSENS)]
    pads = [(k, v) for k, v in m.pads.items() if v['net'].startswith(XSENS)]
    for s in (x for x in m.segs if x[1] == 'B' and x[0] != '/GND'):
        for rc in fz:
            if seg_in_box(s, rc):
                bad.append(f'{s[0]}: bottom segment inside an analog fence {tuple(round(v, 1) for v in rc)}')
                break
        for t in top:
            if seg_seg_dist(s, t) < (s[4] + t[4]) / 2 + 0.1:
                bad.append(f'{s[0]}: bottom segment under {t[0]} (a hop under a sensitive net; bridge it on top)')
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
    gp = [(k, v) for k, v in m.pads.items() if v['net'] == '/GND' and v['smd']]
    used, nov = set(), []
    for k, v in sorted(gp):
        cand = sorted((math.dist(v['c'], g), i) for i, g in enumerate(gv) if i not in used)
        if cand and cand[0][0] <= 3.0:
            used.add(cand[0][1])
        else:
            nov.append(f'{k[0]}.{k[1]}')
    if nov:
        bad.append(f'{len(nov)} SMD ground pads without a via of their own: {nov[:6]}')
    return (not bad, '; '.join(bad[:6]) or f'2 layers, one bottom plane, {len(runs)} bottom runs, {len(gp)} GND pads each with its own via')


# --------------------------------------------------------------------------------------------------- LR-2
def lr2(m):
    bad = []
    for ch, base, bnc, adc in ((1, 100, 'J101', '7'), (2, 200, 'J201', '8')):
        seq = [m.pads[(bnc, '1')]['c'][0], m.pos[f'R{base + 1}'][0], m.pos[f'R{base + 7}'][0], m.pos['U101'][0],
               m.pos[f'R{base + 8}'][0], m.pads[('J602', adc)]['c'][0]]
        if not all(a > b for a, b in zip(seq, seq[1:])):
            bad.append(f'CH{ch}: x does not fall BNC > R1 > Rnp > U101 > Riso > ADC pad: {[round(x, 1) for x in seq]}')
        outl = length_of(m, '/A1' if ch == 1 else '/A0') + length_of(m, f'/CH{ch}_OUT') + (length_of(m, '/CH2_RISO') if ch == 2 else 0)
        hiz = sum(length_of(m, f'/CH{ch}_{n}') for n in ('N', 'M1', 'M2', 'M3', 'NP'))
        if outl <= hiz:
            bad.append(f'CH{ch}: output run {outl:.1f} mm is not longer than the divider side {hiz:.1f} mm')
    g = m.pos['U401']
    if math.dist(g, m.pads[('J601', '5')]['c']) > 15:
        bad.append(f'generator {math.dist(g, m.pads[("J601", "5")]["c"]):.1f} mm from the 5 V pad')
    for j in ('J101', 'J201', 'J301'):
        if math.dist(g, m.pos[j]) < 50:
            bad.append(f'generator {math.dist(g, m.pos[j]):.0f} mm from {j}')
    for r in ('U501', 'U502', 'R501', 'R506'):
        d = min(dist_box_box(m.box[r], m.box[x]) for x in GEN)
        if d < KEEPOUT:
            bad.append(f'{r} only {d:.1f} mm from the generator')
    a = [v['c'] for v in m.pads.values() if v['net'] in ('/CH1_N', '/CH1_NP', '/CH1_IN') and v['c'][0] < 91]
    b = [v['c'] for v in m.pads.values() if v['net'] in ('/CH2_N', '/CH2_NP', '/CH2_IN') and v['c'][0] < 91]
    gap = min(math.dist(p, q) for p in a for q in b)
    if gap < 5.0:
        bad.append(f"channels' divider pads only {gap:.1f} mm apart")
    return (not bad, '; '.join(bad[:5]) or f'flow, generator, quiet zone and channel separation hold (closest divider pads {gap:.1f} mm)')


# --------------------------------------------------------------------------------------------------- LR-3
def segs_close(s, t, d):
    ps, pt_ = seg_pts(s, 0.2), seg_pts(t, 0.2)
    lim = d + (s[4] + t[4]) / 2
    return any(math.dist(p, q) < lim for p in ps for q in pt_)


def lr3(m):
    bad = []
    for n in HIZ:
        net = '/' + n
        if any(v[0] == net for v in m.vias):
            bad.append(f'{net}: a via')
        L = length_of(m, net)
        if L > 14:
            bad.append(f'{net}: {L:.1f} mm of track')
    for s in m.segs:
        if s[0][1:] not in HIZ or s[1] != 'F':
            continue
        for t in m.segs:
            if t[1] != 'F' or t[0] == s[0] or t[0] == '/GND':
                continue
            if segs_close(s, t, 0.6):
                bad.append(f'{s[0]} track within 0.6 mm of {t[0]} track')
                break
    return (not bad, '; '.join(sorted(set(bad))[:6]) or f'{len(HIZ)} divider nets: no via, short, no track beside')


# --------------------------------------------------------------------------------------------------- LR-4
def lr4(m):
    bad = []
    for net in ('/A0', '/A1'):
        if any(v[0] == net for v in m.vias):
            bad.append(f'{net}: a via')
        if any(s[0] == net and s[1] == 'B' for s in m.segs):
            bad.append(f'{net}: bottom copper')
    for r, pinpad in (('R108', ('U101', '7')), ('R208', ('U101', '1'))):
        if math.dist(m.pads[(r, '1')]['c'], m.pads[pinpad]['c']) > 5:
            bad.append(f'{r} not at the output pin')
    for cap, pad in (('C104', ('U101', '8')), ('C305', ('U301', '8')), ('C306', ('U301', '4'))):
        d = math.dist(m.pads[(cap, '1')]['c'], m.pads[pad]['c'])
        if d > 12:
            bad.append(f'{cap} {d:.0f} mm from its supply pin')
    for net in INV_NODES:
        if any(v[0] == net for v in m.vias):
            bad.append(f'{net}: inverting node has a via')
        if any(s[0] == net and s[1] == 'B' for s in m.segs):
            bad.append(f'{net}: inverting node has bottom copper')
    L = length_of(m, '/AWG_FB')
    if L > FB_MAX:
        bad.append(f'AWG inverting node {L:.1f} mm of track (limit {FB_MAX})')
    pts = [p for s in m.segs if s[0] == '/AWG_FB' and s[1] == 'F' for p in seg_pts(s, 0.5)]
    pts += [v['c'] for v in m.pads.values() if v['net'] == '/AWG_FB']
    near = set()
    for p in pts:
        if any(math.dist(p, q) < 0.5 for q in m.extra_top_gnd):
            near.add('added ground copper')
        for s in m.segs:
            if s[0] == '/GND' and s[1] == 'F' and min(math.dist(p, q) for q in seg_pts(s, 0.25)) - s[4] / 2 < 0.5:
                near.add('GND track')
        if any(gnd_top_zone_hit(m, (p[0] + dx, p[1] + dy)) for dx, dy in ((0.5, 0), (-0.5, 0), (0, 0.5), (0, -0.5))):
            near.add('top pour')
    if near:
        bad.append(f'top ground copper within 0.5 mm of the inverting node ({sorted(near)})')
    return (not bad, '; '.join(bad[:5]) or f'A0/A1 top only, no via ({length_of(m, "/A0"):.0f}/{length_of(m, "/A1"):.0f} mm); '
            f'FB node {L:.1f} mm of track; decoupling near; no pour within 0.5 mm of it')


# --------------------------------------------------------------------------------------------------- LR-4 length, LR-12
def lr4_inv(m):
    """LR-4: the track on each inverting / follower-critical node is at most INV_MAX mm (all layers)."""
    bad, fig = [], []
    for net in INV_LEN_NODES:
        L = sum(seg_len(t) for t in m.segs if t[0] == net)
        fig.append(f'{net[1:]} {L:.1f} mm')
        if L > INV_MAX:
            bad.append(f'{net[1:]} {L:.1f} mm of track exceeds INV_MAX {INV_MAX} mm')
    return (not bad, '; '.join(bad) + (' [' + ', '.join(fig) + ']' if bad else '') or
            f'{", ".join(fig)} (<= {INV_MAX})')


def decoup_dist(m, cap):
    ic, pin = DECOUP[cap]
    net = m.pads[(ic, pin)]['net']
    pads = [k for k in ('1', '2') if m.pads[(cap, k)]['net'] == net] or ['1']
    return min(math.dist(m.pads[(cap, k)]['c'], m.pads[(ic, pin)]['c']) for k in pads)


def lr12(m):
    """LR-12: every supply decoupling cap in DECOUP has its supply-net pad within DECOUP_MAX of its IC supply pin."""
    bad, fig = [], []
    for cap, (ic, pin) in DECOUP.items():
        d = decoup_dist(m, cap)
        fig.append(f'{cap}>{ic}.{pin} {d:.1f}')
        if d > DECOUP_MAX:
            bad.append(f'{cap} is {d:.1f} mm from {ic} pin {pin} (limit {DECOUP_MAX})')
    return (not bad, '; '.join(bad) or f'{len(DECOUP)} caps within {DECOUP_MAX} mm: ' + ', '.join(fig))


# --------------------------------------------------------------------------------------------------- LR-5
def lr5(m):
    gen = [m.box[r] for r in GEN]
    near = []
    for s in m.segs:
        if s[1] == 'F' and s[0].startswith(SENSITIVE):
            d = min(min(dist_pt_box(p, g) for p in seg_pts(s, 0.5)) for g in gen)
            if d < KEEPOUT:
                near.append(f'{s[0]} {d:.1f} mm')
    for k, v in m.pads.items():
        if v['net'].startswith(SENSITIVE) and k[0] not in GENERATOR_BLOCK:
            d = min(dist_pt_box(v['c'], g) for g in gen)
            if d < KEEPOUT:
                near.append(f'{v["net"]} pad {k[0]}.{k[1]} {d:.1f} mm')
    return (not near, '; '.join(sorted(set(near))[:6]) or f'sensitive copper >= {KEEPOUT} mm from {"/".join(GEN)}')


# --------------------------------------------------------------------------------------------------- pieces of copper
def pieces(m, net, cut=()):
    """connected pieces of one net's top copper (tracks, vias, pads), the pads in `cut` removed; BRIDGE_PADS are
    joined (the part carries current between them).  Returns a list of sets of refs"""
    nodes = [('s', s) for s in m.segs if s[0] == net and s[1] == 'F']
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
                return any(math.dist(p, q) < 0.02 for p in a[1][2:4] for q in b[1][2:4]) or \
                    any(math.dist(p, q) < 0.05 for p in a[1][2:4] for q in seg_pts(b[1], 0.05)) or \
                    any(math.dist(p, q) < 0.05 for q in b[1][2:4] for p in seg_pts(a[1], 0.05))
            if kb == 'v':
                return any(math.dist(p, b[1][1]) < 0.05 for p in seg_pts(a[1], 0.05))
            bx = b[1][1]['box']
            return any(in_box(p, bx, 0.02) for p in seg_pts(a[1], 0.1))
        if ka == 'v':
            if kb == 'v':
                return math.dist(a[1][1], b[1][1]) < 0.05
            return in_box(a[1][1], b[1][1]['box'], 0.02)
        return False
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if touches(nodes[i], nodes[j]):
                parent[find(i)] = find(j)
    for (ra, pa, rb, pb) in layout.BRIDGE_PADS:
        ia = [i for i, nd in enumerate(nodes) if nd[0] == 'p' and nd[1][0] == (ra, pa)]
        ib = [i for i, nd in enumerate(nodes) if nd[0] == 'p' and nd[1][0] == (rb, pb)]
        if ia and ib:
            parent[find(ia[0])] = find(ib[0])
    groups = defaultdict(set)
    for i, nd in enumerate(nodes):
        if nd[0] == 'p':
            groups[find(i)].add(nd[1][0][0])
        else:
            groups[find(i)]
    return [set(g) for g in groups.values()]


# --------------------------------------------------------------------------------------------------- LR-6
def lr6(m):
    bad = []
    for net, groups in (('/+3V3A', GROUPS_3V3), ('/VNEG_G', GROUPS_VNEG)):
        cut = set(STAR[net])
        have = {k for k, v in m.pads.items() if v['net'] == net}
        missing = [f'{k[0]}.{k[1]}' for k in cut if k not in have]
        if missing:
            bad.append(f'{net}: star pads {missing} are not on the net')
        for pc in pieces(m, net, cut):
            hit = sorted(g for g, refs in groups.items() if pc & refs)
            if len(hit) > 1:
                bad.append(f'{net}: one piece of copper serves {hit}')
    return (not bad, '; '.join(bad[:5]) or '+3V3A and VNEG: one piece per consumer group after cutting the star pads')


# --------------------------------------------------------------------------------------------------- LR-7
def lr7(m):
    bad = []
    L = length_of(m, '/DAC0')
    if L > 12:
        bad.append(f'DAC0 {L:.1f} mm of track')
    for r in ('R301', 'R302'):
        d = math.dist(m.pos[r], m.pos['J301'])
        if d > 16:
            bad.append(f'{r} {d:.0f} mm from J301')
    shell = [p for p in m.fps['J301'].Pads() if p.GetNumber() == '2' and str(p.GetNetname()) == '/GND']
    if len(shell) < 3:
        bad.append(f'{len(shell)} BNC shell pads on ground')
    return (not bad, '; '.join(bad) or f'DAC0 {L:.1f} mm; back-termination at the BNC; shell pads on ground')


# --------------------------------------------------------------------------------------------------- LR-8
def lr8(m):
    import route
    src, groups = route.KELVIN['VREF']
    cut = {tuple(s.split('.')) for s in src}
    refs_of = [{a for a, b in (tuple(s.split('.')) for s in g)} for g in groups]
    bad = []
    for pc in pieces(m, '/VREF', cut):
        hit = sorted(k for k, g in enumerate(refs_of) if pc & g)
        if len(hit) > 1:
            bad.append(f'VREF: branches {hit} share copper ({sorted(pc)[:6]})')
    return (not bad, '; '.join(bad[:4]) or f'VREF: {len(groups)} branches each on its own copper')


# --------------------------------------------------------------------------------------------------- LR-9
def lr9(m):
    digital = {'/SDA', '/SCL'}
    on = defaultdict(set)
    for k, v in m.pads.items():
        on[v['net']].add(k[0])
    bad = []
    for s in m.segs:
        if s[0] in digital:
            for r in ANALOG_REFS:
                if r in on[s[0]] or r not in m.box:
                    continue
                if seg_in_box(s, m.box[r], ZONE_PAD):
                    bad.append(f'{s[0]} through {r}')
    return (not bad, '; '.join(sorted(set(bad))[:6]) or 'SDA / SCL outside every analog courtyard but their own parts')


# --------------------------------------------------------------------------------------------------- LR-10
def lr10(m):
    out = os.path.join(tempfile.mkdtemp(prefix='afe2-drc-'), 'drc.json')
    subprocess.run(['kicad-cli', 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', out, m.path], capture_output=True)
    d = json.load(open(out))
    vio = [v for v in d.get('violations', []) if not v.get('excluded')]
    kinds = defaultdict(int)
    for v in vio:
        kinds[v['type']] += 1
    un = len(d.get('unconnected_items', []))
    return (not vio and not un, f'DRC {dict(kinds) or "clean"}; unconnected {un}')


# --------------------------------------------------------------------------------------------------- LR-11
def lr11(m):
    bad = []
    blocks = defaultdict(set)
    for r, b in m.block.items():
        if b != 'EDGE' or r in layout.BLOCK_OVERRIDE:
            blocks[b].add(r)
    blocks.pop('EDGE', None)
    for b, rects in layout.OUTLINE.items():
        inside = {r for r in m.pos if r in m.block and m.block[r] != 'EDGE' or r in layout.BLOCK_OVERRIDE
                  if any(in_box(m.pos[r], rc) for rc in rects)}
        want = blocks.get(b, set())
        if inside != want:
            bad.append(f'{b}: outline holds {sorted(inside - want)[:5]} extra, lacks {sorted(want - inside)[:5]}')
    def block_of(r):
        b = m.block.get(r)
        if b is None:       # a part design.py does not list (a bridge): the outline that holds it
            b = next((k for k, rcs in layout.OUTLINE.items() if any(in_box(m.pos[r], rc) for rc in rcs)), None)
        return b
    for r in m.fps:
        digits = ''.join(c for c in r if c.isdigit())
        want, b = BLOCK_HUNDREDS.get(digits[:1]) if len(digits) >= 3 else None, block_of(r)
        if want != b:
            bad.append(f'{r}: designator number says {want}, the part is in {b}')
    have = {block_of(r) for r in m.fps if r.startswith('TP') and (r, '1') in m.pads}
    for b in sorted({'CH1', 'CH2', 'AWG', 'POWER', 'REFCAL'} - have):
        bad.append(f'block {b} has no test point')
    for r, (pos, h, vis) in m.refs.items():
        if not vis or h < 0.79:
            bad.append(f'{r}: designator not on silk at 0.8 mm or more')
    tp = {'TP101': '/A1', 'TP201': '/A0', 'TP301': '/AWG_VO', 'TP401': '/+3V3A', 'TP402': '/VNEG', 'TP403': '/+5V_F',
          'TP404': '/GND', 'TP501': '/VREF'}
    for r, n in tp.items():
        if (r, '1') not in m.pads or m.pads[(r, '1')]['net'] != n:
            bad.append(f'{r}: missing or not on {n}')
    names = {t for t, _, _ in m.silk}
    for w in ('CH1', 'CH2', 'AWG', 'POWER', 'REF / CAL', 'CAL', 'ON'):
        if w not in names:
            bad.append(f'silk word {w!r} missing')
    return (not bad, '; '.join(bad[:6]) or f'{len(layout.OUTLINE)} outlines hold exactly their parts, {len(m.refs)} designators, 8 test points')


ROWS = [('LR-1', lr1), ('LR-2', lr2), ('LR-3', lr3), ('LR-4', lr4), ('LR-4 INV_MAX', lr4_inv), ('LR-12 DECOUP_MAX', lr12), ('LR-5', lr5), ('LR-6', lr6), ('LR-7', lr7),
        ('LR-8', lr8), ('LR-9', lr9), ('LR-10', lr10), ('LR-11', lr11)]


# --------------------------------------------------------------------------------------------------- the broken arms
def first_seg(m, net):
    return [s for s in m.segs if s[0] == net][0]


def mut1(m):
    c = m.pos['U101']
    m.segs.append(('/CH1_N', 'B', (c[0] - 1, c[1]), (c[0] + 1, c[1]), 0.2))


def mut2(m):
    m.pos['R107'] = (m.pos['U101'][0] - 5, m.pos['R107'][1])


def mut3(m):
    m.vias.append(('/CH1_N', m.pads[('R102', '2')]['c']))


def mut4(m):
    m.vias.append(('/A0', first_seg(m, '/A0')[2]))


def mut4b(m):
    p = m.pads[('R303', '2')]['c']
    m.extra_top_gnd.append((p[0] + 0.3, p[1]))


def mut5(m):
    c = m.pos['U401']
    m.segs.append(('/VREF', 'F', (c[0] + 4, c[1] + 4), (c[0] + 4, c[1] + 6), 0.2))


def mut6(m):
    m.segs.append(('/+3V3A', 'F', m.pads[('U101', '8')]['c'], m.pads[('U301', '8')]['c'], 0.2))
    m.pads[('U101', '8')]['net'] = '/+3V3A'
    m.pads[('C104', '1')]['net'] = '/+3V3A'


def mut7(m):
    m.segs.append(('/DAC0', 'F', (30.0, 30.0), (60.0, 30.0), 0.2))


def mut8(m):
    m.segs.append(('/VREF', 'F', m.pads[('R506', '2')]['c'], m.pads[('U502', '4')]['c'], 0.2))


def mut9(m):
    c = m.pos['U101']
    m.segs.append(('/SDA', 'F', (c[0] - 2, c[1]), (c[0] + 2, c[1]), 0.2))


def mut11(m):
    m.pos['R201'] = (30.0, 40.0)          # well outside every outline


def mut11b(m):
    r = next(iter(m.refs))
    m.refs[r] = (m.refs[r][0], 0.5, False)


def mut11c(m):
    del m.pads[('TP301', '1')]


def mut1i(m):                       # the via of a non-exempt ground pad (R407.2, the PR-3 bleed) removed: must fail
    c = m.pads[('R407', '2')]['c']
    i = min(range(len(m.vias)), key=lambda j: math.dist(m.vias[j][1], c) if m.vias[j][0] == '/GND' else 1e9)
    del m.vias[i]


def mut1b(m):                       # a 4 mm hop on a free net, clear of every fence
    m.segs.append(('/SCL', 'B', (4.0, 40.0), (8.0, 40.0), 0.2))


def mut1c(m):                       # a short bottom track under A0, in the open
    t = first_seg(m, '/A0')
    c = ((t[2][0] + t[3][0]) / 2, (t[2][1] + t[3][1]) / 2)
    m.segs.append(('/SCL', 'B', (c[0] - 0.5, c[1]), (c[0] + 0.5, c[1]), 0.2))


def mut1f(m):                       # SCL hopping under AREF (the Due's ADC reference): refused, a crossing is a top bridge
    t = first_seg(m, '/AREF')
    c = ((t[2][0] + t[3][0]) / 2, (t[2][1] + t[3][1]) / 2)
    m.segs.append(('/SCL', 'B', (c[0] - 0.5, c[1]), (c[0] + 0.5, c[1]), 0.2))
    m.segs.append(('/SCL', 'B', (c[0], c[1] - 0.5), (c[0], c[1] + 0.5), 0.2))


def mut1g(m):                       # any other net under AREF
    t = first_seg(m, '/AREF')
    c = ((t[2][0] + t[3][0]) / 2, (t[2][1] + t[3][1]) / 2)
    m.segs.append(('/+3V3A', 'B', (c[0] - 0.5, c[1]), (c[0] + 0.5, c[1]), 0.2))
    m.segs.append(('/+3V3A', 'B', (c[0], c[1] - 0.5), (c[0], c[1] + 0.5), 0.2))


def mut1d(m):                       # a 1 mm bottom track on a free net inside the AWG fence
    r = layout.OUTLINE['AWG'][1]
    m.segs.append(('/SCL', 'B', (r[0] + 1, r[1] + 1), (r[0] + 2, r[1] + 1), 0.2))


def mut1e(m):                       # a 1 mm bottom track under the AWG inverting node's pad
    p = m.pads[('R303', '2')]['c']
    m.segs.append(('/SCL', 'B', (p[0] - 0.5, p[1]), (p[0] + 0.5, p[1]), 0.2))


def mut4c(m):
    m.vias.append(('/AWG_FB', m.pads[('R303', '2')]['c']))


def mut4d(m):
    m.segs.append(('/CH1_N', 'B', (3.0, 3.0), (4.0, 3.0), 0.2))


def mut4e(m):                       # a 6 mm detour on the AWG inverting node (and on each follower node)
    for n in INV_NODES:
        p = first_seg(m, n)[2]
        m.segs.append((n, 'F', p, (p[0] + 6.0, p[1]), 0.2))


def mut12(m):                       # every decoupling cap moved 5 mm from its pin
    for cap in DECOUP:
        c = m.pads[(cap, '1')]['c']
        m.pads[(cap, '1')]['c'] = (c[0] + 5.0, c[1])
        c = m.pads[(cap, '2')]['c']
        m.pads[(cap, '2')]['c'] = (c[0] + 5.0, c[1])


def mut12b(m):                      # one cap only (C305, the awg V+ cap) moved 5 mm
    for k in ('1', '2'):
        c = m.pads[('C305', k)]['c']
        m.pads[('C305', k)]['c'] = (c[0], c[1] + 5.0)


def mut11d(m):                      # a CH1 part numbered 399: its hundreds digit says AWG
    m.fps['R399'], m.pos['R399'], m.block['R399'], m.refs['R399'] = m.fps['R101'], m.pos['R101'], 'CH1', m.refs['R101']


def mut11e(m):
    for r in [r for r in m.fps if r.startswith('TP') and m.block.get(r) == 'REFCAL']:
        del m.pads[(r, '1')]


ARMS = [('LR-1', lr1, mut1), ('LR-1 4 mm hop', lr1, mut1b), ('LR-1 under A0', lr1, mut1c), ('LR-1 SCL under AREF', lr1, mut1f), ('LR-1 +3V3A under AREF', lr1, mut1g),
        ('LR-1 inside AWG fence', lr1, mut1d), ('LR-1 ground via removed (R407.2)', lr1, mut1i), ('LR-1 under FB pad', lr1, mut1e),
        ('LR-4 via on AWG FB', lr4, mut4c), ('LR-4 bottom copper on CH1_N', lr4, mut4d), ('LR-2', lr2, mut2), ('LR-3', lr3, mut3), ('LR-4 via in A0', lr4, mut4),
        ('LR-4 pour near FB', lr4, mut4b), ('LR-4 INV_MAX: 6 mm detour on each node', lr4_inv, mut4e),
        ('LR-12 all caps 5 mm away', lr12, mut12), ('LR-12 C305 5 mm away', lr12, mut12b), ('LR-5', lr5, mut5), ('LR-6', lr6, mut6), ('LR-7', lr7, mut7),
        ('LR-8', lr8, mut8), ('LR-9', lr9, mut9), ('LR-11 part out of its outline', lr11, mut11),
        ('LR-11 missing designator', lr11, mut11b), ('LR-11 missing test point', lr11, mut11c),
        ('LR-11 wrong-numbered designator', lr11, mut11d), ('LR-11 block without a TP', lr11, mut11e)]


def lr10_arm(path):
    b = pcb.LoadBoard(path)
    t = pcb.PCB_TRACK(b)
    p = b.FindFootprintByReference('R101').Pads()[0].GetPosition()
    t.SetStart(pcb.VECTOR2I(p.x, p.y + pcb.FromMM(1.0)))
    t.SetEnd(pcb.VECTOR2I(p.x + pcb.FromMM(3.0), p.y + pcb.FromMM(1.0)))
    t.SetWidth(pcb.FromMM(0.1)); t.SetLayer(pcb.F_Cu); t.SetNet(b.FindNet('/CH1_N'))
    b.Add(t)
    tmp = os.path.join(tempfile.mkdtemp(prefix='afe2-mut-'), 'afe-v2.kicad_pcb')
    b.Save(tmp)
    shutil.copy(os.path.join(HERE, 'afe-v2.kicad_pro'), tmp.replace('.kicad_pcb', '.kicad_pro'))
    return tmp


def main(argv):
    mutate = '--mutate' in argv
    args = [a for a in argv if not a.startswith('--')]
    path = args[0] if args else BOARD
    m = load(path)
    fails = []
    if not mutate:
        for name, fn in ROWS:
            ok, d = fn(m)
            print(f'[{"PASS" if ok else "FAIL"}] {name}: {d}', flush=True)
            if not ok:
                fails.append(name)
        print('ALL PASS' if not fails else 'FAIL: ' + ', '.join(fails))
        return 1 if fails else 0
    for name, fn, mut in ARMS:
        mm_ = load(path)
        ok0, _ = fn(mm_)
        mut(mm_)
        ok, d = fn(mm_)
        print(f'[{"FAILED AS REQUIRED" if not ok else "NOT CAUGHT"}] {name} (clean board: {"pass" if ok0 else "fail"}): {d}', flush=True)
        if ok:
            fails.append(name)
    ok, d = lr10(load(lr10_arm(path)))
    print(f'[{"FAILED AS REQUIRED" if not ok else "NOT CAUGHT"}] LR-10 (a 0.1 mm track added): {d}')
    if ok:
        fails.append('LR-10')
    print('every arm caught' if not fails else 'NOT CAUGHT: ' + ', '.join(fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
