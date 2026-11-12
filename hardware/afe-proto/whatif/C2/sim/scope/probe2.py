import sys; sys.path.insert(0,'.')
from run import *
for op in ("OPA365","OPA354"):
  for rng in ("1.25","5"):
    for lab,over in (("BOM",{}),("ideal",dict(C1=None,C2=38e-12))):
        f,h,T=ac_response(pp(op=op,rng=rng,**over),"pr2",fmin=1e2,fmax=1e8,ppd=20)
        a=np.abs(h); g=lambda x: np.interp(x,f,a)
        print(op,rng,lab," ".join(f"{x:.0e}:{20*np.log10(g(x)/g(1e2)):+.3f}" for x in (1e3,1e4,1e5,1e6,4e6,7e6)))
