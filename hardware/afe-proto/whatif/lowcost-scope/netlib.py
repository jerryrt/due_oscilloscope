"""Netlist builders and ngspice plumbing for the scope-channel simulation (2b).
Imported by run.py (python3 -I run.py puts this directory on sys.path)."""
import os, re, subprocess, hashlib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
NETD = os.path.join(HERE, "netlists")
WORK = os.path.join(HERE, "work")
WORK_REL = "../work"          # WORK as seen from NETD (both are siblings, so model paths keep their depth)
MODELS = os.path.join(HERE, "..", "..", "models")
PFX = ""                      # name prefix, so that parallel section processes never share a netlist or data file

OPAMPS = {
    "OPA354": dict(lib="../../../models/opa354/OPA354_PSPICE.lib", sub="OPA354", vos_max=8e-3,
                   en=6.5e-9, gbw=100e6),
    "OPA365": dict(lib="../../../models/opa365/OPA365_PSPICE.lib", sub="OPA365", vos_max=0.2e-3,
                   en=4.5e-9, gbw=50e6),
}

# ---------------------------------------------------------------------------------------------
# Design variants.  'legacy' is the 1 Mohm compensated divider of the first 2b round, kept bit-for-bit
# reproducible (python3 -I run.py --variant legacy -> report_legacy.md, results/legacy/).  'lowz' is the
# uncompensated low-impedance divider of the 2026-11-11 redesign (SC-3 about 20-30 kohm, no x10 probes).
# ---------------------------------------------------------------------------------------------
# nominal design values (E96 / stated), overridable per run
P_LEGACY = dict(
    sw="rf", Rnp=680.0,      # 1 % 0603 E24 (MC-12: fewest part types)
    R1=768e3, R2=335e3, R3=768e3, RF=953.0, RG=249.0,   # settled design; R2 = 330k fixed + 5k trimmer mid-setting; SPEC below is as first specified
    C2=38e-12,          # external C2 at N; + 2 pF op-amp CM + stray -> ~40 pF total
    C1=None,            # None -> compensated: C1 = C2tot*R2/R1
    C2tot_extra=2e-12,  # op-amp input (datasheet 2 pF) added in parallel
    Cwire=4e-12,        # BNC + trace at IN, assumption *(check)*
    Rsrc=50.0,          # source impedance seen at the BNC
    Cf=0.0,             # optional feedback cap across RF
    Cpar=3e-12,         # inverting node: pad 2 pF + trace 1 pF *(assumption)*
    Cpar_extra=0.0,
    Riso=22.0,          # 1 % 0603 E24 (MC-12)
    Cpin=2e-12,         # package/pad capacitance at the ADC pin (Ci 8 pF = Cpin+Csample)
    Ron_sw=3.7, Cs_on=20e-12, Cs_off=6e-12,   # TMUX1119 3.3 V facts
    Rvo=0.05, Cvm1=10e-6, Cvm2=100e-9, esr=0.02,
    vcc=3.3, aref=3.3, vmid=None, v3=None, vos=0.0,
    rng="5",            # "5" = switch open (G=1), "1.25" = switch closed (G=4.83)
    op="OPA354",
    div="comp",         # compensated 1 Mohm divider (C1 across R1, C2 at N)
    sense="shared", Rv3=100.0, inj=None,
)

