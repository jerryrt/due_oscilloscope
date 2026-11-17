"""python3 frroute2.py TAG BOARD S|R   (in the image, cwd /work). Freerouting with the locks outside its network and hops under LR-1.
Locked (never given to Freerouting; their copper goes in as F.Cu keep-outs, outline + clearance, 0.6 clearance for hi-Z): hi-Z dividers, CH1_OUT, CH2_OUT, AWG_FB, A0, A1,
and pf's star / Kelvin legs (+3V3A, VNEG, VREF) with the GND vias. Top only for every net but +5V_F, +5V_DUE, +3V3A, VNEG, SDA, SCL, AREF (hop candidates); LM_FBP, LM_FBN, LM_C1P, LM_C1N, LM_CP
stay on top. S: B.Cu keep-out over the analog fences (CH1, CH2, AWG outlines), hops elsewhere. R: no fence keep-out, supply and I2C nets may use B.Cu inside the fences too.
After the import: LOCKS EXACT (geometry diff of the locked copper), every bottom run checked (<= 3 mm, <= 2 vias, no fence unless R and an allowed net, not under XSENS copper or pads),
violating runs removed and counted as gaps; then zones filled, DRC, rows."""
import sys, os, re, json, math, subprocess, collections
sys.path.append('/usr/lib/python3/dist-packages'); sys.path.insert(0, '/work/hardware/afe-proto')
import pcbnew
T, BOARD, MODE = sys.argv[1], sys.argv[2], sys.argv[3]
H = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand/'
os.chdir(H)
mm = pcbnew.ToMM
def sh(c): return subprocess.run(c, shell=True, capture_output=True, text=True).stdout
HIZ = ['/CH1_N', '/CH1_M1', '/CH1_M2', '/CH1_M3', '/CH1_NP', '/CH2_N', '/CH2_M1', '/CH2_M2', '/CH2_M3', '/CH2_NP']
LOCK = set(HIZ + ['/CH1_OUT', '/CH2_OUT', '/AWG_FB', '/A0', '/A1', '/+3V3A', '/VNEG', '/VREF'])
HOPOK = {'/+5V_F', '/+5V_DUE', '/+3V3A', '/VNEG', '/SDA', '/SCL', '/AREF'}
TOP = {'/LM_FBP', '/LM_FBN', '/LM_C1P', '/LM_C1N', '/LM_CP'}
FENCE = [(62.4, 33.0, 74.9, 49.0), (74.9, 33.0, 80.1, 47.1), (80.1, 33.0, 92.25, 49.0), (58.0, 38.6, 62.4, 49.0), (69.0, 19.75, 92.25, 32.9), (69.5, 4.55, 92.25, 19.25)]    # CH1, CH2, AWG rectangles (the scratch outline table)
if os.environ.get('FENCETAB') == 'old':
    FENCE = [(62.4, 33.0, 74.9, 49.0), (74.9, 33.0, 80.1, 47.1), (80.1, 33.0, 92.25, 49.0), (58.0, 38.6, 62.4, 49.0), (69.0, 19.75, 92.25, 32.9), (59.0, 6.2, 62.2, 18.4), (62.2, 4.55, 80.55, 18.4), (80.55, 6.2, 85.0, 18.4), (85.0, 4.55, 92.25, 18.4), (70.4, 18.4, 92.25, 19.25), (59.0, 18.4, 65.0, 27.4)]
ALLFENCE = FENCE
FIXALLOW = {'/+5V_F', '/+3V3A', '/VNEG', '/SDA', '/SCL'}                 # R: bottom copper allowed inside the fences for these
# ---- 1. board with the fixed copper and pf's star legs
shell = 'cd /work/%s && cp %s %s_g0.kicad_pcb && cp S1.kicad_pro %s_g0.kicad_pro && python3 hr.py %s_g0.kicad_pcb %s_g1.kicad_pcb fixed_noGND.py > /dev/null && cp S1.kicad_pro %s_g1.kicad_pro' % ('hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand', BOARD, T, T, T, T, T)
sh(shell)
print(sh("PF_ONLY='^/(\\+3V3A|VNEG|VREF)' python3 -u pf.py %s_g1.kicad_pcb %s_k_spec.py 14 600 2>&1 | grep METRIC" % (T, T)).strip())
sh("python3 hr.py %s_g1.kicad_pcb %s_g2.kicad_pcb %s_k_spec.py > /dev/null; cp S1.kicad_pro %s_g2.kicad_pro" % (T, T, T, T))
d = json.load(open('S1.kicad_pro')); ns = d.setdefault('net_settings', {}); cl = ns.setdefault('classes', []); base = dict(cl[0]) if cl else {}
cl.append(dict(base, name='HIZ', clearance=0.6, track_width=0.2)); ns['netclass_patterns'] = [{'netclass': 'HIZ', 'pattern': n} for n in HIZ]
for c in cl: c['track_width'] = 0.2
json.dump(d, open(T + '_g2.kicad_pro', 'w'), indent=2)
b = pcbnew.LoadBoard(T + '_g2.kicad_pcb')
locked = []
for t in b.GetTracks():
    if t.GetNetname() in LOCK or t.GetNetname() == '/GND':
        if t.GetClass() == 'PCB_VIA': locked.append(('v', t.GetNetname(), t.GetPosition().x, t.GetPosition().y, t.GetWidth(pcbnew.F_Cu)))
        else: locked.append(('t', t.GetNetname(), t.GetStart().x, t.GetStart().y, t.GetEnd().x, t.GetEnd().y, t.GetWidth(), t.GetLayer()))
