"""Netlist builders and ngspice plumbing for the scope-channel simulation (2b).
Imported by run.py (python3 -I run.py puts this directory on sys.path)."""
import os, re, subprocess, hashlib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
NETD = os.path.join(HERE, "netlists")
WORK = os.path.join(HERE, "work")
MODELS = os.path.join(HERE, "..", "..", "..", "..", "models")

OPAMPS = {
    "OPA354": dict(lib="../../../../../models/opa354/OPA354_PSPICE.lib", sub="OPA354", vos_max=8e-3,
                   en=6.5e-9, gbw=100e6),
    "OPA365": dict(lib="../../../../../models/opa365/OPA365_PSPICE.lib", sub="OPA365", vos_max=0.2e-3,
                   en=4.5e-9, gbw=50e6),
}

# nominal design values (E96 / stated), overridable per run
P0 = dict(
    sw="buf", Rnp=680.0,     # WHATIF R1: unity buffer      # 1 % 0603 E24 (MC-12: fewest part types)
    R1=760e3, R2=330e3, R3=760e3, RF=953.0, RG=249.0,   # WHATIF R1: 330k+330k+100k, R2 330k fixed   # settled design; R2 = 330k fixed + 5k trimmer mid-setting; SPEC below is as first specified
    C2=39e-12,          # WHATIF C2: BOM 39 pF part; external C2 at N; + 2 pF op-amp CM + stray -> ~40 pF total
    C1=12e-12,          # WHATIF C2: BOM 12 pF; None -> compensated: C1 = C2tot*R2/R1
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
    op="OPA365",        # WHATIF C2
    Csw=0.0,            # WHATIF C2b: PA-3 injection switch capacitance at N (to ground)
    vmid_gen=False,     # WHATIF C2b: powercal Vmid generator instead of the 50 mohm source
)

def c1_of(p):
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
    a(f"R1{pre} {pre}in {pre}n {p['R1']:.6g}")
    a(f"C1{pre} {pre}in {pre}n {c1:.6g}")
    a(f"R2{pre} {pre}n vm {p['R2']:.6g}")
    if p["R3"] is not None:
        a(f"R3{pre} {pre}n v3 {p['R3']:.6g}")
    a(f"C2{pre} {pre}n vm {p['C2']:.6g}")
    if p.get("Csw", 0) > 0:
        a(f"Csw{pre} {pre}n 0 {p['Csw']:.6g}")
    a(f"Cw{pre} {pre}in 0 {p['Cwire']:.6g}")
    # op-amp offset as an explicit source in series with the + input (the vendor model has its own as well)
    if p.get("en_extra", 0) > 0:   # WHATIF R1 guard: white noise en_extra (V/rtHz) in series with +IN
        g = p["en_extra"] / (4 * 1.380649e-23 * 300.15 * 1e3) ** 0.5
        a(f"Rnz{pre} {pre}nzp 0 1k")
        a(f"Enz{pre} {pre}nze {pre}n {pre}nzp 0 {g:.6g}")
        n_in = f"{pre}nze"
    else:
        n_in = f"{pre}n"
    if p.get("Rnp", 0) > 0:   # series resistor ahead of the + input limits the clamp current of a fast edge
        a(f"Vos{pre} {n_in} {pre}nv dc {p['vos']:.6g}")
        a(f"Rnp{pre} {pre}nv {pre}np {p['Rnp']:.6g}")
    else:
        a(f"Vos{pre} {n_in} {pre}np dc {p['vos']:.6g}")
    oa = f"{pre}outa" if loopbreak else f"{pre}out"
    if p.get("sw") == "buf":   # WHATIF R1: unity buffer, no RF/RG/range switch; out drives -IN directly
        a(f"XU{pre} {pre}np {pre}out vccl 0 {oa} {o['sub']}")
        if loopbreak:
            a(f"Vlb{pre} {pre}out {pre}outa dc 0 ac 1")
        if p.get("Cpar_out", 0) > 0:   # trace/pad at the output node
            a(f"Cpo{pre} {pre}out 0 {p['Cpar_out']:.6g}")
        if p.get("en_extra", 0) > 0:   # WHATIF R1 guard: extra white voltage noise in series with +IN
            pass
        a(f"Riso{pre} {pre}out {pre}pin {p['Riso']:.6g}")
        a(f"Cp{pre} {pre}pin 0 {p['Cpin']:.6g}")
        if p.get("sh"):   # WHATIF R1: the ADC sample-and-hold as a continuous R-C load (sim/loop convention)
            a(f"Radc{pre} {pre}pin {pre}cs {p['sh'][0]:.6g}")
            a(f"Csh{pre} {pre}cs 0 {p['sh'][1]:.6g}")
        return "\n".join(s)
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
    return "\n".join(s)

def rails(p, vcc=None, vmid=None, ac_vm=False, ac_v3=False, rail_bleed=None):
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
    if p.get("vmid_gen"):
        vm_txt = f"""* WHATIF C2b: powercal Vmid generator (sim/powercal/run.py vmid_netlist): divider, 1 uF, OPA365 follower, 1 ohm, 10 uF + 100 nF, dual-path feedback
Vdvm vpvm 0 dc 3.34
V33m v33m 0 dc {2*vmid} {'ac 1' if ac_vm else ''}
Rtm v33m dvm 100k
Rbm dvm 0 100k
Cdvm dvm 0 1u
Xbm dvm fbm vpvm 0 bom OPA365
Rfbm vm fbm 1k
Cfbm bom fbm 1.6n
Risom bom vm 1.0
Cd1m vm c1m 10u
Resr1m c1m 0 0.005
Cd2m vm c2m 100n
Resr2m c2m 0 0.03
"""
    else:
        vm_txt = f"""* Vmid: ideal source {vmid} V, output impedance {p['Rvo']} ohm, decoupled 10 uF + 100 nF (ESR 20 mohm)
Vm vm0 0 dc {vmid} {'ac 1' if ac_vm else ''}
Rvo vm0 vm {p['Rvo']}
Cvm1 vm cv1 {p['Cvm1']}
Rcv1 cv1 0 {p['esr']}
Cvm2 vm cv2 {p['Cvm2']}
Rcv2 cv2 0 {p['esr']}
"""
    return supply + f"""* 100 nF + 1 uF decoupling (ESR 20 mohm) at the op-amp supply pin
Cdc1 vccl cd1 100n
Rdc1 cd1 0 {p['esr']}
Cdc2 vccl cd2 1u
Rdc2 cd2 0 {p['esr']}
{vm_txt}* V3: the Due's 3.3 V pin (= AREF) sensed for centring, through 100 ohm + 10 uF (+100 nF) so its noise does not reach N
V3s v30 0 dc {v3} {'ac 1' if ac_v3 else ''}
Rv3 v30 v3 100
Cv3a v3 0 10u
Cv3b v3 0 100n
"""

def header(p, title):
    o = OPAMPS[p["op"]]
    return f"* {title}\n.include {o['lib']}\n.include ../models/rangesw.lib\n.options abstol=1e-13 itl1=4000 itl4=500 reltol=1e-4 method=gear\n"

def write_net(name, text):
    os.makedirs(NETD, exist_ok=True)
    path = os.path.join(NETD, name + ".cir")
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
    return f"../work/{name}_{key}.dat"

def load(name, key, cols=None):
    fn = os.path.join(WORK, f"{name}_{key}.dat")
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
            if re.match(r"(R1|R2|R3|C1|C2|Cw)\S* ", l):
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