R100K_6 = 100e3 / 6                         # six 100k 0.1 % in parallel
R2_LOWZ = 8 * 953.0 * 330e3 / (8 * 953.0 + 330e3)   # (8 x 953) || 330k, all 0.1 %
P_LOWZ = dict(P_LEGACY)
P_LOWZ.update(
    div="unc",          # uncompensated divider: no C1, no C2
    R1=R100K_6 + 249.0, # 6 x 100k || + 249 in series: the 249 matches the per-channel sense resistor in the R3 leg
    R2=R2_LOWZ,         # (8 x 953) || 330k = 7451.7 ohm, N to Vmid
    R3=R100K_6,         # 6 x 100k ||, N to the channel's own sense node; + Rs3 249 to the Due 3.3 V pin = R1 at DC
    sense="perch", Rs3=249.0, Cs3=10e-6,     # one 249R 0.1 % + 10 uF sense filter PER CHANNEL (SC-9: a shared one couples)
    Rv3=0.1,            # the Due's 3.3 V pin as a source: 0.1 ohm *(assumption; VT-8)*
    C1=None, C2=0.0, C2tot_extra=0.0,
    Cn=2e-12,           # stray at N: pads of 13 parts + trace *(assumption, G3 parasitics)*
    Cr1=0.3e-12,        # parasitic across the R1 composite (6 x 0603 in parallel) *(assumption)*
    Rnp=0.0,            # no series resistor ahead of the + input: C1 is gone, so no fast edge reaches N (PR-1 case)
    inj="N",            # PA-3 injection TMUX1119 with N on a source pin (owner decision 2026-11-11)
    Csoff=6e-12,        # TMUX1119 CSOFF, datasheet; 10 pF from the IBIS model as a corner
    Cft=1.8e-12,        # S-to-D feedthrough when off, DERIVED from OISO -65 dB at 1 MHz / -45 dB at 10 MHz into 50 ohm
                        # (|H| = w C 50 ohm -> 1.79 pF at both points) *(derived, check)*
    Ron_inj=3.7,        # injection switch Ron when it sits in the R3 leg (inj="R3" proposal)
    vdac=1.65,          # DAC0 DC level for the coupling runs
)
# Round 2 (2026-11-11, coordinator): R3-leg injection adopted; R3 returns to a BUFFERED node, k x the Vmid tap, so the
# Due's 3.3 V pin carries only powercal's divider again.  k = 1 + (953 + 249)/(953 + 2 x 249) = 1.8284, so the buffer
# sits 0.21 V under the 3.23 V rail at AREF 3.30; centring then needs (R3 leg)/R1 = k - 1 = 0.8284.
P_LOWZ2 = dict(P_LOWZ)
P_LOWZ2.update(
    R1=1 / (5 / 100e3 + 1 / 174e3 + 2 / 330e3),              # 5 x 100k || 174k || 2 x 330k = 16179 ohm
    R3=1 / (7 / 100e3 + 2 / 330e3),                          # 7 x 100k || 2 x 330k = 13147 ohm (+ Rs3 249 + switch Ron)
    R2=8 * 953.0 + 249.0,                                    # 7873 ohm
    sense="buf", sbuf="shared", Rbf=953.0 + 249.0, Rbg=953.0 + 2 * 249.0,
    inj="R3", Rdac=249.0, Ron_inj=6.25,   # injection source: DAC0 buffer (OPA365) + 249 ohm, shared (owner); Ron_inj nominal = the 3.7-8.8 ohm mid, used for the matching
    sw="rf",            # the range switch shunts RF, as round 1 (SC-8 is 3 % since 2026-11-11; the Kelvin option, sw="kelvin",
                        # takes Ron out of the gain but widens +/-1.25 V to 15 MHz and fails SC-6 at 216 uV)
)
# 2026-11-11, owner: SM-5 dropped, back to 1 Mohm compensated.  The legacy design plus every approved change since.
P_HZ = dict(P_LEGACY)
P_HZ.update(
    R1=760e3, R3=760e3, R2=330e3,               # 330k + 330k + 100k (0.1 %); R2 330k fixed, no trimmer
    C1=12e-12,                                  # fixed 12 pF C0G (no longer the ideal: C2 is chosen to compensate it)
    C2=20e-12 + 12e-12 + 12e-12 * 20e-12 / 32e-12,   # 20 || 12 || (12 s 20) = 39.5 pF, Basic types only: the 100 kHz-step null
                                                # is 38.96 pF (sec 'comp'); the T-switch C2 was 20 || (12 s 39) = 29.18 pF
    C2tot_extra=0.0,                            # the op-amp's input capacitance is in its model
    Rnp=680.0, Riso=22.0, sw="rf",
    sense="shared", Rv3=0.1, Rs3=249.0, Cs3=10e-6,   # the shared 249R + 10 uF sense filter (approved), the Due pin behind 0.1 ohm
    inj=None,                                   # owner 2026-11-11: BNC-tee calibration, no injection switch on N
    Csoff=6e-12, Cft=1.8e-12, Ron_inj=3.7, Rdac=249.0, vdac=1.65,   # kept for inj="T" (the superseded T-switch, a what-if)
    vmid_perch=True,
)
VARIANTS = {"legacy": P_LEGACY, "lowz": P_LOWZ, "lowz2": P_LOWZ2, "hz": P_HZ}
VARIANT = "hz"
P0 = P_HZ

