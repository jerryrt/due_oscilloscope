import numpy as np, itertools
from pcbtools import boardio
b = boardio.read_board(__import__('sys').argv[1] if len(__import__('sys').argv)>1 else 'kicad/afe-proto.kicad_pcb')
nid = b.nets.index('/AWG_INV')
pts = []
for j in range(len(b.p_fp)):
    if int(b.p_net[j]) == nid:
        pts.append((b.fp_ref[int(b.p_fp[j])], b.p_pin[j], round(float(b.p_x[j]),3), round(float(b.p_y[j]),3)))
print(pts)
def mst(P, metric):
    n=len(P); used=[0]; tot=0; edges=[]
    while len(used)<n:
        best=None
        for i in used:
            for k in range(n):
                if k in used: continue
                d=metric(P[i],P[k])
                if best is None or d<best[0]: best=(d,k,i)
        tot+=best[0]; edges.append((P[best[2]][0],P[best[1]][0],round(best[0],2))); used.append(best[1])
    return tot, edges
P=[(f'{r}.{p}',x,y) for r,p,x,y in pts]
man=lambda a,c: abs(a[1]-c[1])+abs(a[2]-c[2])
print('manhattan MST', mst(P, man))
print('euclid MST', mst(P, lambda a,c: ((a[1]-c[1])**2+(a[2]-c[2])**2)**.5))
