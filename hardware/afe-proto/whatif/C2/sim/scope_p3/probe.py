import sys; sys.path.insert(0,'.')
from run import *
import time; t=time.time()
for lab,over in (("BOM 12/39",{}),("ideal C1, C2 38",dict(C1=None,C2=38e-12))):
    for rng in ("1.25","5"):
        r=ac_summary(pp(rng=rng,**over),"pr")
        print(lab,rng,f"bw {r['bw']/1e6:.2f} pk {r['peak_db']:.2f} pm {r['pm']:.1f}")
print(time.time()-t)