lockedset = collections.Counter((x[0], x[1], x[2], x[3], x[4], x[5]) if x[0] == 't' else (x[0], x[1], x[2], x[3]) for x in locked)
# ---- 2. DSN with the locks outside the network
print('DSN export', pcbnew.ExportSpecctraDSN(b, T + '.dsn'))
s = open(T + '.dsn').read()
def block_end(s, i):
    depth = 0
    for j in range(i, len(s)):
        if s[j] == '(': depth += 1
        elif s[j] == ')':
            depth -= 1
            if depth == 0: return j + 1
def drop_net_blocks(s, names):
    for n in names:
        for m in list(re.finditer(r'\n\s*\(net %s\n' % re.escape(n), s)):
            i = m.start() + 1; j = block_end(s, s.index('(', i)); s = s[:i] + s[j:]
        s = re.sub(r'(\(class [^\n]*?(?:\n[^()\n]*?)*?)\s%s(?=[\s)])' % re.escape(n), r'\1', s)
    return s
# wires of locked nets (the DSN wiring section) are dropped, and the nets leave the network and the classes
wiring = s.index('(wiring')
wend = block_end(s, wiring)
wtxt = s[wiring:wend]
for m in list(re.finditer(r'\n\s*\(wire\b', wtxt))[::-1]:
    i = m.start() + 1; j = block_end(wtxt, wtxt.index('(', i)); blk = wtxt[i:j]
    nm = re.search(r'\(net ([^\s)]+)', blk)
    if nm and nm.group(1).strip('"') in LOCK | {'/GND_never'}: wtxt = wtxt[:i] + wtxt[j:]
for m in list(re.finditer(r'\n\s*\(via\b[^\n]*', wtxt))[::-1]:
    if re.search(r'\(net ([^\s)]+)', wtxt[m.start():m.start() + 200]) and re.search(r'\(net ([^\s)]+)', wtxt[m.start():m.start() + 200]).group(1).strip('"') in LOCK | {'/GND'}: wtxt = wtxt[:m.start()] + wtxt[m.end():]
s = s[:wiring] + wtxt + s[wend:]
s = drop_net_blocks(s, sorted(LOCK))
# keep-outs: the locked copper on F.Cu, outline + clearance
ko = ''
um = lambda v: int(round(mm(v) * 1000))
for x in locked:
    if x[1] == '/GND' and x[0] != 'v': continue
    cle = 600 if x[1] in HIZ else 200
    if x[0] == 't' and x[7] == pcbnew.F_Cu:
        ko += '    (keepout "" (path F.Cu %d  %d %d  %d %d))\n' % (um(x[6]) + 2 * cle, um(x[2]), -um(x[3]), um(x[4]), -um(x[5]))
    elif x[0] == 'v':
        ko += '    (keepout "" (circle F.Cu %d %d %d))\n' % (um(x[4]) + 2 * cle, um(x[2]), -um(x[3]))
        ko += '    (keepout "" (circle B.Cu %d %d %d))\n' % (um(x[4]) + 2 * cle, um(x[2]), -um(x[3]))
WIN = [(24.0, 6.0, 40.0, 26.0), (42.0, 20.0, 58.0, 34.0)]           # where a bottom hop may start: the U401 cluster and the REF/CAL north crossings, both outside every fence
if MODE == 'R': WIN = WIN + FENCE                                       # what-if: the fences too (only the allowed nets can use B.Cu there: every other net is top-only)
def strips(win, X0=17.0, X1=117.0, Y0=-4.5, Y1=53.34, step=2.0):
    out = []; y = Y0
    while y < Y1:
        y2 = min(y + step, Y1); xs = sorted((max(w[0], X0), min(w[2], X1)) for w in win if w[1] < y2 and w[3] > y)
        x = X0
        for a_, b_ in xs:
            if a_ > x: out.append((x, y, a_, y2))
            x = max(x, b_)
        if x < X1: out.append((x, y, X1, y2))
        y = y2
    return out