def use_variant(name):
    """Select a design variant: parameter set, netlist and work directories (siblings of the defaults, so the
    relative model paths in every netlist keep their depth)."""
    global VARIANT, P0, NETD, WORK, WORK_REL
    VARIANT = name
    P0 = VARIANTS[name]
    suf = "" if name == "hz" else "_" + name
    NETD = os.path.join(HERE, "netlists" + suf)
    WORK = os.path.join(HERE, "work" + suf)
    WORK_REL = "../work" + suf

def c1_of(p):
    if p.get("div", "comp") == "unc":
        return 0.0
    if p["C1"] is not None:
        return p["C1"]
    c2tot = p["C2"] + p["C2tot_extra"]
    r2 = p["R2"] if p["R3"] is None else p["R2"] * p["R3"] / (p["R2"] + p["R3"])
    return c2tot * r2 / p["R1"]

def core(p, pre="", loopbreak=False):
    """Channel netlist body.  External nodes: <pre>in, vmc (Vmid local), vccl (op-amp supply pin), <pre>pin.
    Vmid and Vcc sources are NOT included (callers add them).  Returns text."""
    o = OPAMPS[p["op"]]
    c1 = c1_of(p)
    s = []
    a = s.append
    a(f"* channel {pre or 'A'}: op-amp {p['op']}, range {p['rng']}")
    if p.get("div", "comp") == "unc":
        # uncompensated low-impedance divider; R3 returns to this channel's own sense node {pre}v3s
        a(f"R1{pre} {pre}in {pre}n {p['R1']:.6g}")
        a(f"Cr1{pre} {pre}in {pre}n {p['Cr1']:.6g}")
        a(f"R2{pre} {pre}n vm {p['R2']:.6g}")
        sn = f"{pre}v3s" if p.get("sense") in ("perch", "buf") else "v3"     # the channel's sense node
        r3far = f"{pre}r3e" if p.get("inj") == "R3" else sn
        a(f"R3{pre} {pre}n {r3far} {p['R3']:.6g}")
        a(f"Cn{pre} {pre}n 0 {p['Cn']:.6g}")
        if p.get("sense") == "perch":
            a(f"Rs3{pre} v3 {pre}v3s {p['Rs3']:.6g}")
            a(f"Cs3{pre} {pre}v3s 0 {p['Cs3']:.6g}")
        elif p.get("sense") == "buf":
            # R3 returns to a BUFFERED node: OPA365, non-inverting gain k = 1 + Rbf/Rbg from powercal's Vmid divider tap,
            # then this channel's own 249R + 10 uF.  sbuf='shared': one buffer for both channels (node v3b, in rails);
            # 'perch': one per channel (node {pre}v3b, here)
            src = "v3b" if p.get("sbuf", "shared") == "shared" else f"{pre}v3b"
            if p.get("sbuf", "shared") != "shared":
                a(sense_buffer(p, pre))
            a(f"Rs3{pre} {src} {pre}v3s {p['Rs3']:.6g}")
            a(f"Cs3{pre} {pre}v3s 0 {p['Cs3']:.6g}")
        if p.get("inj") == "N":      # TMUX1119, N on S1, D = DAC0, switch off
            a(f"Csw{pre} {pre}n 0 {p['Csoff']:.6g}")
            a(f"Cft{pre} {pre}n dac {p['Cft']:.6g}")
            if p.get("esd_n"):
                # the switch's ESD diodes at N, each through a 0 V ammeter: i(Vesa) into the rail, i(Vesb) out of ground
                a(f"Desa{pre} {pre}n {pre}esa DESD\nVesa{pre} {pre}esa vccl 0\nDesb{pre} {pre}esb {pre}n DESD\nVesb{pre} 0 {pre}esb 0")
        elif p.get("inj") == "R3":   # proposal: the switch in the R3 leg, D on the R3 end, S1 on the sense node, S2 on DAC0
            a(f"XSWI{pre} {pre}r3e {sn} RSW_CLOSED ron={p['Ron_inj']:.6g} con={p['Cs_on']:.6g}")
            a(f"Cft{pre} {pre}r3e dac {p['Cft']:.6g}")
        if p.get("mcp"):   # an MCP3564 input pin on N (powercal, 2026-11-11): series R, pin capacitance, coupling from the AWG nodes
            m = p["mcp"]
            a(f"Rmcp{pre} {pre}n {pre}mp {max(m.get('R', 0.0), 1e-3):.6g}\nCmp{pre} {pre}mp 0 {m['Cp']:.6g}\nCmx{pre} {pre}mp dac {m['Cx']:.6g}")
        a(f"Cw{pre} {pre}in 0 {p['Cwire']:.6g}")
    else:
        a(f"R1{pre} {pre}in {pre}n {p['R1']:.6g}")
        a(f"C1{pre} {pre}in {pre}n {c1:.6g}")
        a(f"R2{pre} {pre}n vm {p['R2']:.6g}")
        if p["R3"] is not None:
            a(f"R3{pre} {pre}n v3 {p['R3']:.6g}")
        a(f"C2{pre} {pre}n vm {p['C2']:.6g}")
        if p.get("inj") == "T":
            # PA-3 T-switch (two TMUX1119 in series, the middle held at Vmid when off), N on a source pin of the N-side switch:
            # CSOFF to ground at N, its S-D feedthrough to the middle node, the middle held at Vmid through Ron with CON on it,
            # and the DAC-side switch's feedthrough from the injection source (DAC0 buffer + 249 ohm) into the middle
            a(f"Csw{pre} {pre}n 0 {p['Csoff']:.6g}")
            a(f"Cft{pre} {pre}n {pre}mt {p['Cft']:.6g}")
            a(f"Rmt{pre} {pre}mt vm {p['Ron_inj']:.6g}\nCmt{pre} {pre}mt 0 {p['Cs_on']:.6g}")
            a(f"Cft2{pre} {pre}mt dac {p['Cft']:.6g}")
            if p.get("esd_n"):
                a(f"Desa{pre} {pre}n {pre}esa DESD\nVesa{pre} {pre}esa vccl 0\nDesb{pre} {pre}esb {pre}n DESD\nVesb{pre} 0 {pre}esb 0")
        a(f"Cw{pre} {pre}in 0 {p['Cwire']:.6g}")
    # op-amp offset as an explicit source in series with the + input (the vendor model has its own as well)
    if p.get("Rnp", 0) > 0:   # series resistor ahead of the + input limits the clamp current of a fast edge
        a(f"Vos{pre} {pre}n {pre}nv dc {p['vos']:.6g}")
        a(f"Rnp{pre} {pre}nv {pre}np {p['Rnp']:.6g}")
    else:
        a(f"Vos{pre} {pre}n {pre}np dc {p['vos']:.6g}")
    oa = f"{pre}outa" if loopbreak else f"{pre}out"
    a(f"XU{pre} {pre}np {pre}fb vccl 0 {oa} {o['sub']}")
    if loopbreak:   # Middlebrook break at the amplifier output: T = -V(outa)/V(out), input source off
        a(f"Vlb{pre} {pre}out {pre}outa dc 0 ac 1")
    if p.get("sw", "rg") == "rg":
        a(f"RF{pre} {pre}out {pre}fb {p['RF']:.6g}")
        if p["Cf"] > 0:
            a(f"CF{pre} {pre}out {pre}fb {p['Cf']:.6g}")
        a(f"RG{pre} {pre}fb {pre}d {p['RG']:.6g}")
        a(f"Cpar{pre} {pre}fb 0 {p['Cpar']+p['Cpar_extra']:.6g}")
        if p["rng"] == "1.25":   # switch closed
            a(f"XSW{pre} {pre}d vm RSW_CLOSED ron={p['Ron_sw']:.6g} con={p['Cs_on']:.6g}")
        else:                    # switch open
            a(f"XSW{pre} {pre}d vm RSW_OPEN coff={p['Cs_off']:.6g}")
    elif p.get("sw") == "kelvin":
        # the TMUX1119 SPDT selects what the inverting input SENSES: D on (-), S1 on the output (+/-5 V, follower),
        # S2 on the RF/RG tap (+/-1.25 V).  Ron carries only the input current, so it is in no gain.
        a(f"RF{pre} {pre}out {pre}tp {p['RF']:.6g}")
        a(f"RG{pre} {pre}tp vm {p['RG']:.6g}")
        a(f"Cpar{pre} {pre}fb 0 {p['Cpar']+p['Cpar_extra']:.6g}")
        a(f"Cptp{pre} {pre}tp 0 1p")
        if p["rng"] == "5":
            a(f"XSW{pre} {pre}fb {pre}out RSW_CLOSED ron={p['Ron_sw']:.6g} con={p['Cs_on']:.6g}")
            a(f"XSWo{pre} {pre}fb {pre}tp RSW_OPEN coff={p['Cs_off']:.6g}")
        else:
            a(f"XSW{pre} {pre}fb {pre}tp RSW_CLOSED ron={p['Ron_sw']:.6g} con={p['Cs_on']:.6g}")
            a(f"XSWo{pre} {pre}fb {pre}out RSW_OPEN coff={p['Cs_off']:.6g}")
    else:   # "rf": the range switch shorts RF (closed = +/-5 V, G=1); RG is fixed to Vmid
        a(f"RF{pre} {pre}out {pre}fb {p['RF']:.6g}")
        if p["Cf"] > 0:
            a(f"CF{pre} {pre}out {pre}fb {p['Cf']:.6g}")
        a(f"RG{pre} {pre}fb vm {p['RG']:.6g}")
        a(f"Cpar{pre} {pre}fb 0 {p['Cpar']+p['Cpar_extra']:.6g}")
        if p["rng"] == "5":
            a(f"XSW{pre} {pre}out {pre}fb RSW_CLOSED ron={p['Ron_sw']:.6g} con={p['Cs_on']:.6g}")
        else:
            a(f"XSW{pre} {pre}out {pre}fb RSW_OPEN coff={p['Cs_off']:.6g}")
    a(f"Riso{pre} {pre}out {pre}pin {p['Riso']:.6g}")
    a(f"Cp{pre} {pre}pin 0 {p['Cpin']:.6g}")
    if p.get("vmid_perch"):
        # one Vmid buffer per channel: powercal's linear stand-in P8-k (OPA365 as A0 / (1 + s A0 / 2 pi GBW) behind Rout,
        # A0 90 dB, GBW 59.2 MHz, Rout 64.4 ohm; 0.2 ohm isolation, 4.7k / 3 nF feedback, 20 uF + 100 nF), its + input on
        # the shared ideal Vmid node 'vm'; every channel element that returned to 'vm' returns to this channel's node
        vmc = f"{pre}vmc"
        s = [re.sub(r"(?<=\s)vm(?=\s|$)", vmc, l) for l in s]
        A0 = 10 ** (90.0 / 20); gbw = 59.2e6
        s += [f"* per-channel Vmid buffer {pre or 'A'} (P8-k stand-in)",
              f"Exa{pre} {pre}vxa 0 vm {pre}vfb {A0:.6g}", f"Rpa{pre} {pre}vxa {pre}vxb 1k", f"Cpa{pre} {pre}vxb 0 {A0 / (2 * np.pi * gbw * 1e3):.6g}",
              f"Eob{pre} {pre}vxo 0 {pre}vxb 0 1", f"Rvo{pre}x {pre}vxo {pre}vbo 64.4", f"Rvmi{pre} {pre}vbo {vmc} 0.2",
              f"Rvfb{pre} {vmc} {pre}vfb 4.7k", f"Cvfb{pre} {pre}vbo {pre}vfb 3n",
              f"Cvd1{pre} {vmc} {pre}vc1 20u", f"Rve1{pre} {pre}vc1 0 2.5m", f"Cvd2{pre} {vmc} {pre}vc2 100n", f"Rve2{pre} {pre}vc2 0 30m"]
    return "\n".join(s)

