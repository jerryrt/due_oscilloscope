import sys, time, math, os
sys.path.insert(0, 'whatif/_scratch')
import numpy as np
import route_lib as R
from pcbtools.boards import v1 as C
t0 = time.time()
src = os.environ.get('SRC', 'whatif/_scratch/final/afe-proto.kicad_pcb')
B = R.Board(src); b = B.b
row = {}
for j in range(len(b.p_fp)): row[(b.fp_ref[int(b.p_fp[j])], str(b.p_pin[j]))] = j
def net_pads(n): return [j for j in range(len(b.p_fp)) if b.nets[int(b.p_net[j])] == n]
def L_of(segs): return sum(math.hypot(s[3][0] - s[2][0], s[3][1] - s[2][1]) for s in segs)
done = set()
log = []
def go(net, **kw):
    ladder = [dict(), dict(width=0.2), dict(width=0.2, extra_margin=-0.03), dict(bottom_cost=4.0), dict(bottom_cost=4.0, width=0.2), dict(vias=False, bottom=False), dict(vias=False, bottom=False, width=0.2)]
    best = None
    for step in ladder:
        kw2 = dict(kw); kw2.update({k: v for k, v in step.items() if not (k == 'width' and kw.get('width', 0.2) <= v)})
        segs, vs, fails = B.route(net, **kw2)
        hop = L_of([s for s in segs if s[1] == 1]) > 2.9 or len(vs) > 2
        score = (len(fails), hop)
        if best is None or score < best[4]: best = (segs, vs, fails, kw2, score)
        if not fails and not hop: break
    segs, vs, fails, kw2, _sc = best
    B.add(segs, vs)
    tag = kw.get('tag')
    print('NET %-10s %-12s len %6.1f vias %d bottom %5.1f w %.2f margin %.2f fails %s' % (net, tag or '', L_of(segs), len(vs), L_of([s for s in segs if s[1] == 1]), kw2.get('width', 0.2), kw2.get('extra_margin', 0.0), fails), flush=True)
    for f_ in fails:
        ref, pin = f_.split('.'); j = row[(ref, pin)]
        nid_ = b.nets.index(net); others_ = {k for k in range(len(b.p_fp)) if int(b.p_net[k]) == nid_ and k != j and (kw.get('pads_subset') is None or k in kw['pads_subset'])}
        if others_:
            kk = min(others_, key=lambda k: math.hypot(b.p_x[k] - b.p_x[j], b.p_y[k] - b.p_y[j]))
            for name, relax, extra in (('margin -0.05', set(), dict(extra_margin=-0.05)), ('width 0.15', set(), dict(width=0.15)), ('bottom courtyard rule off', {'court'}, {}), ('HIZ 0.85 off', {'hiz'}, {}), ('top-only off (vias on)', set(), dict(bottom=True, vias=True))):
                B.relax = set(relax)
                kw3 = {k_: v_ for k_, v_ in kw.items() if k_ != 'pads_subset'}; kw3.update(extra); kw3['pads_subset'] = {j, kk}
                s3, v3, f3 = B.route(net, **kw3); B.relax = set()
                print('      probe', f_, name, '->', 'ROUTES' if not f3 else 'fails', 'len %.1f' % L_of(s3), flush=True)
        near = sorted({(b.nets[int(b.p_net[k])], b.fp_ref[int(b.p_fp[k])] + '.' + str(b.p_pin[k])) for k in range(len(b.p_fp)) if k != j and math.hypot(b.p_x[k] - b.p_x[j], b.p_y[k] - b.p_y[j]) < 2.0})
        print('    FAIL', f_, 'at', round(float(b.p_x[j]), 2), round(float(b.p_y[j]), 2), 'neighbour pads within 2 mm:', near[:10], flush=True)
    return segs, vs, fails
POWER = {'/+5V_DUE': 0.5, '/+5V_F': 0.5, '/+3V3A': 0.4, '/VNEG': 0.4, '/VREF': 0.3, '/SC_VCC': 0.4, '/P33_U': 0.3, '/P33_S': 0.3}
# 1. A1, A0, AWG_INV: top only
for n in ('/A1', '/A0', '/AWG_INV'): go(n, width=0.2); done.add(n)
# 1b. the eight HIZ nets, each on its own copper, kept 0.85 mm from every other track
HORD = ['/CH1_N', '/CH1_NP', '/CH1_R1A', '/CH1_R2A', '/CH2_R1A', '/CH2_N', '/CH2_NP', '/CH2_R2A']
for n in HORD:
    segs, vs, fails = go(n, width=0.2); done.add(n)
    print('   HIZ length', n, round(L_of(segs), 2))
