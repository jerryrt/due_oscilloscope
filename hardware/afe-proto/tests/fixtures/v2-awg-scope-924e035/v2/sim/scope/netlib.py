"""Netlist builders and ngspice plumbing for the version 2 scope channel (both channels on one TPH2502 dual).

Imported by run.py (python3 -I run.py puts this directory on sys.path).

The op-amp is one instance of the vendor's TPH2501_simplify macro per channel (pin order IN+ IN- V+ V- OUT).  The
macro lives in hardware/afe-proto/whatif/tph2502/models/ and is referenced from there, never copied (MC-6); its
sha256 is checked by run.py against models/VENDOR_MODEL.sha256.  It is a SINGLE-amplifier model of the TPH2501,
which shares the TPH2502's die: nothing in it couples two channels, and its input stage is one PMOS pair with no
rail-to-rail crossover.  Everything that depends on those two facts is marked in report.md.
"""
import os, re, subprocess
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
NETD = os.path.join(HERE, "netlists")
WORK = os.path.join(HERE, "work")
WORK_REL = "../work"
OPAMP_MDL_REL = "../../../../whatif/tph2502/models/TPH2501_ngspice.mdl"       # from netlists/
OPAMP_MDL = os.path.normpath(os.path.join(NETD, OPAMP_MDL_REL))
SUB = "TPH2501_simplify"
PFX = ""

# ---------------------------------------------------------------------------------------------------------
# Nominal design.  Every number here is either a design value (the first block) or an assumption marked (check).
# ---------------------------------------------------------------------------------------------------------
P0 = dict(
    # --- design values (v2/sim/scope/design.md) ---
    R1=(510e3, 30e3),            # series pair, 540 k (budget/v2_scope.py; Basic 0603 C23192 + C22984)
    R2=(1e6, 510e3),             # 1.51 M (C22935 + C23192)
    R3=(470e3, 200e3),           # 670 k (C23178 + C25811)
    C1=22e-12,                   # across R1 (C0G 0603, C1653)
    Cn=12e-12,                   # added at N (C0G 0603, C38523); was 22 pF before Cpx (Cpx is 10 pF more at N up to its 34 MHz pole)
    Rnp=470.0,                   # ahead of the amplifier's + input (C23179)
    Cpx=10e-12,                  # +IN to ground after Rnp (C0G, C1634): removes the Rnp x input-capacitance lag (AN-1)
    RF=0.0,                      # follower feedback resistor out -> -IN (decided in design.md)
    Riso=22.0,                   # amplifier output -> ADC pin (C23345)
    pinclamp=True,               # BAV99 at the ADC pin
    # --- parasitics and sources, all *(assumption)* ---
    Cwire=4e-12,                 # BNC + trace at the input
    Cr1=0.1e-12,                 # across the R1 pair (two 0603 bodies)
    Cn_par=3.5e-12,               # pads of R1/R2/R3/Rnp, the trace, at N (the macro adds about 0.5 pF more)
    Cfb=1e-12,                   # pad at the inverting input
    Cpin=2e-12,                  # package + pad at the ADC pin (v1's figure)
    Ccl=1.5e-12,                 # BAV99 at the pin: CJ 1.5 pF, *(check: datasheet)*
    Rsrc=50.0,
    adc=dict(ron=3.8e3, cs=6e-12),   # v1's derived ADC input (sim/scope/run.py ADC_DERIVED)
    vcc=3.3, vr=3.0, aref=3.3, vos=0.0,
    rail_r=0.1, rail_l=10e-9, esr=0.02,
    Zref_r=0.05,                 # REF3030E closed-loop output impedance: 15 ppm/mA source = 0.045 ohm (ref30.pdf, 6.5)
    xt=0.0,                      # input-referred channel crosstalk, V/V, injected a -> b (0 = none)
    Cx=0.0,                      # stray capacitance between the two channels' N nodes
    Cxin=0.0,                    # stray capacitance between the two channels' input nodes
    Cxp=0.0,                     # stray capacitance between the two channels' +IN pads (the dual's pins 3 and 5), after Rnp / Cpx
)

# generic silicon ESD diode: 0.60 V at 10 uA, 0.72 V at 1 mA *(assumption: no datasheet gives the I-V)*, as v1
DESD = ".model DESD D(IS=1e-15 N=1 RS=5)\n"
# BAV99 class, recalled not read *(check: Nexperia datasheet is not in the repository, download blocked, models/SOURCES.md)*
DBAV99 = ".model DBAV99 D(IS=7.8e-9 N=2.35 RS=1.5 CJO=1.5p M=0.4 VJ=0.7 BV=70 IBV=2.5u)\n"


def rsum(t):
    return float(sum(t))


def rp_of(p):
    r1, r2, r3 = rsum(p["R1"]), rsum(p["R2"]), rsum(p["R3"])
    return 1 / (1 / r1 + 1 / r2 + 1 / r3)


def header(title, extra=""):
    return (f"* {title}\n.include {OPAMP_MDL_REL}\n{DESD}{DBAV99}"
            ".options abstol=1e-13 itl1=4000 itl4=500 reltol=1e-4 method=gear\n" + extra)


def rails(p, ac_vcc=False):
    """+3.3 V supply, and the REF3030E as the AC ground of every R3."""
    return f"""* supply: ideal {p['vcc']} V behind {p['rail_r']} ohm + {p['rail_l']*1e9:g} nH, 100 nF + 1 uF at the amplifier
Vcc vcc0 0 dc {p['vcc']} {'ac 1' if ac_vcc else ''}
Rvc vcc0 vcx {p['rail_r']}
Lvc vcx vccl {p['rail_l']}
Cdc1 vccl cd1 100n
Rdc1 cd1 0 {p['esr']}
Cdc2 vccl cd2 1u
Rdc2 cd2 0 {p['esr']}
* REF3030E: {p['vr']} V behind {p['Zref_r']} ohm, 1 uF + 100 nF at its output (the ladder's top tap also loads it)
Vr vr0 0 dc {p['vr']}
Rvr vr0 ref {p['Zref_r']}
Cr1u ref cr1 1u
Rcr1 cr1 0 {p['esr']}
Cr100 ref cr2 100n
Rcr2 cr2 0 {p['esr']}
"""


