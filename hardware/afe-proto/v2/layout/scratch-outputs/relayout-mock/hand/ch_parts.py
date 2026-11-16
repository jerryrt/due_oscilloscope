import sys, json
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
D0, P0 = RP.load('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/dump_all.json')
for r in ('C101','C102','C103','R101','R102','R103','R104','R105','R106','R107','R108','C104','C105','D101','TP101','BR101','BR102','C201','C202','C203','R201','R202','R203','R204','R205','R206','R207','R208','D201','TP201'):
    p = P0[r]; g = RP.part_geom(p, 0, 0)
    print(r, 'rot', p['rot'], 'cy', [round(v, 3) for v in g['cy']], 'pads', [(q['n'], q['net'], round(q['c'][0] - p['x'], 3), round(q['c'][1] - p['y'], 3)) for q in p['pads']])
