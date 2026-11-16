import sys, math
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import numpy as np, relayout_place as RP
sys.argv = ['x']
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
import importlib.util
spec = importlib.util.spec_from_file_location('rcc', R + 'rc_cands.py'); rcc = importlib.util.module_from_spec(spec)
# rc_cands is hard-wired to REFCAL: reuse its helpers with the CH1 block and C105 movable
src = open(R + 'rc_cands.py').read().replace("BLK = 'REFCAL'", "BLK = 'CH1'").replace("PART = sorted(r for r in P0 if RP.block_of(r) == BLK)", "PART = ['C105']").replace("ICS = ('U501', 'U502')", "ICS = ()")
src = src[:src.index("if __name__ == '__main__':")]
ns = {'__name__': 'rcc'}; exec(compile(src, 'rcc', 'exec'), ns)
PN, P0 = ns['PN'], ns['P0']; cands_for = ns['cands_for']
p = PN['C105']; pu = PN['U101']
pin8 = [q for q in pu['pads'] if q['n'] == '8'][0]['c']
print('C105 now', round(p['x'], 2), round(p['y'], 2), p['rot'], 'U101 pin8', [round(v, 2) for v in pin8])
L = cands_for('C105', (p['x'], p['y']), range(4), (0, 2, 4), 4.0, 0.05)
def pad1(c):
    pp = P0['C105']; cs, sn = RP.COS[c[1]], RP.SIN[c[1]]; q = [q for q in pp['pads'] if q['n'] == '1'][0]
    o = (q['c'][0] - pp['x'], q['c'][1] - pp['y']); o = (o[0] * cs - o[1] * sn, o[0] * sn + o[1] * cs); return (c[3] + o[0], c[4] + o[1])
L = [c for c in L if math.hypot(pad1(c)[0] - pin8[0], pad1(c)[1] - pin8[1]) <= 2.79]
print('legal within 2.79 of pin 8:', len(L))
others = [(r, q) for r, q in PN.items() if RP.block_of(r) == 'CH1' and RP.PAS.fullmatch(r) and r != 'C105']
def orient_of(c): return RP.orient(P0['C105'], c[1])
good = []
for c in L:
    o = orient_of(c); ok = False
    for r, q in others:
        qo = RP.orient(P0[r], int(round((q['rot'] - P0[r]['rot']) / 90.0)) % 4)
        if qo != o: continue
        if math.hypot(c[3] - q['x'], c[4] - q['y']) <= 8 and ((o == 0 and abs(c[4] - q['y']) <= 0.05) or (o == 90 and abs(c[3] - q['x']) <= 0.05)): ok = True; break
    if not ok:
        for w in pu['pads']:
            if w['n'] and math.hypot(c[3] - w['c'][0], c[4] - w['c'][1]) <= 4 and ((o == 0 and abs(c[4] - w['c'][1]) <= 0.05) or (o == 90 and abs(c[3] - w['c'][0]) <= 0.05)): ok = True; break
    if ok: good.append(c)
print('aligned candidates:', len(good))
good.sort(key=lambda c: math.hypot(c[3] - p['x'], c[4] - p['y']))
for c in good[:5]: print('CAND', c[:5], 'pad1-pin8', round(math.hypot(pad1(c)[0] - pin8[0], pad1(c)[1] - pin8[1]), 2))