def chan(p, k, loopbreak=False, esd=False, inj=False):
    """One channel.  Nodes: {k}in (BNC), {k}n (the divider node), {k}np (+IN), {k}fb (-IN), {k}out, {k}pin (ADC pin).
    esd=True adds the amplifier's input ESD diodes to the rails at +IN (the vendor macro has none) for the
    protection runs.  inj=True puts a 1 V ac source in series with the amplifier's +IN pin (after Rnp and Cpx), the
    place an input-referred voltage noise sits: the noise sections use it to get the transfer from the amplifier's own
    noise to the output.  Supply nodes: vccl, 0.  REF node: ref."""
    s = []
    a = s.append
    r1a, r1b = p["R1"]
    r2a, r2b = p["R2"]
    r3a, r3b = p["R3"]
    a(f"* channel {k}")
    a(f"Rs{k} {k}src {k}in {p['Rsrc']:.6g}")
    a(f"Cw{k} {k}in 0 {p['Cwire']:.6g}")
    a(f"R1a{k} {k}in {k}m1 {r1a:.6g}\nR1b{k} {k}m1 {k}n {r1b:.6g}")
    a(f"C1{k} {k}in {k}n {p['C1']:.6g}")
    a(f"Cr1{k} {k}in {k}n {p['Cr1']:.6g}")
    a(f"R2a{k} {k}n {k}m2 {r2a:.6g}\nR2b{k} {k}m2 0 {r2b:.6g}")
    a(f"R3a{k} {k}n {k}m3 {r3a:.6g}\nR3b{k} {k}m3 ref {r3b:.6g}")
    a(f"Cn{k} {k}n 0 {p['Cn']:.6g}")
    a(f"Cnp{k} {k}n 0 {p['Cn_par']:.6g}")
    src = f"{k}n"
    if p.get("xt") and k == "b":     # input-referred crosstalk from channel a's output, in series with b's + input
        a(f"Exb {k}nx {k}n aout 0 {p['xt']:.6g}")
        src = f"{k}nx"
    if p.get("vos"):
        a(f"Vos{k} {src} {k}nv dc {p['vos']:.6g}")
        src = f"{k}nv"
    if p["Rnp"] > 0:
        a(f"Rnp{k} {src} {k}np {p['Rnp']:.6g}")
    else:
        a(f"Vnp{k} {src} {k}np dc 0")
    if p.get("Cpx"):
        a(f"Cpx{k} {k}np 0 {p['Cpx']:.6g}")
    amp_in = f"{k}np"
    if inj:
        a(f"Ven{k} {k}np {k}npi dc 0 ac 1")
        amp_in = f"{k}npi"
    if esd:
        a(f"Desu{k} {k}np {k}esu DESD\nVesu{k} {k}esu vccl dc 0\nDesd{k} {k}esd {k}np DESD\nVesd{k} 0 {k}esd dc 0")
    oa = f"{k}outa" if loopbreak else f"{k}out"
    a(f"XU{k} {amp_in} {k}fb vccl 0 {oa} {SUB}")
    if loopbreak:
        a(f"Vlb{k} {k}out {k}outa dc 0 ac 1")
    if p["RF"] > 0:
        a(f"RF{k} {k}out {k}fb {p['RF']:.6g}")
    else:
        a(f"Vfb{k} {k}out {k}fb dc 0")
    a(f"Cfb{k} {k}fb 0 {p['Cfb']:.6g}")
    a(f"Riso{k} {k}out {k}pin {p['Riso']:.6g}")
    a(f"Cpin{k} {k}pin 0 {p['Cpin']:.6g}")
    if p["pinclamp"]:
        a(f"Dpa{k} 0 {k}pin DBAV99\nDpb{k} {k}pin vccl DBAV99")     # BAV99: GND / pin / AFE +3.3 V_A
    return "\n".join(s) + "\n"


def coupling(p):
    t = ""
    if p.get("Cx"):
        t += f"Cxn an bn {p['Cx']:.6g}\n"
    if p.get("Cxin"):
        t += f"Cxi ain bin {p['Cxin']:.6g}\n"
    if p.get("Cxp"):
        t += f"Cxp anp bnp {p['Cxp']:.6g}\n"
    return t


def write_net(name, text):
    os.makedirs(NETD, exist_ok=True)
    path = os.path.join(NETD, PFX + name + ".cir")
    with open(path, "w") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    return path


def run_ng(name, text, timeout=900):
    os.makedirs(WORK, exist_ok=True)
    path = write_net(name, text)
    r = subprocess.run(["ngspice", "-b", os.path.basename(path)], cwd=NETD, capture_output=True, text=True,
                       timeout=timeout)
    return r.stdout + r.stderr


def wr(name, key):
    return f"{WORK_REL}/{PFX}{name}_{key}.dat"


def load(name, key):
    return np.atleast_2d(np.loadtxt(os.path.join(WORK, f"{PFX}{name}_{key}.dat")))


def ngspice_version():
    out = subprocess.run(["ngspice", "-v"], capture_output=True, text=True).stdout
    for l in out.splitlines():
        if "ngspice" in l.lower() and re.search(r"\d", l):
            return l.strip("* ").strip()
    return out.strip()
