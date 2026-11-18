import sys; sys.path[:0]=['/work/hardware/pcbkit/tests','/work/hardware/pcbkit']
import numpy as np
from pcbkit import fills
# a staircase band of cells
c=np.zeros((14,14),bool)
for i in range(10): c[i:i+2,i:i+2]=True
loops=fills._loops(c)
print(len(loops), [fills._area2(l) for l in loops])
d=fills._diagonalise([l for l in loops if fills._area2(l)>0][0])
print(d, fills._octilinear(d))
