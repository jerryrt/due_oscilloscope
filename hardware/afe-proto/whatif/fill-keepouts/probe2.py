import sys, importlib
sys.path[:0] = ['hardware/afe-proto', 'hardware/pcbkit']
from pcbtools import fill_clean as fc
from pcbkit import fills
import numpy as np
path = 'hardware/afe-proto/kicad/afe-proto.kicad_pcb'
tmp = path + '.p.tmp.kicad_pcb'
r0 = fc._fill_to(path, tmp, [], 0.2, 0.3, 0.3, 0.3)
B=(17.0, -4.5, 117.0, 57.84)
k0 = fills.keepouts(r0, 1.0, 0.5, 1.0, bounds=B)
print('no outlines', len(k0), sorted(((k[2]-k[0])*(k[3]-k[1]),k) for k in k0)[-3:])
k1 = fills.keepouts(r0, 1.0, 0.5, 1.0, bounds=B, extra=np.zeros_like(r0.mask))
print('empty extra', len(k1))
import pickle
keeps = fills.keepouts(r0, 1.0, 0.5, 1.0, bounds=B)
r = fc._fill_to(path, tmp, keeps, 1.0, 0.3, 0.3, 0.3)
lo = fills.leftovers(r)
print('lo px', lo.sum(), 'shape', lo.shape)
from scipy import ndimage as ndi
lab, n = ndi.label(lo, structure=np.ones((3,3)))
print('components', n, sorted(ndi.sum(lo, lab, range(1,n+1)))[-5:])
for fr in (1.15,):
    k2 = fills.keepouts(r0, 1.0, 0.5, 1.0, bounds=B, extra=lo)
    print('with extra', len(k2), sorted(((k[2]-k[0])*(k[3]-k[1]),k) for k in k2)[-3:])
k3 = fills.keepouts(r0, 1.0, 0.5, 0.0, bounds=B, extra=lo, hole_area=0)
print('join0 holes0', len(k3), sorted(((k[2]-k[0])*(k[3]-k[1]),k) for k in k3)[-2:])
for fr in (1.0, 1.05):
    k4 = fills.keepouts(r0, 1.0, 0.5, 0.0, bounds=B, extra=lo, hole_area=0, fill_ratio=fr)
    print('fr', fr, len(k4), sorted(((k[2]-k[0])*(k[3]-k[1])) for k in k4)[-3:], 'total', sum((k[2]-k[0])*(k[3]-k[1]) for k in k4))
