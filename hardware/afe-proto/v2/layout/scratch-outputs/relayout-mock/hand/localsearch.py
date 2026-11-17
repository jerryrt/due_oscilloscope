"""pf-in-the-loop local search over the placement of one cluster. In the image, cwd hand/:
    python3 localsearch.py BASE.kicad_pcb START.json OUT_TAG ROUNDS SECONDS SEED
BASE has the fixed copper (hi-Z, outputs, AWG_FB, A0/A1) and no GND copper; START.json {ref: [x, y, rot]} (Due mm) is the cluster's starting placement.
Moves: shift one part by 0.5 / 1 / 2 mm in x or y, turn a part 90 / 180 degrees, swap two parts of one footprint. A candidate must keep the hard
constraints (courtyards apart, lanes clear, LR-12 decoupling distances, LR-2 and LR-5 distances to the generator, the cluster's region) and is
scored by pf.py restricted to the cluster's nets (PF_ONLY): distinct_clusters x 10 + conflict_segments / 10. Accepted moves are logged in OUT_TAG_log.txt."""
import sys, json, random, re, subprocess, math, time, os
sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew
base, start, tag, rounds, secs, seed = sys.argv[1:7]
rounds, secs, seed = int(rounds), float(secs), int(seed)
random.seed(seed)
ONLY = r'^/(TAP|SNS|ADS|VREF|SDA|SCL|AREF|AWG_BNC|AWG_VREF)|3V3A#adc'
REGION = (44.6, 3.4, 65.0, 42.0)               # Due mm: no part's courtyard leaves it (REF/CAL fence west, the A1 lane east)
LANES = [(65.3, 4.6, 66.8, 18.4), (67.9, 4.6, 69.3, 18.4)]
MOV = [r for r in 'C501 C502 C503 J501 R501 R502 R503 R504 R505 R506 R507 R508 R509 R510 R511 R512 R513 R514 TP501 U502 TP301 C303 C304 R305'.split()]
AWGW = ('TP301', 'C303', 'C304', 'R305')           # the AWG block's west spill sits in the REF/CAL region: it may move, within the AWG-side box
REGION_AWG = (44.6, 3.4, 92.0, 25.0)
if os.environ.get('MOVSET'):
    MOV = os.environ['MOVSET'].split(',')
mm = pcbnew.ToMM
cur = json.load(open(start))
log = open(tag + '_log.txt', 'a')
def setpos(text, pl):
    for ref, (x, y, rot) in pl.items():
        i = text.index('(property "Reference" "%s"' % ref); s = text.rfind('\n\t(footprint ', 0, i)
        m = re.compile(r'\(at ([\d.\-]+) ([\d.\-]+)(?: ([\d.\-]+))?\)').search(text, s)
        text = text[:m.start()] + '(at %.4f %.4f %g)' % (x + 50, 150 - y, rot) + text[m.end():]
    return text
BT = open(base).read()
def build(pl, out):
    open(out, 'w').write(setpos(BT, pl)); subprocess.run(['cp', base.replace('.kicad_pcb', '.kicad_pro'), out.replace('.kicad_pcb', '.kicad_pro')])
def courts(brd):
    b = pcbnew.LoadBoard(brd); d = {}
    for f in b.GetFootprints():
        try:
            bb = f.GetCourtyard(pcbnew.F_CrtYd).BBox()
        except Exception:
            bb = f.GetBoundingBox()
        d[f.GetReference()] = (mm(bb.GetX()) - 50, 150 - mm(bb.GetBottom()), mm(bb.GetRight()) - 50, 150 - mm(bb.GetY()))
    pads = {}
    for f in b.GetFootprints():
        for p in f.Pads():
            pads[(f.GetReference(), p.GetNumber())] = (mm(p.GetPosition().x) - 50, 150 - mm(p.GetPosition().y), p.GetNetname())
    return d, pads
