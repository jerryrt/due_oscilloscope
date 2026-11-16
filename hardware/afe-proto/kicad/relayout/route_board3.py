import sys, time, math, os, copy
sys.path.insert(0, 'whatif/_scratch')
import numpy as np
import route_lib as R
from pcbtools.boards import v1 as C
t0 = time.time()
src = os.environ.get('SRC', 'whatif/_scratch/final/afe-proto.kicad_pcb')
MAXIT = int(os.environ.get('MAXIT', '8'))
B0 = R.Board(src); b = B0.b
row = {}
for j in range(len(b.p_fp)): row[(b.fp_ref[int(b.p_fp[j])], str(b.p_pin[j]))] = j
def net_pads(n): return [j for j in range(len(b.p_fp)) if b.nets[int(b.p_net[j])] == n]
def L_of(segs): return sum(math.hypot(s[3][0] - s[2][0], s[3][1] - s[2][1]) for s in segs)
def span(n):
    idx = net_pads(n); return (b.p_x[idx].max() - b.p_x[idx].min()) + (b.p_y[idx].max() - b.p_y[idx].min())
POWERS = {'/+5V_DUE': 0.5, '/+5V_F': 0.5, '/+3V3A': 0.4, '/VNEG': 0.4, '/VREF': 0.3, '/SC_VCC': 0.4, '/P33_U': 0.3, '/P33_S': 0.3}
ANALOG = [r for r in b.fp_ref if C.BLOCK.get(r) in ('AWG', 'SCOPE', 'REFCAL') and not r.startswith(('J', 'MH'))]
HORD = ['/CH1_N', '/CH1_NP', '/CH1_R1A', '/CH1_R2A', '/CH2_R1A', '/CH2_N', '/CH2_NP', '/CH2_R2A']
# ---- tasks: (key, net, kwargs)
tasks = {}
for n in ('/A1', '/A0', '/AWG_INV'): tasks[n] = (n, dict(width=0.2))
for n in HORD: tasks[n] = (n, dict(width=0.2))
vp = net_pads('/VREF'); src_rows = {row[k] for k in C.VREF_SOURCE}
tasks['vsrc'] = ('/VREF', dict(width=0.3, bottom=True, vias=True, pads_subset=src_rows, tag='vsrc'))
brs = [{row[k] for k in br} for br in C.VREF_BRANCHES]
for j in [j for j in vp if j not in src_rows and not any(j in br for br in brs)]:
    k = min(range(len(brs)), key=lambda q: min(math.hypot(b.p_x[j] - b.p_x[m], b.p_y[j] - b.p_y[m]) for m in brs[q])); brs[k].add(j)
for q, br in enumerate(brs):
    near = min(src_rows, key=lambda s: min(math.hypot(b.p_x[s] - b.p_x[m], b.p_y[s] - b.p_y[m]) for m in br))
    tasks[f'vb{q}'] = ('/VREF', dict(width=0.3, bottom=True, vias=True, pads_subset=set(br) | {near}, tag=f'vb{q}'))
PLAN = {'/+3V3A': dict(hub=[('U401', '11'), ('C407', '1'), ('C408', '1'), ('TP404', '1'), ('R407', '1'), ('R406', '1')],
                       legs={'R411': [('R411', '1')], 'R412': [('R412', '1'), ('C501', '1'), ('C505', '1'), ('U501', '1')], 'R413': [('R413', '1')]}),
        '/VNEG': dict(hub=[('U401', '6'), ('C409', '1'), ('C410', '1'), ('R402', '1')], legs={'R410': [('R410', '1')]})}
for rail, pl in PLAN.items():
    hub = {row[k] for k in pl['hub']}
    for name, ks in pl['legs'].items():
        leg = {row[k] for k in ks}
        near = min(hub, key=lambda s: min(math.hypot(b.p_x[s] - b.p_x[m], b.p_y[s] - b.p_y[m]) for m in leg))
        tasks[f'{rail}-leg-{name}'] = (rail, dict(width=0.4, bottom=True, vias=True, pads_subset=leg | {near}, tag='leg-' + name))
    tasks[f'{rail}-hub'] = (rail, dict(width=0.4, bottom=True, vias=True, pads_subset=hub, tag='hub'))