def rails(p, vcc=None, vmid=None, ac_vm=False, ac_v3=False, rail_bleed=None, ac_dac=False):
    """Supply, Vmid and the 3.3 V sense node with stated output impedances and decoupling.
    rail_bleed (ohm): replace the op-amp supply source by a floating rail with this bleed to ground."""
    vcc = p["vcc"] if vcc is None else vcc
    vmid = (p["aref"] / 2 if p["vmid"] is None else p["vmid"]) if vmid is None else vmid
    v3 = p["aref"] if p.get("v3") is None else p["v3"]
    if rail_bleed:
        supply = f"* floating AFE 3.3 V rail with a {rail_bleed} ohm bleed to ground\nRbleed vccl 0 {rail_bleed}\n"
    else:
        supply = f"""* supply: ideal {vcc} V behind 0.1 ohm + 10 nH
Vcc vcc0 0 dc {vcc}
Rvc vcc0 vcx 0.1
Lvc vcx vccl 10n
"""
    return supply + f"""* 100 nF + 1 uF decoupling (ESR 20 mohm) at the op-amp supply pin
Cdc1 vccl cd1 100n
Rdc1 cd1 0 {p['esr']}
Cdc2 vccl cd2 1u
Rdc2 cd2 0 {p['esr']}
* Vmid: ideal source {vmid} V, output impedance {p['Rvo']} ohm, decoupled 10 uF + 100 nF (ESR 20 mohm)
Vm vm0 0 dc {vmid} {'ac 1' if ac_vm else ''}
Rvo vm0 vm {p['Rvo']}
Cvm1 vm cv1 {p['Cvm1']}
Rcv1 cv1 0 {p['esr']}
Cvm2 vm cv2 {p['Cvm2']}
Rcv2 cv2 0 {p['esr']}
""" + sense_and_dac(p, v3, ac_v3, ac_dac)

