import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from whatif import *
for csw, c2 in ((6e-12, 27.5e-12), (20e-12, 14.3729e-12)):
    b = pp(rng="1.25", Csw=csw, C2=c2)
    print(csw, g_bw2(b), g_bw2(dict(b, C1=9.6e-12)), g_bw2(dict(b, C1=10.8e-12)), g_bw2(b), "| Csw+8pF", g_bw2(dict(b, Csw=csw+8e-12)), "| C2 39 (old part)", g_bw2(dict(b, C2=39e-12)))
