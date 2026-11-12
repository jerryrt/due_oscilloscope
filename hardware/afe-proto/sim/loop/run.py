#!/usr/bin/env python3
"""SM-5 shown by simulation: the AWG-to-scope loop with a PAM16 pattern at 1.6 Msym/s.

    python3 -I run.py              # every case; writes results/*.json, prints the tables
    python3 -I run.py fit base     # selected cases (keys of CASES, in order)

DAC0 (behavioural, fitted to the Due's measured edges) -> AWG stage (OPA365, copied from
sim/awg revision 5 with the -2.073 V negative rail) -> 49.9 ohm -> 1 m of 50 ohm line ->
scope channel (sim/scope's netlist builder, imported in place: divider, OPA354 stage,
Riso 22) -> the Due's ADC pin with sim/scope's sample-and-hold model.  The baseline is
the same DAC model straight into the same ADC pin model.

The level band is computed as tools/ets_pam.py (host/etspam.py) computes it: the symbol
boundary is the centre of the folded staircase's movement, each level is read in the middle
fifth of its symbol, and the band is the width of a level there.  The simulation is
noise-free, so the band is the deterministic spread (ISI and settling); noise is combined
afterwards by the arithmetic of docs/afe.md (report.md shows it).

numpy only.  ngspice 47 in batch mode.  TI models are referenced in place from
../../models and never copied (models/SOURCES.md).
"""
import json, os, re, subprocess, sys, time, hashlib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
SCOPE = os.path.join(HERE, "..", "scope")
sys.path.insert(0, SCOPE)
sys.path.insert(0, os.path.join(ROOT, "host"))
import netlib as SN            # sim/scope's channel builder, read in place (not edited)
import etspattern              # the PAM16 pattern exactly as tools/ets_pam.py plays it

NETD = os.path.join(HERE, "netlists")
WORK = os.path.join(HERE, "work")
RES = os.path.join(HERE, "results")
for d in (NETD, WORK, RES):
    os.makedirs(d, exist_ok=True)

# ------------------------------------------------------------------ fixed facts and their sources
MCK = 90e6
TICK = 2 / MCK                    # one timer tick, 22.2 ns (every RC divides MCK/2)
RC_DAC = 28                       # 1,607,143 sym/s: the 1.6 Msym/s of docs/afe.md 4.2 / ets-pam.md
TSYM = RC_DAC * TICK              # 622.2 ns
PAM = 16
PAT = etspattern.pattern(PAM)     # PRBS9 read 4 bits per symbol, 511 symbols, every ordered pair
# DAC volts per code: the measured window 0.578-2.771 V over codes 0..4095 (docs/hardware.md,
# docs/afe.md 4.1).  etspattern places the levels with 2214 mV / 4095 per code; the window
# measured with a scope on the pin is used for the voltage, 2193 mV / 4095.
DAC_V0, DAC_V1 = 0.578, 2.771
dac_volts = lambda code: DAC_V0 + code * (DAC_V1 - DAC_V0) / 4095
# ETS edge measurements, linux-x1, DAC RC 28 (docs/ets-mode.md "The ADC's share of an edge")
ETS_RISE = {999: 136.75e-9, 699: 98.89e-9, 499: 76.59e-9, 350: 62.65e-9, 250: 54.42e-9, 175: 48.60e-9}
ETS_FALL = {999: 127.61e-9, 699: 91.59e-9, 499: 73.24e-9, 350: 61.89e-9, 250: 55.52e-9, 175: 52.02e-9}
FLOOR_RISE, FLOOR_FALL = 42.4e-9, 45.4e-9
# ADC sample-and-hold, as sim/scope uses it (derived from tTRACK = 0.054 Z + 205 ns; Ci <= 8 pF)
ADC = {"derived": dict(ron=3.8e3, cs=6e-12), "stress": dict(ron=1.0e3, cs=8e-12)}
CPIN = 2e-12                      # pad/package at the pin, as sim/scope (P0['Cpin'])
AREF_CODES = 3.20                 # codes are counted at AREF 3.20 V: the most codes per mV (worst)
LABEL_BINS = 280                  # positions per symbol: 28 ticks x LABEL_K 10 (host/etspam.py)
CENTRE_HALF = 0.1                 # host/etspam.py: the middle fifth of a symbol
NPRE = 160                        # preamble symbols (the end of the period) before the measured period
# SM-5 inputs (docs/afe.md section 4.2, SC-6, AW-6, SC-11)
DUE_BAND = (8.6, 11.4)            # codes, same-board, no probes
DUE_FLOOR_MV = 0.64               # the Due's held-code floor, 0.8 codes (afe.md 4.1; AW-6's arithmetic)
SC6_MV, AW6_MV = 0.2, 0.1
LIMIT = 0.10

# AWG, sim/awg revision 5 FINAL set, copied; negative rail -2.073 V per the change in progress
VN_AWG = -2.073
AWG0 = dict(op="OPA365", Ra=13.7e3, Rb=15.8e3, Rx=330e3, Rf=249.0 + 49.9, Rg=249.0, Rs=49.9,
            Ca=20e-12, Cb=12e-12, Cpar_p=1.5e-12, Cpar_n=2.0e-12, Cf=0.0,
            vmid=1.65, rvm=1.0, cvm=10e-6, vp=3.3, vn=VN_AWG, rflt=10.0, cpin=100e-9, cbulk=10e-6,
            clamp=True)
AWG_LIBS = {"OPA365": "../../../models/opa365/OPA365_PSPICE.lib",
            "OPA354": "../../../models/opa354/OPA354_PSPICE.lib"}
# scope channel: sim/scope's settled design (report.md: C1 12 pF, C2 39 pF part, R2 335k leg)
SCOPE0 = dict(SN.P_LEGACY, op="OPA354", rng="1.25", C1=12e-12, C2=39e-12, R2=335e3)
# cable: 1 m of 50 ohm line, 5 ns, lossless, open into the scope input (AW-4, MC-8, SC-3)
CABLE0 = dict(td=5e-9, z0=50.0)

OUT = {}


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


# ------------------------------------------------------------------ DAC model: slew -> pole -> Rout
def expm(A):
    """Matrix exponential by scaling and squaring of a Taylor series (numpy only)."""
    n = np.linalg.norm(A, 1)
    s = max(0, int(np.ceil(np.log2(n))) + 1) if n > 0 else 0
    B = A / 2 ** s
    E = np.eye(len(A)); T = np.eye(len(A))
    for k in range(1, 20):
        T = T @ B / k; E = E + T
    for _ in range(s):
        E = E @ E
    return E


def base_numeric(step, slew, taud, ron, cs, rout=0.0, dt=0.05e-9, tend=600e-9, cpin=CPIN):
    """The baseline DAC -> pin -> S/H network as a linear state space driven by the
    slew-limited step: returns t, v(cs).  Used to fit the DAC's pole to the measured floor."""
    t = np.arange(0, tend, dt)
    u = np.clip(t * slew / abs(step), 0, 1) * step if slew else np.full_like(t, step)
    taud = max(taud, 1e-12)
    rout = max(rout, 1e-3)
    A = np.array([[-1 / taud, 0, 0],
                  [1 / (rout * cpin), -1 / (rout * cpin) - 1 / (ron * cpin), 1 / (ron * cpin)],
                  [0, 1 / (ron * cs), -1 / (ron * cs)]])
    Bv = np.array([1 / taud, 0, 0])
    M = np.zeros((4, 4)); M[:3, :3] = A; M[:3, 3] = Bv
    E = expm(M * dt)
    Ad, Bd = E[:3, :3], E[:3, 3]
    x = np.zeros(3); out = np.empty_like(t)
    for i, ui in enumerate(u):
        out[i] = x[2]; x = Ad @ x + Bd * ui
    return t, out


def rise_10_90(t, v):
    v = v / v[-1]
    return float(t[np.argmax(v >= 0.9)] - t[np.argmax(v >= 0.1)])


def fit_dac(adc, rout=0.0, floor=FLOOR_RISE, ref=ETS_RISE):
    """Pole taud so the small-step 10-90 equals the measured floor; then slew S so the
    999 mV edge equals its measured rise.  Returns (taud, slew, notes)."""
    def rr(taud, slew, step):
        return rise_10_90(*base_numeric(step, slew, taud, adc["ron"], adc["cs"], rout))
    r0 = rr(1e-12, 0, 1.0)
    if r0 >= floor:
        taud = 1e-12
        note = f"the S/H alone gives {r0*1e9:.1f} ns, above the measured {floor*1e9:.1f} ns floor: DAC pole set to 0"
    else:
        lo, hi = 1e-12, 60e-9
        for _ in range(40):
            m = 0.5 * (lo + hi)
            lo, hi = (m, hi) if rr(m, 0, 1.0) < floor else (lo, m)
        taud = 0.5 * (lo + hi); note = ""
    lo, hi = 2e6, 30e6       # V/s
    for _ in range(40):
        m = 0.5 * (lo + hi)
        lo, hi = (lo, m) if rr(taud, m, 0.999) < ref[999] else (m, hi)
    slew = 0.5 * (lo + hi)
    pred = {k: rr(taud, slew, k / 1000) for k in ref}
    return taud, slew, note, pred


# ------------------------------------------------------------------ netlists
def dac_lines(dac, pwl):
    """Ideal slew-limited staircase -> one pole (taud) -> output resistance -> node 'dac'."""
    taud = max(dac["taud"], 1e-12)
    return [f"Vdp dsrc 0 PWL({pwl})",
            f"Rdp dsrc dp 1k", f"Cdp dp 0 {taud/1e3:.6g}",
            f"Edb db 0 dp 0 1", f"Rdo db dacp {max(dac['rout'], 1e-3):.6g}"]


def vmid_awg(a):
    if a.get("vmid_gen") == "divider":      # sim/awg variant buf: its own 330k/330k divider, 12 pF, bare follower
        return awg_vmid_divider_lines("_g", lin=a.get("vm_lin", True))
    if a.get("vmid_gen"):
        return vmid_gen_lines("a_vm", a["vmid"], "_g", lin=a["vmid_gen"] == "lin")
    return [f"Xavm a_vms 0 VMID_BUF params: v={a['vmid']} rout={a['rvm']}",
            f"Rvmx a_vms a_vm 1m", f"Cvm1 a_vm a_vmc {a['cvm']}", "Re1 a_vmc 0 0.02",
            "Cvm2 a_vm a_vmd 100n", "Re2 a_vmd 0 0.05"]


def rnet(spec, name, a, b, cnode, L, ctr):
    """whatif/awg-rab's network builder: a number is one part, a list is in series, a tuple in parallel;
    every node a series string adds gets cnode to ground (copied, 2026-11-11)."""
    if isinstance(spec, list):
        nodes = [a] + [f"{name.lower()}n{next(ctr)}" for _ in spec[:-1]] + [b]
        for x, (u, v) in zip(spec, zip(nodes, nodes[1:])):
            rnet(x, name, u, v, cnode, L, ctr)
        for nd in nodes[1:-1]:
            L.append(f"C{nd}p {nd} 0 {cnode:.6g}")
    elif isinstance(spec, tuple):
        for x in spec:
            rnet(x, name, a, b, cnode, L, ctr)
    else:
        L.append(f"{name}{next(ctr)} {a} {b} {spec}")


def awg_lines(a):
    """sim/awg revision 5 FINAL, prefixed a_ so it shares no node with sim/scope's core.
    With Ra_spec/Rb_spec, the resistors are networks of parts (whatif/awg-rab variant n1)."""
    if a.get("inv"):
        return inv_lines(a)
    L = []; src = "dacp"
    if a.get("buf"):      # DAC0 buffered by a unity-gain OPA365 on +3.3 V_A (own Schottky, 100 nF), 680 ohm in, 330k to Vmid
        bo = "a_boo" if a.get("pm_buf") else "a_bo"
        L += ["Rbin dacp a_bin 680", f"Rbpl a_bin {'0' if a.get('bias_gnd') else 'a_vm'} 330k",
              "Dbs a_vcc a_bvc DBAT54", "Visb a_bvc a_bvcx 0", "Cbd a_bvcx a_bcd 100n", "Rbcd a_bcd 0 0.05",
              f"X2 a_bin a_bo a_bvcx 0 {bo} OPA365"]
        if a.get("pm_buf"):
            L.append("Vinjb a_bo a_boo DC 0 AC 1")
        L.append(f"Cbo a_bo 0 {a['Cpar_p']}")
        src = "a_bo"
    if a.get("Ra_spec"):
        import itertools
        ctr = itertools.count(1)
        cn = 0.3e-12 * a["Cpar_p"] / 1.5e-12          # whatif/awg-rab CNODE, scaled with the V+ corner
        rnet(a["Ra_spec"], "Ra", src, "a_vp0", cn, L, ctr)
        rnet(a["Rb_spec"], "Rb", "a_vp0", "0", cn, L, ctr)
    else:
        L += [f"Ra {src} a_vp0 {a['Ra']}", f"Rb a_vp0 0 {a['Rb']}"]
    if a["Ca"]: L.append(f"Ca {src} a_vp0 {a['Ca']}")
    if a["Rx"]: L.append(f"Rx a_vp0 a_vm {a['Rx']}")
    L += [f"Cpp a_vp0 0 {a['Cpar_p'] + a['Cb']}", "Vosa a_vp0 a_vp DC 0",
          f"Rf a_out a_inv {a['Rf']}"]
    if a["Cf"]: L.append(f"Cf a_out a_inv {a['Cf']}")
    L += [f"Rg a_inv a_vm {a['Rg']}", f"Cpn a_inv 0 {a['Cpar_n']}",
          *vmid_awg(a),
          f"Xsup a_sp a_sn 0 LM27762_BEH params: vp={a['vp']} vn={a['vn']} rp=0.2 rn=0.2 rsink=1e9 rbl=4.7k",
          f"Cb1 a_sp a_cb1 {a['cbulk']}", "Rcb1 a_cb1 0 0.02", f"Cb2 a_sn a_cb2 {a['cbulk']}", "Rcb2 a_cb2 0 0.02",
          f"Rfp a_sp a_vcc {a['rflt']}", f"Rfn a_sn a_vee {a['rflt']}",
          f"Cp1 a_vcc a_cp1 {a['cpin']}", "Rcp1 a_cp1 0 0.05", f"Cp2 a_vee a_cp2 {a['cpin']}", "Rcp2 a_cp2 0 0.05",
          "Dsp a_vcc a_vcc2 DBAT54", "Visp a_vcc2 a_vccx 0", "Dsn a_veex a_vee3 DBAT54", "Visn a_vee3 a_vee 0",
          f"X1 a_vp a_inv a_vccx a_veex {'a_oo' if a.get('pm') else 'a_out'} {a['op']}"]
    if a.get("pm"):      # Middlebrook injection at the op-amp output: T = -V(a_oo)/V(a_out)
        L.append("Vinj a_out a_oo DC 0 AC 1")
    L += [f"Rs a_out bnc {a['Rs']}"]
    if a["clamp"]:       # 3-diode BAV99 stacks each way to ground on the op-amp side (sim/awg S1)
        L += ["Dga1 a_out ga1 DBAV99", "Dga2 ga1 ga2 DBAV99", "Dga3 ga2 0 DBAV99",
              "Dgb1 0 gb1 DBAV99", "Dgb2 gb1 gb2 DBAV99", "Dgb3 gb2 a_out DBAV99"]
    # element names get an _a suffix so none collides with sim/scope's core and rails
    return [re.sub(r"^(\S+)", r"\1_a", l) for l in L]


