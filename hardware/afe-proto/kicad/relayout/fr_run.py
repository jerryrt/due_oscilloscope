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
    ok = pcbnew.ImportSpecctraSES(b, os.path.abspath(W + '/out.ses'))
    print('import', ok)
    pcbnew.SaveBoard(out, b)
    print('saved', out)