for (x0, y0, x1, y1) in strips(WIN):
    X0, X1, Y0, Y1 = int((x0 + 50) * 1000), int((x1 + 50) * 1000), -int((150 - y0) * 1000), -int((150 - y1) * 1000)
    ko += '    (keepout "" (polygon B.Cu 0  %d %d %d %d %d %d %d %d %d %d))\n' % (X0, Y0, X1, Y0, X1, Y1, X0, Y1, X0, Y0)
i = s.index('    (via "Via')
s = s[:i] + ko + s[i:]
# top-only class: the nets that may not use B.Cu (circuit use_layer)
names = re.findall(r'\n\s*\(net ([^\s]+)\n', s)
topnets = [n for n in names if n.strip('"') not in HOPOK and n.strip('"') != '/GND']
topnets = [n for n in topnets] + [n for n in names if n.strip('"') in TOP and n not in topnets]
topnets = [n for n in dict.fromkeys(topnets) if n.strip('"') not in HOPOK]
for n in topnets:
    s = re.sub(r'(\(class kicad_default[^\n]*?(?:\n[^()\n]*?)*?)\s%s(?=[\s)])' % re.escape(n), r'\1', s)
cls = '    (class TOPONLY %s\n      (circuit (use_layer F.Cu))\n      (rule (width 200) (clearance 200))\n    )\n' % ' '.join(topnets)
i = s.index('(class kicad_default')
s = s[:i] + cls.lstrip() + '    ' + s[i:]
open(T + '.dsn', 'w').write(s)
print('locked nets', len(LOCK), 'keep-out shapes', ko.count('keepout'), 'top-only nets', len(topnets))
# ---- 3. Freerouting
sh('timeout 1500 bash /work/docker/pcb/freeroute.sh %s.dsn %s.ses --passes 20 --timeout 1200 > %s_fr.log 2>&1' % (T, T, T))
print('last pass:', sh('grep "Auto-routing pass" %s_fr.log | tail -1' % T).strip()[-110:])
b0 = pcbnew.LoadBoard(T + '_g2.kicad_pcb')
keep = [t.Duplicate() for t in b0.GetTracks() if t.GetNetname() in LOCK or t.GetNetname() == '/GND']
b = pcbnew.LoadBoard(T + '_g2.kicad_pcb')
print('SES import', pcbnew.ImportSpecctraSES(b, T + '.ses'))
for t in [t for t in b.GetTracks() if t.GetNetname() in LOCK or t.GetNetname() == '/GND']:
    b.Remove(t)
for t in keep:
    b.Add(t)
# ---- 4. LOCKS EXACT
now = collections.Counter()
for t in b.GetTracks():
    n = t.GetNetname()
    if n in LOCK or n == '/GND':
        if t.GetClass() == 'PCB_VIA': now[('v', n, t.GetPosition().x, t.GetPosition().y)] += 1
        else: now[('t', n, t.GetStart().x, t.GetStart().y, t.GetEnd().x, t.GetEnd().y)] += 1
lost = lockedset - now
extra = collections.Counter({k: v for k, v in now.items() if k not in lockedset})
print('  lost', list(lost.items())[:2], 'extra', list(extra.items())[:2])
print('LOCKS EXACT:', 'yes' if not lost and not extra else 'NO (%d locked items changed or missing, %d new on locked nets)' % (sum(lost.values()), sum(extra.values())))
# ---- 5. bottom runs
tr = [t for t in b.GetTracks()]
bot = [t for t in tr if t.GetClass() != 'PCB_VIA' and t.GetLayer() == pcbnew.B_Cu and t.GetNetname() != '/GND']
vias = [t for t in tr if t.GetClass() == 'PCB_VIA' and t.GetNetname() != '/GND']
par = {}
def f(a):
    while par.setdefault(a, a) != a: par[a] = par[par[a]]; a = par[a]
    return a
def key(p): return (round(mm(p.x), 2), round(mm(p.y), 2))
for t in bot:
    par[f(('s', id(t)))] = f(('p',) + key(t.GetStart())); par[f(('s', id(t)))] = f(('p',) + key(t.GetEnd()))
    f(('p',) + key(t.GetStart())); par[f(('p',) + key(t.GetStart()))] = f(('p',) + key(t.GetEnd()))