def span(n):
    idx = net_pads(n); return (b.p_x[idx].max() - b.p_x[idx].min()) + (b.p_y[idx].max() - b.p_y[idx].min())
ANALOG = [r for r in b.fp_ref if C.BLOCK.get(r) in ('AWG', 'SCOPE', 'REFCAL') and not r.startswith(('J', 'MH'))]
POWERS = {'/+5V_DUE': 0.5, '/+5V_F': 0.5, '/+3V3A': 0.4, '/VNEG': 0.4, '/VREF': 0.3, '/SC_VCC': 0.4, '/P33_U': 0.3, '/P33_S': 0.3}
def route_plain(n):
    w = POWERS.get(n, 0.2)
    own = {b.fp_ref[int(b.p_fp[j])] for j in net_pads(n)}
    cour = [r for r in ANALOG if r not in own] if n in ('/SDA1', '/SCL1', '/SDA1_A', '/SCL1_A') else None
    go(n, width=w, bottom=True, vias=True, net_courtyards=cour); done.add(n)
RAILV = {'/VREF', '/+3V3A', '/VNEG'}
short = sorted([n for n in b.nets if n and n != C.GND and n not in done and n not in RAILV and len(net_pads(n)) >= 2 and n not in POWERS and span(n) <= 12.0], key=span)
for n in short: route_plain(n)
# 2. VREF: the source, then each branch on its own copper (LR-8); extra VREF pads join the nearest branch
vp = net_pads('/VREF')
src_rows = {row[k] for k in C.VREF_SOURCE}
go('/VREF', width=0.3, bottom=True, vias=True, pads_subset=src_rows, tag='vsrc')
brs = [{row[k] for k in br} for br in C.VREF_BRANCHES]
extra = [j for j in vp if j not in src_rows and not any(j in br for br in brs)]
for j in extra:
    k = min(range(len(brs)), key=lambda q: min(math.hypot(b.p_x[j] - b.p_x[m], b.p_y[j] - b.p_y[m]) for m in brs[q])); brs[k].add(j)
print('extra VREF pads', [(b.fp_ref[int(b.p_fp[j])], b.p_pin[j]) for j in extra])
for q, br in enumerate(brs):
    near = min(src_rows, key=lambda s: min(math.hypot(b.p_x[s] - b.p_x[m], b.p_y[s] - b.p_y[m]) for m in br))
    go('/VREF', width=0.3, bottom=True, vias=True, pads_subset=set(br) | {near}, tag=f'vb{q}')
done.add('/VREF')
# 3. rails: one leg per bridge pad first, then the hub (the star pads and the local loads); the REF/ADS loads sit on the R412 leg
PLAN = {'/+3V3A': dict(hub=[('U401', '11'), ('C407', '1'), ('C408', '1'), ('TP404', '1'), ('R407', '1'), ('R406', '1')],
                       legs={'R411': [('R411', '1')], 'R412': [('R412', '1'), ('C501', '1'), ('C505', '1'), ('U501', '1')], 'R413': [('R413', '1')]}),
        '/VNEG': dict(hub=[('U401', '6'), ('C409', '1'), ('C410', '1'), ('R402', '1')], legs={'R410': [('R410', '1')]})}
for rail, pl in PLAN.items():
    hub = {row[k] for k in pl['hub']}
    assert {row[k] for k in pl['hub']} | {row[k] for ks in pl['legs'].values() for k in ks} == set(net_pads(rail)), (rail, 'pads not all planned')
    for name, ks in pl['legs'].items():
        leg = {row[k] for k in ks}
        near = min(hub, key=lambda s: min(math.hypot(b.p_x[s] - b.p_x[m], b.p_y[s] - b.p_y[m]) for m in leg))
        go(rail, width=0.4, bottom=True, vias=True, pads_subset=leg | {near}, tag='leg-' + name)
    go(rail, width=0.4, bottom=True, vias=True, pads_subset=hub, tag='hub')
    done.add(rail)
# 4. everything left, shortest first, power last
others = [n for n in b.nets if n and n != C.GND and n not in done and len(net_pads(n)) >= 2]
others.sort(key=lambda n: (n in POWERS, span(n)))
for n in others: route_plain(n)
B.save('whatif/_scratch/route2/signals2.kicad_pcb')
print('done', round(time.time() - t0), 's')