# ------------------------------------------------------------------ the inverting AWG (owner's route, 2026-11-11)
# DAC0 -> Rin -> (-); Rf from the output; (+) at Vref' = Vmid x G/(1+G) from a divider off the AWG's Vmid.
# Values from existing types only: Rin = 4 x 4.7k + 680 = 19.48k (AW-5), Rf = (5 x 4.7k) || 330k = 21.94k,
# G = 1.1263; Vref' divider: top (174k || 174k) + 1k + 680 = 88.68k, bottom 100k (ratio 0.52999 vs G/(1+G) 0.52968),
# decoupled by 100 nF.  Every node a series string adds carries 0.3 pF, scaled with the parasitic corner *(check)*.
INV = dict(inv=True, Rin_spec=[4.7e3, 4.7e3, 4.7e3, 4.7e3, 680.0],
           Rf_spec=([4.7e3, 4.7e3, 4.7e3, 4.7e3, 4.7e3], 330e3),
           Rt_spec=[(174e3, 174e3), 1e3, 680.0], Rbot_spec=100e3, Cref=100e-9, Cf=0.0, Ca=0.0, Cb=0.0)


def rspec_val(spec):
    if isinstance(spec, list): return sum(rspec_val(x) for x in spec)
    if isinstance(spec, tuple): return 1.0 / sum(1.0 / rspec_val(x) for x in spec)
    return spec


def inv_lines(a):
    import itertools
    ctr = itertools.count(1); L = []
    cn = 0.3e-12 * a["Cpar_n"] / 1.5e-12
    rnet(a["Rin_spec"], "Rin", "dacp", "a_inv", cn, L, ctr)
    rnet(a["Rf_spec"], "Rf", "a_out", "a_inv", cn, L, ctr)
    if a["Cf"]: L.append(f"Cf a_out a_inv {a['Cf']}")
    L.append(f"Cpn a_inv 0 {a['Cpar_n']}")
    rnet(a["Rt_spec"], "Rt", "a_vm", "a_vp", 0.3e-12, L, ctr)
    rnet(a["Rbot_spec"], "Rbt", "a_vp", "0", 0.3e-12, L, ctr)
    L += [f"Cref a_vp a_cr {a['Cref']}", "Rcr a_cr 0 0.05", f"Cpp a_vp 0 {a['Cpar_p']}"]
    L += [*vmid_awg(a),
          f"Xsup a_sp a_sn 0 LM27762_BEH params: vp={a['vp']} vn={a['vn']} rp=0.2 rn=0.2 rsink=1e9 rbl=4.7k",
          f"Cb1 a_sp a_cb1 {a['cbulk']}", "Rcb1 a_cb1 0 0.02", f"Cb2 a_sn a_cb2 {a['cbulk']}", "Rcb2 a_cb2 0 0.02",
          f"Rfp a_sp a_vcc {a['rflt']}", f"Rfn a_sn a_vee {a['rflt']}",
          f"Cp1 a_vcc a_cp1 {a['cpin']}", "Rcp1 a_cp1 0 0.05", f"Cp2 a_vee a_cp2 {a['cpin']}", "Rcp2 a_cp2 0 0.05",
          "Dsp a_vcc a_vcc2 DBAT54", "Visp a_vcc2 a_vccx 0", "Dsn a_veex a_vee3 DBAT54", "Visn a_vee3 a_vee 0",
          f"X1 a_vp a_inv a_vccx a_veex {'a_oo' if a.get('pm') else 'a_out'} {a['op']}"]
    if a.get("pm"):
        L.append("Vinj a_out a_oo DC 0 AC 1")
    L += [f"Rs a_out bnc {a['Rs']}"]
    if a["clamp"]:
        L += ["Dga1 a_out ga1 DBAV99", "Dga2 ga1 ga2 DBAV99", "Dga3 ga2 0 DBAV99",
              "Dgb1 0 gb1 DBAV99", "Dgb2 gb1 gb2 DBAV99", "Dgb3 gb2 a_out DBAV99"]
    return [re.sub(r"^(\S+)", r"\1_a", l) for l in L]


VMID_LIN_RO = 50.0     # fitted: |Z| within 2.3 % of the macromodel version over 1 kHz-10 MHz (11.4 mohm at 1 kHz, 1.16 ohm at 38 kHz)


# Per-channel Vmid loops.  'v1': the loop of the first combined run (1R, 1k, 1.6 nF, 10 uF).  'stiff': powercal's
# stiffened loop (2026-11-11): 5 x 1R in parallel, 4.7k DC feedback, 2 x 1.5 nF HF feedback, 2 x 10 uF + 100 nF at the node;
# peak |Z| 0.228 ohm at 22 kHz (0.287 worst), powercal P8-i.
VMID_LOOPS = {"v1": dict(riso=1.0, rfb=1e3, cfb=1.6e-9, cd1=10e-6, esr1=0.005),
              "stiff": dict(riso=0.2, rfb=4.7e3, cfb=3.0e-9, cd1=20e-6, esr1=0.0025)}
# Linear OPA365 stand-ins: A0 / (1 + s A0 / (2 pi GBW)) behind Rout.  'v1': fitted here to the v1 loop (Aol 1e5, GBW 50 MHz,
# Rout 50 ohm, within 2.3 % of the macromodel's |Z|).  'p8k': powercal P8-k, fitted to the stiffened loop (A0 90.0 dB,
# GBW 59.2 MHz, Rout 64.4 ohm, within 0.53 % from 100 Hz to 10 MHz; fitted values, not datasheet figures).
OPA365_LIN = {"v1": dict(a0=1e5, gbw=50e6, rout=VMID_LIN_RO), "p8k": dict(a0=10 ** (90.0 / 20), gbw=59.2e6, rout=64.4)}
# The AWG's bare Vmid follower: P8-k's A0 and GBW, Rout and an input capacitance refitted to the macromodel in that
# configuration (awg_vmid_follower_check; P8-k unchanged reads 6 % low in |Zout| and 15 % fast on the tap step, because
# it has no input capacitance and the 12 pF tap sees the macromodel's).
OPA365_LIN["awgfol"] = dict(OPA365_LIN["p8k"], rout=68.0, cin=6.0e-12)


def lin_opamp(sfx, inp, inn, out, m):
    """Linear op-amp: 1 mS into A0/1mS || C (one pole at GBW/A0), unity buffer, Rout."""
    rp = m["a0"] / 1e-3
    return ([f"Cinl{sfx} {inp} 0 {m['cin']:.6g}"] if m.get("cin") else []) + [f"Gol{sfx} 0 olp{sfx} {inp} {inn} 1m", f"Rol{sfx} olp{sfx} 0 {rp:.6g}",
            f"Col{sfx} olp{sfx} 0 {1/(2*np.pi*(m['gbw']/m['a0'])*rp):.6g}",
            f"Eob{sfx} olo{sfx} 0 olp{sfx} 0 1", f"Rob{sfx} olo{sfx} {out} {m['rout']:.6g}"]


def vmid_gen_lines(node, vmid, sfx, lin=False, loop="v1"):
    """powercal's per-channel Vmid generator (whatif/C2/sim/scope/netlib.py vmid_gen for 'v1'; powercal's stiffened
    loop for 'stiff'): divider off the sensed 3.3 V, 1 uF, OPA365 follower with dual-path feedback, isolation, node caps.
    lin: False = the TI macromodel; True = the stand-in fitted to that loop ('v1' -> OPA365_LIN v1, 'stiff' -> p8k)."""
    v = VMID_LOOPS[loop]
    L = [f"Vdvm{sfx} vpvm{sfx} 0 dc 3.34", f"V33m{sfx} v33m{sfx} 0 dc {2*vmid}", f"Rtm{sfx} v33m{sfx} dvm{sfx} 100k",
         f"Rbm{sfx} dvm{sfx} 0 100k", f"Cdvm{sfx} dvm{sfx} 0 1u"]
    if lin:
        L += lin_opamp(sfx, f"dvm{sfx}", f"fbm{sfx}", f"bom{sfx}", OPA365_LIN["p8k" if loop == "stiff" else "v1"])
    else:
        L.append(f"Xbm{sfx} dvm{sfx} fbm{sfx} vpvm{sfx} 0 bom{sfx} OPA365")
    return L + [f"Rfbm{sfx} {node} fbm{sfx} {v['rfb']:.6g}", f"Cfbm{sfx} bom{sfx} fbm{sfx} {v['cfb']:.6g}",
                f"Risom{sfx} bom{sfx} {node} {v['riso']:.6g}",
                f"Cd1m{sfx} {node} c1m{sfx} {v['cd1']:.6g}", f"Resr1m{sfx} c1m{sfx} 0 {v['esr1']:.6g}",
                f"Cd2m{sfx} {node} c2m{sfx} 100n", f"Resr2m{sfx} c2m{sfx} 0 0.03"]


def awg_vmid_divider_lines(sfx="_g", lin=True):
    """The AWG's own Vmid (sim/awg variant buf): 330k / 330k off +3.3 V_A (a_vcc), 12 pF at the tap, bare OPA365 follower."""
    L = [f"Rdt{sfx} a_vcc avt{sfx} 330k", f"Rdb{sfx} avt{sfx} 0 330k", f"Cdt{sfx} avt{sfx} 0 12p"]
    if lin:
        L += lin_opamp(sfx, f"avt{sfx}", "a_vm", "a_vm", OPA365_LIN["awgfol"])
    else:
        L.append(f"Xavf{sfx} avt{sfx} a_vm a_vccx 0 a_vm OPA365")
    return L


def scope_rails(scope, dac_node="dacp"):
    t = SN.rails(scope)
    if re.search(r"^Vdac dac 0 .*$", t, flags=re.M):   # sim/scope's PA-3 feedthrough source: tie it to the loop's DAC0 node
        t = re.sub(r"^Vdac dac 0 .*$", f"Rdlink dac {dac_node} 1m", t, flags=re.M)
    if scope.get("vmid_gen"):
        vm = scope["aref"] / 2 if scope.get("vmid") is None else scope["vmid"]
        t = re.sub(r"\* Vmid:.*?\nRcv2 cv2 0 \S+\n", "* Vmid: powercal per-channel generator\n" + "\n".join(vmid_gen_lines("vm", vm, "_s", lin=scope["vmid_gen"] == "lin", loop=scope.get("vm_loop", "v1"))) + "\n", t, flags=re.S)
        assert "Vdvm_s" in t, "Vmid block not replaced"
        if scope.get("vm_noc"):
            t = re.sub(r"^Cd1m_s .*$", "* guard: 10 uF removed", t, flags=re.M)
    return t


def trim_lines(scope):
    """Route (b): a compensation trim at the divider node N.  'ideal': a linear capacitor N to Vmid.
    'varactor': N - Cblk - M, a varactor from M to ground (cathode at M), Rb from M to a filtered bias."""
    t = scope.get("trim")
    if not t:
        return []
    if t["kind"] == "ideal":
        return [f"Ctrim n vm {t['C']:.6g}"]
    if t["kind"] == "varlin":     # the same network with a linear capacitor for the varactor (separates its two effects)
        return [f"Cblk n vmt {t['Cblk']:.6g}", f"Cvl vmt 0 {t['Cv']:.6g}", f"Rbias vmt vbias {t['Rb']:.6g}", f"Vbias vbias 0 {t['Vb']:.6g}"]
    return [f"Cblk n vmt {t['Cblk']:.6g}", f"Dvar 0 vmt DVAR", f"Rbias vmt vbias {t['Rb']:.6g}", f"Vbias vbias 0 {t['Vb']:.6g}",
            f".model DVAR D(IS=1e-15 CJO={t['CJO']*t.get('tcfac',1.0):.6g} VJ={t['VJ']} M={t['M']} RS=0.5 BV=30)"]


def sh_lines(adc, node="pin"):
    """The ADC's sample-and-hold, continuously tracking (see report: switched check)."""
    return [f"Radc {node} cs {adc['ron']:.6g}", f"Csh cs 0 {adc['cs']:.6g}"]


def staircase(levels_v, slew, t0):
    """PWL text: hold each level for TSYM, ramp to the next at `slew` (instant if slew is None)."""
    pts = [(0.0, levels_v[0])]
    for k in range(1, len(levels_v)):
        tk = t0 + k * TSYM
        a, b = levels_v[k - 1], levels_v[k]
        if a == b:
            continue
        dur = abs(b - a) / slew if slew else 1e-12
        pts.append((tk, a)); pts.append((tk + dur, b))
    pts.append((t0 + len(levels_v) * TSYM + 1e-6, levels_v[-1]))
    return " ".join(f"{t:.6e} {v:.6f}" for t, v in pts)


def sequence(swing_mv=None):
    """Symbols played: the last NPRE of the period as a preamble, then one full period."""
    pat = etspattern.pattern(PAM, swing_mv)
    sy = pat.symbols
    seq = sy[-NPRE:] + sy
    return pat, seq, [dac_volts(pat.codes[s]) for s in seq]


