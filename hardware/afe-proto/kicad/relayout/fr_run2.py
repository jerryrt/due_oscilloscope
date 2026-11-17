"""fr_run2.py MODE BOARD OUT [PASSES] [TIMEOUT]   MODE = S (strict: one layer) or R (relief what-if: B.Cu for supply, P33_R and I2C nets).
The pre-routed nets that are COMPLETE are kept out of Freerouting's network: their copper goes into the DSN as F.Cu keep-out shapes (hi-Z wider, so the 0.6 mm
class clearance holds), so the router cannot touch or reroute them. Incomplete pre-routes are dropped and the net is routed by Freerouting from scratch."""
import sys, os, re, math, subprocess
sys.path.append('/usr/lib/python3/dist-packages'); sys.path.insert(0, '.')
import numpy as np
import pcbnew
from pcbtools import boardio, rules
from pcbtools.boards import v1 as C
mode, board, out = sys.argv[1], sys.argv[2], sys.argv[3]
PASSES = sys.argv[4] if len(sys.argv) > 4 else '40'; TMO = sys.argv[5] if len(sys.argv) > 5 else '1800'
W = 'whatif/_scratch/fr'; mm = pcbnew.ToMM
RELIEF = {'/+5V_F', '/+3V3A', '/VNEG', '/P33_R', '/SCL1', '/SCL1_A', '/SDA1', '/SDA1_A'}
bd = boardio.read_board(board)
# 1. which pre-routed nets are complete
tracked = {bd.nets[int(bd.s_net[k])] for k in range(len(bd.s_idx))}
locked = {'/GND'}
for n in sorted(tracked - {'/GND'}):
    pcs = [p for p in rules.pieces_keys(bd, C, n) if p]
    if len(pcs) <= 1: locked.add(n)
print('LOCKED nets', len(locked) - 1, 'partial (dropped, routed by Freerouting):', sorted(tracked - locked))
b = pcbnew.LoadBoard(board)
tr0 = list(b.GetTracks())
keep_items = [t for t in tr0 if t.GetNetname() in locked]
for t in tr0:
    if t.GetNetname() not in locked: b.RemoveNative(t)
pcbnew.ExportSpecctraDSN(b, W + '/inS.dsn')
t = open(W + '/inS.dsn').read()
U = lambda v: int(round(v * 1000)); X = lambda x: U(x + 50.0); Y = lambda y: U(y - 150.0)
HZ = set(C.HIZ) | {'/A0', '/A1', '/AWG_INV'}
# 2. remove locked nets from the network and from the classes; empty the wiring
for n in locked:
    t = re.sub(r'\n    \(net (?:"%s"|%s)\n.*?\n    \)' % (re.escape(n), re.escape(n)), '', t, flags=re.S)
i = t.index('  (wiring'); t = t[:i] + '  (wiring\n  )\n)\n'
# 3. keep-outs: locked copper, fences/courtyards on B.Cu
ko = ''
def kpath(a, c, w): return '    (keepout "" (path F.Cu %d %d %d %d %d))\n' % (U(w), U(mm(a.x)), -U(mm(a.y)) if False else U(mm(a.y)) * 1, U(mm(c.x)), U(mm(c.y)))
for tk in keep_items:
    if tk.GetClass() == 'PCB_VIA':
        p = tk.GetPosition(); d = U(mm(tk.GetWidth(pcbnew.F_Cu)))
        for L_ in ('F.Cu', 'B.Cu'): ko += '    (keepout "" (circle %s %d %d %d))\n' % (L_, d, U(mm(p.x)), -U(mm(p.y)))
    elif tk.GetLayer() == pcbnew.F_Cu:
        w = mm(tk.GetWidth()) + (0.8 if tk.GetNetname() in HZ else 0.0)
        a, c = tk.GetStart(), tk.GetEnd()
        ko += '    (keepout "" (path F.Cu %d %d %d %d %d))\n' % (U(w), U(mm(a.x)), -U(mm(a.y)), U(mm(c.x)), -U(mm(c.y)))
def rect(x0, y0, x1, y1):
    xa, xb = sorted((X(x0), X(x1))); ya, yb = sorted((Y(y0), Y(y1)))
    return '    (keepout "" (rect B.Cu %d %d %d %d))\n' % (xa, ya, xb, yb)
if mode == 'S':
    ko += '    (keepout "" (rect B.Cu %d %d %d %d))\n' % (X(10), Y(-10), X(125), Y(60))
else:
    for k in range(len(bd.fp_ref)):
        if bd.fp_ref[k] in C.ANALOG_REFS and not np.isnan(bd.fp_cx0[k]):
            ko += rect(bd.fp_cx0[k] - 0.45, bd.fp_cy0[k] - 0.45, bd.fp_cx1[k] + 0.45, bd.fp_cy1[k] + 0.45)
