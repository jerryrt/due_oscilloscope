"""The layout rules of docs/afe.md section 11.1 (LR-1 .. LR-10) that a program can decide, checked on the board.

    /usr/bin/python3.14 -I lr_check.py [board.kicad_pcb]        exit 0 only if every rule passes

What each check reads, so a pass is not mistaken for more than it is:
  LR-1  every bottom-layer track that is not GND: none may touch an analog part's courtyard (blocks ch1, ch2, vmid,
        awg, cal, inflated by ZONE_PAD), and each connected bottom run must be a short hop (<= HOP_MAX).
  LR-4  A0 and A1: no via and no bottom-layer copper; their lengths are printed for the capacitance budget.
  LR-5  no copper of a sensitive net (ADC lines, reference, ladder taps, sense and the channels' high-impedance
        side) within KEEPOUT of the rail generator's or its flying capacitor's courtyard.
  LR-6  each rail's copper, with the star point's pads taken out, falls apart into pieces that each serve one block.
  LR-8  VREF's copper, with the reference's output pad taken out, falls apart into one piece per named branch.
  LR-9  no copper of a Due digital net touches an analog part's courtyard other than the parts on that net.
LR-2, LR-3, LR-7 and the judgement parts of the others are reviewed by eye (VT-19's table); LR-10 is the DRC's.
"""
import math
import os
import sys
from collections import defaultdict

sys.path.append('/usr/lib/python3/dist-packages')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pcbnew as pcb  # noqa: E402
import design  # noqa: E402

BOARD = os.path.join(HERE, 'afe-proto.kicad_pcb')
ANALOG = ('ch1', 'ch2', 'vmid', 'awg', 'cal')
ZONE_PAD = 0.3          # mm added round each analog courtyard (design value)
HOP_MAX = 5.0           # mm: the longest bottom-layer hop LR-1 calls "short" (design value)
KEEPOUT = 10.0          # mm, LR-5
GENERATOR = ('U7', 'C31')                       # LM27762 and its flying capacitor
STAR = {                                        # LR-6: rail -> the star point's pads (ref, pad)
    '/+3V3A': [('U7', '11'), ('C40', '1'), ('C41', '1')],       # OUT+ and its output capacitors
    '/VNEG': [('U7', '6'), ('C42', '1'), ('C43', '1')],         # OUT- and its output capacitors
}
KELVIN = {                                      # LR-8: net -> (source pad, branches as sets of refs)
    '/VREF': (('U8', '2'), [{'R50'}, {'U9', 'C26', 'C27'}, {'U12'}, {'R81'}, {'J5'}, {'TP6'}]),
}
SENSITIVE_PREFIX = ('/A0', '/A1', '/VREF', '/TAP', '/SNS', '/AWG_BNC')


def mm(v):
    return pcb.ToMM(v)


def due(p):
    return mm(p.x) - 50.0, 150.0 - mm(p.y)


class Box:
    def __init__(self, ref, bb, pad=0.0):
        self.ref = ref
        self.x0, self.x1 = mm(bb.GetLeft()) - pad, mm(bb.GetRight()) + pad
        self.y0, self.y1 = mm(bb.GetTop()) - pad, mm(bb.GetBottom()) + pad

    def hits_seg(self, a, b, w):
        """segment a-b of width w against the box, by sampling (0.05 mm), which is plenty at these sizes"""
        n = max(2, int(math.dist(a, b) / 0.05) + 1)
        for k in range(n + 1):
            x = a[0] + (b[0] - a[0]) * k / n
            y = a[1] + (b[1] - a[1]) * k / n
            if self.x0 - w / 2 <= x <= self.x1 + w / 2 and self.y0 - w / 2 <= y <= self.y1 + w / 2:
                return True
        return False

    def dist_seg(self, a, b):
        n = max(2, int(math.dist(a, b) / 0.1) + 1)
        best = 1e9
        for k in range(n + 1):
            x = a[0] + (b[0] - a[0]) * k / n
            y = a[1] + (b[1] - a[1]) * k / n
            dx = max(self.x0 - x, 0, x - self.x1)
            dy = max(self.y0 - y, 0, y - self.y1)
            best = min(best, math.hypot(dx, dy))
        return best