special = {t[0] for t in tasks.values()}
for n in b.nets:
    if not n or n == C.GND or n in special or len(net_pads(n)) < 2: continue
    own = {b.fp_ref[int(b.p_fp[j])] for j in net_pads(n)}
    cour = [r for r in ANALOG if r not in own] if n in ('/SDA1', '/SCL1', '/SDA1_A', '/SCL1_A') else None
    tasks[n] = (n, dict(width=POWERS.get(n, 0.2), bottom=True, vias=True, net_courtyards=cour))
critical = ['/A1', '/A0', '/AWG_INV'] + HORD
vref = ['vsrc', 'vb0', 'vb1', 'vb2', 'vb3']
rails = [k for k in tasks if '-leg-' in k or k.endswith('-hub')]
plain = [k for k in tasks if k not in critical + vref + rails]
short = sorted([k for k in plain if k not in POWERS and span(tasks[k][0]) <= 12.0], key=lambda k: span(tasks[k][0]))
long_ = sorted([k for k in plain if k not in short], key=lambda k: (k in POWERS, span(tasks[k][0])))
base_order = critical + short + vref + rails + long_
FINE = ['U401', 'U101', 'U301', 'U501', 'U502']
def run(order, verbose=False):
    B = R.Board(src); fails_by = {}
    # escape stubs first, so no later net can box in a fine-pitch pad
    nstub = 0; nfail = 0
    for ref in FINE:
        for j in range(len(b.p_fp)):
            if b.fp_ref[int(b.p_fp[j])] != ref: continue
            net = b.nets[int(b.p_net[j])]
            if not net or net == C.GND: continue
            if net in C.HIZ: continue
            segs, vs, ok = B.escape(net, j, ref, dist=1.2, width=0.2)
            if ok: B.add(segs, vs); nstub += 1
            else: nfail += 1
    print('ESCAPES', nstub, 'failed', nfail, flush=True)
    def go(key):
        net, kw = tasks[key]
        ladder = [dict(), dict(width=0.2), dict(width=0.2, extra_margin=-0.03), dict(bottom_cost=4.0), dict(bottom_cost=4.0, width=0.2), dict(vias=False, bottom=False), dict(vias=False, bottom=False, width=0.2)]
        best = None
        for step in ladder:
            kw2 = dict(kw); kw2.update({k: v for k, v in step.items() if not (k == 'width' and kw.get('width', 0.2) <= v)})
            if kw.get('bottom') is False and 'bottom' in step: continue
            segs, vs, fails = B.route(net, **kw2)
            hop = L_of([s for s in segs if s[1] == 1]) > 2.9 or len(vs) > 2
            score = (len(fails), hop)
            if best is None or score < best[2]: best = (segs, vs, score, fails)
            if not fails and not hop: break
        segs, vs, score, fails = best
        B.add(segs, vs)
        if fails: fails_by[key] = fails
        if verbose: print('TASK %-18s len %6.1f vias %d fails %s' % (key, L_of(segs), len(vs), fails), flush=True)
    for key in order: go(key)
    return B, fails_by
order = list(base_order); best = None
for it in range(MAXIT):
    B, fails_by = run(order, verbose=(it == MAXIT - 1))
    nf = sum(len(v) for v in fails_by.values())
    print('ITER', it, 'failing pads', nf, {k: v for k, v in fails_by.items()}, round(time.time() - t0), 's', flush=True)
    if best is None or nf < best[0]: best = (nf, B, list(order))
    if nf == 0: break
    front = [k for k in fails_by if k not in critical]
    order = critical + front + [k for k in order if k not in critical and k not in front]
nf, B, order = best
B.save('whatif/_scratch/route2/signals3.kicad_pcb')
print('BEST failing pads', nf, 'done', round(time.time() - t0), 's')
