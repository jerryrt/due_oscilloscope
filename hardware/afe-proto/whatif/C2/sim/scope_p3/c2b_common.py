import sys; sys.path.insert(0,'.')
from run import *
from whatif import bw_rel
CASES = {"Csw6_C2_27.5": (6e-12, 27.5e-12, "N on S1, CSOFF 6 pF (datasheet); C2 = 20 || (12 s 20), 3 parts"),
         "Csw10_C2_24": (10e-12, 24e-12, "N on S1, IBIS sterm_3.3 C_comp 10.1 pF; C2 = 12 || 12, 2 parts"),
         "Csw20_C2_14.37": (20e-12, 14.3729e-12, "N on D, CDON 20 pF (BOM review); C2 = 20 s (12 || 39), 3 parts"),
         "Csw20_C2_39": (20e-12, 39e-12, "BOM review's switch with the old 39 pF (uncompensated reference)")}
def comp_row(p):
    out = {}
    for rng in ("5", "1.25"):
        q = dict(p, rng=rng)
        f, h, T = ac_response(q, "cr", fmin=1e2, fmax=2e9, ppd=40); a = np.abs(h); g = lambda x: np.interp(x, f, a)
        flat = max(abs(20*np.log10(g(x)/g(1e5))) for x in (1e6, 2e6, 4e6, 6e6, 8e6))
        m = freq_metrics(f[f >= 1e4], h[f >= 1e4])
        out[rng] = dict(step10k=(g(1e4)/g(1e3)-1)*100, step100k=(g(1e5)/g(1e3)-1)*100, flat_1_8MHz_db=flat,
                        bw10k=m["bw"], bwDC=bw_rel(f, h, 1e2), bw100k=bw_rel(f, h, 1e5), pk_vs_DC=float(20*np.log10(a[f > 1e2].max()/g(1e2))))
    return out
