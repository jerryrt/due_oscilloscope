import sys; sys.path.insert(0,'.')
from run import *
from whatif import bw_rel
# implied C2tot at N with each model: fit HF/DC ratio at 100 kHz against the divider
for op in ("OPA365","OPA354"):
    for c2 in (30e-12, 33e-12, 36e-12, 39e-12):
        out=[]
        for rng in ("5","1.25"):
            f,h,T=ac_response(pp(op=op,rng=rng,C2=c2),"cmp",fmin=1e2,fmax=2e9,ppd=40)
            a=np.abs(h); g=lambda x: np.interp(x,f,a)
            m=freq_metrics(f[f>=1e4],h[f>=1e4])
            out.append(f"{rng}: step100k {(g(1e5)/g(1e2)-1)*100:+.2f} % bw10k {m['bw']/1e6:.2f} bwDC {bw_rel(f,h,1e2)/1e6:.2f} bw100k {bw_rel(f,h,1e5)/1e6:.2f} pk {20*np.log10(a[f>1e2].max()/g(1e2)):.2f}")
        print(op, f"C2 {c2*1e12:.0f}p", " | ".join(out), flush=True)