runs = collections.defaultdict(lambda: dict(L=0.0, v=0, segs=[], vias=[], net=None, pts=[]))
for t in bot:
    r = runs[f(('p',) + key(t.GetStart()))]; r['L'] += mm(t.GetLength()); r['segs'].append(t); r['net'] = t.GetNetname(); r['pts'] += [key(t.GetStart()), key(t.GetEnd())]
for v in vias:
    k = f(('p',) + key(v.GetPosition()))
    if k in runs: runs[k]['v'] += 1; runs[k]['vias'].append(v)
def in_fence(p, rects=ALLFENCE): return any(x0 <= p[0] - 50 <= x1 and y0 <= 150 - p[1] <= y1 for x0, y0, x1, y1 in rects)
XS = ('/A0', '/A1', '/VREF', '/TAP', '/SNS', '/AWG_BNC', '/ADS_', '/AWG_FB', '/AWG_BIN', '/CH1_N', '/CH2_N', '/CH1_M', '/CH2_M', '/CH1_IN', '/CH2_IN')
sens_items = [(t.GetStart(), t.GetEnd()) for t in tr if t.GetClass() != 'PCB_VIA' and t.GetLayer() == pcbnew.F_Cu and t.GetNetname().startswith(XS)]
def under(seg):
    a, c = seg
    for (p, q) in sens_items:
        d = min(math.hypot(mm(a.x - p.x), mm(a.y - p.y)), math.hypot(mm(c.x - q.x), mm(c.y - q.y)))
        if d < 0.5: return True
    return False
removed, fence_mm, kept_mm = [], collections.defaultdict(float), 0.0
for k, r in runs.items():
    n = r['net']; why = None
    infence = any(in_fence(p) for p in r['pts'])
    if n not in HOPOK: why = 'net not allowed on B.Cu'
    elif r['L'] > 3.0 or r['v'] > 2: why = 'run %.1f mm %d vias' % (r['L'], r['v'])
    elif infence and not (MODE == 'R' and n in FIXALLOW): why = 'inside an analog fence'
    elif any(under((s.GetStart(), s.GetEnd())) for s in r['segs']): why = 'under sensitive copper'
    if why:
        removed.append((n, why, round(r['L'], 1), r['v'], key(r['segs'][0].GetStart())))
        for s in r['segs'] + r['vias']: b.Remove(s)
    else:
        kept_mm += r['L']
        if infence: fence_mm[n] += r['L']
print('bottom runs kept: %d (%.1f mm); in fences: %s' % (len(runs) - len(removed), kept_mm, {k: round(v, 1) for k, v in fence_mm.items()}))
print('bottom runs ripped (counted as gaps): %d' % len(removed), collections.Counter(w for _, w, *_ in removed))
pcbnew.SaveBoard(T + '_r.kicad_pcb', b)
sh('cp %s_g2.kicad_pro %s_r.kicad_pro' % (T, T))
sh("python3 -c \"import sys; sys.path.insert(0,'/work/hardware/afe-proto'); from pcbtools.editor import edit\nwith edit('%s_r.kicad_pcb') as e: e.fill_zones()\"" % T)
sh('kicad-cli pcb drc --severity-all --format json -o %s_r_drc.json %s_r.kicad_pcb > /dev/null 2>&1' % (T, T))
dd = json.load(open(T + '_r_drc.json'))
print('DRC by type', dict(collections.Counter(v['type'] for v in dd['violations'])), 'unconnected', len(dd.get('unconnected_items', [])))
nets, where = collections.Counter(), collections.defaultdict(list)
for u in dd.get('unconnected_items', []):
    its = u['items']; nm = re.search(r'\[(/[^\]]+)\]', its[0]['description']); nm = nm.group(1) if nm else '?'
    nets[nm] += 1; where[nm].append((round(its[0]['pos']['x'] - 50, 1), round(150 - its[0]['pos']['y'], 1)))
print('UNROUTED by net', dict(nets))
blocks = {'POWER': (17.9, 4.6, 43.6, 37), 'REFCAL': (45.5, 4.6, 65.0, 27.8), 'AWG': (69.5, 4.55, 92.25, 19.25), 'CH2': (69.0, 19.75, 92.25, 32.9), 'CH1': (58.0, 33.0, 92.25, 49.0)}
pb = collections.Counter()
for n, pts in where.items():
    for p in pts:
        pb[next((k for k, (x0, y0, x1, y1) in blocks.items() if x0 <= p[0] <= x1 and y0 <= p[1] <= y1), 'other')] += 1
print('GAPS by block', dict(pb))
print('RIPPED', removed[:12])