def sense_and_dac(p, v3, ac_v3=False, ac_dac=False):
    if p.get("sense", "shared") == "shared" and p.get("Rv3", 100.0) == 100.0 and p.get("div", "comp") == "comp":
        return f"""* V3: the Due's 3.3 V pin (= AREF) sensed for centring, through 100 ohm + 10 uF (+100 nF) so its noise does not reach N
V3s v30 0 dc {v3} {'ac 1' if ac_v3 else ''}
Rv3 v30 v3 100
Cv3a v3 0 10u
Cv3b v3 0 100n
"""
    t = f"* V3: the Due's 3.3 V pin (= AREF) as a source behind {p['Rv3']} ohm; "
    if p.get("sense") == "perch":
        t += "each channel has its own 249R + 10 uF sense filter (in core)\n"
        t += f"V3s v30 0 dc {v3} {'ac 1' if ac_v3 else ''}\nRv3 v30 v3 {p['Rv3']}\n"
    else:   # one shared filter (the approved 2026-11-11 BOM: 249R + 10 uF), used as the SC-9 guard mutation
        t += f"one shared {p.get('Rs3', 249.0)} ohm + 10 uF sense filter for both channels\n"
        t += f"V3s v30 0 dc {v3} {'ac 1' if ac_v3 else ''}\nRv3 v30 v3p {p['Rv3']}\nRs3sh v3p v3 {p.get('Rs3', 249.0)}\nCs3sh v3 0 {p.get('Cs3', 10e-6)}\n"
    if p.get("sense") == "buf":
        # powercal's network on the Due's 3.3 V pin: the shared 249R + 10 uF sense filter (Rs3sh/Cs3sh above), then the
        # Vmid divider 330k/330k with 10 uF at its tap.  The sense buffer's + input is that tap; the Vmid source itself is
        # still the ideal one above (its +/-30 mV centring error is not tracked by the tap: conservative).
        t += "Rva v3 tap 330k\nRvb tap 0 330k\nCtap tap 0 10u\n"
        if p.get("sbuf", "shared") == "shared":
            t += sense_buffer(p, "")
    if p.get("inj"):
        rs = p.get("Rdac", 0.0)
        t += f"* DAC0 source for the injection switch: the AWG's DAC0 buffer (OPA365, ideal here) + {rs} ohm\n"
        t += f"Vdac dac0 0 dc {p.get('vdac', 1.65)} {'ac 1' if ac_dac else ''}\nRdac dac0 dac {max(rs, 1e-3):.6g}\n"
    return t