def load(path):
    b = pcb.LoadBoard(path)
    fps = {f.GetReference(): f for f in b.GetFootprints()}
    block = {p['ref']: p['block'] for p in design.PARTS}
    boxes = {}
    for r, f in fps.items():
        f.BuildCourtyardCaches()
        c = f.GetCourtyard(pcb.F_CrtYd).BBox()
        if c.GetWidth():
            boxes[r] = Box(r, c, ZONE_PAD)
    segs, vias = [], []
    for t in b.GetTracks():
        if t.GetClass() == 'PCB_VIA':
            vias.append((t.GetNetname(), (mm(t.GetPosition().x), mm(t.GetPosition().y)), mm(t.GetWidth(pcb.F_Cu)) / 2))
        else:
            segs.append((t.GetNetname(), t.GetLayer(), (mm(t.GetStart().x), mm(t.GetStart().y)),
                         (mm(t.GetEnd().x), mm(t.GetEnd().y)), mm(t.GetWidth())))
    pads = []
    for r, f in fps.items():
        for p in f.Pads():
            pads.append((r, p.GetNumber(), p.GetNetname(), p))
    return b, fps, block, boxes, segs, vias, pads


def copper_pieces(net, segs, vias, pads, cut=()):
    """Connected pieces of one net's copper (tracks, vias, pads), with the pads in `cut` removed.
    Returns a list of sets of (ref, pad) reached by each piece."""
    nodes = []          # (kind, data)
    for s in segs:
        if s[0] == net:
            nodes.append(('s', s))
    for v in vias:
        if v[0] == net:
            nodes.append(('v', v))
    padn = [(r, n, p) for r, n, nn, p in pads if nn == net and (r, n) not in cut]
    for r, n, p in padn:
        nodes.append(('p', (r, n, p)))
    parent = list(range(len(nodes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(i, j):
        parent[find(i)] = find(j)

    def ends(nd):
        k, d = nd
        if k == 's':
            return [(d[1], d[2]), (d[1], d[3])]
        if k == 'v':
            return [(pcb.F_Cu, d[1]), (pcb.B_Cu, d[1])]
        return []
    eps = 0.01
    for i, a in enumerate(nodes):
        for j in range(i + 1, len(nodes)):
            b = nodes[j]
            if a[0] == 'p' or b[0] == 'p':
                pnode, other = (a, b) if a[0] == 'p' else (b, a)
                if other[0] == 'p':
                    continue
                p = pnode[1][2]
                for L, pt in ends(other):
                    if p.IsOnLayer(L) and p.HitTest(pcb.VECTOR2I(pcb.FromMM(pt[0]), pcb.FromMM(pt[1]))):
                        join(i, j)
                        break
                continue
            hit = False
            for La, pa in ends(a):
                for Lb, pb in ends(b):
                    if La == Lb and math.dist(pa, pb) < eps:
                        hit = True
            if hit:
                join(i, j)
    groups = defaultdict(set)
    for i, nd in enumerate(nodes):
        if nd[0] == 'p':
            groups[find(i)].add((nd[1][0], nd[1][1]))
        else:
            groups[find(i)]
    return [g for g in groups.values()]


def main(path):
    b, fps, block, boxes, segs, vias, pads = load(path)
    analog = {r: bx for r, bx in boxes.items() if block.get(r) in ANALOG}
    netrefs = defaultdict(set)
    for r, n, nn, p in pads:
        netrefs[nn].add(r)
    fails = []

    def check(name, bad, ok_detail, limit=8):
        print(f'[{"PASS" if not bad else "FAIL"}] {name}: ' + (ok_detail if not bad else f'{len(bad)} found'))
        for x in bad[:limit]:
            print('      ', x)
        if bad:
            fails.append(name)

    # LR-1
    bsegs = [s for s in segs if s[1] == pcb.B_Cu and s[0] != '/GND']
    under = []
    for s in bsegs:
        for r, bx in analog.items():
            if bx.hits_seg(s[2], s[3], s[4]):
                under.append(f'{s[0]} bottom track at {tuple(round(v, 2) for v in due(pcb.VECTOR2I(pcb.FromMM(s[2][0]), pcb.FromMM(s[2][1]))))} under {r} ({block[r]})')
                break
    check('LR-1 no bottom track under an analog part', under, f'{len(bsegs)} bottom tracks, none under one')
    # bottom runs: chain the bottom segments of a net by shared end points
    runs = []
    bynet = defaultdict(list)
    for s in bsegs:
        bynet[s[0]].append(s)
    for net, ss in bynet.items():
        seen = [False] * len(ss)
        for i in range(len(ss)):
            if seen[i]:
                continue
            stack, length, seen[i] = [i], 0.0, True
            while stack:
                k = stack.pop()
                length += math.dist(ss[k][2], ss[k][3])
                for j in range(len(ss)):
                    if not seen[j] and any(math.dist(p, q) < 0.01 for p in ss[k][2:4] for q in ss[j][2:4]):
                        seen[j] = True
                        stack.append(j)
            if length > HOP_MAX:
                runs.append(f'{net}: a {length:.1f} mm bottom run')
    check(f'LR-1 every bottom run a short hop (<= {HOP_MAX} mm)', runs, 'all short')

    # LR-4
    bad, lens = [], {}
    for net in ('/A0', '/A1'):
        nv = [v for v in vias if v[0] == net]
        nb = [s for s in segs if s[0] == net and s[1] == pcb.B_Cu]
        if nv:
            bad.append(f'{net}: {len(nv)} via(s)')
        if nb:
            bad.append(f'{net}: {len(nb)} bottom segment(s)')
        lens[net] = sum(math.dist(s[2], s[3]) for s in segs if s[0] == net)
    check('LR-4 A0/A1 on top only, no via', bad, ', '.join(f'{k} {v:.1f} mm' for k, v in lens.items()))

    # LR-5
    gen = [boxes[r] for r in GENERATOR if r in boxes]
    near = []
    for s in segs:
        if s[0].startswith(SENSITIVE_PREFIX) or any(block.get(r) in ('ch1', 'ch2') for r in netrefs[s[0]]) \
                and not s[0].startswith(('/GND', '/+', '/VNEG', '/V+', '/V-')):
            d = min(g.dist_seg(s[2], s[3]) for g in gen)
            if d < KEEPOUT:
                near.append(f'{s[0]} {d:.1f} mm from the generator')
    check(f'LR-5 sensitive copper >= {KEEPOUT} mm from {"/".join(GENERATOR)}', sorted(set(near)), 'clear')

    # every pad the LR-6 / LR-8 tables name must exist on its net, or those checks would pass on nothing
    have = {(r, n): nn for r, n, nn, p in pads}
    named = [(net, rp) for net, star in STAR.items() for rp in star] + [(net, src) for net, (src, _) in KELVIN.items()]
    missing = [f'{rp[0]}.{rp[1]} is not on {net} (it is on {have.get(rp)})' for net, rp in named if have.get(rp) != net]
    check('LR-6/LR-8 tables name real pads', missing, f'{len(named)} pads found')

    # LR-6
    bad = []
    for net, star in STAR.items():
        pieces = copper_pieces(net, segs, vias, pads, cut=set(star))
        for g in pieces:
            blocks = {block.get(r) for r, n in g} - {'power', None}
            if len(blocks) > 1:
                bad.append(f'{net}: one piece of copper serves {sorted(blocks)}')
    check('LR-6 rails are stars from the generator', bad, ', '.join(STAR))

    # LR-8
    bad = []
    for net, (src, branches) in KELVIN.items():
        pieces = copper_pieces(net, segs, vias, pads, cut={src})
        for g in pieces:
            refs = {r for r, n in g}
            hit = [k for k, br in enumerate(branches) if refs & br]
            if len(hit) > 1:
                bad.append(f'{net}: branches {[sorted(branches[k]) for k in hit]} share copper')
    check('LR-8 the reference is Kelvin-routed', bad, ', '.join(KELVIN))

    # LR-9
    digital = sorted({nn for r, n, nn, p in pads if r in ('J7', 'J8', 'J9', 'J10') and nn
                      and not nn.startswith(('/GND', '/+', '/AREF', 'unconnected'))})
    bad = []
    for s in segs:
        if s[0] not in digital:
            continue
        for r, bx in analog.items():
            if r in netrefs[s[0]]:
                continue
            if bx.hits_seg(s[2], s[3], s[4]):
                bad.append(f'{s[0]} crosses {r} ({block[r]})')
                break
    check(f'LR-9 digital lines ({", ".join(d.lstrip("/") for d in digital)}) off the analog parts', sorted(set(bad)),
          'clear', limit=12)

    print('ALL PASS' if not fails else f'FAIL: {", ".join(fails)}')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else BOARD))
