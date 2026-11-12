"""Write a translated scratch copy of TI's LM27762_TRANS.LIB.  TI's file is read in place and never modified;
the copy goes to the session scratch directory given as argv[2] (outside the repository, MC-6).
Each patch is named so a run can say which ones it used.  usage: patch_lib.py PATCHES OUTFILE  (PATCHES: comma list or 'none')"""
import hashlib, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "../../models/lm27762/LM27762_TRANS.LIB")
SHA = "16c322a7ad5f3ff2b5a7bb1355f4474ec12fe7335487aed5ec1b1dff293af42a"   # models/SOURCES.md
PATCHES = {
    # D_DBACK: N=0.001 is a 26 uV thermal voltage; ngspice's junction limiting stalls on it
    "ddback": [(".MODEL D_DB D( Rs=0.001 N=0.001)", ".MODEL D_DB D( Rs=0.001 N=0.05)")],
    # d_d: n=0.01 (260 uV) used as an ideal diode in the RC delays
    "dd": [("+ n=0.01\n", "+ n=0.05\n")],
    # PHI1 / PHI2 are IF() steps with no RC, driving the log-interpolated switches directly; every other gate in TI's file
    # has 1 ohm / 1 nF on its output.  Give these two the same, so the switches see a 1 ns edge instead of a discontinuity.
    "phi": [("E_ABM3         PHI2 0 VALUE", "R_PHI2X PHI2_X PHI2 1\nC_PHI2X PHI2 0 1n\nE_ABM3         PHI2_X 0 VALUE"),
            ("E_ABM2         PHI1 0 VALUE", "R_PHI1X PHI1_X PHI1 1\nC_PHI1X PHI1 0 1n\nE_ABM2         PHI1_X 0 VALUE")],
    # the same for the other un-filtered IF() outputs that drive switches: PRECH_PULSE (S15) and N17559799 (S2, CPOUT pull)
    "edges": [("E_U5_ABM7         PRECH_PULSE 0 VALUE", "R_PRX PRECH_X PRECH_PULSE 1\nC_PRX PRECH_PULSE 0 1n\nE_U5_ABM7         PRECH_X 0 VALUE"),
              ("E_ABM9         N17559799 0 VALUE", "R_N99X N99_X N17559799 1\nC_N99X N17559799 0 1n\nE_ABM9         N99_X 0 VALUE")],
    # the four pump switches (S11-S14) are off at 1e12 ohm in series with 0 V current probes (V14-V16): the probe currents
    # are then solved to round-off (~1e-9 A noise against ampere currents) and ngspice's convergence test on them stalls.
    # 1e9 ohm, as TI's own S15 and S1 already use, leaks 5 nA at 5 V.
    "roff": [("Roff=1e12", "Roff=1e9")],
    # D_D1 (N = 0.1, 2.6 mV thermal voltage) clamps the latch / flip-flop integrators (GQ = +-5 A into 1 nF) at 0 and 1 V
    # and the oscillator ramp at 5 V; ngspice stalls on it about 20 us into pumping.  N = 1 makes the clamp an ordinary
    # diode; the logic thresholds (0.5 V) are inside the clamped range either way.
    "dfd": [(".MODEL D_D1 D( IS=1e-15 TT=10p Rs=0.05 N=.1  )", ".MODEL D_D1 D( IS=1e-15 TT=10p Rs=0.05 N=1  )")],
    "dfd5": [(".MODEL D_D1 D( IS=1e-15 TT=10p Rs=0.05 N=.1  )", ".MODEL D_D1 D( IS=1e-15 TT=10p Rs=0.05 N=.5  )")],
    # d_d has no series resistance; as the fast-reset diode of the 1 uF timers (PFM U25, enable delays U5/U8) it dumps 1 uF
    # in picoseconds when an IF() comparator output steps, and ngspice stalls on the PFM timer node.  10 mohm makes that
    # a 10 ns discharge, against the 250 ns pump half-period and the 1 us timer.
    "ddrs": [("+ tt=1e-011\n", "+ tt=1e-011\n+ rs=0.01\n")],
    # E4 gate drive of M1: 1.7*V/((0.75*V/-0.5)-0.7) has a pole at V(CPOUT) = -0.467 V, which the pump crosses on every
    # start-up; PSpice steps over it, ngspice's Newton stalls (timestep too small).  Clamp the gate drive at 10 mV, where M1
    # already passes 50 A (KP 1e6) and the 1.2 A limit of M2 (Vgs 1.55 mV) governs, as it does either side of the pole.
    "lim": [("+  IF(V(U_SW_ARRAY_ILIM_COMP)>0.5,SQRT(", "+  IF(V(U_SW_ARRAY_ILIM_COMP)>0.5,MIN(10m,SQRT("),
            ("),1m)\n+  }", ")),1m)\n+  }")],
    # E4 gate drive: sqrt(abs(x)) has an infinite derivative at x = 0 (CPOUT = 0 before the pump runs)
    "sqrt": [("/(-1000000)))", "/(-1000000))+1e-12)")],
}
import re
def vswitch_to_sw(t):
    """PSpice VSWITCH (smooth between Voff and Von) -> ngspice SW (abrupt at VT = (Voff+Von)/2, no hysteresis)."""
    def f(m):
        name, roff, ron, voff, von = m.groups()
        vt = (float(voff) + float(von)) / 2
        return f".MODEL {name} SW Roff={roff} Ron={ron} VT={vt:g} VH=0"
    t2, n = re.subn(r"\.MODEL\s+(\S+)\s+VSWITCH\s+Roff=(\S+)\s+Ron=(\S+)\s+Voff=([-0-9.e]+)V?\s+Von=([-0-9.e]+)V?", f, t)
    assert n == 10, n
    return t2
raw = open(SRC, "rb").read()
assert hashlib.sha256(raw).hexdigest() == SHA, "TI file does not match SOURCES.md"
t = raw.decode("latin-1").replace("\r\n", "\n")
use = [] if sys.argv[1] == "none" else sys.argv[1].split(",")
for p in use:
    if p == "sw":
        t = vswitch_to_sw(t); continue
    for a, b in PATCHES[p]:
        assert t.count(a) == (4 if p == "roff" else 1), (p, a, t.count(a))
        t = t.replace(a, b)
open(sys.argv[2], "w", encoding="latin-1").write(t)
print("patched:", use or "none", "->", sys.argv[2])