def sense_buffer(p, pre):
    """OPA365 non-inverting buffer of the Vmid tap, gain k = 1 + Rbf/Rbg, supplied from the AFE rail (vccl).
    Output node {pre}v3b.  vos_b: an explicit offset at its + input."""
    return (f"* sense buffer {pre or '(shared)'}: OPA365, gain 1 + {p['Rbf']:.6g}/{p['Rbg']:.6g}\n"
            f"VSBUFOS{pre} tap {pre}sbtap dc {p.get('vos_b', 0.0):.6g}\n"
            f"XSBUF{pre} {pre}sbtap {pre}sbfb vccl 0 {pre}v3b OPA365\n"
            f"RSBUFF{pre} {pre}v3b {pre}sbfb {p['Rbf']:.6g}\nRSBUFG{pre} {pre}sbfb 0 {p['Rbg']:.6g}\n")

def header(p, title):
    o = OPAMPS[p["op"]]
    t = f"* {title}\n.include {o['lib']}\n.include ../models/rangesw.lib\n.options abstol=1e-13 itl1=4000 itl4=500 reltol=1e-4 method=gear\n"
    if p.get("sense") == "buf" and p["op"] != "OPA365":
        t += f".include {OPAMPS['OPA365']['lib']}\n"
    if p.get("div", "comp") == "unc" or p.get("inj"):
        t += DESD_MODEL
    return t

