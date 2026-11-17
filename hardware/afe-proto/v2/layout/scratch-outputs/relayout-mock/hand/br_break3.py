"""LR-6 / LR-8 on the committed bridge-free board with the real config (no monkeypatch): a logic test, straight tracks between pad
centres (not a layout), a passing arm per rule, then the break-on-purpose arms. python3 br_break3.py   (in the container: /work)"""
import sys, types, subprocess, shutil, json
sys.path.insert(0, '/work/hardware/afe-proto'); sys.path.insert(0, '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand')
from pcbtools import boardio, rules
from pcbtools.boards import v2_layout as C
H = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand/'
BD = '/work/hardware/afe-proto/v2/layout/integrated/afe-v2-integrated'
PAD = {(p['ref'], p['pin']): (p['x'], p['y'], p['net']) for p in json.load(open(H + 'pads.json'))}
def seg(a, b, net=None):
    (ra, pa), (rb, pb) = a, b
    return (net or PAD[a][2], 'F', [PAD[a][:2], PAD[b][:2]], 0.2)
PADS = json.load(open(H + 'pads.json'))
def sd(p, a, b):                         # distance point to segment
    ax, ay = a; bx, by = b; px, py = p; dx, dy = bx - ax, by - ay; L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** .5
def ccw(a, b, c): return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
def sdd(a, b, c, d):                     # distance segment to segment
    if ccw(a, c, d) * ccw(b, c, d) < 0 and ccw(a, b, c) * ccw(a, b, d) < 0: return 0
    return min(sd(a, c, d), sd(b, c, d), sd(c, a, b), sd(d, a, b))
def variants(a, b):
    (ax, ay), (bx, by) = a, b
    return [[a, b], [a, (bx, ay), b], [a, (ax, by), b]]
def plan(chains, keep=0.3, skip_pads=()):
    """chains: [[root, pad, pad ...]]; one polyline per link, chosen so no two chains' copper (or another chain's pad of the same net) comes within `keep`"""
    links = []
    for ci, c in enumerate(chains):                          # Prim from the root: each pad joins the nearest pad already in
        inn, out = [c[0]], list(c[1:])
        while out:
            d, a, b = min(((PAD[x][0] - PAD[y][0]) ** 2 + (PAD[x][1] - PAD[y][1]) ** 2, x, y) for x in inn for y in out)
            links.append((ci, PAD[a][:2], PAD[b][:2])); inn.append(b); out.remove(b)
    links.sort(key=lambda l: -((l[1][0] - l[2][0]) ** 2 + (l[1][1] - l[2][1]) ** 2))
    own = [set(c) for c in chains]
    placed = []
    def ok(ci, poly):
        for cj, p2 in placed:
            if cj != ci and any(sdd(poly[i], poly[i + 1], p2[j], p2[j + 1]) < keep for i in range(len(poly) - 1) for j in range(len(p2) - 1)): return False
        for p in PADS:
            k = (p['ref'], p['pin'])
            if k in own[ci] or k in skip_pads or p['net'] != PAD[chains[ci][0]][2]: continue
            if any(sd((p['x'], p['y']), poly[i], poly[i + 1]) < keep for i in range(len(poly) - 1)): return False
        return True
    def rec(n):
        if n == len(links): return True
        ci, a, b = links[n]
        for v in variants(a, b):
            if ok(ci, v):
                placed.append((ci, v))
                if rec(n + 1): return True
                placed.pop()
        return False
    if not rec(0): raise SystemExit('no crossing-free dog-leg set for these chains')
    return [(PAD[chains[ci][0]][2], 'F', v, 0.2) for ci, v in placed]
def run(tag, routes, rule, sub=False):
    out = H + 'brk3_%s.kicad_pcb' % tag
    open(H + 'brk3_%s.py' % tag, 'w').write('ROUTES = %r\nVIAS = []\n' % routes)
    subprocess.run(['python3', H + 'hr.py', BD + '.kicad_pcb', out, H + 'brk3_%s.py' % tag], check=True, capture_output=True)
    shutil.copy(BD + '.kicad_pro', out.replace('.kicad_pcb', '.kicad_pro'))
    b = boardio.read_board_retry(out); cc = C
    if rule == '8' and sub:                      # the real source and the real shared leg, plus only the branches this arm wires
        cc = types.SimpleNamespace(**{k: getattr(C, k) for k in dir(C) if not k.startswith('__')}); cc.VREF_BRANCHES = [C.VREF_BRANCHES[-1]] if sub == 1 else [[('R509', '2')], [('R106', '2'), ('R206', '2')]]
    r = {'6': rules.lr6, '8': rules.lr8}[rule](b, cc)
    print(tag, 'LR-' + rule, 'PASS' if r.ok else 'FAIL', '|', r.detail[:1500].replace(';', '\n     '))
U = lambda r, p: (r, p)
sc = [U('U401', '11'), U('U101', '8'), U('C104', '1'), U('C105', '1'), U('D101', '2'), U('D201', '2')]
aw = [U('C405', '1'), U('U301', '8'), U('C305', '1')]
ad = [U('C406', '1'), U('U501', '1'), U('C502', '1'), U('U502', '8'), U('C503', '1'), U('R512', '1'), U('R513', '1')]
vn = [[U('U401', '6'), U('U301', '4'), U('C306', '1')]]
STAR6 = {U('U401', '11'), U('C405', '1'), U('C406', '1'), U('R401', '1'), U('TP401', '1'), U('R407', '1'), U('U401', '6'), U('C407', '1'), U('C408', '1'), U('R403', '1')}
ad_alone, vn_t, sc_aw = plan([ad], skip_pads=STAR6), plan(vn, skip_pads=STAR6), plan([sc, aw], skip_pads=STAR6)
print('--- LR-6: scope and awg groups wired to their star, VNEG wired, adc group left unwired (expect only the adc message)')
run('p6', sc_aw + vn_t, '6')
print('--- break on purpose: one track joins the scope group to the awg group (expect "one piece of copper serves")')
run('b6', sc_aw + vn_t + [seg(U('C104', '1'), U('C305', '1'))], '6')
print('--- break on purpose: the VNEG spoke left out (expect a /VNEG message: the key is live, not skipped)')
run('b6v', sc_aw, '6')
print('--- adc group alone wired (expect no adc message)')
run('p6a', ad_alone, '6')
src = U('U501', '2')
def br8(keys, shared=False):
    ch = [[src, U(*k)] for k in keys] + ([[src, U('R509', '2'), U('R106', '2'), U('R206', '2')]] if shared else [])
    return [seg(src, U('C501', '1'))] + plan(ch, skip_pads={U('U501', '2'), U('C501', '1')})
print('--- LR-8: the shared centring leg (R509.2, R106.2, R206.2) wired from the source (sub-config: the real source, the real shared branch alone; expect PASS)')
g8 = br8([], True)
run('p8', g8, '8', sub=1)
print('--- break on purpose: (see next line)  the ADC leg the same copper judged as two branches R509.2 | R106.2+R206.2 (expect "share copper")')
run('b8', g8, '8', sub=2)
print('--- break on purpose: the shared leg stops short of R206.2 (expect branch 5 (R206.2) not connected: no silent skip)')
run('b8b', [t for t in g8 if PAD[U('R206', '2')][:2] != t[2][-1]], '8', sub=1)
