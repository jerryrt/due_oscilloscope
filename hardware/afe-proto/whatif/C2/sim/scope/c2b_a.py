import sys, itertools; sys.path.insert(0,'.')
from run import *
def step(p):
    f,h,T=ac_response(p,"c2ba",fmin=1e2,fmax=1e8,ppd=40); a=np.abs(h); g=lambda x: np.interp(x,f,a)
    return (g(1e5)/g(1e3)-1)*100
xs=np.arange(30,38.01,1.0); ys=[step(pp(rng="5",C2=x*1e-12)) for x in xs]
k=np.polyfit(xs,ys,2); r=np.roots(k); z=[float(x.real) for x in r if 30<=x.real<=38][0]
print("step vs C2ext (Csw 0):", [f"{x:.0f}:{y:+.2f}" for x,y in zip(xs,ys)], "zero at", round(z,2))
for csw in (6.0,10.0,20.0):
    print("linearity Csw", csw, "C2", round(z-csw,2), "step", round(step(pp(rng="5",C2=(z-csw)*1e-12,Csw=csw*1e-12)),3), "%")
# series-parallel networks of {12,20,39} pF, up to 4 parts
V={1:{(c,(str(c),)) for c in (12.0,20.0,39.0)}}
for n in range(2,5):
    s=set()
    for a in range(1,n):
        for (x,px) in V[a]:
            for (y,py) in V[n-a]:
                s.add((round(x+y,4),("(%s || %s)"%(" ".join(px)," ".join(py)),)))
                s.add((round(x*y/(x+y),4),("(%s s %s)"%(" ".join(px)," ".join(py)),)))
    V[n]=s
best={}
for n in V:
    for v,d in V[n]:
        if v not in best or best[v][0]>n: best[v]=(n,d[0])
json.dump(dict(zero=z),open("results/c2b_zero.json","w"))
for csw in (6.0,10.0,20.0):
    t=z-csw; c=sorted(best.items(), key=lambda kv: (abs(kv[0]-t)))[:12]
    print(f"Csw {csw}: target C2 {t:.2f} pF ->", "; ".join(f"{v:.2f} pF ({(v/t-1)*100:+.1f} %, {n} parts: {d})" for v,(n,d) in c))
