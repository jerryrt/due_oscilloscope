import sys; sys.path.insert(0,'.')
from run import *
for p in (pp(rng="1.25", RG=60.4), pp(rng="1.25", RG=60.4, C2=33e-12), pp(rng="1.25", RG=30.1, C2=33e-12)):
    a=ac_summary(p,"nzc"); print(p["RG"], p["C2"], a["bw"]/1e6, noise_total(p,"nzc",1.5*a["bw"],"all")*1e6)
