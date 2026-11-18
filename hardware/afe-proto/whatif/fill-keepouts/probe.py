import sys, os, importlib
sys.path[:0] = ['hardware/afe-proto', 'hardware/pcbkit']
from pcbtools import fill_clean as fc
from pcbkit import fills
import numpy as np
cfg = importlib.import_module('pcbtools.boards.v1_layout')
outl = [tuple(r) for rs in cfg.OUTLINE.values() for r in rs]
path = 'hardware/afe-proto/kicad/afe-proto.kicad_pcb'
tmp = path + '.p.tmp.kicad_pcb'
r0 = fc._fill_to(path, tmp, [], 0.2, 0.3, 0.3, 0.3)
keeps = fills.keepouts(r0, 1.0, 0.5, 1.0, outlines=outl, bounds=(17.0, -4.5, 117.0, 57.84))
r = fc._fill_to(path, tmp, keeps, 1.0, 0.3, 0.3, 0.3)
print('keeps', len(keeps), 'pour area', r.mask.sum() / 400)
for neck in (1.2, 1.5):
    for small in (4, 8, 12):
        lo = fills.leftovers(r, neck=neck, small=small, dead_width=0.0001)
        print(neck, small, 'blobs mm2', lo.sum() / 400)
lo = fills.leftovers(r, neck=99, small=0)
print('dead ends mm2', fills.leftovers(r, neck=0.1, small=0).sum() / 400)
extra = None
for rd in range(3):
    lo = fills.leftovers(r)
    print('round', rd, 'leftover mm2', lo.sum() / 400)
    extra = lo if extra is None else (extra | lo)
    keeps = fills.keepouts(r0, 1.0, 0.5, 1.0, outlines=outl, bounds=(17.0, -4.5, 117.0, 57.84), extra=extra)
    tot = sum((k[2]-k[0])*(k[3]-k[1]) for k in keeps)
    r = fc._fill_to(path, tmp, keeps, 1.0, 0.3, 0.3, 0.3)
    print('  keeps', len(keeps), 'area', tot, 'pour', r.mask.sum() / 400)
