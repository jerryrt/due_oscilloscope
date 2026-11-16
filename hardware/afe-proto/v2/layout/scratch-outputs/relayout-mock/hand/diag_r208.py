import sys, os, math, json
os.environ['BLK'] = 'CH2'
sys.argv = ['x', 'diag']
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock')
import ch_cands as C
RP, np = C.RP, C.np
r = 'R208'; p = C.P0[r]; pn = C.PN[r]
x, y, rot = pn['x'], pn['y'], pn['rot']
k = int(round((rot - round(p['rot'])) / 90.0)) % 4
print('R208 committed', (x, y, rot), 'k', k, 'main rot', p['rot'], 'label now', (round(pn['tx'], 3), round(pn['ty'], 3)))
for ls in (0, 2, 4):
    gg = RP.part_geom(p, k, ls)
    def box(b): return np.array([[x + b[0], y + b[1], x + b[2], y + b[3]]])
    E = box(gg['ext']); CYB = box(gg['cy']); LB = box(gg['lab']); ZB = box(gg['zone'])
    res = {}
    res['ext_in_region_mask'] = float(C.vbad(C.mext, E)[0])
    res['label_in_region_mask'] = float(C.vbad(C.mlab, LB)[0])
    res['cy_vs_fixed_cy'] = bool(C.OVm(CYB, C.f_cy, 0.0).any())
    res['zone_vs_fixed_cy'] = bool(C.OVm(ZB, C.f_cy, 0).any())
    res['label_vs_fixed_labels_0.5'] = bool(C.OVm(LB, C.f_lab, 0.5).any())
    res['cy_vs_fixed_labels'] = bool(C.OVm(CYB, C.f_lab, 0).any())
    res['label_infl_vs_fixed_ext'] = bool(C.OVm(LB + np.array([-0.3, -0.3, 0.3, 0.3]), C.f_ext, 0).any())
    res['3b_label_in_beside_place'] = bool(C.pl_any(LB, C.f_bcy).any())
    cand = (r, k, ls, x, y)
    res['tie_ok'] = C.tie_ok(cand)
    print('ls', ls, 'label box', [round(float(v), 2) for v in LB[0]], res)
print('CH2 region', C.RP.REGIONS['CH2'])
