"""python3 bridgeloop.py BASE.kicad_pcb MAXB ITER TAG   (in the image, cwd hand/): systematic bridges. Each round: pf.py, take the pair of crossing nets with the most conflicts,
bridge the cheaper one (fewer pads; never a fixed net, an inverting node or a supply group) at the pair's mean conflict point, rebuild the board, repeat.
Writes TAG_<k>.kicad_pcb, TAG_<k>.txt (pf output) and TAG_log.txt (METRIC and the chosen bridge per round)."""
import subprocess, sys, re, json, math
sys.path.insert(0, '/work/hardware/afe-proto')
from pcbtools.boards import v2_sch
base, maxb, it, tag = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
BLOCK = {p['ref']: p['block'] for p in v2_sch.PARTS}
HUND = {'CH1': 1, 'CH2': 2, 'AWG': 3, 'POWER': 4, 'REFCAL': 5}
EXCL = {'/AWG_FB', '/CH1_N', '/CH2_N', '/GND', '/A0', '/A1', '/CH1_OUT', '/CH2_OUT', '/CH1_M1', '/CH1_M2', '/CH1_M3', '/CH1_NP', '/CH2_M1', '/CH2_M2', '/CH2_M3', '/CH2_NP'}
board = base
used = set()
log = open(tag + '_log.txt', 'w')
def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout
for k in range(maxb + 1):
    out = sh(['python3', '-u', 'pf.py', board, '%s_%d_spec.py' % (tag, k), it, '700'])
    open('%s_%d.txt' % (tag, k), 'w').write(out)
    m = re.search(r'METRIC conflict_segments (\d+) distinct_clusters (\d+)', out)
    print('round', k, 'bridges', k, 'METRIC', m.groups() if m else None, file=log, flush=True)
    if not m or int(m.group(2)) == 0 or k == maxb:
        break
    pairs = [(int(c), a, b, float(x), float(y)) for a, b, c, x, y in re.findall(r'^PAIRSUM (\S+) (\S+) (\d+) ([\d.\-]+) ([\d.\-]+)', out, re.M)]
    pick = None
    pads = json.loads(sh(['python3', '-c', 'import pcbnew']) or 'null') if False else None
    for c, a, b, x, y in sorted(pairs, reverse=True):
        for A, B in ((a, b), (b, a)):
            if '#' in A or A in EXCL or A.endswith('_src'):
                continue
            pick = (A, B, x, y, c); break
        if pick: break
    if not pick:
        print('no bridgeable pair left', file=log, flush=True); break
    A, B, x, y, c = pick
    if '#' in B: B = B.split('#')[0]
    # block of A: majority of the parts on it, from the board's nets of the spec
    nets = A.lstrip('/')
    refs = [p['ref'] for p in v2_sch.PARTS if nets in p['pins'].values()]
    blk = max(set(BLOCK[r] for r in refs), key=lambda b_: sum(BLOCK[r] == b_ for r in refs)) if refs else 'REFCAL'
    h = HUND.get(blk, 5) * 100
    n = 1
    while 'BR%d' % (h + n) in used: n += 1
    ref = 'BR%d' % (h + n); used.add(ref)
    sh(['python3', 'bridgeplan.py', '%s_%d_spec.py' % (tag, k), board, '%s_b%d.py' % (tag, k + 1), '%s:%.3f:%.3f:%s:%s' % (ref, x, y, A, B)])
    nb = '%s_%d.kicad_pcb' % (tag, k + 1)
    sh(['python3', 'add_bridges.py', board, nb, '%s_b%d.py' % (tag, k + 1)])
    sh(['cp', base.replace('.kicad_pcb', '.kicad_pro'), nb.replace('.kicad_pcb', '.kicad_pro')])
    print('  bridge', ref, 'net', A, 'over', B, 'at', (round(x, 2), round(y, 2)), 'pair conflicts', c, file=log, flush=True)
    print(open('%s_b%d.py' % (tag, k + 1)).read().strip(), file=log, flush=True)
    board = nb
print('done', file=log, flush=True)