# generic silicon ESD/clamp diode for the TMUX1119 pins and the unpowered netlists: 0.60 V at 10 uA, 0.72 V at 1 mA
# *(assumption: no datasheet gives the ESD diodes' I-V)*
DESD_MODEL = ".model DESD D(IS=1e-15 N=1 RS=5)\n"

def write_net(name, text):
    os.makedirs(NETD, exist_ok=True)
    path = os.path.join(NETD, PFX + name + ".cir")
    with open(path, "w") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    return path

def run_ng(name, text, timeout=600):
    """Write netlists/<name>.cir and run ngspice -b with cwd = netlists (relative model paths)."""
    os.makedirs(WORK, exist_ok=True)
    path = write_net(name, text)
    r = subprocess.run(["ngspice", "-b", os.path.basename(path)], cwd=NETD, capture_output=True,
                       text=True, timeout=timeout)
    return r.stdout + r.stderr

def wr(name, key):
    return f"{WORK_REL}/{PFX}{name}_{key}.dat"

def load(name, key, cols=None):
    fn = os.path.join(WORK, f"{PFX}{name}_{key}.dat")
    return np.loadtxt(fn)

def ngspice_version():
    out = subprocess.run(["ngspice", "-v"], capture_output=True, text=True).stdout
    for l in out.splitlines():
        if "ngspice" in l.lower() and re.search(r"\d", l):
            return l.strip()
    return out.strip().splitlines()[0]

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def freq_metrics(f, h):
    """-3 dB point relative to the low-frequency gain (first point), peaking in dB."""
    h = np.abs(h); db = 20 * np.log10(h / h[0])
    pk = db.max()
    idx = np.where(db < -3.0)[0]
    if len(idx) == 0:
        return dict(g0=float(h[0]), bw=float("inf"), peak_db=float(pk))
    i = idx[0]
    # log-interpolate the crossing
    f1, f2, d1, d2 = f[i - 1], f[i], db[i - 1], db[i]
    bw = 10 ** (np.log10(f1) + (np.log10(f2) - np.log10(f1)) * (-3.0 - d1) / (d2 - d1))
    return dict(g0=float(h[0]), bw=float(bw), peak_db=float(pk), f_peak=float(f[np.argmax(db)]))