t = t.replace('    (via "', ko + '    (via "', 1)
t = t.replace('      (clearance 50 (type smd_smd))\n', '')
# 4. classes
m = re.search(r'\(class kicad_default(.*?)\n      \(circuit', t, re.S); body = m.group(1)
names = [n for n in bd.nets if n and n not in locked]
hiz = [n for n in names if n in HZ]
quiet = [n for n in names if n.startswith(tuple(C.SENSITIVE)) and n not in HZ] + [n for n in ('/AWG_S', '/AWG_I', '/AWG_BIN', '/AWG_X', '/AWG_BPL', '/AWG_SP', '/CH1_IN', '/CH2_IN', '/DAC0') if n in names]
quiet = sorted(set(quiet) - set(hiz))
relief = [n for n in names if n in RELIEF] if mode == 'R' else []
for n in hiz + quiet + relief + sorted(locked): body = re.sub(r'(?<![\\w/])%s(?=\s)' % re.escape(n), '', body)
default = '(class kicad_default' + body + '\n      (circuit\n        (use_layer F.Cu)\n      )\n      (rule\n        (width 200)\n        (clearance 200)\n      )\n    )\n'
def cls(nm, nets, lay, cl): return '    (class %s %s\n      (circuit\n        %s\n      )\n      (rule\n        (width 200)\n        (clearance %d)\n      )\n    )\n' % (nm, ' '.join(nets), lay, cl)
extra = cls('hiz', hiz, '(use_layer F.Cu)', 600) + cls('quiet', quiet, '(use_layer F.Cu)', 200)
if relief: extra += cls('relief', relief, '(use_via "Via[0-1]_600:300_um")', 200)
i = t.index('    (class kicad_default'); j = t.index('  (wiring'); end_net = t.rindex('\n  )\n', i, j) + 1
t = t[:i] + '    ' + default.lstrip() + extra + t[end_net:]
open(W + '/inS_rules.dsn', 'w').write(t)
r = subprocess.run(['/work/docker/pcb/freeroute.sh', W + '/inS_rules.dsn', W + '/outS.ses', '--passes', PASSES, '--timeout', TMO], capture_output=True, text=True)
print('FREEROUTING exit', r.returncode)
ok = pcbnew.ImportSpecctraSES(b, os.path.abspath(W + '/outS.ses')); print('import', ok)
# the importer replaces the board's copper with the SES: put the locked pre-route copper back from a fresh load, and prove it
b0 = pcbnew.LoadBoard(board)
for t_ in [x for x in b.GetTracks() if x.GetNetname() in locked]: b.RemoveNative(t_)
nk = 0
for t_ in b0.GetTracks():
    if t_.GetNetname() in locked:
        d_ = t_.Duplicate(); d_.SetNet(b.FindNet(t_.GetNetname())); b.Add(d_); nk += 1
print('LOCKED copper re-inserted', nk, 'items; on the board:', len([x for x in b.GetTracks() if x.GetNetname() in locked]))
# 5. post: width floor, stubs, bottom runs
padbox = []
for fp in b.GetFootprints():
    for pd in fp.Pads():
        bb = pd.GetBoundingBox(); padbox.append((pd.GetNetname(), mm(bb.GetX()) - 0.02, mm(bb.GetY()) - 0.02, mm(bb.GetRight()) + 0.02, mm(bb.GetBottom()) + 0.02))
def on_pad(n, p): return any(n == q[0] and q[1] <= p[0] <= q[3] and q[2] <= p[1] <= q[4] for q in padbox)
new = [t_ for t_ in b.GetTracks() if t_.GetNetname() not in locked]
narrow = [t_ for t_ in new if t_.GetClass() != 'PCB_VIA' and mm(t_.GetWidth()) < 0.199]
for t_ in narrow: b.RemoveNative(t_)
print('POST narrow removed', len(narrow))
# bottom runs (mode R): connected bottom copper per net through vias; rip any run > 3 mm or with > 2 vias
bot_rip = 0; bot_len = 0.0; stats = {}
if mode == 'R':
    allt = [t_ for t_ in b.GetTracks() if t_.GetNetname() not in locked]
    bots = [t_ for t_ in allt if t_.GetClass() != 'PCB_VIA' and t_.GetLayer() == pcbnew.B_Cu]
    vias_ = [t_ for t_ in allt if t_.GetClass() == 'PCB_VIA']
    by = {}
    for t_ in bots: by.setdefault(t_.GetNetname(), []).append(t_)
    for n, lst in by.items():
        runs = []; used = set()
        for t_ in lst:
            if id(t_) in used: continue
            run = [t_]; used.add(id(t_)); changed = True
            while changed:
                changed = False
                for o in lst:
                    if id(o) in used: continue
                    pts = {(round(mm(p.x), 2), round(mm(p.y), 2)) for q in run for p in (q.GetStart(), q.GetEnd())}
                    if any((round(mm(p.x), 2), round(mm(p.y), 2)) in pts for p in (o.GetStart(), o.GetEnd())): run.append(o); used.add(id(o)); changed = True
            runs.append(run)
        for run in runs:
            L = sum(math.hypot(mm(q.GetEnd().x - q.GetStart().x), mm(q.GetEnd().y - q.GetStart().y)) for q in run)
            pts = {(round(mm(p.x), 2), round(mm(p.y), 2)) for q in run for p in (q.GetStart(), q.GetEnd())}
            nv = [v for v in vias_ if v.GetNetname() == n and (round(mm(v.GetPosition().x), 2), round(mm(v.GetPosition().y), 2)) in pts]
            if L > 3.0 or len(nv) > 2:
                for q in run: b.RemoveNative(q)
                for v in nv: b.RemoveNative(v)
                bot_rip += 1
            else:
                bot_len += L
                for q in run:
                    a, c = q.GetStart(), q.GetEnd(); mx, my = mm((a.x + c.x) // 2), mm((a.y + c.y) // 2)
                    for blk in ('AWG', 'REFCAL', 'SCOPE'):
                        for (x0, y0, x1, y1) in C.OUTLINE[blk]:
                            if x0 <= mx - 50 <= x1 and y0 <= 150 - my <= y1:
                                stats[blk] = stats.get(blk, 0.0) + math.hypot(mm(c.x - a.x), mm(c.y - a.y))
    print('BOTTOM runs ripped (>3 mm or >2 vias):', bot_rip, 'kept bottom copper mm:', round(bot_len, 1), 'inside fences (mm):', {k: round(v, 1) for k, v in stats.items()})
pcbnew.SaveBoard(out, b); print('saved', out)
