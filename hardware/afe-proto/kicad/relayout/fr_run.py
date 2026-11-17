"""fr_run.py BOARD OUTBOARD [PASSES] [TIMEOUT]: Freerouting on the board with the project's rules encoded in the DSN (run in the pcb image, cwd = hardware/afe-proto).
B.Cu keep-outs over every analog fence and every analog part's courtyard (LR-1), the hi-Z nets + A0/A1 + AWG_INV in a class with 0.6 mm clearance and
F.Cu only (LR-3 / LR-4: no via), the quiet-zone nets F.Cu only. Output: the imported board."""
import sys, os, re, subprocess
sys.path.append('/usr/lib/python3/dist-packages')
sys.path.insert(0, '.')
import pcbnew
from pcbtools import boardio
from pcbtools.boards import v1 as C
board, out = sys.argv[1], sys.argv[2]
PASSES = sys.argv[3] if len(sys.argv) > 3 else '30'
TMO = sys.argv[4] if len(sys.argv) > 4 else '1500'
W = 'whatif/_scratch/fr'
os.makedirs(W, exist_ok=True)
b = pcbnew.LoadBoard(board)
if os.environ.get('LOCK'):
    for t_ in b.GetTracks():
        t_.SetLocked(True)
pcbnew.ExportSpecctraDSN(b, W + '/in.dsn')
t = open(W + '/in.dsn').read()
bd = boardio.read_board(board)
U = lambda v: int(round(v * 1000))
X = lambda x: U(x + 50.0)
Y = lambda y: U(y - 150.0)
def rect(x0, y0, x1, y1):
    xa, xb = sorted((X(x0), X(x1))); ya, yb = sorted((Y(y0), Y(y1)))
    return '    (keepout "" (rect B.Cu %d %d %d %d))\n' % (xa, ya, xb, yb)
ko = ''
for blk in ('REFCAL', 'AWG', 'SCOPE'):
    for (x0, y0, x1, y1) in C.OUTLINE[blk]:
        ko += rect(x0 - 0.4, y0 - 0.4, x1 + 0.4, y1 + 0.4)
import numpy as np
for k in range(len(bd.fp_ref)):
    if bd.fp_ref[k] in C.ANALOG_REFS and not np.isnan(bd.fp_cx0[k]):
        ko += rect(bd.fp_cx0[k] - 0.45, bd.fp_cy0[k] - 0.45, bd.fp_cx1[k] + 0.45, bd.fp_cy1[k] + 0.45)
if os.environ.get('BOTNO'):       # strict LR-1: no signal copper on B.Cu at all (the GND vias and zone are added afterwards)
    ko = rect(-60, -60, 160, 160) if False else '    (keepout "" (rect B.Cu %d %d %d %d))\n' % (X(10), Y(-10), X(125), Y(60))
if os.environ.get('NOSMD'):
    t = t.replace('      (clearance 50 (type smd_smd))\n', '')
t = t.replace('    (via "', ko + '    (via "', 1)
# classes
hiz = list(C.HIZ) + ['/A0', '/A1', '/AWG_INV']
quiet = [n for n in bd.nets if n and n.startswith(tuple(C.SENSITIVE)) and n not in hiz]
quiet += [n for n in ('/AWG_S', '/AWG_I', '/AWG_BIN', '/AWG_X', '/AWG_BPL', '/AWG_SP', '/CH1_IN', '/CH2_IN', '/DAC0') if n in bd.nets]
quiet = sorted(set(quiet) - set(hiz))
m = re.search(r'\(class kicad_default(.*?)\n      \(circuit', t, re.S)
body = m.group(1)
for n in hiz + quiet:
    body = re.sub(r'(?<![\w/])%s(?=\s)' % re.escape(n), '', body)
default = '(class kicad_default' + body + '\n      (circuit\n        (use_via "Via[0-1]_600:300_um")\n      )\n      (rule\n        (width 200)\n        (clearance 200)\n      )\n    )\n'
cls = '    (class hiz ' + ' '.join(hiz) + '\n      (circuit\n        (use_layer F.Cu)\n      )\n      (rule\n        (width 200)\n        (clearance 600)\n      )\n    )\n'
cls += '    (class quiet ' + ' '.join(quiet) + '\n      (circuit\n        (use_layer F.Cu)\n      )\n      (rule\n        (width 200)\n        (clearance 200)\n      )\n    )\n'
i = t.index('    (class kicad_default'); j = t.index('  (wiring')
j = t.rindex('  )', i, j) if False else j
end_net = t.rindex('\n  )\n', i, j) + 1
t = t[:i] + '    ' + default.lstrip() + cls + t[end_net:]
open(W + '/in_rules.dsn', 'w').write(t)
r = subprocess.run(['/work/docker/pcb/freeroute.sh', W + '/in_rules.dsn', W + '/out.ses', '--passes', PASSES, '--timeout', TMO], capture_output=True, text=True)
print('FREEROUTING exit', r.returncode)
print((r.stdout + r.stderr)[-1500:])
if os.path.exists(W + '/out.ses'):
    if os.environ.get('STRIP'):          # the fixed wiring travels through the DSN and comes back in the SES: do not import it twice
        for t_ in list(b.GetTracks()):
            b.RemoveNative(t_)
    ok = pcbnew.ImportSpecctraSES(b, os.path.abspath(W + '/out.ses'))
    print('import', ok)
    nw = 0
    if os.environ.get('WIDEN'):
        for t_ in b.GetTracks():
            if t_.GetClass() != 'PCB_VIA' and pcbnew.ToMM(t_.GetWidth()) < 0.199:
                t_.SetWidth(pcbnew.FromMM(0.2)); nw += 1
    print('widened', nw)
    if os.environ.get('DEDUP'):          # identical copper twice (same net, layer, width, endpoints either way): drop one copy; nothing is extended or moved
        seen = {}; dup = []
        for t_ in list(b.GetTracks()):
            if t_.GetClass() == 'PCB_VIA':
                k_ = ('v', t_.GetNetname(), round(pcbnew.ToMM(t_.GetPosition().x), 3), round(pcbnew.ToMM(t_.GetPosition().y), 3))
            else:
                a_ = (round(pcbnew.ToMM(t_.GetStart().x), 3), round(pcbnew.ToMM(t_.GetStart().y), 3)); c_ = (round(pcbnew.ToMM(t_.GetEnd().x), 3), round(pcbnew.ToMM(t_.GetEnd().y), 3))
                k_ = (t_.GetLayer(), t_.GetNetname(), round(pcbnew.ToMM(t_.GetWidth()), 3)) + tuple(sorted((a_, c_)))
            if k_ in seen: dup.append(t_)
            else: seen[k_] = t_
        for t_ in dup: b.RemoveNative(t_)
        print('DEDUP removed', len(dup))
    from collections import Counter
    nar = Counter(t_.GetNetname() for t_ in b.GetTracks() if t_.GetClass() != 'PCB_VIA' and pcbnew.ToMM(t_.GetWidth()) < 0.199)
    print('NARROW', dict(nar))
    pcbnew.SaveBoard(out, b)
    print('saved', out)