def ov(a, c, m=0.05): return min(a[2], c[2]) - max(a[0], c[0]) > m and min(a[3], c[3]) - max(a[1], c[1]) > m
SENSP = ('/A0', '/A1', '/VREF', '/TAP', '/SNS', '/AWG_BNC', '/ADS_', '/CH1_N', '/CH2_N')
def violations(brd, moved):
    d, pads = courts(brd); v = []
    for r in moved:
        c = d[r]
        rg = REGION_AWG if r in AWGW else REGION
        if not (c[0] >= rg[0] and c[1] >= rg[1] and c[2] <= rg[2] and c[3] <= rg[3]): v.append('region ' + r)
        for l in LANES:
            if ov(c, l): v.append('lane ' + r)
        for o, c2 in d.items():
            if o != r and ov(c, c2): v.append('court %s/%s' % (r, o))
    for cap, ic, pin in (('C502', 'U501', '1'), ('C501', 'U501', '2'), ('C503', 'U502', '8')):
        a, b2 = pads[(cap, '1')], pads[(ic, pin)]
        dist = min(math.hypot(pads[(cap, k)][0] - b2[0], pads[(cap, k)][1] - b2[1]) for k in '12')
        if dist > 3.0: v.append('LR-12 %s %.1f' % (cap, dist))
    gen = [(p[0], p[1]) for k, p in pads.items() if k[0] in ('U401', 'C409')]
    for r in ('R501', 'R506', 'U501', 'U502'):
        for k, p in pads.items():
            if k[0] == r and min(math.hypot(p[0] - g[0], p[1] - g[1]) for g in gen) < 10.0: v.append('LR-2 ' + r); break
    for k, p in pads.items():
        if p[2].startswith(SENSP) and min(math.hypot(p[0] - g[0], p[1] - g[1]) for g in gen) < 10.0: v.append('LR-5 %s.%s' % k)
    return sorted(set(v))
def score(pl, tagn):
    brd = '%s_cand.kicad_pcb' % tag
    build(pl, brd)
    v = violations(brd, list(pl))
    if v: return 1e6 + 1000 * len(v), v
    env = dict(os.environ, PF_ONLY=ONLY, PF_NOGND='1')
    out = subprocess.run(['python3', '-u', 'pf.py', brd, '%s_cand_spec.py' % tag, str(rounds), '300'], capture_output=True, text=True, env=env).stdout
    m = re.search(r'METRIC conflict_segments (\d+) distinct_clusters (\d+)', out)
    if not m: return 2e6, ['pf failed']
    return int(m.group(2)) * 10 + int(m.group(1)) / 10.0, (int(m.group(1)), int(m.group(2)))
t0 = time.time()
best, info = score(cur, 'start')
print('start', best, info, file=log, flush=True)
n = 0
while time.time() - t0 < secs:
    cand = {k: list(v) for k, v in cur.items()}
    mv = random.choice(['shift', 'shift', 'shift', 'turn', 'swap', 'jump'])
    r = random.choice(MOV)
    if mv == 'jump' and r not in AWGW and random.random() < 0.6:
        mv = 'shift'
    if mv == 'shift':
        dx, dy = random.choice([(0.5, 0), (-0.5, 0), (0, 0.5), (0, -0.5), (1, 0), (-1, 0), (0, 1), (0, -1), (2, 0), (-2, 0), (0, 2), (0, -2)])
        cand[r][0] += dx; cand[r][1] += dy; desc = '%s shift %+g,%+g' % (r, dx, dy)
    elif mv == 'jump':
        rg = REGION_AWG if r in AWGW else REGION
        cand[r][0] = round(random.uniform(rg[0] + 1, rg[2] - 1), 1); cand[r][1] = round(random.uniform(rg[1] + 1, rg[3] - 1), 1)
        desc = '%s jump to %.1f,%.1f' % (r, cand[r][0], cand[r][1])
    elif mv == 'turn':
        a = random.choice([90, 180, 270]); cand[r][2] = (cand[r][2] + a) % 360; desc = '%s turn %d' % (r, a)
    else:
        same = [o for o in MOV if o != r and o[0] == r[0] and o[0] in 'RC' and ((o in AWGW) == (r in AWGW))]
        if not same: continue
        o = random.choice(same); cand[r], cand[o] = list(cur[o]), list(cur[r]); desc = 'swap %s %s' % (r, o)
    sc, inf = score(cand, 'c')
    n += 1
    if sc < best or (sc == best and best >= 1e6 and random.random() < 0.5):
        best, cur = sc, cand; json.dump(cur, open(tag + '_best.json', 'w'))
        print('accept', desc, best, inf, round(time.time() - t0), file=log, flush=True)
    else:
        print('reject', desc, inf if sc >= 1e6 else round(sc, 1), file=log, flush=True)
print('done', n, 'moves tried; best', best, file=log, flush=True)