def run_ng(name, text, timeout=3000):
    path = os.path.join(NETD, name + ".cir")
    open(path, "w").write(text if text.endswith("\n") else text + "\n")
    r = subprocess.run(["ngspice", "-b", os.path.basename(path)], cwd=NETD,
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout + r.stderr


def tran(name, body, tstop, reltol=1e-5, tmax=1e-9, temp=27, nodes="v(cs)", method="gear", vntol=1e-8, abstol=1e-13):
    hdr = (f"* {name}: generated by sim/loop/run.py\n"
           f".include {AWG_LIBS['OPA365']}\n.include {AWG_LIBS['OPA354']}\n"
           ".include ../models/loop_behavioural.lib\n.include ../../scope/models/rangesw.lib\n" + SN.DESD_MODEL
           + f".options reltol={reltol} abstol={abstol} vntol={vntol} itl1=4000 itl4=500 method={method} temp={temp}\n")
    out = f"../work/{name}.dat"
    txt = hdr + body + f"\n.control\ntran 0.5n {tstop:.6e} 0 {tmax:.3e}\nwrdata {out} {nodes}\n.endc\n.end\n"
    t0 = time.time()
    log = run_ng(name, txt)
    fn = os.path.join(WORK, name + ".dat")
    if not os.path.exists(fn):
        raise RuntimeError(f"{name}: no output\n{log[-2500:]}")
    d = np.loadtxt(fn)
    os.remove(fn)
    return d, time.time() - t0, log


def loop_body(dac, awg, scope, adc, cable, pwl, baseline=False):
    L = dac_lines(dac, pwl)
    if baseline:
        L += [f"Cpd dacp 0 {CPIN}"] + sh_lines(adc, "dacp")
        return "\n".join(L)
    if scope.get("loopback"):   # route (e): DAC0 straight to node N through the PA-3 switch (TMUX1119 class)
        srcn = "dacp"
        if scope.get("loop_buf"):   # ... or from the buffered DAC0 node (OPA365 follower, ideal 3.3 V supply)
            L += ["Rbin dacp lbin 680", "Vlbs lbs 0 3.3", "Clbs lbs 0 100n", "Xlb lbin lbo lbs 0 lbo OPA365"]
            srcn = "lbo"
        L += [f"Rswl {srcn} n {scope.get('ron_sw', 3.7)}", f"Csl1 {srcn} 0 10p", "Csl2 n 0 10p"]
        L.append(scope_rails(scope, "a_bo" if awg.get("buf") else "dacp") + SN.core(scope))
        L += trim_lines(scope) + sh_lines(adc, "pin")
        return "\n".join(L)
    if awg.get("ideal"):      # attribution only: the AWG as an ideal gain behind 49.9 ohm
        L += ["Vari ari 0 1.65", f"Eawi a_ide 0 dacp ari {awg.get('gain', 1.1533)}"]
        if awg.get("pole"):   # guard: one slow pole after the ideal gain
            L += [f"Rpl a_ide a_pl 1k", f"Cpl a_pl 0 {awg['pole']/1e3:.6g}", "Epl a_out 0 a_pl 0 1"]
        else:
            L += ["Rpl a_ide a_out 1m"]
        L += [f"Rs_a a_out bnc {awg['Rs']}"]
    else:
        L += awg_lines(awg)
    if cable is None:
        L.append("Rcab bnc in 1m")
    elif cable.get("term"):
        L += [f"T1 bnc 0 in 0 Z0={cable['z0']} TD={cable['td']:.4g}", "Rterm in 0 50"]
    else:
        L.append(f"T1 bnc 0 in 0 Z0={cable['z0']} TD={cable['td']:.4g}")
    if scope.get("ideal"):    # attribution only: the scope as an ideal gain, its input load, Riso, the pin
        g = 1.1265 if scope["rng"] == "1.25" else 0.2330
        L += ["Rin in 0 1Meg", "Cin in 0 15p", "Vsm smid 0 1.65", f"Esc sout smid in 0 {g}",
              f"Riso sout pin {scope['Riso']}", f"Cp pin 0 {scope['Cpin']}"]
    else:
        L.append(scope_rails(scope, "a_bo" if awg.get("buf") else "dacp") + SN.core(scope))
        L += trim_lines(scope)
    if adc.get("switched"):   # the real switched S/H: track 15 ADC clocks, one channel at ADC RC 45
        per = 45 * TICK
        L += [".model swsh sw(vt=0.5 vh=0.1 ron=0.001 roff=1e12)", "Ssh pin mx shc 0 swsh",
              f"Radc mx cs {adc['ron']:.6g}", f"Csh cs 0 {adc['cs']:.6g}",
              f"Vshc shc 0 pulse(0 1 {adc['t0']:.6e} 1n 1n {15/22.5e6 - 2e-9:.6e} {per:.6e})"]
    else:
        L += sh_lines(adc, "pin")
    return "\n".join(L)


# ------------------------------------------------------------------ the band, as host/etspam.py reads it
def boundary_from_energy(energy, rc):
    """host/etspam.py _boundary_from_energy, unchanged in substance."""
    w = max(3, rc // 3)
    e = np.asarray(energy)
    sums = np.array([e[(p + np.arange(w)) % rc].sum() for p in range(rc)])
    phi = int(np.argmax(sums))
    wts = e[(phi + np.arange(w)) % rc]
    if wts.sum() <= 0:
        return 0.0
    c = float((np.arange(w) * wts).sum() / wts.sum())
    return (phi + c + 1.0 + rc / 2.0) % rc - rc / 2.0


def band(t, v, seq, t0, aref=AREF_CODES, window=(0.5 - CENTRE_HALF, 0.5 + CENTRE_HALF), nph=57,
         phases=None, inject=0.0):
    """Level band of the measured period in codes.  Returns the per-level widths (max - min,
    the noise-free stand-in for the 0.1 % to 99.9 % width), the boundary found, and the means."""
    code = 4096.0 / aref
    meas = np.arange(NPRE, len(seq))
    tk = t0 + meas * TSYM
    grid = tk[:, None] + (np.arange(LABEL_BINS) / LABEL_BINS * TSYM)[None, :]
    curve = np.interp(grid.ravel(), t, v)
    d = np.abs(np.roll(curve, -1) - curve)
    energy = d.reshape(-1, LABEL_BINS).sum(axis=0)
    b = boundary_from_energy(energy, LABEL_BINS) / LABEL_BINS        # in symbols
    if phases is None:
        phases = np.linspace(window[0], window[1], nph)
    ts = tk[:, None] + (b + phases)[None, :] * TSYM
    vs = np.interp(ts.ravel(), t, v).reshape(ts.shape) * code
    if inject:      # positive control: a known fraction of the previous symbol added to every sample
        vp = np.interp((ts - TSYM).ravel(), t, v).reshape(ts.shape) * code
        vs = vs + inject * (vp - vp.mean())
    lev = np.array([seq[i] for i in meas])
    widths, means = [], []
    for L in range(PAM):
        x = vs[lev == L]
        widths.append(float(x.max() - x.min())); means.append(float(x.mean()))
    sp = abs(means[-1] - means[0]) / (PAM - 1)     # abs: an inverting AWG reverses the level order
    return dict(widths=widths, worst=float(max(widths)), worst_level=int(np.argmax(widths)),
                mean_width=float(np.mean(widths)), boundary_sym=float(b), boundary_ns=float(b * TSYM * 1e9),
                spacing=float(sp), means=means)


# ------------------------------------------------------------------ one case
FIT = {}


def dac_for(adc_name="derived", rout=0.0, slew=None):
    k = f"{adc_name}|{rout:g}"
    if k not in FIT:
        taud, sl, note, pred = fit_dac(ADC[adc_name], rout)
        FIT[k] = dict(taud=taud, slew=sl, note=note, pred_rise_ns={str(a): b * 1e9 for a, b in pred.items()})
    f = FIT[k]
    return dict(taud=f["taud"], slew=slew if slew else f["slew"], rout=rout)


def simulate(tag, adc_name="derived", rout=0.0, slew=None, awg=None, scope=None, cable="default",
             baseline=False, swing_mv=None, reltol=1e-5, temp=27, switched=False, phase_sweep=False,
             keep=False, save_wave=False, method="gear", vntol=1e-8, abstol=1e-13):
    dac = dac_for(adc_name, rout, slew)
    adc = dict(ADC[adc_name])
    pat, seq, lv = sequence(swing_mv)
    t0 = 1e-6
    if switched:
        adc.update(switched=True, t0=t0 + NPRE * TSYM)
    pwl = staircase(lv, dac["slew"], t0)
    a = dict(AWG0); a.update(awg or {})
    s = dict(SCOPE0); s.update(scope or {})
    cab = CABLE0 if cable == "default" else cable
    body = loop_body(dac, a, s, adc, cab, pwl, baseline)
    tstop = t0 + len(seq) * TSYM + 50e-9
    so = dict(method=method, vntol=vntol, abstol=abstol)
    d, secs, log = tran(tag, body, tstop, reltol=reltol, temp=temp, **so)
    if d[-1, 0] < tstop - 10e-9:      # an aborted transient writes what it had: refuse it, retry once finer
        d, secs2, log = tran(tag, body, tstop, reltol=reltol, temp=temp, tmax=0.25e-9, **so)
        secs += secs2
        if d[-1, 0] < tstop - 10e-9:
            m = re.findall(r"(?:Error|doAnalyses)[^\n]*", log)
            raise RuntimeError(f"transient stopped at {d[-1,0]*1e6:.1f} us of {tstop*1e6:.1f}: " + " | ".join(m[:3]))
    t, v = d[:, 0], d[:, 1]
    r = band(t, v, seq, t0)
    if not r["spacing"] > 10:
        raise RuntimeError(f"no PAM staircase at the pin (spacing {r['spacing']:.3g} codes): the run is invalid")
    r.update(tag=tag, secs=round(secs, 1), dac=dac, adc=adc_name)
    if phase_sweep:
        r["phase"] = {f"{ph:.2f}": band(t, v, seq, t0, phases=np.array([ph]))["worst"]
                      for ph in np.arange(0.20, 0.96, 0.05)}
        r["window_0.3_0.7"] = band(t, v, seq, t0, window=(0.3, 0.7), nph=81)["worst"]
    if switched:    # samples at the end of each track window, against the continuous model's run
        per = 45 * TICK
        te = adc["t0"] + 15 / 22.5e6 - 2e-9 + per * np.arange(int((t[-1] - adc["t0"]) / per) - 1)
        r["_te"], r["_ve"] = te, np.interp(te, t, v)
    if keep:
        r["_t"], r["_v"], r["_seq"], r["_t0"] = t, v, seq, t0
    if save_wave:      # the waveform of the S/H node, for the host-calibration step
        os.makedirs(os.path.join(WORK, "wave"), exist_ok=True)
        np.savez(os.path.join(WORK, "wave", tag + ".npz"), t=t, v=v, seq=np.array(seq), t0=t0)
    return r


def job(args):
    tag, kw = args
    try:
        return tag, simulate(tag, **kw)
    except Exception as e:     # a failed run is a row that says so, never a silent pass
        return tag, dict(error=str(e)[-1500:])


# ------------------------------------------------------------------ the cases
OPS = ("OPA354", "OPA365")
RAB1 = dict(Ca=20e-12, Ra=10e3 + 4.7e3, Rb=4.7e3 / 2 + 10e3 + 4.7e3)
# whatif/awg-rab variant n1 (approved 2026-11-11): Ra (4.7k||4.7k)+4.7k x3 = 16.45k, Rb 4.7k x4 = 18.8k, 1 %,
# 0.3 pF per added node, supply filter 22 || 22 = 11 ohm
N1 = dict(Ra=16.45e3, Rb=18.8e3, Ra_spec=[(4.7e3, 4.7e3), 4.7e3, 4.7e3, 4.7e3], Rb_spec=[4.7e3, 4.7e3, 4.7e3, 4.7e3], rflt=11.0)      # scope op-amp: sim/scope's choice and the owner's conditional replacement


def cases():
    """(tag, kwargs, baseline tag) for every loop run.  Each corner is one change from nominal."""
    C = []
    for op in OPS:
        sc = dict(op=op)
        for ca in (20e-12, 24e-12):
            aw = dict(Ca=ca)
            n = f"{op}_Ca{ca*1e12:.0f}"
            C.append((f"{n}_nom", dict(awg=aw, scope=sc, phase_sweep=True), "base"))
            for cp in (0.5e-12, 3.5e-12):
                C.append((f"{n}_Cpar{cp*1e12:g}", dict(awg=dict(aw, Cpar_p=cp), scope=sc), "base"))
            C.append((f"{n}_C1hi_C2lo", dict(awg=aw, scope=dict(sc, C1=12.6e-12, C2=37.05e-12)), "base"))
            C.append((f"{n}_C1lo_C2hi", dict(awg=aw, scope=dict(sc, C1=11.4e-12, C2=40.95e-12)), "base"))
            C.append((f"{n}_R2_330k", dict(awg=aw, scope=dict(sc, R2=330e3)), "base"))
            C.append((f"{n}_R2_340k", dict(awg=aw, scope=dict(sc, R2=340e3)), "base"))
            C.append((f"{n}_adcstress", dict(awg=aw, scope=sc, adc_name="stress"), "base_stress"))
            for ro in (300.0, 1000.0):
                C.append((f"{n}_rout{ro:g}", dict(awg=aw, scope=sc, rout=ro), f"base_rout{ro:g}"))
            for sl in (5.9e6, 6.6e6):
                C.append((f"{n}_slew{sl/1e6:g}", dict(awg=aw, scope=sc, slew=sl), f"base_slew{sl/1e6:g}"))
            C.append((f"{n}_rails_weak", dict(awg=dict(aw, vp=3.23, vn=0.95 * VN_AWG), scope=dict(sc, vcc=3.23)), "base"))
            C.append((f"{n}_vmid_0.05ohm", dict(awg=dict(aw, rvm=0.05), scope=sc), "base"))
            C.append((f"{n}_cable2m", dict(awg=aw, scope=sc, cable=dict(td=10e-9, z0=50.0)), "base"))
            C.append((f"{n}_nocable", dict(awg=aw, scope=sc, cable=None), "base"))
            for tp in (0, 50, 70):
                C.append((f"{n}_T{tp}", dict(awg=aw, scope=sc, temp=tp), "base"))
            C.append((f"{n}_range5", dict(awg=aw, scope=dict(sc, rng="5")), "base"))
            # attribution: which stage carries the band
            C.append((f"{n}_idealscope", dict(awg=aw, scope=dict(sc, ideal=True)), "base"))
        C.append((f"{op}_idealawg", dict(awg=dict(ideal=True), scope=sc), "base"))
        C.append((f"{op}_reltol1e-4", dict(awg=dict(Ca=20e-12), scope=sc, reltol=1e-4), "base"))
    # proposed 1 %-only attenuator (2026-11-11): Ra = 10k + 4.7k, Rb = (4.7k || 4.7k) + 10k + 4.7k; Ca stays 20 pF
    for op in OPS:
        sc = dict(op=op); aw = dict(RAB1)
        n = f"{op}_Rab1pct"
        C.append((f"{n}_nom", dict(awg=aw, scope=sc, phase_sweep=True), "base"))
        for cp in (0.5e-12, 3.5e-12):
            C.append((f"{n}_Cpar{cp*1e12:g}", dict(awg=dict(aw, Cpar_p=cp), scope=sc), "base"))
        C.append((f"{n}_C1hi_C2lo", dict(awg=aw, scope=dict(sc, C1=12.6e-12, C2=37.05e-12)), "base"))
        C.append((f"{n}_C1lo_C2hi", dict(awg=aw, scope=dict(sc, C1=11.4e-12, C2=40.95e-12)), "base"))
        C.append((f"{n}_idealscope", dict(awg=aw, scope=dict(sc, ideal=True)), "base"))
    C.append(("idealboth", dict(awg=dict(ideal=True), scope=dict(ideal=True)), "base"))
    C.append(("idealboth_range5", dict(awg=dict(ideal=True), scope=dict(ideal=True, rng="5")), "base"))
    return C


BASES = {"base": dict(baseline=True, phase_sweep=True), "base_stress": dict(baseline=True, adc_name="stress"),
         "base_rout300": dict(baseline=True, rout=300.0), "base_rout1000": dict(baseline=True, rout=1000.0),
         "base_slew5.9": dict(baseline=True, slew=5.9e6), "base_slew6.6": dict(baseline=True, slew=6.6e6)}


def sweeps():
    """Sensitivity: each stage alone (the other ideal), its compensation swept."""
    J = []
    for ca in (16, 18, 20, 22, 24, 26, 28, 30):
        J.append((f"sw_awg_Ca{ca}", dict(awg=dict(Ca=ca * 1e-12), scope=dict(ideal=True))))
    for ca in (16, 18, 20, 22, 24, 26, 28, 30):
        J.append((f"sw_awg1pct_Ca{ca}", dict(awg=dict(RAB1, Ca=ca * 1e-12), scope=dict(ideal=True))))
    for cp in (0.5, 3.5):
        for ca in (20, 24):
            J.append((f"sw_awg_Ca{ca}_Cpar{cp:g}", dict(awg=dict(Ca=ca * 1e-12, Cpar_p=cp * 1e-12), scope=dict(ideal=True))))
    for op in OPS:
        for c2 in (31, 33, 35, 37, 39, 41, 43):
            J.append((f"sw_scope_{op}_C2_{c2}", dict(awg=dict(ideal=True), scope=dict(op=op, C2=c2 * 1e-12))))
    return J


def run_all(workers=3, jobs=None):
    from concurrent.futures import ProcessPoolExecutor
    for k in ("derived", "stress"):
        dac_for(k)
    for ro in (300.0, 1000.0):
        dac_for("derived", ro)
    if jobs is None:
        jobs = [(k, v) for k, v in BASES.items()] + [(t, kw) for t, kw, _ in cases()]
    res = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for tag, r in ex.map(job, jobs):
            res[tag] = r
            print(f"  {tag}: " + (f"worst {r['worst']:.2f} codes, {r['secs']} s" if "error" not in r else "ERROR"), flush=True)
    return res


def extras(workers=3):
    """Guard, positive control of the band metric, and the switched-S/H check."""
    from concurrent.futures import ProcessPoolExecutor
    dac_for("derived")
    jobs = [("guard_pass", dict(awg=dict(ideal=True), scope=dict(ideal=True))),
            ("guard_slowawg", dict(awg=dict(ideal=True, pole=150e-9), scope=dict(ideal=True))),
            ("guard_slowawg_real", dict(awg=dict(Ca=20e-12, Cf=1e-9), scope=dict(op="OPA365"))),
            ("sw_cont", dict(awg=dict(Ca=20e-12), scope=dict(op="OPA365"), keep=True)),
            ("pc_base", dict(baseline=True, keep=True)),
            ("sw_switched", dict(awg=dict(Ca=20e-12), scope=dict(op="OPA365"), switched=True))]
    res = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for tag, r in ex.map(job, jobs):
            res[tag] = r
    E = {k: {a: b for a, b in v.items() if not a.startswith("_")} for k, v in res.items()}
    # positive control of the metric: inject a known 1 % of the previous symbol into the noise-free loop
    c = res["pc_base"]
    pc = {}
    for inj in (0.0, 0.002, 0.01):
        b = band(c["_t"], c["_v"], c["_seq"], c["_t0"], inject=inj)
        pc[f"{inj:g}"] = b["worst"]
    # expected: the band grows by inj x the spread of the previous symbol's centre value, 15 spacings
    E["inject"] = dict(widths=pc, spacing=c["spacing"],
                       expected_growth={k: float(k) * 15 * c["spacing"] for k in pc})
    c = res["sw_cont"]
    # switched S/H: same instants, continuous model against the switch
    sw = res["sw_switched"]
    vc = np.interp(sw["_te"], c["_t"], c["_v"])
    diff = (sw["_ve"] - vc) * 4096 / AREF_CODES
    E["switched"] = dict(n=int(len(diff)), max_abs_codes=float(np.max(np.abs(diff))), rms_codes=float(np.sqrt(np.mean(diff**2))))
    json.dump(E, open(os.path.join(RES, "extras.json"), "w"), indent=1, default=float)
    return E


# ================================================================== follow-up 1: the AWG with no compensation caps
NOCAP = dict(Ca=0.0, Cb=0.0)
RAB1_NOCAP = dict(RAB1, Ca=0.0, Cb=0.0)
AWG_SETS = {"Rab_cur": {}, "Rab_1pct": dict(Ra=RAB1["Ra"], Rb=RAB1["Rb"])}
LOADS = {"hiz": ["Rl bnc 0 1Meg", "Cl bnc 0 15p"], "r50": ["Rl bnc 0 50"],
         "cable_open": ["T1 bnc 0 far 0 Z0=50 TD=5n", "Rl far 0 1G"],
         "cable_r50": ["T1 bnc 0 far 0 Z0=50 TD=5n", "Rl far 0 50"], "short": ["Rl bnc 0 1u"]}


def parse_raw(path):
    """ngspice ASCII raw file -> {vector: array} (copied from sim/awg/run.py)."""
    txt = open(path).read().split("\n")
    i = 0; nv = npnt = 0; names = []; cplx = False
    while i < len(txt):
        l = txt[i]
        if l.startswith("Flags:"): cplx = "complex" in l
        if l.startswith("No. Variables:"): nv = int(l.split()[-1])
        if l.startswith("No. Points:"): npnt = int(l.split()[-1])
        if l.startswith("Variables:"):
            for k in range(nv): names.append(txt[i + 1 + k].split()[1])
            i += nv
        if l.startswith("Values:"): i += 1; break
        i += 1
    data = np.zeros((nv, npnt), dtype=complex if cplx else float)
    p = 0; k = 0
    for l in txt[i:]:
        sp = l.split()
        if not sp: continue
        if not l.startswith("\t"):
            p = int(sp[0]); sp = sp[1:]; k = 0
        for tok in sp:
            data[k, p] = complex(*map(float, tok.split(","))) if cplx else float(tok)
            k += 1
    return {n.lower(): data[j] for j, n in enumerate(names)}


def awg_only(name, a, load, analysis, rout=0.0, src="DC 1.65 AC 1", plot=None):
    """The AWG stage alone (the same awg_lines the loop uses) with the sim/awg loads."""
    hdr = (f"* {name}: generated by sim/loop/run.py (AWG rows)\n.include {AWG_LIBS['OPA365']}\n"
           ".include ../models/loop_behavioural.lib\n.options reltol=1e-5 abstol=1e-13 itl1=4000 itl4=500 method=gear\n")
    L = [f"Vdac dac0 0 {src}", f"Rdo dac0 dacp {max(rout, 1e-3):.6g}"] + awg_lines(a) + LOADS[load]
    raw = f"../work/{name}.raw"
    ctl = [".control", "set filetype=ascii", "run"] + ([f"setplot {plot}"] if plot else []) + [f"write {raw} all", ".endc"]
    log = run_ng(name, hdr + "\n".join(L) + "\n" + analysis + "\n" + "\n".join(ctl) + "\n.end\n")
    fn = os.path.join(WORK, name + ".raw")
    if not os.path.exists(fn):
        raise RuntimeError(f"{name}: no output\n{log[-1500:]}")
    r = parse_raw(fn); os.remove(fn)
    return r


def awg_bw(a, load, rout=0.0, name="arow_ac"):
    r = awg_only(name, a, load, ".ac dec 40 1k 1G", rout=rout)
    node = "v(far)" if load.startswith("cable") else "v(bnc)"
    f = r["frequency"].real; g = np.abs(r[node])
    idx = np.where(g < g[0] / np.sqrt(2))[0]
    return dict(dc=float(g[0]), f3db=float(f[idx[0]]) if len(idx) else float("inf"),
                peak_db=float(20 * np.log10(g.max() / g[0])),
                g8M=float(np.interp(8e6, f, g) / g[0]), g1M=float(np.interp(1e6, f, g) / g[0]))


def awg_overshoot(a, name="arow_st"):
    """sim/awg's AW-4 row: a 0.5 V DAC step in 52 ns (42 ns 10-90) into 1 m open cable, far end."""
    t0 = 0.5e-6
    src = f"DC 1.4 PWL(0 1.4 {t0} 1.4 {t0+52e-9} 1.9 10u 1.9)"
    r = awg_only(name, a, "cable_open", ".tran 0.5n 1.5u", src=src)
    t = r["time"].real; v = r["v(far)"].real
    base = np.interp(t0 - 20e-9, t, v); fin = np.interp(t[-1] - 50e-9, t, v)
    n = (v - base) / (fin - base); k = t >= t0
    bad = np.where(np.abs(n[k] - 1) > 0.01)[0]
    return dict(overshoot=float(n[k].max() - 1), settle_1pct_ns=float((t[k][bad[-1]] - t0) * 1e9) if len(bad) else 0.0)


def awg_noise(a, name="arow_nz", hi=100e6):
    """AW-6 as sim/awg computes it: .noise at the BNC into 1 Mohm || 15 pF, quiet DC source,
    10 Hz to 100 MHz, the behavioural supply's own resistors and diodes removed."""
    r = awg_only(name, a, "hiz", ".noise v(bnc) Vdac dec 40 10 1G 1", src="DC 1.65 AC 1", plot="noise1")
    f = r["frequency"].real
    tot2 = r["onoise_spectrum"].real ** 2
    for k in list(r):
        if k.startswith("onoise_") and ".xsup_a." in k:
            tot2 = tot2 - r[k].real ** 2
    m = (f >= 10) & (f <= hi)
    return float(np.sqrt(np.trapezoid(tot2[m], f[m])))


def awg_rows_one(args):
    tag, a = args
    try:
        r = dict(bw_hiz=awg_bw(a, "hiz", name=f"ar_{tag}_hz"), bw_r50=awg_bw(a, "r50", name=f"ar_{tag}_r5"),
                 bw_cable_open=awg_bw(a, "cable_open", name=f"ar_{tag}_co"),
                 bw_rout1k=awg_bw(a, "hiz", rout=1000.0, name=f"ar_{tag}_ro"),
                 step=awg_overshoot(a, name=f"ar_{tag}_st"))
        if a.get("noise", True):
            r["aw6_uV"] = awg_noise(a, name=f"ar_{tag}_nz") * 1e6
        return tag, r
    except Exception as e:
        return tag, dict(error=str(e)[-1500:])


def nocap_jobs():
    J = []
    for rs, rab in AWG_SETS.items():
        for cp in (0.5, 1.5, 3.5):
            aw = dict(rab, Ca=0.0, Cb=0.0, Cpar_p=cp * 1e-12)
            J.append((f"nc_{rs}_Cpar{cp:g}_idealscope", dict(awg=aw, scope=dict(ideal=True))))
            for op in OPS:
                J.append((f"nc_{rs}_Cpar{cp:g}_{op}", dict(awg=aw, scope=dict(op=op), save_wave=(cp == 1.5))))
    return J


def awg_row_jobs():
    J = [("final_Ca20Cb12_Cpar1.5", dict(Ca=20e-12, Cb=12e-12))]       # validation against sim/awg
    for rs, rab in AWG_SETS.items():
        for cp in (0.5, 1.5, 3.5):
            J.append((f"nocap_{rs}_Cpar{cp:g}", dict(rab, Ca=0.0, Cb=0.0, Cpar_p=cp * 1e-12, noise=(cp == 1.5))))
    # guards: each new row must be able to fail
    J += [("guard_bw_Cf100p", dict(Ca=0.0, Cb=0.0, Cf=100e-12, noise=False)),
          ("guard_ov_Ca33Cb22_Cpar0.5", dict(Ca=33e-12, Cb=22e-12, Cpar_p=0.5e-12, noise=False)),
          ("guard_nz_Rx40", dict(Ca=0.0, Cb=0.0, Rf=40 * (249.0 + 49.9), Rg=40 * 249.0))]
    return J


def run_pool(fn, jobs, workers=4):
    from concurrent.futures import ProcessPoolExecutor
    res = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for tag, r in ex.map(fn, jobs):
            res[tag] = r
            print(f"  {tag}: " + ("ERROR " + r["error"][:200] if "error" in r else "ok"), flush=True)
    return res


def awg_rows(a_override):
    out = {}
    for tag, a in a_override:
        q = dict(AWG0); q.update(a); out[tag] = q
    return out


def step_nocap(workers=4):
    dac_for("derived")
    jl = [(t, dict(AWG0, **a)) for t, a in awg_row_jobs()]
    rows = run_pool(awg_rows_one, jl, workers)
    loop = run_pool(job, nocap_jobs(), workers)
    json.dump(dict(rows=rows, loop=loop), open(os.path.join(RES, "nocap.json"), "w"), indent=1, default=float)




# ================================================================== scope-divider routes (owner, 2026-11-11)
R760 = dict(R1=760e3, R3=760e3)          # 330k + 330k + 100k replaces the out-of-stock 768k
C0G_TC = 30e-6 * 20                       # +/-30 ppm/K over +/-20 K
VAR = dict(VJ=0.7, M=0.5, Cblk=220e-12, Vb=1.5)   # varactor assumption *(check)*: abrupt junction, see report
VAR_TC = 400e-6 * 20                      # varactor capacitance tempco assumed 400 ppm/K *(check)*


def scope_ac(tag_scope):
    """SM-3: BNC behind 50 ohm (as sim/scope) -> channel -> pin with the S/H; -3 dB from 10 kHz."""
    tag, sc = tag_scope
    try:
        s = dict(SCOPE0); s.update(sc)
        body = "Vs src 0 dc 0 ac 1\nRs src in 50\n" + SN.rails(s) + SN.core(s) + "\n" + "\n".join(trim_lines(s) + sh_lines(ADC["derived"], "pin"))
        hdr = (f"* {tag}\n.include {AWG_LIBS['OPA365']}\n.include {AWG_LIBS['OPA354']}\n.include ../../scope/models/rangesw.lib\n"
               ".options reltol=1e-5 abstol=1e-13 itl1=4000 method=gear\n")
        run_ng(tag, hdr + body + f"\n.control\nac dec 40 1e4 1e9\nwrdata ../work/{tag}.dat v(pin)\n.endc\n.end\n")
        d = np.loadtxt(os.path.join(WORK, tag + ".dat")); os.remove(os.path.join(WORK, tag + ".dat"))
        f = d[:, 0]; g = np.abs(d[:, 1] + 1j * d[:, 2])
        db = 20 * np.log10(g / g[0]); i = np.where(db < -3)[0]
        if len(i):
            k = i[0]; bw = 10 ** (np.log10(f[k-1]) + (np.log10(f[k]) - np.log10(f[k-1])) * (-3 - db[k-1]) / (db[k] - db[k-1]))
        else:
            bw = float("inf")
        return tag, dict(bw=float(bw), g0=float(g[0]), peak_db=float(db.max()))
    except Exception as e:
        return tag, dict(error=str(e)[-800:])


def null_fit(c2s, isi):
    """V-shaped ISI against C2: fit |slope| x |C2 - C0| + floor to the points either side of the minimum."""
    c2s = np.asarray(c2s); isi = np.asarray(isi); k = int(np.argmin(isi))
    lo = slice(max(0, k - 3), k + 1); hi = slice(k, min(len(c2s), k + 4))
    a1 = np.polyfit(c2s[lo], isi[lo], 1) if k >= 1 else None
    a2 = np.polyfit(c2s[hi], isi[hi], 1) if k + 1 < len(c2s) else None
    if a1 is None or a2 is None:
        return dict(c2=float(c2s[k]), slope=float("nan"))
    c0 = (a2[1] - a1[1]) / (a1[0] - a2[0])
    return dict(c2=float(c0), slope_down=float(a1[0]), slope_up=float(a2[0]), slope=float((a2[0] - a1[0]) / 2))


def jobsc(tag, sc, **kw):
    return (tag, dict(awg=dict(ideal=True), scope=dict(R760, **sc), **kw))


def step_routes(workers=5):
    dac_for("derived")
    out = {}
    grid = {"OPA354": np.arange(37.0, 41.01, 0.5), "OPA365": np.arange(31.0, 35.51, 0.5)}
    # phase A: the C2 null of each op-amp with R1 = R3 = 760k
    J = [jobsc(f"ro_null_{op}_{c2:.1f}", dict(op=op, C2=c2 * 1e-12)) for op, g in grid.items() for c2 in g]
    J.append(("ro_base", dict(baseline=True)))
    J.append(("ro_base270", dict(baseline=True, swing_mv=270.0)))
    A = run_pool(job, J, workers)
    out["A"] = A
    nulls = {}
    for op, g in grid.items():
        isi = [A[f"ro_null_{op}_{c2:.1f}"]["worst"] - A["ro_base"]["worst"] for c2 in g]
        nulls[op] = null_fit(g, isi); nulls[op]["isi"] = isi; nulls[op]["grid"] = list(map(float, g))
    out["nulls"] = nulls
    # phase B
    J, ACJ = [], []
    for op in OPS:
        c2n = nulls[op]["c2"] * 1e-12
        c1n = 12e-12
        # (c2) tighter capacitors at the null
        J.append(jobsc(f"rc2_{op}_null", dict(op=op, C2=c2n)))
        for t in (0.01, 0.02, 0.05):
            J.append(jobsc(f"rc2_{op}_t{t*100:g}_C1hi", dict(op=op, C1=c1n * (1 + t), C2=c2n * (1 - t))))
            J.append(jobsc(f"rc2_{op}_t{t*100:g}_C1lo", dict(op=op, C1=c1n * (1 - t), C2=c2n * (1 + t))))
        for sgn, nm in ((1, "a"), (-1, "b")):     # C0G drift after an exact null
            J.append(jobsc(f"rc2_{op}_c0gdrift_{nm}", dict(op=op, C1=c1n * (1 + sgn * C0G_TC), C2=c2n * (1 - sgn * C0G_TC))))
        # (c) uncompensated divider, R scaled: strays 0.1 pF across R1 *(check)*, 2 pF at N (sim/scope)
        for sc_ in (1.0, 0.3, 0.1, 0.03, 0.01, 0.003, 0.001):
            sc = dict(op=op, R1=760e3 * sc_, R2=335e3 * sc_, R3=760e3 * sc_, C1=0.1e-12, C2=2e-12)
            J.append(jobsc(f"runc_{op}_s{sc_:g}", sc)); ACJ.append((f"acunc_{op}_s{sc_:g}", dict(sc, **R760) | dict(R1=760e3 * sc_, R3=760e3 * sc_)))
        # (c) compensated divider at 1 M, 100 k, 10 k with +/-5 % C0G (C2 part rescaled so the nominal sits at the null)
        r23 = 335e3 * 760e3 / (335e3 + 760e3)
        c2tot = c1n * 760e3 / r23; cext = c2tot - c2n
        for sc_ in (1.0, 0.1, 0.01):
            c1s, c2s = c1n / sc_, c2tot / sc_ - cext
            base = dict(op=op, R1=760e3 * sc_, R2=335e3 * sc_, R3=760e3 * sc_)
            J.append(jobsc(f"rcomp_{op}_s{sc_:g}_nom", dict(base, C1=c1s, C2=c2s)))
            J.append(jobsc(f"rcomp_{op}_s{sc_:g}_C1hi", dict(base, C1=c1s * 1.05, C2=c2s * 0.95)))
            J.append(jobsc(f"rcomp_{op}_s{sc_:g}_C1lo", dict(base, C1=c1s * 0.95, C2=c2s * 1.05)))
            ACJ.append((f"accomp_{op}_s{sc_:g}", dict(R760, **base, C1=c1s, C2=c2s)))
        # (b) trim: a varactor network sized to sit at the null at Vb 1.5 V; C2 part reduced by the trim's Ceff
        cv_mid = 20e-12
        ceff = 1 / (1 / VAR["Cblk"] + 1 / cv_mid)
        cjo = cv_mid * (1 + VAR["Vb"] / VAR["VJ"]) ** VAR["M"]
        tr = dict(kind="varactor", Cblk=VAR["Cblk"], Vb=VAR["Vb"], VJ=VAR["VJ"], M=VAR["M"], CJO=cjo)
        c2part = c2n - ceff
        for rb in (1e6, 10e6, 100e6):
            J.append(jobsc(f"rvar_{op}_Rb{rb/1e6:g}M", dict(op=op, C2=c2part, trim=dict(tr, Rb=rb))))
        trb = dict(tr, Rb=100e6)
        for sgn, nm in ((1, "hot"), (-1, "cold")):
            J.append(jobsc(f"rvar_{op}_vartc_{nm}", dict(op=op, C2=c2part, trim=dict(trb, tcfac=1 + sgn * VAR_TC))))
            J.append(jobsc(f"rvar_{op}_c0g_{nm}", dict(op=op, C1=c1n * (1 + sgn * C0G_TC), C2=c2part * (1 - sgn * C0G_TC), trim=trb)))
        J.append(jobsc(f"rvar_{op}_range5", dict(op=op, C2=c2part, trim=trb, rng="5")))
        J.append(jobsc(f"rideal_{op}_range5", dict(op=op, C2=c2n, rng="5")))
        J.append(jobsc(f"rideal_{op}_lin", dict(op=op, C2=c2part, trim=dict(kind="ideal", C=ceff))))
        # (e) DAC0 to node N through the PA-3 switch, 270 mV swing (N moves as in the loop)
        for ro in (0.0, 300.0, 1000.0):
            J.append((f"rloop_{op}_rout{ro:g}", dict(scope=dict(R760, op=op, C2=c2n, loopback=True), rout=ro, swing_mv=270.0)))
        J.append((f"rloop_{op}_C1hi5", dict(scope=dict(R760, op=op, C1=c1n * 1.05, C2=c2n * 0.95, loopback=True), swing_mv=270.0)))
    J += [("ro_base_rout300_270", dict(baseline=True, rout=300.0, swing_mv=270.0)),
          ("ro_base_rout1000_270", dict(baseline=True, rout=1000.0, swing_mv=270.0))]
    for ro in (300.0, 1000.0):
        dac_for("derived", ro)
    out["B"] = run_pool(job, J, workers)
    out["AC"] = run_pool(scope_ac, ACJ, workers)
    out["var"] = dict(VAR, cv_mid=20e-12, ceff=ceff, cjo=cjo, tc=VAR_TC)
    json.dump(out, open(os.path.join(RES, "routes.json"), "w"), indent=1, default=float)
    return out


UNC_SCALES = (1.0, 0.3, 0.1, 0.05, 0.04, 0.03, 0.02, 0.01, 0.007, 0.005, 0.003, 0.001)


def step_routes2(workers=5):
    """Refines (c)'s window and separates the varactor's bias-network effect from its non-linearity."""
    dac_for("derived")
    O = json.load(open(os.path.join(RES, "routes.json")))
    J, ACJ = [], []
    for op in OPS:
        for sc_ in (0.05, 0.04, 0.02, 0.007, 0.005):
            sc = dict(R760, op=op, R1=760e3 * sc_, R2=335e3 * sc_, R3=760e3 * sc_, C1=0.1e-12, C2=2e-12)
            J.append(jobsc(f"runc_{op}_s{sc_:g}", sc)); ACJ.append((f"acunc_{op}_s{sc_:g}", sc))
        c2part = O["nulls"][op]["c2"] * 1e-12 - O["var"]["ceff"]
        J.append(jobsc(f"rvarlin_{op}_Rb100M", dict(op=op, C2=c2part, trim=dict(kind="varlin", Cblk=VAR["Cblk"], Cv=20e-12, Rb=100e6, Vb=1.5))))
    O["B"].update(run_pool(job, J, workers)); O["AC"].update(run_pool(scope_ac, ACJ, workers))
    json.dump(O, open(os.path.join(RES, "routes.json"), "w"), indent=1, default=float)


# ------------------------------------------------------------------ inverting AWG rows
def awg_pm(a, load, name):
    """AN-1: Middlebrook injection at the op-amp output, DAC quiet; PM at the last |T| = 1 crossing."""
    r = awg_only(name, dict(a, pm=True), load, ".ac dec 60 1k 2G", src="DC 1.65")
    f = r["frequency"].real; T = -r["v(a_oo)"] / r["v(a_out)"]
    m = np.abs(T); ph = np.degrees(np.unwrap(np.angle(T)))
    i = np.where((m[:-1] >= 1) & (m[1:] < 1))[0]
    if not len(i):
        return dict(pm=float("nan"), fc=float("nan"))
    i = i[0]; w = np.log(m[i]) / (np.log(m[i]) - np.log(m[i + 1]))   # the first (loop) crossing
    pm = 180 + ph[i] + w * (ph[i + 1] - ph[i])
    pm = (pm + 180) % 360 - 180
    return dict(pm=float(pm), fc=float(np.exp(np.log(f[i]) + w * (np.log(f[i + 1]) - np.log(f[i])))))


def awg_dc(a, load, name, lo=0.578, hi=2.771):
    r = awg_only(name, a, load, f".dc Vdac {lo} {hi} 0.001", src="DC 1.65")
    v = r["v(bnc)"].real; x = r["v(dac0)"].real if "v(dac0)" in r else np.linspace(lo, hi, len(v))
    i = -r["i(vdac)"].real if "i(vdac)" in r else None
    return x, v, i


def awg_op(a, load, vdac, name, rout=0.0):
    r = awg_only(name, a, load, ".op", src=f"DC {vdac}", rout=rout)
    out = {k: float(np.real(v[0])) for k, v in r.items() if k.startswith("v(") or k.startswith("i(")}
    return out


def inv_rows_one(args):
    tag, a = args
    try:
        R = {}
        pms = {}
        for ld in ("hiz", "r50", "cable_open", "cable_r50"):
            pms[ld] = awg_pm(a, ld, f"iv_{tag}_pm_{ld}")
        R["pm"] = pms
        if a.get("rows_only_pm"):
            return tag, R
        R.update(bw_hiz=awg_bw(a, "hiz", name=f"iv_{tag}_hz"), bw_r50=awg_bw(a, "r50", name=f"iv_{tag}_r5"),
                 bw_cable_open=awg_bw(a, "cable_open", name=f"iv_{tag}_co"),
                 bw_rout1k=awg_bw(a, "hiz", rout=1000.0, name=f"iv_{tag}_ro"),
                 step=awg_overshoot(a, name=f"iv_{tag}_st"))
        if a.get("noise", True):
            R["aw6_uV"] = awg_noise(a, name=f"iv_{tag}_nz") * 1e6
        if a.get("full", False):
            # AW-1, AW-5: DC map over the measured window, high-Z and 50 ohm, nominal and weak rails
            for rl, (vp, vn) in (("nom", (3.3, VN_AWG)), ("weak", (3.23, 0.95 * VN_AWG))):
                q = dict(a, vp=vp, vn=vn)
                x, vh, ih = awg_dc(q, "hiz", f"iv_{tag}_dch_{rl}")
                _, v5, _ = awg_dc(q, "r50", f"iv_{tag}_dc5_{rl}")
                k = np.argmin(np.abs(x - 1.65))
                g = (vh[k + 50] - vh[k - 50]) / (x[k + 50] - x[k - 50])
                lin = vh[k] + g * (x - x[k])
                m = np.abs(lin) <= 1.0
                R[f"dc_{rl}"] = dict(gain=float(g), offset_at_1v65=float(vh[k]), dac_for_pm1V=[float(x[k] - 1 / g), float(x[k] + 1 / g)],
                                     hiz_err_mV=float(np.max(np.abs(vh[m] - lin[m])) * 1e3),
                                     r50_err_mV=float(np.max(np.abs(v5[m] - lin[m] * 50 / (50 + a["Rs"]))) * 1e3),
                                     r50_min_max=[float(v5[m].min()), float(v5[m].max())],
                                     dac_uA_max=float(np.max(np.abs(ih)) * 1e6) if ih is not None else None)
            # PW-3: short at the window ends
            R["pw3_mA"] = max(abs(awg_op(a, "short", vd, f"iv_{tag}_sh{j}").get("v(a_out)", 0.0)) / a["Rs"] * 1e3
                              for j, vd in enumerate((0.578, 2.771)))
            # AW-8: DAC0 at its reset/boot levels, Vmid and rail corners
            w8 = []
            for vd, ro in ((0.0, 0.0), (3.3, 0.0), (-0.1, 0.0), (0.2, 0.0), (1.65, 1e9)):
                for vm in (1.55, 1.685):
                    for vp, vn in ((3.37, 1.05 * VN_AWG), (3.23, 0.95 * VN_AWG)):
                        o = awg_op(dict(a, vmid=vm, vp=vp, vn=vn), "hiz", vd, f"iv_{tag}_b", rout=ro)
                        w8.append((vd if ro < 1 else "floating", vm, vp, vn, o["v(bnc)"]))
            R["aw8"] = w8
        return tag, R
    except Exception as e:
        return tag, dict(error=str(e)[-1500:])


def step_inv(workers=5):
    dac_for("derived")
    A0 = dict(AWG0, **INV)
    rows = [("val_noninv_final", dict(AWG0, Ca=20e-12, Cb=12e-12, rows_only_pm=True))]
    for cp in (0.5, 1.5, 3.5):
        rows.append((f"inv_Cf0_C{cp:g}", dict(A0, Cpar_p=cp * 1e-12, Cpar_n=cp * 1e-12, full=(cp == 1.5), noise=(cp == 1.5))))
    for cf, nm in ((12e-12 / 3, "4p"), (6e-12, "6p"), (10e-12, "10p")):     # 12+12+12, 12+12, 20+20 pF in series
        rows.append((f"inv_Cf{nm}_C1.5", dict(A0, Cf=cf, noise=False)))
    rows += [("guard_pm_Cn20p", dict(A0, Cpar_n=20e-12, rows_only_pm=True)),
             ("guard_aw5_Rin3x4k7", dict(A0, Rin_spec=[4.7e3, 4.7e3, 4.7e3], Rf_spec=[4.7e3, 4.7e3, 4.7e3, 680.0], full=True, noise=False)),
             ("guard_aw8_Rf+30pct", dict(A0, Rf_spec=([4.7e3] * 6 + [680.0], 330e3), full=True, noise=False))]
    R = run_pool(inv_rows_one, rows, workers)
    J = [("ro_base", dict(baseline=True))]
    for cp in (0.5, 1.5, 3.5):
        J.append((f"invL_Cf0_C{cp:g}_ideal", dict(awg=dict(INV, Cpar_p=cp * 1e-12, Cpar_n=cp * 1e-12), scope=dict(ideal=True))))
        J.append((f"invL_Cf0_C{cp:g}_OPA354", dict(awg=dict(INV, Cpar_p=cp * 1e-12, Cpar_n=cp * 1e-12), scope=dict(R760, op="OPA354", C2=38.5e-12))))
    for cf, nm in ((12e-12 / 3, "4p"), (6e-12, "6p")):
        J.append((f"invL_Cf{nm}_C1.5_ideal", dict(awg=dict(INV, Cf=cf), scope=dict(ideal=True))))
    J.append(("guard_invL_slowCf100p", dict(awg=dict(INV, Cf=100e-12), scope=dict(ideal=True))))
    Lr = run_pool(job, J, workers)
    json.dump(dict(rows=R, loop=Lr), open(os.path.join(RES, "inv.json"), "w"), indent=1, default=float)


# ------------------------------------------------------------------ buffered DAC0 + low-impedance attenuator
# Buffer: OPA365 follower on +3.3 V_A (BAT54 + 100 nF), 680 ohm in series at its input, 330k from its input to Vmid
# (a floating DAC0 then gives 0 V out).  Attenuator: Ra 953, Rb 953 + (249 || 249) + 22 = 1099.5 (0.1 % / 1 % types),
# no Rx, Rf = Rb's network value 1099.5, Rg 953: slope Rb/Ra = 1.1537 and zero at Vmid exactly, no Ca/Cb.
BUF = dict(buf=True, Ra=953.0, Rb=953.0 + 124.5 + 22.0, Rb_spec=[953.0, (249.0, 249.0), 22.0], Ra_spec=953.0,
           Rx=0.0, Rf=953.0 + 124.5 + 22.0, Rg=953.0, Ca=0.0, Cb=0.0, Cf=12e-12)
# Cf 12 pF across Rf (one existing part, Rf.Cf = 13 ns): without it AW-4 reads 9.6 % and AW-6 118 uV (guard rows)


def buf_rows_one(args):
    tag, a = args
    tg, R = inv_rows_one((tag, a))
    if "error" in R:
        return tag, R
    try:
        R["pm_buf"] = {ld: awg_pm_buf(a, ld, f"bf_{tag}_pmb_{ld}") for ld in ("hiz", "r50")}
        if a.get("full"):
            R["i33_mA"] = {f"{vd:g}": awg_op(a, "hiz", vd, f"bf_{tag}_i{j}").get("i(visb_a)", float("nan")) * 1e3
                           for j, vd in enumerate((0.578, 1.65, 2.771))}
            R["buf_out_reset"] = {f"{vd:g}": awg_op(a, "hiz", vd, f"bf_{tag}_r{j}").get("v(a_bo)") for j, vd in enumerate((0.0, -0.1, 0.2, 3.3))}
        return tag, R
    except Exception as e:
        R["error_buf"] = str(e)[-800:]
        return tag, R


def awg_pm_buf(a, load, name):
    r = awg_only(name, dict(a, pm_buf=True), load, ".ac dec 60 1k 2G", src="DC 1.65")
    f = r["frequency"].real; T = -r["v(a_boo)"] / r["v(a_bo)"]
    m = np.abs(T); ph = np.degrees(np.unwrap(np.angle(T)))
    i = np.where((m[:-1] >= 1) & (m[1:] < 1))[0]
    if not len(i):
        return dict(pm=float("nan"), fc=float("nan"))
    i = i[0]; w = np.log(m[i]) / (np.log(m[i]) - np.log(m[i + 1]))
    pm = 180 + ph[i] + w * (ph[i + 1] - ph[i]); pm = (pm + 180) % 360 - 180
    return dict(pm=float(pm), fc=float(np.exp(np.log(f[i]) + w * (np.log(f[i + 1]) - np.log(f[i])))))


def step_buf(workers=5):
    dac_for("derived"); dac_for("derived", 1000.0)
    A0 = dict(AWG0, **BUF)
    rows = []
    for cp in (0.5, 1.5, 3.5):
        rows.append((f"buf_C{cp:g}", dict(A0, Cpar_p=cp * 1e-12, Cpar_n=cp * 1e-12, full=(cp == 1.5), noise=(cp == 1.5))))
    rows += [("guard_buf_slow_Ra4k7x4", dict(A0, Ra=18.8e3, Ra_spec=[4.7e3] * 4, Rb=4.7e3 * 4 * 1.1537, Rb_spec=4.7e3 * 4 * 1.1537, noise=False)),
             ("guard_buf_noCf", dict(A0, Cf=0.0, noise=True)),
             ("info_buf_pm_Cbo1n", dict(A0, Cpar_p=1e-9, noise=False))]
    R = run_pool(buf_rows_one, rows, workers)
    J = [("ro_base", dict(baseline=True))]
    for cp in (0.5, 1.5, 3.5):
        J.append((f"bufL_C{cp:g}_ideal", dict(awg=dict(BUF, Cpar_p=cp * 1e-12, Cpar_n=cp * 1e-12), scope=dict(ideal=True))))
    J.append(("bufL_C1.5_ideal_rout1k", dict(awg=dict(BUF), scope=dict(ideal=True), rout=1000.0)))
    J.append(("ro_base_rout1000", dict(baseline=True, rout=1000.0)))
    J.append(("guard_bufL_slow_Ra4k7x4", dict(awg=dict(BUF, Ra=18.8e3, Ra_spec=[4.7e3] * 4, Rb=4.7e3 * 4 * 1.1537, Rb_spec=4.7e3 * 4 * 1.1537), scope=dict(ideal=True))))
    # PA-3 injection from the buffered node (DAC0 Rout 1 k, the case that failed unbuffered)
    J.append(("rloopbuf_OPA365_rout1000", dict(scope=dict(R760, op="OPA365", C2=33.06e-12, loopback=True, loop_buf=True), rout=1000.0, swing_mv=270.0)))
    J.append(("rloopbuf_OPA354_rout1000", dict(scope=dict(R760, op="OPA354", C2=38.5e-12, loopback=True, loop_buf=True), rout=1000.0, swing_mv=270.0)))
    J.append(("ro_base_rout1000_270", dict(baseline=True, rout=1000.0, swing_mv=270.0)))
    Lr = run_pool(job, J, workers)
    json.dump(dict(rows=R, loop=Lr), open(os.path.join(RES, "buf.json"), "w"), indent=1, default=float)


def summary_buf():
    fn = os.path.join(RES, "buf.json")
    if not os.path.exists(fn):
        return ""
    O = json.load(open(fn)); L = ["\n# Buffered DAC0 + low-impedance attenuator (OPA365 follower; Ra 953, Rb 953 + 249||249 + 22, Rf = Rb, Rg 953, no Rx, no Ca/Cb)\n"]
    L.append("| case | AN-1 AWG stage hi-Z / 50 ohm / 1 m open | AN-1 buffer hi-Z / 50 ohm | BW hi-Z (peak) | BW 50 ohm | AW-4 overshoot | settle 1 % | AW-6 |\n|---|---|---|---|---|---|---|---|")
    for k, r in O["rows"].items():
        if "error" in r:
            L.append(f"| {k} | failed {r['error'][:120]} |"); continue
        pm = " / ".join(f"{r['pm'][l]['pm']:.1f}" for l in ("hiz", "r50", "cable_open"))
        pb = " / ".join(f"{r['pm_buf'][l]['pm']:.1f}" for l in ("hiz", "r50")) if "pm_buf" in r else ""
        nz = f"{r['aw6_uV']:.1f} uV" if "aw6_uV" in r else ""
        L.append(f"| {k} | {pm} | {pb} | {r['bw_hiz']['f3db']/1e6:.1f} MHz ({r['bw_hiz']['peak_db']:.2f} dB) | {r['bw_r50']['f3db']/1e6:.1f} MHz | "
                 f"{r['step']['overshoot']*100:.2f} % | {r['step']['settle_1pct_ns']:.0f} ns | {nz} |")
    for k, r in O["rows"].items():
        if "dc_nom" in r:
            d, w = r["dc_nom"], r["dc_weak"]; w8 = max(abs(x[4]) for x in r["aw8"])
            L.append(f"\n{k}: gain {d['gain']:.4f}, offset at 1.65 V {d['offset_at_1v65']*1e3:+.1f} mV; DAC for +/-1 V {d['dac_for_pm1V'][0]:.3f}..{d['dac_for_pm1V'][1]:.3f} V "
                     f"({abs(d['dac_for_pm1V'][1]-d['dac_for_pm1V'][0])/2.193*100:.1f} % of the window); 50 ohm, weak rails {w['r50_min_max'][0]:.4f}..{w['r50_min_max'][1]:.4f} V "
                     f"(error {w['r50_err_mV']:.3f} mV); AW-5 (buffer input) {d['dac_uA_max']:.2f} uA; PW-3 {r['pw3_mA']:.2f} mA; AW-8 worst |out| {w8:.3f} V; "
                     f"buffer output at DAC0 0 / -0.1 / 0.2 / 3.3 V: " + " / ".join(f"{v:.3f}" for v in r["buf_out_reset"].values()) +
                     " V; +3.3 V_A current added (buffer, DAC0 0.578 / 1.65 / 2.771 V): " + " / ".join(f"{v:.2f}" for v in r["i33_mA"].values()) + " mA")
    b = O["loop"]["ro_base"]
    L.append("\n| loop run (+/-1.25 V) | ISI at the pin | ISI normalised | allowance at the pin | SM-5 |\n|---|---|---|---|---|")
    for k, r in O["loop"].items():
        if k.startswith("ro_base"): continue
        if "error" in r:
            L.append(f"| {k} | failed {r['error'][:140]} | | | |"); continue
        bb = O["loop"].get("ro_base_rout1000_270") if k.startswith("rloopbuf") else (O["loop"].get("ro_base_rout1000") if "rout1k" in k else b)
        n = norm_isi(r, bb)
        L.append(f"| {k} | {n['isi_pin']:+.2f} | {n['isi_norm']:+.2f} | {n['allow_pin']:.2f} | {'PASS' if n['ok'] else '**FAIL**'} |")
    return "\n".join(L) + "\n"


def step_vmid(workers=5):
    """Combined run: buffered AWG (Cf 12 pF) into sim/scope's low-impedance channel (netlib P_LOWZ), +/-1.25 V,
    with ideal Vmid sources and with powercal's per-channel Vmid generator (linear stand-in, see VMID_LIN_RO) on the
    scope channel and on the AWG."""
    dac_for("derived")
    J = [("ro_base", dict(baseline=True))]
    for op in OPS:
        for vg in (False, "lin"):
            sc = dict(SN.P_LOWZ, op=op, rng="1.25", vmid_gen=vg)
            aw = dict(BUF, vmid_gen=vg)
            if not vg:
                sc["Rvo"] = 1e-3; aw["rvm"] = 1e-3
            for cp in (0.5, 1.5, 3.5):
                J.append((f"cmb_{op}_{'vmreal' if vg else 'vmideal'}_C{cp:g}", dict(awg=dict(aw, Cpar_p=cp * 1e-12, Cpar_n=cp * 1e-12), scope=sc)))
        J.append((f"cmb_{op}_vmideal_noCsoff", dict(awg=dict(BUF, rvm=1e-3), scope=dict(SN.P_LOWZ, op=op, rng="1.25", Rvo=1e-3, Csoff=1e-18))))
        J.append((f"cmb_{op}_vmreal_noCsoff", dict(awg=dict(BUF, vmid_gen="lin"), scope=dict(SN.P_LOWZ, op=op, rng="1.25", vmid_gen="lin", Csoff=1e-18))))
    # guard: the scope's Vmid generator with its 10 uF removed must read worse
    J.append(("guard_cmb_OPA365_vmreal_noC10u_noCsoff", dict(awg=dict(BUF, vmid_gen="lin"), scope=dict(SN.P_LOWZ, op="OPA365", rng="1.25", vmid_gen="lin", vm_noc=True, Csoff=1e-18))))
    zc = {}
    for lin in (False, True):      # the stand-in's |Z| against the macromodel generator's
        L = vmid_gen_lines("vm", 1.65, "_s", lin=lin)
        run_ng("vz", f"* vz\n.include {AWG_LIBS['OPA365']}\n" + "\n".join(L) + "\nIac 0 vm DC 0 AC 1\n.control\nac dec 40 100 100meg\nwrdata ../work/vz.dat v(vm)\n.endc\n.end\n")
        d = np.loadtxt(os.path.join(WORK, "vz.dat")); os.remove(os.path.join(WORK, "vz.dat"))
        zc["lin" if lin else "macro"] = (d[:, 0], np.abs(d[:, 1] + 1j * d[:, 2]))
    f, zm = zc["macro"]; zl = zc["lin"][1]; m = (f >= 1e3) & (f <= 1e7)
    zchk = dict(macro_1k=float(np.interp(1e3, f, zm)), macro_38k=float(np.interp(38e3, f, zm)), lin_1k=float(np.interp(1e3, f, zl)),
                lin_38k=float(np.interp(38e3, f, zl)), max_rel_err_1k_10M=float(np.max(np.abs(zl[m] / zm[m] - 1))))
    json.dump(dict(netlib_sha=sha(os.path.join(SCOPE, "netlib.py")), zcheck=zchk, runs=run_pool(job, J, workers)), open(os.path.join(RES, "vmid.json"), "w"), indent=1, default=float)


def summary_vmid():
    fn = os.path.join(RES, "vmid.json")
    if not os.path.exists(fn):
        return ""
    D = json.load(open(fn)); O = D["runs"]; b = O["ro_base"]
    z = D["zcheck"]
    L = [f"\n# Combined: buffered AWG into sim/scope P_LOWZ (netlib sha {D['netlib_sha'][:16]}), +/-1.25 V, Vmid ideal against powercal's per-channel generator\n",
         f"Generator stand-in |Z|: {z['lin_1k']*1e3:.1f} mohm at 1 kHz and {z['lin_38k']:.3f} ohm at 38 kHz against the macromodel's {z['macro_1k']*1e3:.1f} mohm and {z['macro_38k']:.3f} ohm; within {z['max_rel_err_1k_10M']*100:.1f} % over 1 kHz-10 MHz.\n",
         "| run | ISI at the pin | ISI normalised | allowance at the pin | SM-5 |\n|---|---|---|---|---|"]
    for k, r in O.items():
        if k == "ro_base": continue
        if "error" in r:
            L.append(f"| {k} | failed {r['error'][:140]} | | | |"); continue
        n = norm_isi(r, b)
        L.append(f"| {k} | {n['isi_pin']:+.2f} | {n['isi_norm']:+.2f} | {n['allow_pin']:.2f} | {'PASS' if n['ok'] else '**FAIL**'} |")
    return "\n".join(L) + "\n"


def awg_vmid_follower_check(fit=True):
    """The AWG's own Vmid follower (330k/330k tap, 12 pF, bare OPA365 follower, no output capacitor): its output
    impedance 100 Hz-10 MHz and its response to a 100 mV step on the divider's top, TI macromodel against the linear
    stand-in.  The follower's supply is +3.3 V_A behind its BAT54S (taken as 2.95 V) and ground *(check)*."""
    def net(lin, m, kind, name):
        L = ["Vtop top 0 dc 3.3" + (" PWL(0 3.3 2u 3.3 2.001u 3.4 1 3.4)" if kind == "step" else ""),
             "Vsp vsp 0 dc 2.95", "Rdt top tap 330k", "Rdb tap 0 330k", "Cdt tap 0 12p"]
        L += lin_opamp("_c", "tap", "out", "out", m) if lin else ["Xf tap out vsp 0 out OPA365"]
        if kind == "z":
            L.append("Iac 0 out DC 0 AC 1")
            an = "ac dec 40 100 10meg"
        else:
            L.append("Rld out 0 1e9")
            an = "tran 1n 30u 0 5n"
        run_ng(name, f"* {name}\n.include {AWG_LIBS['OPA365']}\n" + "\n".join(L) +
               f"\n.control\n{an}\nwrdata ../work/{name}.dat v(out) v(tap)\n.endc\n.end\n")
        d = np.loadtxt(os.path.join(WORK, name + ".dat")); os.remove(os.path.join(WORK, name + ".dat"))
        return d
    dm = net(False, None, "z", "vfz_m"); f = dm[:, 0]; zm = np.abs(dm[:, 1] + 1j * dm[:, 2])
    sm = net(False, None, "step", "vfs_m"); ts = sm[:, 0]; ym = sm[:, 1] - sm[0, 1]
    def score(m):
        dl = net(True, m, "z", "vfz_l"); zl = np.abs(dl[:, 1] + 1j * dl[:, 2])
        sl = net(True, m, "step", "vfs_l"); yl = np.interp(ts, sl[:, 0], sl[:, 1] - sl[0, 1])
        return float(np.max(np.abs(zl / zm - 1))), float(np.max(np.abs(yl - ym)) / 0.05), zl
    out = {"macro": dict(z100=float(zm[0]), z1k=float(np.interp(1e3, f, zm)), z1M=float(np.interp(1e6, f, zm)),
                         z10M=float(zm[-1]), step_final_mV=float(ym[-1] * 1e3))}
    e, es, _ = score(OPA365_LIN["p8k"])
    out["p8k"] = dict(z_max_rel_err=e, step_max_err_rel=es)
    e, es, _ = score(OPA365_LIN["awgfol"])
    out["awgfol_in_use"] = dict(OPA365_LIN["awgfol"], z_max_rel_err=e, step_max_err_rel=es)
    if fit:
        best = None
        for ro in (64.4, 66.0, 67.0, 68.0, 69.0, 70.0, 72.0):
            for cin in (0.0, 4e-12, 5e-12, 5.5e-12, 6e-12, 6.5e-12, 7e-12):
                m = dict(OPA365_LIN["p8k"], rout=ro, cin=cin)
                e2, es2, _ = score(m)
                k = max(e2, es2)
                if best is None or k < best[0]:
                    best = (k, e2, es2, dict(a0_db=90.0, gbw=59.2e6, rout=ro, cin=cin))
        best = best[1:]
        out["fit"] = dict(z_max_rel_err=best[0], step_max_err_rel=best[1], **best[2])
    json.dump(out, open(os.path.join(RES, "vmid_awg_check.json"), "w"), indent=1, default=float)
    return out


# ------------------------------------------------------------------ SM-5 arithmetic and tables
GAIN_RNG = {"1.25": 1.1265, "5": 0.2330}     # scope gain to the pin, sim/scope (as built)
AWG_GAIN = 1.1533                            # DAC pin to AWG output, sim/awg


def k_noise(rng):
    """docs/afe.md AW-6 arithmetic: the Due's 0.64 mV floor with SC-6 at the pin and AW-6 through the scope gain."""
    return float(np.sqrt(DUE_FLOOR_MV**2 + SC6_MV**2 + (AW6_MV * GAIN_RNG[rng])**2) / DUE_FLOOR_MV)


def growth(disi, rng, B):
    """Band with the AFE = the Due's band widened by the noise ratio, plus the AFE-added ISI in full."""
    return (B * k_noise(rng) + disi) / B - 1


def summary():
    D = json.load(open(os.path.join(RES, "runs.json")))
    R, F = D["runs"], D["fit"]
    L = []
    A = L.append
    A("## DAC fit (baseline network, numpy state space)\n")
    A("| S/H model, DAC Rout | DAC pole tau | slew | predicted rise 999/699/499/350/250/175 mV (ns) | note |\n|---|---|---|---|---|")
    for k, f in F.items():
        pr = " / ".join(f"{f['pred_rise_ns'][s]:.1f}" for s in ("999", "699", "499", "350", "250", "175"))
        A(f"| {k} | {f['taud']*1e9:.2f} ns | {f['slew']/1e6:.2f} V/us | {pr} | {f['note']} |")
    A("\nMeasured (linux-x1, docs/ets-mode.md): " + " / ".join(f"{ETS_RISE[s]*1e9:.1f}" for s in (999, 699, 499, 350, 250, 175)) + " ns.\n")
    A("## Noise factor (docs/afe.md arithmetic)\n")
    for rng in ("1.25", "5"):
        A(f"- +/-{rng} V: sqrt({DUE_FLOOR_MV}^2 + {SC6_MV}^2 + ({AW6_MV} x {GAIN_RNG[rng]})^2) / {DUE_FLOOR_MV} = {k_noise(rng):.4f} "
          f"(+{(k_noise(rng)-1)*100:.2f} %), leaving {(LIMIT-(k_noise(rng)-1))*8.6:.3f} codes of ISI at a band of 8.6 codes and {(LIMIT-(k_noise(rng)-1))*11.4:.3f} at 11.4")
    A("\n## Every loop run against its baseline\n")
    A("| case | baseline | loop band, worst level (codes) | baseline band | AFE-added ISI | growth at 8.6 | growth at 11.4 | SM-5 (10 %) |\n|---|---|---|---|---|---|---|---|")
    for t, kw, bt in cases():
        r, b = R.get(t, {}), R.get(bt, {})
        rng = (kw.get("scope") or {}).get("rng", "1.25")
        if "error" in r or "worst" not in r:
            A(f"| {t} | {bt} | run failed: {r.get('error','missing')[:160]} | | | | | NOT RUN |")
            continue
        d = r["worst"] - b["worst"]
        g1, g2 = growth(d, rng, 8.6), growth(d, rng, 11.4)
        A(f"| {t} | {bt} | {r['worst']:.2f} | {b['worst']:.2f} | {d:+.2f} | {g1*100:+.1f} % | {g2*100:+.1f} % | {'PASS' if g1 <= LIMIT else '**FAIL**'} |")
    A("\n## Sampling phase (single phase, worst level, codes; centre of the fold's window = 0.50)\n")
    keys = [k for k in R if "phase" in R[k]]
    ph = list(R[keys[0]]["phase"].keys())
    A("| case | " + " | ".join(ph) + " | window 0.3-0.7 |\n|" + "---|" * (len(ph) + 2))
    for k in keys:
        A(f"| {k} | " + " | ".join(f"{R[k]['phase'][p]:.2f}" for p in ph) + f" | {R[k]['window_0.3_0.7']:.2f} |")
    if os.path.exists(os.path.join(RES, "sweeps.json")):
        S = json.load(open(os.path.join(RES, "sweeps.json")))
        A("\n## Each stage alone, compensation swept (the other stage ideal)\n")
        A("| run | band, worst level (codes) | AFE-added ISI (against base) | boundary (ns) |\n|---|---|---|---|")
        for k, r in S.items():
            if "error" in r:
                A(f"| {k} | failed: {r['error'][:120]} | | |"); continue
            A(f"| {k} | {r['worst']:.2f} | {r['worst']-R['base']['worst']:+.2f} | {r['boundary_ns']:.0f} |")
    if os.path.exists(os.path.join(RES, "extras.json")):
        E = json.load(open(os.path.join(RES, "extras.json")))
        A("\n## Guard, positive control, switched S/H\n")
        for k in ("guard_pass", "guard_slowawg", "guard_slowawg_real", "sw_cont"):
            r = E[k]
            if "error" in r:
                A(f"- {k}: failed {r['error'][:200]}"); continue
            d = r["worst"] - R["base"]["worst"]
            A(f"- {k}: band {r['worst']:.2f} codes, AFE-added {d:+.2f}, growth at 8.6 {growth(d,'1.25',8.6)*100:+.1f} % -> {'PASS' if growth(d,'1.25',8.6) <= LIMIT else 'FAIL'}")
        A(f"- metric positive control (baseline waveform + a known fraction of the previous symbol): " +
          ", ".join(f"inject {k}: {v:.2f} codes (expected {E['inject']['widths']['0'] + E['inject']['expected_growth'][k]:.2f})" for k, v in E["inject"]["widths"].items()))
        A(f"- switched S/H against the continuous one, same instants ({E['switched']['n']} samples): max {E['switched']['max_abs_codes']:.3f} codes, rms {E['switched']['rms_codes']:.3f}")
    txt = "\n".join(L) + "\n" + summary_followups() + summary_routes() + summary_n1() + summary_inv() + summary_buf() + summary_vmid() + summary_vmchk()
    open(os.path.join(RES, "summary.md"), "w").write(txt)
    return txt


def readings(isi, sp_loop, sp_base, rng, B=8.6):
    """Three SM-5 readings of one result (growth at band B):
    codes  : docs/afe.md's arithmetic, the Due's floor held fixed in codes;
    codesD : the floor is DAC0's 0.64 mV, white (owner, 2026-11-11), so it is amplified by the loop gain;
    norm   : the same, but the band divided by the level spacing (input-referred)."""
    gl = sp_loop / sp_base
    kn = float(np.sqrt((DUE_FLOOR_MV * gl) ** 2 + SC6_MV ** 2 + (AW6_MV * GAIN_RNG[rng]) ** 2) / (DUE_FLOOR_MV * gl))
    return dict(gain=gl, codes=growth(isi, rng, B), codesD=(B * gl * kn + isi) / B - 1,
                norm=(B * kn + isi / gl) / B - 1)


def fmt_read(d):
    v = lambda x: f"{x*100:+.1f} %{'' if x <= LIMIT else ' F'}"
    return f"{v(d['codes'])} | {v(d['codesD'])} | {v(d['norm'])}"


def summary_followups():
    L = []; A = L.append
    D = json.load(open(os.path.join(RES, "runs.json")))["runs"]
    base, bsp = D["base"]["worst"], D["base"]["spacing"]
    A("\n## Three SM-5 readings (growth at a band of 8.6 codes; F = over 10 %)\n")
    A("codes: docs/afe.md arithmetic, floor fixed in codes. codes, DAC floor: the 0.64 mV floor is DAC0's own white noise and is amplified by the loop gain. "
      "normalised: the same floor, the band divided by the level spacing (input-referred). Loop gain = loop spacing / baseline spacing.\n")
    A("| run | ISI (codes) | loop gain | codes | codes, DAC floor | normalised |\n|---|---|---|---|---|---|")
    pick = ["OPA365_Ca20_nom", "OPA354_Ca20_nom", "OPA365_idealawg", "OPA354_idealawg", "idealboth", "OPA365_Ca20_range5", "OPA354_Ca20_range5"]
    for k in pick:
        r = D[k]; rng = "5" if "range5" in k else "1.25"
        A(f"| {k} | {r['worst']-base:+.2f} | {r['spacing']/bsp:.3f} | " + fmt_read(readings(r['worst'] - base, r['spacing'], bsp, rng)) + " |")
    fn = os.path.join(RES, "nocap.json")
    if os.path.exists(fn):
        N = json.load(open(fn))
        A("\n## Follow-up 1: AWG with no Ca and no Cb\n")
        A("### AWG rows (stage alone, sim/awg's loads; first row validates this copy against sim/awg revision 5)\n")
        A("| case | BW hi-Z | BW 50 ohm | BW 1 m open (far end) | gain 8 MHz / DC, hi-Z | DAC Rout 1 k: gain, BW | AW-4 overshoot (limit 5 %) | settle 1 % | AW-6 (limit 100 uV) |\n|---|---|---|---|---|---|---|---|---|")
        for k, r in N["rows"].items():
            if "error" in r:
                A(f"| {k} | failed: {r['error'][:150]} |"); continue
            nz = f"{r['aw6_uV']:.1f} uV" if "aw6_uV" in r else ""
            A(f"| {k} | {r['bw_hiz']['f3db']/1e6:.1f} MHz | {r['bw_r50']['f3db']/1e6:.1f} MHz | {r['bw_cable_open']['f3db']/1e6:.1f} MHz | {r['bw_hiz']['g8M']:.3f} | "
              f"{r['bw_rout1k']['dc']:.3f}, {r['bw_rout1k']['f3db']/1e6:.1f} MHz | {r['step']['overshoot']*100:.2f} % | {r['step']['settle_1pct_ns']:.0f} ns | {nz} |")
        A("\n### Loop ISI with the no-cap AWG (+/-1.25 V)\n")
        A("| run | ISI (codes) | loop gain | codes | codes, DAC floor | normalised |\n|---|---|---|---|---|---|")
        for k, r in N["loop"].items():
            if "error" in r:
                A(f"| {k} | failed: {r['error'][:150]} |"); continue
            A(f"| {k} | {r['worst']-base:+.2f} | {r['spacing']/bsp:.3f} | " + fmt_read(readings(r['worst'] - base, r['spacing'], bsp, "1.25")) + " |")
    A("\nHost frequency-response correction of the scope shelf was tried and dropped: the owner holds SM-5 on the raw signal (2026-11-11).\n")
    return "\n".join(L) + "\n"


def norm_isi(r, b, rng="1.25", B=8.6):
    """SM-5 as the owner holds it (2026-11-11): the band relative to the level spacing, raw signal.
    The Due's floor (0.64 mV, DAC0's own white noise) scales with the loop gain like the levels, so
    in normalised form only SC-6 and AW-6 widen it.  ISI_norm = worst/G - base, G = spacing/base spacing."""
    g = r["spacing"] / b["spacing"]
    kn = float(np.sqrt((DUE_FLOOR_MV * g) ** 2 + SC6_MV ** 2 + (AW6_MV * GAIN_RNG[rng]) ** 2) / (DUE_FLOOR_MV * g))
    isi = r["worst"] / g - b["worst"]
    allow = (LIMIT - (kn - 1)) * B
    return dict(G=g, kn=kn, isi_norm=isi, isi_pin=isi * g, allow_norm=allow, allow_pin=allow * g,
                growth=(B * kn + isi) / B - 1, ok=isi <= allow)


def summary_routes():
    fn = os.path.join(RES, "routes.json")
    if not os.path.exists(fn):
        return ""
    O = json.load(open(fn)); A_, B_ = O["A"], O["B"]; ALL = dict(A_, **B_)
    base, b270 = ALL["ro_base"], ALL["ro_base270"]
    L = []; A = L.append
    def row(tag, b=base, rng="1.25", extra=""):
        r = ALL.get(tag, {})
        if "error" in r or "worst" not in r:
            return f"| {tag} | run failed: {r.get('error','missing')[:140]} | | | | | |"
        n = norm_isi(r, b, rng)
        return (f"| {tag} | {n['isi_pin']:+.2f} | {n['isi_norm']:+.2f} | {n['allow_pin']:.2f} | {n['growth']*100:+.1f} % | "
                f"{'PASS' if n['ok'] else '**FAIL**'} | {extra} |")
    hdr = "| run | ISI at the pin (codes) | ISI normalised (baseline codes) | allowance at the pin | growth (normalised) | SM-5 | note |\n|---|---|---|---|---|---|---|"
    # guard on the normalised reading: a pure gain must read zero
    g = 1.3; fake = dict(worst=base["worst"] * g, spacing=base["spacing"] * g)
    n0 = norm_isi(fake, base)
    A("\n# Scope-divider routes (R1 = R3 = 760k; AWG ideal so the scope's share is alone)\n")
    n = norm_isi(ALL["ro_null_OPA354_39.0"], base)
    A(f"**Allowance (SM-5 normalised, raw signal).** The 0.64 mV floor is DAC0's and scales with the loop gain G like the levels, so "
      f"k = sqrt((0.64 G)^2 + 0.2^2 + (0.1 x 1.1265)^2) / (0.64 G); at G = {n['G']:.3f}: k = {n['kn']:.4f} (+{(n['kn']-1)*100:.2f} %), "
      f"leaving (10 % - {(n['kn']-1)*100:.2f} %) x 8.6 = **{n['allow_norm']:.3f} codes normalised = {n['allow_pin']:.2f} codes at the pin** "
      f"(at 11.4: {(LIMIT-(n['kn']-1))*11.4*n['G']:.2f} at the pin). This budget is shared by the AWG and the scope.\n")
    A(f"Guard on the reading: the baseline scaled by 1.3 (a pure gain) reads {n0['isi_norm']:+.3f} codes normalised; the codes reading would read {(g-1)*base['worst']:+.2f}.\n")
    A("## C2 nulls\n\n| op-amp | C2 sweep (pF): ISI at the pin | null C2 | slope (codes per pF) | C2 accuracy needed for the whole allowance |\n|---|---|---|---|---|")
    for op, d in O["nulls"].items():
        pts = ", ".join(f"{c:g}: {v:.1f}" for c, v in zip(d["grid"], d["isi"]))
        res = n["allow_pin"] / abs(d["slope"]) if d.get("slope") == d.get("slope") else float("nan")
        A(f"| {op} | {pts} | {d['c2']:.2f} pF | {d['slope_down']:.1f} / +{d['slope_up']:.1f} | +/-{res*1e3:.0f} fF |")
    # null_fit self-check on a synthetic V
    sv = null_fit(np.arange(30, 40.1, 0.5), np.abs(np.arange(30, 40.1, 0.5) - 34.3) * 12 + 0.2)
    A(f"\nnull_fit self-check: synthetic V with its null at 34.30 pF and slope 12 reads {sv['c2']:.2f} pF, slope {sv['slope']:.2f}.\n")
    A("## (c2) Tighter capacitors at the null (C1 and C2 at opposite ends of the tolerance)\n\n" + hdr)
    for op in OPS:
        A(row(f"rc2_{op}_null", extra=f"C2 at the null {O['nulls'][op]['c2']:.2f} pF"))
        for t in (1, 2, 5):
            for e in ("C1hi", "C1lo"):
                A(row(f"rc2_{op}_t{t}_{e}", extra=f"+/-{t} %"))
        for e in ("a", "b"):
            A(row(f"rc2_{op}_c0gdrift_{e}", extra="C0G +/-30 ppm/K x 20 K, opposite on C1/C2, from an exact null"))
    A("\n## (c) Uncompensated divider, R scaled (0.1 pF across R1, 2 pF at N, strays *(check)*)\n")
    A("| op-amp | scale | R1 / R2 / R3 | Thevenin at N | input resistance | SM-3 bandwidth | ISI at the pin | ISI normalised | SM-3 | SM-5 |\n|---|---|---|---|---|---|---|---|---|---|")
    AC = O["AC"]
    for op in OPS:
        need = 8e6 if op == "OPA354" else 7e6
        for sc_ in UNC_SCALES:
            if f"runc_{op}_s{sc_:g}" not in ALL:
                continue
            r1, r2, r3 = 760e3 * sc_, 335e3 * sc_, 760e3 * sc_
            rth = 1 / (1 / r1 + 1 / r2 + 1 / r3); rin = r1 + 1 / (1 / r2 + 1 / r3)
            r = ALL.get(f"runc_{op}_s{sc_:g}", {}); a = AC.get(f"acunc_{op}_s{sc_:g}", {})
            if "worst" not in r or "bw" not in a:
                A(f"| {op} | {sc_:g} | failed | | | | | | | |"); continue
            nn = norm_isi(r, base)
            A(f"| {op} | {sc_:g} | {r1/1e3:.4g}k / {r2/1e3:.4g}k / {r3/1e3:.4g}k | {rth/1e3:.3g} k | {rin/1e3:.4g} k | {a['bw']/1e6:.2f} MHz | {nn['isi_pin']:+.2f} | {nn['isi_norm']:+.2f} | "
              f"{'PASS' if a['bw'] >= need else '**FAIL**'} | {'PASS' if nn['ok'] else '**FAIL**'} |")
    A("\n## (c) Compensated divider at 1 M, 100 k and 10 k, C0G +/-5 % (C2 part rescaled so the nominal is the null)\n")
    A("| op-amp | input resistance | SM-3 bandwidth | ISI nominal | ISI C1 +5 % / C2 -5 % | ISI C1 -5 % / C2 +5 % | worst SM-5 |\n|---|---|---|---|---|---|---|")
    for op in OPS:
        for sc_ in (1.0, 0.1, 0.01):
            rin = (760e3 + 1 / (1 / 335e3 + 1 / 760e3)) * sc_
            v = [ALL.get(f"rcomp_{op}_s{sc_:g}_{e}", {}) for e in ("nom", "C1hi", "C1lo")]
            if any("worst" not in x for x in v):
                A(f"| {op} | {rin/1e3:.4g} k | failed | | | | |"); continue
            nn = [norm_isi(x, base) for x in v]; a = AC.get(f"accomp_{op}_s{sc_:g}", {})
            A(f"| {op} | {rin/1e3:.4g} k | {a.get('bw', float('nan'))/1e6:.2f} MHz | " + " | ".join(f"{x['isi_pin']:+.2f}" for x in nn) +
              f" | {'PASS' if all(x['ok'] for x in nn) else '**FAIL**'} |")
    V = O["var"]
    A("\n## (b) Varactor trim (assumed abrupt junction, VJ 0.7 V, M 0.5, 400 ppm/K, Cblk 220 pF C0G, set at Vb 1.5 V where Cv = 20 pF) *(check)*\n")
    A(f"Cv(1.5 V) = 20 pF, Ceff = Cblk series Cv = {V['ceff']*1e12:.2f} pF, CJO = {V['cjo']*1e12:.2f} pF; the C2 part is the null minus Ceff.\n\n" + hdr)
    for op in OPS:
        A(row(f"rideal_{op}_lin", extra="linear trim of the same Ceff (reference: should equal the null)"))
        for rb in ("1", "10", "100"):
            A(row(f"rvar_{op}_Rb{rb}M", extra=f"varactor, bias resistor {rb} Mohm (signal dependence included)"))
        if f"rvarlin_{op}_Rb100M" in ALL:
            A(row(f"rvarlin_{op}_Rb100M", extra="the same network, varactor replaced by a linear 20 pF: the bias network alone"))
        for nm in ("hot", "cold"):
            A(row(f"rvar_{op}_vartc_{nm}", extra="+ varactor tempco 400 ppm/K x 20 K *(check)*"))
            A(row(f"rvar_{op}_c0g_{nm}", extra="+ C0G drift of C1/C2, opposite"))
        A(row(f"rvar_{op}_range5", rng="5", extra="+/-5 V range (normalised against the +/-1.25 V baseline gain reading)"))
        A(row(f"rideal_{op}_range5", rng="5", extra="+/-5 V range, ideal null, no varactor"))
    A("\n## (e) Internal loopback: DAC0 to node N through the PA-3 switch (3.7 ohm), 270 mV swing, against a 270 mV baseline\n\n" + hdr)
    for op in OPS:
        A(row(f"rloop_{op}_rout0", b=b270, extra="DAC Rout 0"))
        A(row(f"rloop_{op}_rout300", b=ALL.get("ro_base_rout300_270", b270), extra="DAC Rout 300 ohm"))
        A(row(f"rloop_{op}_rout1000", b=ALL.get("ro_base_rout1000_270", b270), extra="DAC Rout 1 kohm"))
        A(row(f"rloop_{op}_C1hi5", b=b270, extra="C1 +5 % / C2 -5 %"))
    return "\n".join(L) + "\n"


# ================================================================== AWG n1 (whatif/awg-rab), with and without Ca/Cb
def step_n1(workers=5):
    dac_for("derived")
    rows = [("n1_Ca20Cb12_Cpar1.5", dict(N1, Ca=20e-12, Cb=12e-12))]
    for cp in (0.5, 1.5, 3.5):
        rows.append((f"n1_nocap_Cpar{cp:g}", dict(N1, Ca=0.0, Cb=0.0, Cpar_p=cp * 1e-12, noise=(cp == 1.5))))
        rows.append((f"n1_Ca20Cb12_Cpar{cp:g}x", dict(N1, Ca=20e-12, Cb=12e-12, Cpar_p=cp * 1e-12, noise=False)))
    rows.append(("ref_13k7_15k8_Ca20Cb12", dict(Ca=20e-12, Cb=12e-12)))
    R = run_pool(awg_rows_one, [(t, dict(AWG0, **a)) for t, a in rows], workers)
    scopes = {"ideal": dict(ideal=True), "OPA354": dict(R760, op="OPA354", C2=38.5e-12),
              "OPA365": dict(R760, op="OPA365", C2=33.06e-12),
              "OPA354_unc30k": dict(R760, op="OPA354", R1=760e3 * 0.03, R2=335e3 * 0.03, R3=760e3 * 0.03, C1=0.1e-12, C2=2e-12)}
    J = []
    for cp in (0.5, 1.5, 3.5):
        for cap, aw in (("nocap", dict(N1, Ca=0.0, Cb=0.0)), ("Ca20Cb12", dict(N1, Ca=20e-12, Cb=12e-12))):
            for sn, sc in scopes.items():
                J.append((f"n1L_{cap}_Cpar{cp:g}_{sn}", dict(awg=dict(aw, Cpar_p=cp * 1e-12), scope=sc)))
    J.append(("n1L_ref13k7_Cpar1.5_ideal", dict(awg=dict(Ca=20e-12, Cb=12e-12), scope=dict(ideal=True))))
    J.append(("ro_base", dict(baseline=True)))
    L = run_pool(job, J, workers)
    json.dump(dict(rows=R, loop=L), open(os.path.join(RES, "n1.json"), "w"), indent=1, default=float)


def step_n1ca(workers=5):
    """Where n1's attenuator null sits: Ca swept with Cb 12 pF, scope ideal, V+ parasitic 1.5 pF."""
    dac_for("derived")
    J = [(f"n1ca_{ca:g}", dict(awg=dict(N1, Ca=ca * 1e-12, Cb=12e-12), scope=dict(ideal=True))) for ca in (18, 19, 20, 21, 22, 23, 24, 25, 26)]
    J.append(("ro_base", dict(baseline=True)))
    json.dump(run_pool(job, J, workers), open(os.path.join(RES, "n1ca.json"), "w"), indent=1, default=float)


def summary_n1():
    fn = os.path.join(RES, "n1.json")
    if not os.path.exists(fn):
        return ""
    O = json.load(open(fn)); base = O["loop"]["ro_base"]
    L = ["\n# AWG n1 (Ra 16.45k, Rb 18.8k, 1 %, 0.3 pF per node, 11 ohm supply filter)\n",
         "| case | BW hi-Z | BW 50 ohm | BW 1 m open (far end) | DAC Rout 1 k: gain, BW | AW-4 overshoot (5 %) | settle 1 % | AW-6 (100 uV) |\n|---|---|---|---|---|---|---|---|"]
    for k, r in O["rows"].items():
        if "error" in r:
            L.append(f"| {k} | failed: {r['error'][:150]} |"); continue
        nz = f"{r['aw6_uV']:.1f} uV" if "aw6_uV" in r else ""
        L.append(f"| {k} | {r['bw_hiz']['f3db']/1e6:.1f} MHz | {r['bw_r50']['f3db']/1e6:.1f} MHz | {r['bw_cable_open']['f3db']/1e6:.1f} MHz | "
                 f"{r['bw_rout1k']['dc']:.3f}, {r['bw_rout1k']['f3db']/1e6:.1f} MHz | {r['step']['overshoot']*100:.2f} % | {r['step']['settle_1pct_ns']:.0f} ns | {nz} |")
    L.append("\nLoop, +/-1.25 V, scope at its C2 null with R1 = R3 = 760k (or the uncompensated 30 k divider), normalised SM-5:\n")
    L.append("| run | ISI at the pin | ISI normalised | allowance at the pin | growth | SM-5 |\n|---|---|---|---|---|---|")
    for k, r in O["loop"].items():
        if k == "ro_base": continue
        if "error" in r or "worst" not in r:
            L.append(f"| {k} | failed: {r.get('error','')[:140]} | | | | |"); continue
        n = norm_isi(r, base)
        L.append(f"| {k} | {n['isi_pin']:+.2f} | {n['isi_norm']:+.2f} | {n['allow_pin']:.2f} | {n['growth']*100:+.1f} % | {'PASS' if n['ok'] else '**FAIL**'} |")
    fn2 = os.path.join(RES, "n1ca.json")
    if os.path.exists(fn2):
        C = json.load(open(fn2)); b = C["ro_base"]
        pts = [(float(k.split("_")[1]), norm_isi(v, b)["isi_pin"]) for k, v in C.items() if k.startswith("n1ca_") and "worst" in v]
        nf = null_fit([p[0] for p in pts], [p[1] for p in pts])
        L.append("\nn1 attenuator, Ca swept (Cb 12 pF, V+ 1.5 pF, scope ideal), ISI at the pin: " + ", ".join(f"{c:g} pF: {v:.1f}" for c, v in pts) +
                 f"; null {nf['c2']:.2f} pF, slope {nf.get('slope_down', float('nan')):.1f} / +{nf.get('slope_up', float('nan')):.1f} codes per pF.\n")
    return "\n".join(L) + "\n"


def summary_inv():
    fn = os.path.join(RES, "inv.json")
    if not os.path.exists(fn):
        return ""
    O = json.load(open(fn)); L = ["\n# Inverting AWG (Rin 4 x 4.7k + 680 = 19.48k, Rf (5 x 4.7k) || 330k = 21.94k, G 1.126; Vref' (174k || 174k) + 1k + 680 over 100k, 100 nF)\n"]
    L.append("Phase margin by Middlebrook injection at the op-amp output (first |T| = 1 crossing). The method reads the non-inverting revision-5 stage at "
             "80.9 deg (hi-Z) where sim/awg's loop-break reads about 72: use it to rank, not to the degree *(check)*.\n")
    L.append("| case | AN-1 PM hi-Z / 50 ohm / 1 m open (>= 45 deg) | BW hi-Z (peaking) | BW 50 ohm | AW-4 overshoot | settle 1 % | AW-6 |\n|---|---|---|---|---|---|---|")
    for k, r in O["rows"].items():
        if "error" in r:
            L.append(f"| {k} | failed {r['error'][:120]} |"); continue
        pm = " / ".join(f"{r['pm'][l]['pm']:.1f}" for l in ("hiz", "r50", "cable_open"))
        if "bw_hiz" not in r:
            L.append(f"| {k} | {pm} | | | | | |"); continue
        nz = f"{r['aw6_uV']:.0f} uV" if "aw6_uV" in r else ""
        L.append(f"| {k} | {pm} | {r['bw_hiz']['f3db']/1e6:.2f} MHz ({r['bw_hiz']['peak_db']:.1f} dB) | {r['bw_r50']['f3db']/1e6:.2f} MHz | "
                 f"{r['step']['overshoot']*100:.1f} % | {r['step']['settle_1pct_ns']:.0f} ns | {nz} |")
    for k, r in O["rows"].items():
        if "dc_nom" in r:
            d, w = r["dc_nom"], r["dc_weak"]
            w8 = max(abs(x[4]) for x in r["aw8"])
            L.append(f"\n{k}: gain {d['gain']:.4f}, offset at 1.65 V {d['offset_at_1v65']*1e3:+.1f} mV; DAC for +/-1 V {d['dac_for_pm1V'][1]:.3f}..{d['dac_for_pm1V'][0]:.3f} V "
                     f"(window 0.578-2.771 V, {(d['dac_for_pm1V'][0]-d['dac_for_pm1V'][1])/2.193*100:.1f} % of it); AW-1 into 50 ohm, weak rails: {w['r50_min_max'][0]:.4f}..{w['r50_min_max'][1]:.4f} V, "
                     f"error {w['r50_err_mV']:.3f} mV; AW-5 {d['dac_uA_max']:.1f} uA; PW-3 {r['pw3_mA']:.2f} mA; AW-8 worst |out| {w8:.3f} V "
                     f"(DAC0 0 / -0.1 / +0.2 / 3.3 V / floating, Vmid 1.55-1.685, both rail corners)")
    b = O["loop"]["ro_base"]
    L.append("\n| loop run | ISI at the pin | ISI normalised | allowance at the pin | SM-5 |\n|---|---|---|---|---|")
    for k, r in O["loop"].items():
        if k == "ro_base": continue
        if "error" in r:
            L.append(f"| {k} | failed {r['error'][:120]} | | | |"); continue
        n = norm_isi(r, b)
        L.append(f"| {k} | {n['isi_pin']:+.1f} | {n['isi_norm']:+.1f} | {n['allow_pin']:.2f} | {'PASS' if n['ok'] else '**FAIL**'} |")
    return "\n".join(L) + "\n"


def summary_vmchk():
    fn = os.path.join(RES, "vmid_awg_check.json")
    if not os.path.exists(fn):
        return ""
    O = json.load(open(fn)); m, p, u = O["macro"], O["p8k"], O["awgfol_in_use"]
    return ("\n# AWG Vmid follower stand-in (330k/330k tap, 12 pF, bare OPA365 follower)\n\n"
            f"Macromodel |Zout|: {m['z100']*1e3:.2f} mohm at 100 Hz, {m['z1k']*1e3:.2f} mohm at 1 kHz, {m['z1M']:.3f} ohm at 1 MHz, {m['z10M']:.2f} ohm at 10 MHz. "
            f"P8-k unchanged: |Zout| within {p['z_max_rel_err']*100:.1f} %, tap step (100 mV on the divider top, 50 mV at the tap) within {p['step_max_err_rel']*100:.1f} % of the step: not used. "
            f"In use: A0 90.0 dB, GBW 59.2 MHz, Rout {u['rout']:.0f} ohm, input capacitance {u['cin']*1e12:.0f} pF: |Zout| within {u['z_max_rel_err']*100:.1f} % from 100 Hz to 10 MHz, step within {u['step_max_err_rel']*100:.2f} %.\n")


if __name__ == "__main__":
    want = sys.argv[1:] or ["all"]
    t0 = time.time()
    if "all" in want or "sims" in want:
        R = run_all()
        json.dump(dict(fit=FIT, runs=R), open(os.path.join(RES, "runs.json"), "w"), indent=1, default=float)
    if "rerun" in want:      # re-run listed tags (argv after 'rerun') into runs.json
        tags = set(want[want.index("rerun") + 1:])
        J = [(k, v) for k, v in BASES.items() if k in tags] + [(t, kw) for t, kw, _ in cases() if t in tags]
        D = json.load(open(os.path.join(RES, "runs.json")))
        D["runs"].update(run_all(jobs=J)); D["fit"].update(FIT)
        json.dump(D, open(os.path.join(RES, "runs.json"), "w"), indent=1, default=float)
    if "all" in want or "sweeps" in want:
        json.dump(run_all(jobs=sweeps()), open(os.path.join(RES, "sweeps.json"), "w"), indent=1, default=float)
    if "all" in want or "extras" in want:
        print(json.dumps(extras(), indent=1, default=float)[:3000])
    if "all" in want or "nocap" in want:
        step_nocap()
    if "all" in want or "routes" in want:
        step_routes()
    if "all" in want or "routes2" in want:
        step_routes2()
    if "all" in want or "n1" in want:
        step_n1()
    if "all" in want or "n1ca" in want:
        step_n1ca()
    if "all" in want or "inv" in want:
        step_inv()
    if "all" in want or "buf" in want:
        step_buf()
    if "all" in want or "vmid" in want:
        step_vmid()
    if "all" in want or "vmchk" in want:
        print(json.dumps(awg_vmid_follower_check(), indent=1, default=float))
    if "all" in want or "summary" in want:
        print(summary())
    print(f"done in {time.time()-t0:.0f} s")