def phase_margin(f, T):
    """Phase margin (deg) at the highest-frequency |T|=1 crossing; also gain margin (dB) at -180 deg."""
    mag = np.abs(T); ph = np.unwrap(np.angle(T)) * 180 / np.pi
    idx = np.where((mag[:-1] >= 1) & (mag[1:] < 1))[0]
    if len(idx) == 0:
        return dict(pm=None, fc=None, gm=None)
    i = idx[-1]
    w = (0 - np.log10(mag[i])) / (np.log10(mag[i + 1]) - np.log10(mag[i]))
    fc = 10 ** (np.log10(f[i]) + w * (np.log10(f[i + 1]) - np.log10(f[i])))
    phc = ph[i] + w * (ph[i + 1] - ph[i])
    # normalise so that a stable single-pole loop reads ~ -90 .. : phase relative to -180 wrap
    pm = 180 + phc
    while pm > 360: pm -= 360
    while pm < -180: pm += 360
    gm = None
    j = np.where((ph[:-1] > -180) & (ph[1:] <= -180))[0]
    if len(j):
        gm = float(-20 * np.log10(mag[j[0]]))
    return dict(pm=float(pm), fc=float(fc), gm=gm)

def ac_response(p, name, fmin=1e3, fmax=2e9, ppd=40):
    """Signal gain IN(BNC, via Rsrc) -> ADC pin, plus the output-break loop gain."""
    txt = header(p, name) + rails(p) + f"""Vs src 0 dc 0 ac 1
Rs src in {p['Rsrc']}
""" + core(p) + f"""
.control
ac dec {ppd} {fmin} {fmax}
wrdata {wr(name,'h')} v(pin)
.endc
.end
"""
    run_ng(name, txt)
    d = load(name, "h")
    f = d[:, 0]; h = d[:, 1] + 1j * d[:, 2]
    # loop gain run: input source quiet, break at amp output
    nm2 = name + "_T"
    txt = header(p, nm2) + rails(p) + f"""Vs src 0 dc 0 ac 0
Rs src in {p['Rsrc']}
""" + core(p, loopbreak=True) + f"""
.control
ac dec {ppd} {fmin} {fmax}
wrdata {wr(nm2,'t')} v(outa) v(out)
.endc
.end
"""
    run_ng(nm2, txt)
    d = load(nm2, "t")
    T = -(d[:, 1] + 1j * d[:, 2]) / (d[:, 4] + 1j * d[:, 5])
    return f, h, T

# the design as first specified (R2 to Vmid only, switch in the RG leg, RF 3.83k / RG 1.00k)
SPEC = dict(R2=237e3, R3=None, RF=3.83e3, RG=1.00e3, sw="rg", Rnp=0.0)


def noise_total(p, name, fmax, mode="all", fmin=10.0, ppd=20):
    """Output noise (V rms, 10 Hz..fmax) at the ADC pin.
    mode all : everything the netlist has;
    res      : resistor thermal noise only (op-amp replaced by a noiseless ideal 1e6 gain block);
    amp      : op-amp only, divider replaced by a noiseless Thevenin source, all resistors noiseless
               (op-amp voltage noise; its current noise acts on ~1 kohm and is negligible)."""
    q = dict(p)
    body = core(q)
    if mode == "res":
        body = re.sub(r"XU(\S*) (\S+) (\S+) vccl 0 (\S+) \S+", r"EU\1 \4 0 \2 \3 1e6", body)
    if mode == "amp":
        # divider: replace R1..R3 / C's with an ideal source at N (noiseless) and mark the gain network noiseless
        lines = []
        for l in body.splitlines():
            if re.match(r"(R1|R2|R3|C1|C2|Cw|Cr1|Cn|Csw|Cft)\S* ", l):
                continue
            lines.append(l)
        body = "\n".join(lines) + "\nVN n 0 dc 1.65\n"
    # silence resistors in amp mode
    if mode == "amp":
        body = re.sub(r"^(R\w+ \S+ \S+ [0-9.eE+-]+)$", r"\1 noisy=0", body, flags=re.M)
    txt = header(p, name) + rails(p) + "Vs src 0 dc 0 ac 1\nRs src in 50\n" + body + f"""
.control
noise v(pin) Vs dec {ppd} {fmin} {fmax}
setplot noise1
wrdata {wr(name,'n')} onoise_spectrum
setplot noise2
print onoise_total
.endc
.end
"""
    out = run_ng(name, txt)
    m = re.search(r"onoise_total\s*=\s*([0-9.eE+-]+)", out)
    if not m:
        raise RuntimeError("noise run failed: " + out[-800:])
    return float(m.group(1))
