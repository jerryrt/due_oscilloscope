#!/usr/bin/env python3
"""AFE plan step 2c: AWG output simulation.  Regenerates every number in report.md.

    python3 -I run.py [--jobs=4] [CASE ...]   # the design (approved 2026-11-11): buffered DAC0, the AWG's own fast Vmid;
                                              # writes raw/results.json, netlists to netlists/<case>/ when --jobs > 1
    python3 -I run.py --variant=legacy        # revision 7 of the unbuffered design (13.7k / 15.8k, Ca/Cb), kept reproducible:
                                              # writes raw_legacy/results.json and netlists_legacy/
    python3 -I run.py vmid                    # the AWG-Vmid option sweep (about 7 min, four processes)

numpy only.  ngspice 47 is run in batch mode; netlists are written to netlists/.
The vendor op-amp models are referenced by relative path from ../../models and are
never copied (TI terms, models/SOURCES.md).
"""
import json, os, re, subprocess, sys, hashlib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
# ---------------------------------------------------------------- variant selection
# The design (owner, 2026-11-11) is the buffered AWG: an OPA365 follower on DAC0 feeding a low-impedance attenuator, with the
# AWG's own fast Vmid (sim/loop step `buf`, which passes SM-5).  'legacy' is the unbuffered revision 7 design, kept
# reproducible.  Everything the buffered design changes is behind BUFV.  '--variant=buf' is accepted as the design's old name.
VARIANT, JOBS = 'design', 1
for _a in list(sys.argv[1:]):
    if _a.startswith('--variant='):
        VARIANT = _a.split('=', 1)[1]; sys.argv.remove(_a)
    elif _a.startswith('--jobs='):
        JOBS = max(1, min(4, int(_a.split('=', 1)[1]))); sys.argv.remove(_a)
if VARIANT == 'buf':
    VARIANT = 'design'
if VARIANT not in ('design', 'legacy', 'lowcost'):
    raise SystemExit(f'unknown variant {VARIANT}')
BUFV = VARIANT == 'design'
# 'lowcost' (what-if, 2026-11-11, the owner's $35 target): the unbuffered n1 attenuator driven by DAC0 directly, with the AWG's
# own fast Vmid, the 22 || 22 filters and BAT54S kept; the precision ADC (an ADS1220 input) reads the BNC through 10k.  It runs
# the legacy code paths (BUFV False) with these parts.
LOWV = VARIANT == 'lowcost'
NETDIR = os.path.join(HERE, {'design': 'netlists', 'legacy': 'netlists_legacy', 'lowcost': 'netlists_lowcost'}[VARIANT])
RAWDIR = os.path.join(HERE, {'design': 'raw', 'legacy': 'raw_legacy', 'lowcost': 'raw_lowcost'}[VARIANT])
MODELS = {
    'OPA365': '../../models/opa365/OPA365_PSPICE.lib',
    'OPA354': '../../models/opa354/OPA354_PSPICE.lib',
    'OPA356': '../../models/opa356/OPA356_PSPICE.LIB',
}
KT4 = 4 * 1.380649e-23 * 300.15
# The rails' 10 uF parts are Samsung CL21A106KAYNNNE (C15850), two per LM27762 output (sim/powercal, approved 2026-11-11).
# Samsung's characterisation is read as sim/powercal reads it, from the product page's embedded datasheetData JSON in
# ../../models/cl21a106kaynnne/ (vendor file, git-ignored, hash-pinned in models/manifest.json), parsed as data, never executed.
SAM_FILE = os.path.join(HERE, '../../models/cl21a106kaynnne/CL21A106KAYNNN_product_page.html')
SAM_SHA = '4b7cf7d8e24b0af8cb7f0d2118a8077c6b512ade8c0662c6b0ab1a4bb4f27c24'


def samsung_c15850():
    raw = open(SAM_FILE, 'rb').read()
    assert hashlib.sha256(raw).hexdigest() == SAM_SHA, 'Samsung C15850 file does not match manifest.json'
    t = raw.decode('utf-8', 'replace'); i = t.index('var datasheetData = ') + len('var datasheetData = '); dpt = 0
    for j in range(i, len(t)):
        if t[j] == '[': dpt += 1
        elif t[j] == ']':
            dpt -= 1
            if dpt == 0: break
    data = json.loads(t[i:j + 1])
    z = [b_ for b_ in data if b_['graphType'] == '|Z|_R'][0]['selectPartsList'][0]['chartList']
    arr = lambda ch: (np.array([float(q['x']) for q in ch['data']]) * 1e6, np.array([float(q['y']) for q in ch['data']]))
    fz, Z = arr([c for c in z if c['graphSubType'] == '|Z|'][0]); fr, Rr = arr([c for c in z if c['graphSubType'] == 'R'][0])
    dc = [b_ for b_ in data if b_['graphType'] == 'DCBias'][0]['selectPartsList'][0]['chartList'][0]['data']
    xv = np.array([float(q['x']) for q in dc]); yv = np.array([float(q['y']) for q in dc]); o = np.argsort(xv)
    m = (fz >= 3e6) & (fz <= 10e6); w = 2 * np.pi * fz[m]; X = np.sqrt(np.maximum(Z[m] ** 2 - np.interp(fz[m], fr, Rr) ** 2, 0))
    esl = float(np.median((X + 1 / (w * 10e-6)) / w))
    return dict(esr=lambda f_: float(np.interp(f_, fr, Rr)), k=lambda v: 1 + float(np.interp(abs(v), xv[o], yv[o])) / 100, esl=esl)


SAM = samsung_c15850()
C10_TOL = 0.9                                               # -10 % (K) on top of the DC-bias derating
K10_33, K10_N = SAM['k'](3.3) * C10_TOL, SAM['k'](2.07) * C10_TOL
ESR10_2M = SAM['esr'](2e6)
ESR10_HI = max(SAM['esr'](x) for x in np.linspace(3e6, 10.5e6, 40))
ESL10 = SAM['esl']
N_RAIL10 = 2

# ---------------------------------------------------------------- the design
# Negative rail (AW-1 into 50 ohm, revision 6): LM27762 OUT- = -1.22 V x (R3 + R4)/R4 (SNVSAF7C Sec 7.2.2.3, Eq. 3;
# VFB- -1.238..-1.202 V over temperature, Sec 5.5; R4 >= 50 kohm; adjustable -1.5..-5 V).
# R3 = 768k || 330k, R4 = 330k: BOM types only (the scope's R1/R3 and R2 types, 0.1 %).  -2.073 V (owner, 2026-11-11):
# the bare rails at the datasheet tolerance maxima stay under the OPA365's 5.5 V (-2.156 V, 330k||100k / 100k, gave 5.532 V).
# -1.8 V (47.5k / 100k) left the op-amp's -V pin near -1.14 V at 19 mA (BAT54 + 10 ohm) and failed AW-1 into 50 ohm.
R3_N, R4_N = 768e3 * 330e3 / (768e3 + 330e3), 330e3
if BUFV or LOWV:   # the rail as the variant states it: R3 = (330k + 330k + 100k) || 330k, R4 = 330k (no 768k type): -2.0706 V
    # the approved divider (sim/powercal, 2026-11-11): R3 = 330k || 100k, R4 = 330k / 3 (3 x 330k in parallel): -2.0712 V,
    # 45 kohm at FB- (it was (330k + 330k + 100k) || 330k / 330k, -2.0706 V at 136 kohm)
    R3_N, R4_N = 1 / (1 / 330e3 + 1 / 100e3), 330e3 / 3
VN = -1.22 * (R3_N + R4_N) / R4_N                  # -2.073 V (legacy), -2.0712 V (design)
# + rail divider (sim/powercal: 174k / 100k, VFB+ 1.182..1.218 V, Sec 5.5)
R1_P, R2_P = 174e3, 100e3
RTOL_FB = 0.001                                    # feedback resistors 0.1 %


def ds_rails(r3=None, r4=None, rt=RTOL_FB):
    """LM27762 rails at the datasheet's feedback-reference limits (Sec 5.5) with the divider resistors at their tolerance:
    ((vp_min, vn_weak), (vp_max, vn_strong)), vn negative.  Load and line regulation (34 uV/mA, 1.5 mV/V typ, Sec 5.5) are
    not added: the behavioural supply carries 0.2 ohm per rail, which is more than 34 uV/mA."""
    r3 = R3_N if r3 is None else r3; r4 = R4_N if r4 is None else r4
    lo = lambda vfb, a, b: vfb * (1 + a * (1 - rt) / (b * (1 + rt)))
    hi = lambda vfb, a, b: vfb * (1 + a * (1 + rt) / (b * (1 - rt)))
    return (lo(1.182, R1_P, R2_P), -lo(1.202, r3, r4)), (hi(1.218, R1_P, R2_P), -hi(1.238, r3, r4))


R_DS_WEAK, R_DS_STRONG = ds_rails()                # (+3.235, -2.041), (+3.342, -2.106)
BARE_MAX = R_DS_STRONG[0] - R_DS_STRONG[1]         # 5.447 V
# rail corners used by every other DC/abs-max check: + rail +3.23..3.37 V; - rail +/-5 % of nominal (wider than the datasheet)
RAILS = ((3.3, VN), (3.23, 0.95 * VN), (3.37, 1.05 * VN))
R_WEAK, R_STRONG = RAILS[1], RAILS[2]
# AW-1 into 50 ohm (owner, 2026-11-11): the weak corner is the datasheet's, not the blanket 5 %.  The strong corner stays blanket
# (wider; the swing has more room there).  'blanket5' restores the old basis (the break-on-purpose arm; it must fail).
AW1_50_BASIS = 'datasheet'
RAILS_AW1_50 = {'datasheet': ((3.3, VN), R_DS_WEAK, R_STRONG), 'blanket5': RAILS}
# Stocked 0.1 % parts only (MC-12, fewest types; docs/jlcpcb-parts.md), C0G capacitors.
# Zero output at Vdac = Vmid needs Rf/Rg = Rb/Ra + Rb/Rx, and then the slope is Rb/Ra.
# Rf is two parts in series, 249 + 49.9 (the 49.9 is the AW-4 output resistor's type), so that
# no AWG-only feedback value is needed: Rf/Rg = 298.9/249 = 1.2004 against 1.2003 required.
# Rx 330k (the scope's R2 type) returns V+ to Vmid; a floating DAC0 then leaves the output at
# about -1.85 V (AW-8 limit 2.1 V).  Ra is sized for AW-5: the DAC sources (Vdac - V+)/Ra.
D = dict(
    opamp='OPA365',
    Ra=13.7e3, Rb=15.8e3, Rx=330e3, Rf=249.0 + 49.9, Rg=249.0, Rs=49.9,
    Ca=0.0,            # across Ra: compensates the attenuator for the capacitance at V+
    Cb=0.0,            # extra capacitor V+ to ground
    Cpar_p=1.5e-12,    # PCB at V+ (assumed)
    Cpar_n=2.0e-12,    # AN-1: 2 pF extra at the inverting node
    Cf=0.0,            # across Rf
    rout=0.0,          # DAC output impedance (datasheet gives none)
    vdac=1.65, vmid=1.65, vp=3.3, vn=VN, rp=0.2, rn=0.2, rsink=1e9, rbl=4.7e3,
    rflt=0.0, cbulk=10e-6, cpin=100e-9, ripple=0.0,
    load='hiz',        # hiz | open | r50 | cable_open | cable_r50 | cable_scope | short | none
    vos=0.0, rvm=1.0, cvm=10e-6,
    loop=False, Cin_n=5.4e-12,
    sw=False,          # reset-safe gate (analog switch) between DAC0 and Ra
    swv=3.3,           # its control voltage: 0 = open (reset), 3.3 = closed
    sw_pwl='',         # optional PWL for the control
    esd_only=False,    # unpowered op-amp = its ESD diodes only (powercal's G6 treatment)
    R2=0.0,            # second series element between the clamp node M and the BNC
    clamp='none',      # none | gnd3 | rails | tvs33 | tvs50
    iso=False,         # series Schottky in each op-amp supply pin (powercal's isolation)
    esr_bulk=None,     # the rail 10 uF parts: None = Samsung's C15850 data (ESR at 2 MHz, ESL, DC bias, -10 %), N_RAIL10 per rail;
                       # a number = that ESR on one nominal 10 uF with no ESL (the earlier assumptions, for comparison)
    dsch='DBAT54S_TYP', dleak=True,   # the Schottky is BAT54S C7420333 for every variant (2026-11-11), fitted model; the AW-1
                                      # swing rows take DBAT54S_MAX (headroom); 'DBAT54' is the old recalled model
)
# The buffered variant (sim/loop step `buf`): DAC0 -> 680 ohm -> OPA365 follower (+IN; 330k from +IN to Vmid, so a
# floating DAC0 commands 0 V) on +3.3 V_A through its own BAT54 and 100 nF, V- at ground -> Ra 953 -> V+, Rb = 953 +
# (249 || 249) + 22 to ground, no Rx; Rf = Rb's value with Cf 12 pF across it, Rg 953.  Slope Rb/Ra = 1.1537, zero at
# Vmid by construction (Rf/Rg = Rb/Ra), and x 330k / 330.68k for the input divider.
RB_BUF = 953.0 + 1 / (1 / 249.0 + 1 / 249.0) + 22.0          # 1099.5 ohm
CBO_NOM = 10e-12        # buffer output node: PCB trace, 5-10 pF assumed *(check)*; the PM rows sweep the loads (case_buf)
if BUFV:
    D.update(Ra=953.0, Rb=RB_BUF, Rx=0.0, Rf=RB_BUF, Rg=953.0, Cf=12e-12,
             buf=True, Rbin=680.0, Rbpl=330e3, Cbo=CBO_NOM, cbuf=100e-9, biso=True, bq=0.0,
             bmode='closed', Crep=0.0, bsup='sp', Rsh=0.0,
             bpl_to='0',   # Rbpl to ground, not Vmid (2026-11-11): unpowered, a dead Vmid buffer pulled through Rg would drag the
                           # undriven DAC0 pin to -0.49 V through 330k (PR-2); cost: an undriven DAC0 commands -1.15 x Vmid
             vm_div=(330e3, 330e3, 12e-12), cvm=0.0, cvm2=False,   # the AWG's own Vmid (2026-11-11, case_vmid; owned by powercal):
                                                                  # 330k / 330k from +3.3 V_A, 12 pF at the tap, OPA365 follower, no output capacitor
             Rinj=0.0,      # the PA-3 injection branch and its 249 ohm isolation are removed (2026-11-11, BNC-tee calibration)
             sense_ref='vm')   # the sense divider's far end: 'vm' (the AWG Vmid) or '3.0' (the 3.0 V reference); powercal switches it

if LOWV:   # n1: Ra = (4.7k || 4.7k) + 3 x 4.7k = 16.45k, Rb = 4 x 4.7k = 18.8k (4.7k C23162, 1 %), Rx 330k, Rf 249 + 49.9, Rg 249
    D.update(Ra=4.7e3 / 2 + 3 * 4.7e3, Rb=4 * 4.7e3, Rx=330e3, Rf=249.0 + 49.9, Rg=249.0, n1=True,
             vm_div=(330e3, 330e3, 12e-12), cvm=0.0, cvm2=False,   # the AWG's own fast Vmid, as the design
             adc_in=True)   # the precision ADC at the BNC: 10k into a high-impedance input clamped to +3.3 V_A / the - rail


def build(p, analysis, ac=(), extra='', start=''):
    """Netlist text.  ac: names of sources given AC 1 (dac, vcc, vee, vmid, vos)."""
    q = dict(D); q.update(p)
    A = lambda n: 1 if n in ac else 0
    L = [f"* AFE AWG output, generated by run.py ({q['opamp']})",
         f".include {MODELS[q['opamp']]}", ".include models/awg_behavioural.lib"]
    if (q.get('buf') or q.get('vm_div')) and q['opamp'] != 'OPA365':   # the DAC0 and Vmid buffers stay OPA365 when the AWG op-amp is swapped
        L.append(f".include {MODELS['OPA365']}")
    dsch = q.get('dsch', 'DBAT54')                   # the supply-pin Schottky: the fitted BAT54S (D) or the old recalled DBAT54
    if dsch != 'DBAT54':
        L.append(f".include {BAT54S_LIB}")
    # 12.5 Mohm across each supply Schottky when dleak: the datasheet's 2 uA maximum reverse current at 25 V
    lk = lambda n, a, b: f"\nRlk{n} {a} {b} 12.5Meg" if q.get('dleak') else ''
    if q.get('dac_pwl'):
        L.append(f"Vdp dsrc 0 DC {q['vdac']} PWL({q['dac_pwl']})\nRdo dsrc dac {max(q['rout'], 1e-3)}")
    else:
        L.append(f"Xdac dac 0 DAC0_SRC params: v={q['vdac']} rout={q['rout']} acmag={A('dac')}")
    ra_in = 'dac'
    if q['sw']:
        ra_in = 'dacs'
        ctl = f"DC {q['swv']}" + (f" PWL({q['sw_pwl']})" if q['sw_pwl'] else '')
        L.append(f"Ssw dac dacs swc 0 SWM\nVswc swc 0 {ctl}\nCsw1 dac 0 10p\nCsw2 dacs 0 10p")
    if q.get('buf'):
        # DAC0 -> Rbin -> +IN (bin), Rbpl bin -> Vmid.  Supply: +3.3 V_A (the LM27762 + output 'sp', or 'vcc' after the AWG
        # op-amp's filter) -> BAT54 -> bvcx with 100 nF; V- at ground.  bmode: 'closed' (follower), 'break' (loop broken at -IN
        # by 1 GH / 1000 F, AC 1 into -IN, Crep replicating -IN's load on the output), 'mid' (sim/loop's Middlebrook voltage
        # injection between the output pin and the load), 'esd' (unpowered: the ESD diodes only, as the main op-amp's).
        L.append(f"Rbin {ra_in} bin {q['Rbin']}\nRbpl bin {q.get('bpl_to', 'vm')} {q['Rbpl']}")
        if q.get('Cbin'): L.append(f"Cbin bin 0 {q['Cbin']}")     # extra capacitance at the buffer input (pad, trace)
        bs = q.get('bsup', 'sp')
        L.append(f"Dbs {bs} bvc {dsch}{lk('bs', bs, 'bvc')}\nVisb bvc bvcx 0" if q.get('biso', True) else f"Visb {bs} bvcx 0")
        L.append(f"Cbd bvcx bcd {q['cbuf']}\nRbcd bcd 0 0.05")
        bm = 'esd' if q['esd_only'] else q.get('bmode', 'closed')
        if bm == 'esd':
            L.append(".model DESDB D(IS=1e-14 N=1.05 RS=5)\nDbi1 bin bvcx DESDB\nDbi2 0 bin DESDB\nDbo1 bo bvcx DESDB\nDbo2 0 bo DESDB")
            if q.get('bq'):     # bound: the dead buffer drawing current across its supply pins (phantom powering), as a resistor
                L.append(f"Rbq bvcx 0 {q['bq']}")
        elif bm == 'break':
            L.append(f"X2 bin bfb bvcx 0 bo OPA365\nLbk bo bfb 1G\nCbk vsb bfb 1000\nVsb vsb 0 DC 0 AC 1")
            if q.get('Crep'): L.append(f"Crep bo 0 {q['Crep']}")
        elif bm == 'mid':
            L.append("X2 bin bo bvcx 0 boo OPA365\nVinjb bo boo DC 0 AC 1")
        else:
            L.append("X2 bin bo bvcx 0 bo OPA365")
        L.append(f"Cbo bo 0 {q['Cbo']}")            # the trace at the buffer pin
        if q.get('Cfar'):   # what-if: the injection branch's capacitance behind its own series resistor (info rows only)
            L.append(f"Riso bo bi {q['Riso']}\nCfar bi 0 {q['Cfar']}")
        ra_in = 'bo'
        if q.get('Rsh'):    # isolation resistor feeding both the attenuator and the injection branch
            L.append(f"Rsh bo bs {q['Rsh']}"); ra_in = 'bs'
        if q.get('inj') is not None:
            # PA-3 injection branch: [Rinj] -> node bi (10 pF trace, each switch's source side 10 pF) -> TMUX1119 (Ron, 10 pF
            # on its drain side when on) -> node N, modelled as 4.5 kohm to Vmid + 2 pF (the 20-30 kohm uncompensated divider).
            # inj = number of switches on (0, 1, 2); two switches in all.  Switch capacitances are assumptions *(check, G7)*.
            src = ra_in
            if q.get('Rinj'):
                L.append(f"Rinj {src} bi {q['Rinj']}"); src = 'bi'
            L.append(f"Cbi {src} 0 {10e-12 + 2 * 10e-12}")
            for k in range(int(q['inj'])):
                L.append(f"Ron{k} {src} n{k} {q.get('ron', 3.7)}\nCnd{k} n{k} 0 {10e-12 + 2e-12}\nRnth{k} n{k} vm {q.get('rnth', 4.5e3)}")
    L.append(f"Ra {ra_in} vp0 {q['Ra']}")
    if q['Ca']: L.append(f"Ca {ra_in} vp0 {q['Ca']}")
    L.append(f"Rb vp0 0 {q['Rb']}")
    if q['Rx']: L.append(f"Rx vp0 vm {q['Rx']}")
    L.append(f"Cpp vp0 0 {q['Cpar_p'] + q['Cb']}")
    L.append(f"Vos vp0 vp DC {q['vos']} AC {A('vos')}")
    fb = 'vo' if q['loop'] else 'out'
    L.append(f"Rf {fb} inv {q['Rf']}")
    if q['Cf']: L.append(f"Cf {fb} inv {q['Cf']}")
    if q['loop']:
        L.append("Vo vsrc 0 DC 0 AC 1\nCdc vsrc vo 1000\nLdc out vo 1G")
        L.append(f"Rfd out dd {q['Rf']}")
        if q['Cf']: L.append(f"Cfd out dd {q['Cf']}")
        L.append(f"Rgd dd vm {q['Rg']}")
        L.append(f"Cdd dd 0 {q['Cpar_n'] + q['Cin_n']}")
    L.append(f"Rg inv vm {q['Rg']}")
    L.append(f"Cpn inv 0 {q['Cpar_n']}")
    if q.get('vm_div'):
        # the AWG's own Vmid (2026-11-11, proposed for sim/powercal): a divider Rt / Rb from +3.3 V_A ('sp') with Ctap at its
        # tap, buffered by an OPA365 on +3.3 V_A modelled as a current-limited follower: +/-65 mA (ISC typ, SBOS365G), output no
        # higher than its own supply, 'rvm' as its output resistance in the linear region; AC 'vmid' in series for the buffer's
        # noise allowance.  The output network (cvm + 100 nF) follows.
        rt, rb, ct = q['vm_div']
        L.append(f"Rvt sp vmt {rt}\nRvb vmt 0 {rb}\nCvt vmt 0 {ct}")
        # the OPA365 macromodel as a follower on +3.3 V_A behind its own Schottky die and 100 nF, as the DAC0 buffer
        dv = dsch if dsch != 'DBAT54' else 'DBAT54S_TYP'
        if dsch == 'DBAT54': L.append(f".include {BAT54S_LIB}")
        L.append(f"Dvs sp vsx {dv}{lk('vs', 'sp', 'vsx')}\nCvsd vsx vsd 100n\nRvsd vsd 0 0.05\nVvmac vma vms DC 0 AC {A('vmid')}")
        if q.get('vm_beh') and not q['esd_only']:
            # behavioural follower for the Vmid op-amp's requirements: A0 1e5, one pole at GBW / A0, open-loop output resistance
            # ro, output inside its supply (vsx) and ground, current limit ilim
            gbw, ro, ilim = q['vm_beh']
            L.append(f"Gvb 0 vbn vmt vms 0.1\nRvb1 vbn 0 1Meg\nCvb1 vbn 0 {1e5/(2*np.pi*1e6*gbw):.6g}\n"
                     f"Bvbo vbo 0 V=max(min(v(vbn),v(vsx)),0)\nRvbo vbo vbo2 {ro}\n"
                     f"Bvbl vbo2 vma I=max(min((v(vbo2)-v(vma))/0.01,{ilim}),-{ilim})")
        elif q['esd_only']:     # unpowered: the Vmid buffer as its ESD diodes too
            L.append(".model DESDV D(IS=1e-14 N=1.05 RS=5)\nDv1 vmt vsx DESDV\nDv2 0 vmt DESDV\nDv3 vma vsx DESDV\nDv4 0 vma DESDV")
        else:
            L.append("X3 vmt vms vsx 0 vma OPA365")
    elif q.get('vm_tau'):      # Vmid charging from 0 with a time constant (sim/powercal PW-7: 2 x 330k, 10 uF at the tap, tau 1.65 s)
        L.append(f"Bvm vma 0 V={q['vmid']}*(1-exp(-time/{q['vm_tau']}))\nRvmo vma vms {q['rvm']}")
    elif q.get('vm_ramp'):     # Vmid rising with a supply ramp (td, tr), behind the same output resistance
        td_, tr_ = q['vm_ramp']
        L.append(f"Bvm vma 0 V={q['vmid']}*min(max((time-{td_})/{tr_},0),1)\nRvmo vma vms {q['rvm']}")
    else:
        L.append(f"Xvm vms 0 VMID_BUF params: v={q['vmid']} rout={q['rvm']} acmag={A('vmid')}")
    L.append(f"Rvmx vms vm 1m" + ("\nCvm2 vm vmd 100n\nRe2 vmd 0 0.05" if q.get('cvm2', True) else '')
             + (f"\nCvm1 vm vmc {q['cvm']}\nRe1 vmc 0 0.02" if q['cvm'] else ''))
    if q.get('ramp'):
        rp_ = q['ramp']
        L.append(f"Xsup sp sn 0 LM27762_RAMP params: vp={q['vp']} vn={q['vn']} rp={q['rp']} rn={q['rn']} "
                 f"rsink={q['rsink']} rbl={q['rbl']} tdp={rp_[0]} tdn={rp_[1]} tr={rp_[2]} ripple={q['ripple']}")
    else:
        L.append(f"Xsup sp sn 0 LM27762_BEH params: vp={q['vp']} vn={q['vn']} rp={q['rp']} rn={q['rn']} "
                 f"rsink={q['rsink']} rbl={q['rbl']} acp={A('vcc')} acn={A('vee')} ripple={q['ripple']}")
    if q['esr_bulk'] is None:     # N_RAIL10 x C15850 per rail, Samsung's ESR (2 MHz unless esr_hi), ESL and DC-bias derating
        eb = ESR10_HI if q.get('esr_hi') else ESR10_2M
        # the ESL (0.37 nH) matters only for the MHz lines: it is carried in the small-signal analyses; in a transient it stalls
        # ngspice's first step against the op-amp macromodel and is left out (it moves nothing a transient row reads)
        ac_ = analysis.lstrip().lower().startswith(('.ac', '.noise'))
        for i_ in range(N_RAIL10):
            if ac_:
                L.append(f"Cb1{i_} sp cb1{i_} {q['cbulk']*K10_33}\nRcb1{i_} cb1{i_} cl1{i_} {eb}\nLcb1{i_} cl1{i_} 0 {ESL10}\n"
                         f"Cb2{i_} sn cb2{i_} {q['cbulk']*K10_N}\nRcb2{i_} cb2{i_} cl2{i_} {eb}\nLcb2{i_} cl2{i_} 0 {ESL10}")
            else:
                L.append(f"Cb1{i_} sp cb1{i_} {q['cbulk']*K10_33}\nRcb1{i_} cb1{i_} 0 {eb}\n"
                         f"Cb2{i_} sn cb2{i_} {q['cbulk']*K10_N}\nRcb2{i_} cb2{i_} 0 {eb}")
    else:
        eb = q['esr_bulk']
        L.append(f"Cb1 sp cb1 {q['cbulk']}\nRcb1 cb1 0 {eb}\nCb2 sn cb2 {q['cbulk']}\nRcb2 cb2 0 {eb}")
    rf = max(q['rflt'], 1e-3)
    L.append(f"Rfp sp vcc {rf}\nRfn sn vee {rf}")
    L.append(f"Cp1 vcc cp1 {q['cpin']}\nRcp1 cp1 0 0.05\nCp2 vee cp2 {q['cpin']}\nRcp2 cp2 0 0.05")
    if q['iso']:
        L.append(f"Dsp vcc vcc2 {dsch}{lk('sp', 'vcc', 'vcc2')}\nVisp vcc2 vccx 0\nDsn veex vee3 {dsch}{lk('sn', 'veex', 'vee3')}\nVisn vee3 vee 0")
    else:
        L.append("Visp vcc vccx 0\nVisn vee veex 0")     # zero-volt sense sources: supply currents
    pins = 'out veex vp inv vccx' if q['opamp'] == 'OPA356' else 'vp inv vccx veex out'   # OPA356: OUT -V +IN -IN +V
    if q['esd_only']:
        L.append(".model DESD D(IS=1e-14 N=1.05 RS=5)\nDeo1 out vccx DESD\nDeo2 veex out DESD\nDei1 vp vccx DESD\nDei2 veex vp DESD\nDen1 inv vccx DESD\nDen2 veex inv DESD")
    else:
        L.append(f"X1 {pins} {q['opamp']}")
    if q['R2']:
        L.append(f"Rs out m {q['Rs']}\nRs2 m bnc {max(q['R2'], 1e-3)}")
        cn = 'm'
    else:
        L.append(f"Rs out bnc {q['Rs']}")
        cn = q.get('cat', 'bnc')            # clamp node for a single series resistor: 'bnc' (load side) or 'out' (op-amp side)
    cl = q['clamp']
    if cl in ('gnd2', 'gnd3'):
        # two stacks to ground, one per polarity; 0 V sense sources Vca/Vcb read the clamp current (node to ground = i(Vca) + i(Vcb))
        n = 2 if cl == 'gnd2' else 3
        na = [cn] + [f'ga{i}' for i in range(1, n)] + ['gas']
        L += [f"Dga{i} {na[i-1]} {na[i]} DBAV99" for i in range(1, n + 1)] + [f"Vca gas 0 0"]
        nb = ['gbs'] + [f'gb{i}' for i in range(1, n)] + [cn]
        L += [f"Dgb{i} {nb[i-1]} {nb[i]} DBAV99" for i in range(1, n + 1)] + [f"Vcb gbs 0 0"]
        # stack b conducts ground -> node: ground, Vcb, diodes, node
    elif cl == 'rails':
        L.append(f"Dcp {cn} vcc {dsch}\nDcn vee {cn} {dsch}")
    elif cl == 'tvs33':
        L.append(f"Dt1 {cn} tm DTVS33\nDt2 0 tm DTVS33")
    elif cl == 'tvs50':
        L.append(f"Dt1 {cn} tm DTVS50\nDt2 0 tm DTVS50")
    if q.get('adc_in'):
        # ADS1220 input through 10k at the BNC (another agent's variant, modelled as asked): 1 Gohm input, clamped by a BAT54S die
        # to +3.3 V_A ('sp') and to the - rail ('sn')
        L.append(f"Radc bnc adin 10k\nRadc2 adin 0 1G\nDadp adin sp {dsch if dsch != 'DBAT54' else 'DBAT54S_TYP'}\n"
                 f"Dadn sn adin {dsch if dsch != 'DBAT54' else 'DBAT54S_TYP'}")
    if q.get('sense'):
        # the ADS124S08's sense divider (sim/powercal owns it): BNC -> 100k -> tap -> 100k -> Vmid or 3.0 V, 0.1 %; the ADC input
        # as 1 nA/V (1 Gohm) to ground.  Unpowered, the 3.0 V reference is 0 V.
        sr = q.get('sense_ref', 'vm')
        rt_, rb_ = q.get('sense_r', (200e3, 100e3))     # (BNC to tap, tap to far end): 100k + 100k, then 100k; k = 1/3 (approved 2026-11-11)
        far = 'vm' if sr == 'vm' else 'sref'
        L.append(f"Rse1 bnc stp {rt_}\nRse2 stp {far} {rb_}\nRse3 stp 0 1G")
        if sr != 'vm':
            L.append(f"Vsref sref 0 DC {0.0 if q['esd_only'] else float(sr)}")
    ld = q['load']
    L.append({'hiz': "Rl bnc 0 1Meg\nCl bnc 0 15p", 'open': "Rl bnc 0 1G", 'r50': "Rl bnc 0 50",
              'short': "Rl bnc 0 1u",
              'cable_open': "T1 bnc 0 far 0 Z0=50 TD=5n\nRl far 0 1G",
              'cable_r50': "T1 bnc 0 far 0 Z0=50 TD=5n\nRl far 0 50",
              'cable_scope': "T1 bnc 0 far 0 Z0=50 TD=5n\nRl far 0 1Meg\nCl far 0 15p",
              'none': ""}[ld])
    L += [extra, analysis]
    return '\n'.join(L)


def parse_raw(path):
    txt = open(path).read().split('\n')
    i = 0; nv = npnt = 0; names = []; cplx = False
    while i < len(txt):
        l = txt[i]
        if l.startswith('Flags:'): cplx = 'complex' in l
        if l.startswith('No. Variables:'): nv = int(l.split()[-1])
        if l.startswith('No. Points:'): npnt = int(l.split()[-1])
        if l.startswith('Variables:'):
            for k in range(nv): names.append(txt[i + 1 + k].split()[1])
            i += nv
        if l.startswith('Values:'): i += 1; break
        i += 1
    data = np.zeros((nv, npnt), dtype=complex if cplx else float)
    p = 0; k = 0
    for l in txt[i:]:
        s = l.split()
        if not s: continue
        if not l.startswith('\t'):
            p = int(s[0]); s = s[1:]; k = 0
        for tok in s:
            data[k, p] = complex(*map(float, tok.split(','))) if cplx else float(tok)
            k += 1
    return {n.lower(): data[j] for j, n in enumerate(names)}


def ng(name, text, vecs='all', plot=None, keep=False):
    """Run a netlist whose analysis cards are in `text`; return {vector: array}."""
    os.makedirs(NETDIR, exist_ok=True)
    os.makedirs(RAWDIR, exist_ok=True)
    cir = f'{NETDIR}/{name}.cir'
    raw = f'{RAWDIR}/{name}.raw'
    body = text.replace('.end\n', '')
    ctl = ['.control', 'set filetype=ascii', 'set noaskquit', 'run']
    if plot: ctl.append(f'setplot {plot}')
    ctl.append(f'write {raw} {vecs}')
    ctl.append('.endc')
    open(cir, 'w').write(body + '\n' + '\n'.join(ctl) + '\n.end\n')
    r = subprocess.run(['ngspice', '-b', cir], capture_output=True, text=True, cwd=HERE)
    log = r.stdout + r.stderr
    if not os.path.exists(raw):
        raise RuntimeError(f'{name}: ngspice produced no raw file\n{log[-2000:]}')
    out = parse_raw(raw)
    out['_nl'] = cir
    if not keep: os.remove(raw)
    out['_log'] = log
    return out


# ---------------------------------------------------------------- helpers
def integ(f, d2, lo=10.0, hi=100e6):
    """Integral of a power density d2 (V^2/Hz) over [lo, hi], log-log trapezoid on
    the simulation grid (the grid is dense: 40 points per decade)."""
    m = (f >= lo) & (f <= hi)
    return float(np.trapezoid(d2[m], f[m]))


def noise_split(p, hi=100e6, lo=10.0, extra_groups=None, tag='nz'):
    """AW-6 noise of the stage with a quiet DC source, density and integrated rms,
    split by contributor.  Output node is the BNC, into 1 Mohm || 15 pF (the load the
    spec measures into)."""
    q = dict(p); q.setdefault('load', 'hiz')
    t = build(q, f".noise v(bnc) Vos dec 40 10 1G 1\n", ac=('vos',))
    r = ng(tag, t, plot='noise1')
    f = r['frequency'].real
    tot2 = r['onoise_spectrum'].real ** 2
    g = lambda n: r['onoise_' + n].real ** 2
    # the behavioural supply's own bleed resistors and diodes are model artefacts (the real
    # rail noise is added separately from its datasheet density and a transfer function)
    art = sum(g(n) for n in ('r.xsup.rbn', 'r.xsup.rbp', 'r.xsup.rno', 'r.xsup.rpo', 'r.xsup.rsn',
                             'r.xsup.rsp', 'd.xsup.dn', 'd.xsup.dp'))
    tot2 = tot2 - art
    parts = {'Ra': g('ra'), 'Rb': g('rb'), 'Rx': g('rx') if 'onoise_rx' in r else 0 * f, 'Rf': g('rf'), 'Rg': g('rg'),
             'Rs': g('rs') + (g('rs2') if 'onoise_rs2' in r else 0), 'Rout(DAC)': g('r.xdac.ro'), 'Rl': g('rl')}
    parts['supply/Vmid network R'] = sum(g(n) for n in ('rfp', 'rfn', 'rcb1', 'rcb2', 'rcp1', 'rcp2',
                                                        're1', 're2', 'rvmx', 'r.xvm.ro') if 'onoise_' + n in r)
    if 'onoise_rvt' in r:    # the AWG's own Vmid divider
        parts['AWG Vmid divider'] = g('rvt') + g('rvb')
    if 'onoise_rbin' in r:   # buffered variant: its input network (the buffer op-amp's own noise is in 'op-amp (model)')
        parts['Rbin 680 + Rbpl 330k'] = g('rbin') + g('rbpl')
        parts['supply/Vmid network R'] = parts['supply/Vmid network R'] + g('rbcd')
    ext = sum(parts.values())
    parts['op-amp (model)'] = np.maximum(tot2 - ext, 0)
    out = {'f_lo': lo, 'f_hi': hi,
           'total_uV': integ(f, tot2, lo, hi) ** 0.5 * 1e6,
           'density_nV_1MHz': float(np.interp(1e6, f, tot2 ** 0.5)) * 1e9,
           'density_nV_10MHz': float(np.interp(1e7, f, tot2 ** 0.5)) * 1e9,
           'by_part_uV': {k: integ(f, v, lo, hi) ** 0.5 * 1e6 for k, v in parts.items()}}
    out['_f'] = f; out['_tot2'] = tot2
    return out


def ac_resp(p, ac=('dac',), vec='v(bnc)', fmin=1e3, fmax=1e9, tag='ac'):
    t = build(p, f".ac dec 100 {fmin} {fmax}\n", ac=ac)
    r = ng(tag, t, vecs=f'{vec} v(vp) v(out)')
    return r['frequency'].real, r[vec]


def bw_stats(f, h):
    g = np.abs(h); g0 = g[0]
    idx = np.where(g < g0 / np.sqrt(2))[0]
    f3 = float(f[idx[0]]) if len(idx) else float('nan')
    return dict(dc=float(g0), f3db=f3, peak_db=float(20 * np.log10(g.max() / g0)),
                f_peak=float(f[g.argmax()]))


def phase_margin(p, tag='lg'):
    q = dict(p); q['loop'] = True
    t = build(q, ".ac dec 200 1k 2G\n", ac=())
    # Vo carries AC 1 in loop mode; the DAC source is silent
    r = ng(tag, t, vecs='v(out)')
    f = r['frequency'].real; T = -r['v(out)']
    mag = np.abs(T)
    i = np.where((mag[:-1] >= 1) & (mag[1:] < 1))[0]
    if not len(i): return dict(pm=float('nan'), fc=float('nan'), T0=float(mag[0]))
    i = i[0]
    # interpolate the crossing on log f
    a = (np.log(1) - np.log(mag[i])) / (np.log(mag[i + 1]) - np.log(mag[i]))
    fc = np.exp(np.log(f[i]) + a * (np.log(f[i + 1]) - np.log(f[i])))
    ph = np.unwrap(np.angle(T)); phc = ph[i] + a * (ph[i + 1] - ph[i])
    return dict(pm=float(180 + np.degrees(phc)), fc=float(fc), T0=float(mag[0]),
                f=f, T=T)


# ================================================================= cases
FINAL = dict(Ca=20e-12, Cb=12e-12, Cf=0.0, rflt=10.0, Rs=49.9, R2=0.0, clamp='gnd3', cat='out', iso=True)   # the recommended set: Cf = 0, no deliberate band limit (owner decision, SC-5/MC-6); protection: ONE 49.9 ohm 0.1 % resistor (AW-4) and a 3-diode stack each way to ground on the op-amp side (see case_protect)
if BUFV:   # no Ca/Cb, Cf 12 pF, supply filters 22 || 22 = 11 ohm; protection and Schottkys as the default
    FINAL = dict(Ca=0.0, Cb=0.0, Cf=12e-12, rflt=11.0, Rs=49.9, R2=0.0, clamp='gnd3', cat='out', iso=True,
                 inj=None,                         # no PA-3 injection branch (2026-11-11: replaced by a BNC-tee calibration)
                 sense=True)                       # the precision ADC's sense divider on the AWG output (powercal's; modelled here)
    GAIN_NOM = (1 + D['Rf'] / D['Rg']) * D['Rb'] / (D['Ra'] + D.get('Rsh', 0.0) + D['Rb']) * D['Rbpl'] / (D['Rbpl'] + D['Rbin'])   # 1.1513 with Rsh 0
else:
    _S = 1 / D['Ra'] + 1 / D['Rb'] + 1 / D['Rx']
    GAIN_NOM = (1 + D['Rf'] / D['Rg']) / (D['Ra'] * _S)     # DAC pin to output, nominal parts (1.1529)
if LOWV:   # n1 with Ca 20 / Cb 12 pF, no Cf, the design's 22 || 22 filters
    FINAL = dict(Ca=20e-12, Cb=12e-12, Cf=0.0, rflt=11.0, Rs=49.9, R2=0.0, clamp='gnd3', cat='out', iso=True)
PW3_LIM = 30.0 if (BUFV or LOWV) else 26.0     # mA; afe.md PW-3 is 30 mA since 2026-11-11 (the default keeps its recorded 26 mA rows)
BAT54S_LIB = '../../models-open/bat54s-c7420333/bat54s_c7420333.lib'   # fitted to the C7420333 datasheet (own, CC BY-SA)
BUF_IQ_MA = 5.0      # OPA365 quiescent, 5 mA max (SBOS365G Sec 7.6, p7; models/datasheet-facts.md)
ROWS = []      # pass/fail table rows
OUT = {}       # everything, written to raw/results.json


def add(req, case, limit, worst, margin, ok, note=''):
    ROWS.append(dict(req=req, case=case, limit=limit, worst=worst, margin=margin, ok=bool(ok), note=note))


def P(**kw):
    q = dict(FINAL); q.update(kw); return q


def rng_(seed=20261111): return np.random.default_rng(seed)


# --------------------------------------------------------------- DC, AW-1/2/5/7
def dc_mc(aref, scen, n=40000, p=None, seed=1, tol=0.001):
    """Monte Carlo of the DC map.  scen 'A': DAC window theory 1/6..5/6 of AREF, Vmid-to-window
    centring error uniform +/-30 mV.  scen 'B': the measured board window 0.578-2.771 V (scaled
    with AREF from 3.27 V), centre 39.5 mV above AREF/2, residual +/-5 mV.  Parts: 0.1 % (the stocked grade)."""
    q = dict(D); q.update(p or {})
    if q.get('buf'):
        return dc_mc_buf(aref, scen, n, q, seed, tol)
    r = np.random.default_rng(seed)
    t = lambda x: x * (1 + r.uniform(-tol, tol, n))
    Ra, Rb, Rx, Rf, Rg =t(q['Ra']) + q['rout'] + (8.8 if q.get('sw') else 0.0), t(q['Rb']), t(q['Rx']) if q['Rx'] else np.full(n, 1e12), t(q['Rf']), t(q['Rg'])
    if q.get('n1'):   # every 4.7k placement draws its own 1 % (C23162)
        t1 = lambda x: x * (1 + r.uniform(-0.01, 0.01, n))
        k_ = q['Ra'] / (4.7e3 / 2 + 3 * 4.7e3); kb_ = q['Rb'] / (4 * 4.7e3)
        Ra = (1 / (1 / t1(4.7e3) + 1 / t1(4.7e3)) + t1(4.7e3) + t1(4.7e3) + t1(4.7e3)) * k_ + q['rout']
        Rb = (t1(4.7e3) + t1(4.7e3) + t1(4.7e3) + t1(4.7e3)) * kb_
    G = 1 + Rf / Rg
    if scen == 'A':
        lo, hi = aref / 6, 5 * aref / 6
        vmid = aref / 2 + r.uniform(-0.030, 0.030, n)
    else:
        k = aref / 3.27
        lo, hi = 0.578 * k, 2.771 * k
        vmid = aref / 2 + r.uniform(-0.005, 0.005, n)
    if q.get('vm_div'):   # the AWG's own Vmid: +3.3 V_A x its divider, independent of AREF
        rt_, rb_, _ = q['vm_div']; tl = VMDIV_TOL.get(rt_, 0.01)
        a_, b_ = rt_ * (1 + r.uniform(-tl, tl, n)), rb_ * (1 + r.uniform(-tl, tl, n))
        vmid = r.uniform(R_DS_WEAK[0], R_DS_STRONG[0], n) * b_ / (a_ + b_)
    vos = r.uniform(-1, 1, n) * {'OPA365': 0.2e-3, 'OPA354': 8e-3, 'OPA356': 9e-3}[q['opamp']]
    S = 1 / Ra + 1 / Rb + 1 / Rx
    gain = G * (1 / Ra) / S
    vplus = lambda vd: (vd / Ra + vmid / Rx) / S
    out = lambda vd: G * (vplus(vd) + vos) - (G - 1) * vmid
    c = (lo + hi) / 2
    span = hi - lo
    off0 = out(0.0)
    vd_hi, vd_lo = (1.0 - off0) / gain, (-1.0 - off0) / gain
    use = (vd_hi - vd_lo) / span
    edge = np.maximum(vd_hi - lo, hi - vd_lo) * 0 + np.maximum(np.abs(vd_hi - c), np.abs(vd_lo - c)) / (span / 2)
    i_hi = (hi - vplus(hi)) / Ra
    i_lo = (lo - vplus(lo)) / Ra
    return dict(gain=gain, off=out(c), use=use, edge=edge, i_top=i_hi, i_bot=i_lo,
                lsb_out=span / 4096 * gain, G=G, vmid=vmid, out_lo=out(lo), out_hi=out(hi))


RTOL_1PCT = 0.01    # 680 ohm C23228: 1 % (docs/jlcpcb-parts.md, "Status read 2026-11-11": "680R 1 % 0603")
RTOL_22 = 0.05      # 22 ohm C23345: its page says +/-1 % but the part code 0603WAF220JT5E's "J" means 5 %; taken as 5 % *(check)*


def dc_mc_buf(aref, scen, n, q, seed, tol):
    """dc_mc for the buffered variant.  Every placement draws its own tolerance: Rb and Rf are each 953 + (249 || 249) + 22
    (0.1 %, 0.1 %, 1 %), scaled when a case overrides their value; Ra, Rg 953 0.1 %; Rbin 680 1 %, Rbpl 330k 0.1 %; the buffer's
    and the AWG op-amp's offsets uniform +/-0.2 mV (OPA365 max, SBOS365G p6)."""
    r = np.random.default_rng(seed)
    t = lambda x, tl=tol: x * (1 + r.uniform(-tl, tl, n))
    comp = lambda: t(953.0) + 1 / (1 / t(249.0) + 1 / t(249.0)) + t(22.0, RTOL_22)
    Ra, Rg = t(q['Ra']) + (t(q['Rsh']) if q.get('Rsh') else 0.0), t(q['Rg'])
    Rb, Rf = comp() * q['Rb'] / RB_BUF, comp() * q['Rf'] / RB_BUF
    Rin, Rpl = t(q['Rbin'], RTOL_1PCT) + q['rout'], t(q['Rbpl'])
    G = 1 + Rf / Rg
    if scen == 'A':
        lo, hi = aref / 6, 5 * aref / 6
        vmid = aref / 2 + r.uniform(-0.030, 0.030, n)
    else:
        k = aref / 3.27
        lo, hi = 0.578 * k, 2.771 * k
        vmid = aref / 2 + r.uniform(-0.005, 0.005, n)
    if q.get('vm_div'):   # the AWG's own Vmid: +3.3 V_A (LM27762 datasheet span 3.235-3.342 V) x its divider, independent of AREF
        rt_, rb_, _ = q['vm_div']; tl = VMDIV_TOL.get(rt_, 0.01)
        a_, b_ = t(rt_, tl), t(rb_, tl)
        vmid = r.uniform(R_DS_WEAK[0], R_DS_STRONG[0], n) * b_ / (a_ + b_)
    vosb, vosm = r.uniform(-1, 1, n) * 0.2e-3, r.uniform(-1, 1, n) * 0.2e-3
    vret = 0.0 if q.get('bpl_to') == '0' else vmid
    vbin = lambda vd: (vd * Rpl + vret * Rin) / (Rin + Rpl)
    out = lambda vd: G * ((vbin(vd) + vosb) * Rb / (Ra + Rb) + vosm) - (G - 1) * vmid
    gain = G * Rb / (Ra + Rb) * Rpl / (Rin + Rpl)
    c = (lo + hi) / 2; span = hi - lo
    off0 = out(0.0)
    vd_hi, vd_lo = (1.0 - off0) / gain, (-1.0 - off0) / gain
    use = (vd_hi - vd_lo) / span
    edge = np.maximum(np.abs(vd_hi - c), np.abs(vd_lo - c)) / (span / 2)
    i_hi = (hi - vbin(hi)) / Rin
    i_lo = (lo - vbin(lo)) / Rin
    return dict(gain=gain, off=out(c), use=use, edge=edge, i_top=i_hi, i_bot=i_lo,
                lsb_out=span / 4096 * gain, G=G, vmid=vmid, out_lo=out(lo), out_hi=out(hi))


VMDIV_TOL = {4.7e3: 0.01, 100e3: 0.001, 330e3: 0.001}     # 4.7k C23162 1 %; 100k C394537 and 330k C351655 0.1 % (jlcpcb-parts.md)


# ---------------------------------------------------------------- LM27762 ripple, calibrated (2026-11-11, with sim/powercal P4-b)
# The datasheet's 5 mV (Fig 5-1, read as peak at its own condition: COUT 2.2 uF) is placed as sim/powercal places it: a source
# behind the LDO's output impedance, 11 mohm + 0.8 uH (powercal gap G2, assumed), scaled so that it reads 5 mV / n on the LDO's
# 2.2 uF (20 mohm ESR) alone.  The netlists keep their 0.2 ohm DC source (load regulation, start-up); the ripple is applied to the
# rail impedance each AC run measures at 'sp' / 'sn', with the LDO's 2.2 uF added in parallel.  Lines: fundamentals 1.7 / 2.0 /
# 2.3 MHz (the worst taken), harmonics n = 1..5 up to 10.5 MHz at 5 mV / n, both rails summed in phase, as powercal does.
LDO_RIP_A1, LDO_ZS_R, LDO_ZS_L, LDO_C, LDO_C_ESR = 5e-3, 0.011, 0.8e-6, 2.2e-6, 0.02
z_ldo_c = lambda f: LDO_C_ESR + 1 / (2j * np.pi * f * LDO_C)
z_ldo_s = lambda f: LDO_ZS_R + 2j * np.pi * f * LDO_ZS_L
kcal_ldo = lambda f: abs(z_ldo_s(f) + z_ldo_c(f)) / abs(z_ldo_c(f))      # source amplitude per volt read on 2.2 uF alone


def rail_transfer(p, src, tag='rt'):
    """For the rail driven by `src` ('vcc' or 'vee'): frequency, the rail's own impedance at sp / sn (from the AC run's current
    through the subcircuit's 0.2 ohm), and the output per volt on that rail node."""
    node, bn, an = ('sp', 'xsup.bp', 'xsup.ap') if src == 'vcc' else ('sn', 'xsup.bn', 'xsup.an')
    r = ng(tag, build(p, ".ac dec 40 10 1G\n", ac=(src,)), vecs=f'v(bnc) v({node}) v({bn}) v({an})')
    f = r['frequency'].real
    rp = p.get('rp', D['rp']) if src == 'vcc' else p.get('rn', D['rn'])
    i = (r[f'v({an})'] - r[f'v({bn})']) / rp
    sgn = 1 if src == 'vcc' else -1
    return f, sgn * r[f'v({node})'] / (sgn * i), r['v(bnc)'] / r[f'v({node})']


def ripple_ldo(p, flat=False, tag='rl'):
    """LM27762 ripple at the AWG output, rms: worst fundamental, both rails coherent; flat=True puts 5 mV on every harmonic n=1..4
    at 2 MHz (sim/awg's earlier weighting) for comparison.  Also returns the + rail's ripple at 2 MHz."""
    T = {s: rail_transfer(p, s, tag) for s in ('vcc', 'vee')}
    # Samsung's ESR at 2 MHz for lines below 3 MHz and its 3-10.5 MHz maximum above, stitched by frequency as sim/powercal does
    Th = {s: rail_transfer(dict(p, esr_hi=True), s, tag + 'h') for s in ('vcc', 'vee')} if p.get('esr_bulk', D['esr_bulk']) is None else T
    def line(src, fr, a):
        f, zr, h = (Th if fr >= 3e6 else T)[src]
        z = np.interp(fr, f, zr.real) + 1j * np.interp(fr, f, zr.imag)
        hh = abs(np.interp(fr, f, h.real) + 1j * np.interp(fr, f, h.imag))
        zp = 1 / (1 / z + 1 / z_ldo_c(fr))
        vr = a * kcal_ldo(fr) * abs(zp / (z_ldo_s(fr) + zp))
        return vr, vr * hh
    best = None
    for fs in ((2.0e6,) if flat else (1.7e6, 2.0e6, 2.3e6)):
        ns = range(1, 5) if flat else [n for n in range(1, 6) if fs * n <= 10.5e6]
        tot = sum((line('vcc', fs * n, LDO_RIP_A1 if flat else LDO_RIP_A1 / n)[1] + line('vee', fs * n, LDO_RIP_A1 if flat else LDO_RIP_A1 / n)[1]) ** 2 / 2 for n in ns)
        if best is None or tot > best[0]: best = (tot, fs)
    return dict(rms=float(np.sqrt(best[0])), fs=best[1], rail_pos_2MHz_mV=float(line('vcc', 2e6, LDO_RIP_A1)[0] * 1e3),
                rail_neg_2MHz_mV=float(line('vee', 2e6, LDO_RIP_A1)[0] * 1e3))


_RIP_TR = {}


def rip_tr():
    """The 2 MHz source amplitude for the transient runs (0.2 ohm source, as the netlist carries it) that puts the calibrated
    ripple on the + rail: the start-up rows' ripple."""
    if 'a' not in _RIP_TR:
        f, zr, h = rail_transfer(P(), 'vcc', 'rtr')
        z = np.interp(2e6, f, zr.real) + 1j * np.interp(2e6, f, zr.imag)
        old = abs(z / (z + 0.2 + 0.08))               # the 0.2 ohm source and the diode's small-signal resistance, about
        new = ripple_ldo(P(), tag='rtr')['rail_pos_2MHz_mV'] * 1e-3 / LDO_RIP_A1
        _RIP_TR['a'] = float(LDO_RIP_A1 * new / old)
    return _RIP_TR['a']


def aw6_total(p, tag='nzv'):
    """AW-6 as case_noise sums it: circuit .noise + LM27762 rail noise (22 uV rms 10 Hz-100 kHz, flat) through each rail's
    transfer + the 2 MHz 5 mV pk ripple and three harmonics on both rails (sim/powercal's LDO ripple, 5 mV pk) + Vmid buffer
    10 nV/rtHz.  With the AWG's own Vmid divider on +3.3 V_A, the + rail's transfer includes the divider path."""
    n = noise_split(p, tag=tag)
    f, tfp = tf_to_bnc(p, 'vcc'); _, tfn = tf_to_bnc(p, 'vee'); _, tfm = tf_to_bnc(p, 'vmid')
    dens = 22e-6 / np.sqrt(1e5 - 10)
    sup = (integ(f, (tfp * dens) ** 2) + integ(f, (tfn * dens) ** 2)) ** 0.5
    vmn = 0.0 if p.get('vm_div') else integ(f, tfm ** 2) ** 0.5 * 10e-9   # a real buffer's noise is in .noise
    rip = ripple_ldo(p, tag=tag + 'r')['rms']
    tot = float(np.sqrt((n['total_uV'] * 1e-6) ** 2 + sup ** 2 + vmn ** 2 + rip ** 2) * 1e6)
    return dict(total_uV=tot, circuit_uV=n['total_uV'], supply_uV=sup * 1e6, ripple_uV=float(rip * 1e6),
                divider_uV=n['by_part_uV'].get('AWG Vmid divider', 0.0), tf_vcc_2MHz=float(np.interp(2e6, f, tfp)))


def vmid_buffer_pm(load, tag='vmpm'):
    """Loop-break PM of an OPA365 follower at 1.65 V on a 3.0 V supply (+3.3 V_A behind its Schottky) driving `load`."""
    t = (f".include {MODELS['OPA365']}\nVp vcc 0 3.0\nVn vee 0 0\nVi in 0 DC 1.65\nX1 in fb vcc vee out OPA365\nLb out fb 1G\n"
         f"Cb s fb 1000\nVs s 0 DC 0 AC 1\n{load}\nRl out 0 953\n.ac dec 100 10 2G\n")
    r = ng(tag, t, vecs='v(out) v(fb)')
    return pm_from_T(r['frequency'].real, -r['v(out)'] / r['v(fb)'])


VMID_OUTPUTS = {'10 uF + 100 nF': ('Cl out a 10u\nRa a 0 0.02\nC2 out b 100n\nRb b 0 0.05', dict(cvm=10e-6, cvm2=True)),
                'bare (no capacitor)': ('', dict(cvm=0.0, cvm2=False))}


def vmid_option(args):
    """One AWG-Vmid option: AW-8 start-up grid and power-up arms, AW-6, offset span, divider current."""
    global NETDIR, RAWDIR
    lab, vd, outk = args
    cvm = VMID_OUTPUTS[outk][1]
    tg = re.sub(r'[^A-Za-z0-9]+', '_', lab)
    NETDIR = os.path.join(HERE, 'netlists', 'vmid', tg); RAWDIR = os.path.join(HERE, 'raw', 'w_vmid_' + tg)
    ex = dict(vm_div=vd, **cvm)
    L8 = 2.1
    grid = {}
    for name, ramp in (('+3.3 first', (0, 200e-6, 100e-6)), ('- rail first', (200e-6, 0, 100e-6)), ('simultaneous 1 ms', (0, 0, 1e-3)),
                       ('simultaneous 10 us', (0, 0, 10e-6))):
        for dl, (vdac, ro) in (('DAC floating', (0.0, 1e9)), ('DAC 0 V', (0.0, 0.001)), ('DAC 3.3 V', (3.3, 0.001))):
            for vp_, vn_ in ((3.37, R_STRONG[1]), (3.23, R_WEAK[1])):
                q = P(ramp=ramp, vp=vp_, vn=vn_, ripple=rip_tr(), rout=ro, vdac=vdac, load='hiz', **ex)
                b = ng('sv', build(q, ".tran 0.2u 4m\n"), vecs='v(bnc)')['v(bnc)'].real
                grid[f'{name}/{dl}/{vp_}'] = float(np.abs(b).max())
    pu = {}
    for ss in (20e-6, 2e-3):          # sim/powercal's soft-start corners
        for dl, pwl in (('reset trace', '0 3.3 1.4 0.0'), ('0 V held', '0 0 1.4 0')):
            for vp_, vn_ in ((3.37, R_STRONG[1]), (3.23, R_WEAK[1])):
                q = P(ramp=(0, 0, ss), vp=vp_, vn=vn_, dac_pwl=pwl, vdac=float(pwl.split()[1]), load='hiz', **ex)
                r_ = ng('pv', build(q, ".tran 2u 60m 0 5u\n"), vecs='v(bnc) v(vm)')
                b = r_['v(bnc)'].real; t_ = r_['time'].real; o = t_[np.abs(b) > L8]
                pu[f'{ss}/{dl}/{vp_}'] = dict(peak=float(np.abs(b).max()), t_over_ms=float(o[-1] - o[0]) * 1e3 if len(o) else 0.0)
    nz = aw6_total(P(**ex), tag='nzv')
    m = dc_mc_buf(3.2, 'B', 20000, dict(D, **dict(P(), **ex)), 3, 0.001)
    m3 = dc_mc_buf(3.3, 'B', 20000, dict(D, **dict(P(), **ex)), 3, 0.001)
    rt, rb, ct = vd
    return lab, dict(grid_max=max(grid.values()), grid_worst=max(grid, key=grid.get), powerup_max=max(v['peak'] for v in pu.values()),
                     powerup_worst=max(pu, key=lambda k: pu[k]['peak']), powerup=pu, aw6=nz,
                     edge=float(max(m['edge'].max(), m3['edge'].max())), off_mV=float(max(np.abs(m['off']).max(), np.abs(m3['off']).max()) * 1e3),
                     vmid_span=(float(m['vmid'].min()), float(m['vmid'].max())), i_div_uA=R_DS_STRONG[0] / (rt + rb) * 1e6,
                     tau_tap_ms=(rt * rb / (rt + rb)) * ct * 1e3)


VMID_OPTIONS = [(f'{rn} / {rn}, tap {cn}, output {on}', (r, r, c), on)
                for rn, r in (('4.7k', 4.7e3), ('100k', 100e3), ('330k', 330e3))
                for cn, c in (('12 pF', 12e-12), ('1.5 nF', 1.5e-9), ('100 nF', 100e-9))
                for on in VMID_OUTPUTS]


def case_vmid():
    """The AWG's own Vmid (owned by sim/powercal; evaluated here): divider and capacitor options from existing types."""
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=4, mp_context=mp.get_context('fork')) as ex:
        res = dict(ex.map(vmid_option, VMID_OPTIONS))
    OUT['vmid_options'] = res
    bpm = {k: vmid_buffer_pm(v[0])['pm'] for k, v in VMID_OUTPUTS.items()}
    OUT['vmid_buffer_pm'] = bpm
    add('AN-1 info', 'the Vmid buffer (OPA365 follower, 953 ohm load) driving its output network: ' + ' / '.join(bpm), 'info (>= 45 deg)',
        ' / '.join(f'{v:.1f}' for v in bpm.values()) + ' deg', '', True)
    for lab, v in res.items():
        ok = v['grid_max'] <= 2.1 and v['powerup_max'] <= 2.1 and v['aw6']['total_uV'] <= 100 and v['edge'] <= 0.92
        add('AW-8/AW-6 info', f'AWG own Vmid [{lab}]: AW-8 grid / power-up worst; AW-6 total (ripple); AW-1 edge; offset; Vmid span; divider current; tap tau',
            'info: AW-8 <= 2.1 V, AW-6 <= 100 uV, AW-1 <= 92 %',
            f"{v['grid_max']:.3f} / {v['powerup_max']:.3f} V; {v['aw6']['total_uV']:.1f} ({v['aw6']['ripple_uV']:.1f}) uV; {v['edge']*100:.1f} %; "
            f"{v['off_mV']:.1f} mV; {v['vmid_span'][0]:.4f}-{v['vmid_span'][1]:.4f} V; {v['i_div_uA']:.1f} uA; {v['tau_tap_ms']:.3g} ms",
            'all four hold' if ok else 'fails', True)
    return res


def case_dc():
    res = {}
    arefs = np.round(np.arange(3.10, 3.3001, 0.025), 3)
    lim = dict(gain=(1.10, 1.20), off=0.060, use=0.92, edge=0.92, i=100e-6, lsb=1e-3)
    holds = {k: [] for k in ('AW-7 gain', 'AW-7 offset', 'AW-1 width', 'AW-1 edge', 'AW-5', 'AW-2')}
    for scen in ('A', 'B'):
        for aref in arefs:
            m = dc_mc(aref, scen)
            row = dict(gain=(m['gain'].min(), m['gain'].max()), off=float(np.abs(m['off']).max()),
                       use=float(m['use'].max()), edge=float(m['edge'].max()),
                       i=float(max(np.abs(m['i_top']).max(), np.abs(m['i_bot']).max())),
                       lsb=float(m['lsb_out'].max()))
            res[f'{scen}_{aref}'] = row
            ok = {'AW-7 gain': row['gain'][0] >= 1.10 and row['gain'][1] <= 1.20,
                  'AW-7 offset': row['off'] <= 0.060, 'AW-1 width': row['use'] <= 0.92,
                  'AW-1 edge': row['edge'] <= 0.92, 'AW-5': row['i'] <= 100e-6, 'AW-2': row['lsb'] <= 1e-3}
            for k, v in ok.items(): holds[k].append((scen, float(aref), bool(v)))
    OUT['dc'] = res
    # worst over the whole AREF range, per scenario
    for scen in ('A', 'B'):
        rows = [v for k, v in res.items() if k.startswith(scen) and float(k.split('_')[1]) >= 3.2 - 1e-9]
        g = (min(r['gain'][0] for r in rows), max(r['gain'][1] for r in rows))
        sc = {'A': 'window theory 1/6-5/6 AREF, +/-30 mV centring', 'B': 'measured board window 0.578-2.771 V, +39.5 mV centre'}[scen]
        add('AW-7', f'gain 1.10-1.20 [{sc}]', '1.10..1.20', f'{g[0]:.4f}..{g[1]:.4f}', f'{min(g[0]-1.10, 1.20-g[1]):+.4f}', 1.10 <= g[0] and g[1] <= 1.20)
        o = max(r['off'] for r in rows)
        if BUFV or LOWV:   # owner, 2026-11-11: information only; AW-1's 92 % window (below) is the binding as-built check
            add('AW-7 info', f'offset at window centre [{scen}] (calibrated by the MCP3564; AW-1 window use is the binding check)', 'info (was <= 60 mV)',
                f'{o*1e3:.1f} mV', f'{(0.060-o)*1e3:+.1f} mV against the old 60 mV', True)
        else:
            add('AW-7', f'offset at window centre [{scen}]', '<= 60 mV', f'{o*1e3:.1f} mV', f'{(0.060-o)*1e3:+.1f} mV', o <= 0.060)
        u = max(r['use'] for r in rows)
        add('AW-1', f'window use, width [{scen}]', '<= 92 %', f'{u*100:.1f} %', f'{(0.92-u)*100:+.1f} %', u <= 0.92)
        e = max(r['edge'] for r in rows)
        add('AW-1', f'window use, position-aware (+/-1 V ends vs window ends) [{scen}]', '<= 92 %', f'{e*100:.1f} %', f'{(0.92-e)*100:+.1f} %', e <= 0.92)
        i = max(r['i'] for r in rows)
        add('AW-5', f'DAC pin load at window ends [{scen}]', '<= 0.1 mA', f'{i*1e6:.1f} uA', f'{(100e-6-i)*1e6:+.1f} uA', i <= 100e-6)
        l = max(r['lsb'] for r in rows)
        add('AW-2', f'one DAC code at the output [{scen}] (ideal 12-bit)', '<= 1 mV', f'{l*1e3:.3f} mV', f'{(1e-3-l)*1e3:+.3f} mV', l <= 1e-3)
    # lowest AREF at which each limit still holds (both scenarios must hold at and above it)
    low = {}
    for k, lst in holds.items():
        ok_arefs = [a for a in arefs if all(v for (s, aa, v) in lst if aa == a)]
        # contiguous from 3.30 downwards
        lowest = None
        for a in sorted(arefs, reverse=True):
            if a in ok_arefs: lowest = float(a)
            else: break
        low[k] = lowest
    OUT['dc_lowest_aref'] = low
    # step with DNL: datasheet DNL +/-3 LSB max (Table 46-40, SAM3X/A datasheet p.1421-1422)
    lsb = OUT['dc']['A_3.3']['lsb']
    OUT['dnl_step_mV'] = (1 + 3) * lsb * 1e3
    add('AW-2', 'info: single-code step incl. datasheet DNL +3 LSB (the Due\'s, not an AFE limit)', 'nominal step <= 1 mV',
        f'{OUT["dnl_step_mV"]:.2f} mV', '', True, 'informational: DNL belongs to the Due')
    # sensitivity: 0.2 % (0.1 % plus 25 ppm/K over an assumed +/-40 K *(check)*) instead of 0.1 %
    m = dc_mc(3.2, 'A', tol=0.002); mb = dc_mc(3.2, 'B', tol=0.002)
    OUT['dc_tol_0p1pct'] = dict(gain=(float(m['gain'].min()), float(m['gain'].max())), off_A=float(np.abs(m['off']).max()),
                                off_B=float(np.abs(mb['off']).max()), use=float(m['use'].max()))
    # ngspice cross-check of the analytic map, nominal parts
    t = build(P(vdac=2.5, vmid=1.65), ".op\n")
    r = ng('dc_chk', t, vecs='v(out)')
    d = dict(D); d.update(P())
    G = 1 + d['Rf'] / d['Rg']
    if BUFV:
        vb = (2.5 * d['Rbpl'] + (0.0 if d.get('bpl_to') == '0' else 1.65) * d['Rbin']) / (d['Rbin'] + d['Rbpl'])
        pred = G * vb * d['Rb'] / (d['Ra'] + d.get('Rsh', 0.0) + d['Rb']) - (G - 1) * 1.65
    else:
        S = 1 / d['Ra'] + 1 / d['Rb'] + 1 / d['Rx']
        pred = G * ((2.5 / d['Ra'] + 1.65 / d['Rx']) / S) - (G - 1) * 1.65
    OUT['dc_xcheck'] = dict(spice=float(r['v(out)'][0]), analytic=pred)
    r0 = ng('dc_mid', build(P(vdac=1.65, vmid=1.65), ".op\n"), vecs='v(out)')
    v0 = float(r0['v(out)'][0]); OUT['dc_offset_nominal_V'] = v0
    add('AW-7 info', 'nominal parts, DAC at Vmid (1.65 V): output (zero-offset pick Rf/Rg = Rb/Ra + Rb/Rx)', 'info (a few mV)', f'{v0*1e3:+.2f} mV', '', True)
    return OUT['dc_xcheck']


# --------------------------------------------------------------- AW-1 swing in the circuit (the rows above are the linear map only)
def swing_err(kw, ld, vm, vp, vn, sg):
    """v(bnc) with the DAC at Vmid + sg/GAIN_NOM (+/-1.0 V at high-Z), and its error against the linear map through Vmid."""
    if 'dsch' not in kw:     # headroom: the Schottky at its datasheet maximum drop
        kw = dict(kw, dsch='DBAT54S_MAX')
    v = lambda vd: float(ng('swing', build(P(**dict(dict(vdac=vd, vmid=vm, vp=vp, vn=vn, load=ld), **{k: x for k, x in kw.items() if k not in ('vp', 'vn')})), ".op\n"), vecs='v(bnc)')['v(bnc)'][0])
    if D.get('vm_div') and 'vm_div' not in kw or kw.get('vm_div'):   # Vmid is set by +3.3 V_A: centre on the actual value
        q_ = P(**dict(dict(vdac=1.65, vp=vp, vn=vn, load=ld), **{k: x for k, x in kw.items() if k not in ('vp', 'vn')}))
        vm = float(ng('swing', build(q_, ".op\n"), vecs='v(vm)')['v(vm)'][0])
    c = v(vm); k = (v(vm + 0.01) - v(vm - 0.01)) / 0.02
    vd = vm + sg / GAIN_NOM
    a = v(vd)
    return a, abs(a - (c + k * (vd - vm)))


def case_swing(p=None):
    """AW-1: the output must reach +/-1.0 V into high-Z and +/-0.5 V into 50 ohm.  The DC rows above use the linear map and cannot
    see the op-amp's swing limit, which the supply-pin Schottky and the 10 ohm filter resistor (PR-3, PW-2) move inward.  Each corner:
    the DAC level that commands +/-1.0 V at high-Z; the error is v(bnc) against the linear prediction from the incremental gain at Vmid."""
    res = {}
    for ld, tgt in (('hiz', 1.0), ('r50', 0.5)):
        worst = 0.0; least = 9.0
        corners = RAILS if ld == 'hiz' else RAILS_AW1_50[AW1_50_BASIS]
        wk = corners[1]
        basis = ('blanket +/-5 % of the setting' if ld == 'hiz' or AW1_50_BASIS == 'blanket5'
                 else 'LM27762 datasheet: VFB+/- limits (Sec 5.5) and 0.1 % feedback resistors')
        for vm in (1.55, 1.685):
            for vp_, vn_ in corners:
                for sg in (1, -1):
                    a, e = swing_err(p or {}, ld, vm, vp_, vn_, sg)
                    res[f'{ld}/{vm}/{vn_}/{sg:+d}'] = dict(v=a, err=e)
                    worst = max(worst, e); least = min(least, abs(a))
        res[ld] = dict(err_max=worst, least=least, weak=wk, basis=basis)
        judged50 = not ((BUFV or LOWV) and ld == 'r50' and p is None)
        add('AW-1' if judged50 else 'AW-1 info', f'circuit swing: output at +/-1.0 V commanded (high-Z level), into {ld}, 2 Vmid x 3 rail corners, weak corner {wk[0]:+.3f} / {wk[1]:+.3f} V ({basis}): error against the linear map'
            + ('' if judged50 else ' [model rails, 0.2 ohm = 200 uV/mA: information; the row below is judged]'),
            '<= 0.62 mV (one DAC code, AW-2)', f'{worst*1e3:.2f} mV (smallest |v(bnc)| {least:.4f} V, target {tgt} V)', f'{0.62-worst*1e3:+.2f} mV', worst * 1e3 <= 0.62 or not judged50)
        if not judged50:
            # the AWG's own Vmid follows +3.3 V_A, so the rail's load regulation is a linearity term into 50 ohm.  Judged at the
            # LM27762's 34 uV/mA (SNVSAF7C Sec 5.5, typical, stated for the - LDO; no + LDO figure) on both rails; VT-8 measures it
            w2 = 0.0
            for vm in (1.55, 1.685):
                for vp_, vn_ in corners:
                    for sg in (1, -1):
                        w2 = max(w2, swing_err(dict(rp=0.034, rn=0.034), ld, vm, vp_, vn_, sg)[1])
            res['r50_reg34'] = w2
            add('AW-1', f'circuit swing into r50, the same corners, rails at the datasheet load regulation 34 uV/mA (judged; VT-8 measures the + rail into 50 ohm)',
                '<= 0.62 mV (one DAC code, AW-2)', f'{w2*1e3:.2f} mV', f'{0.62-w2*1e3:+.2f} mV', w2 * 1e3 <= 0.62)
    # the margin of the 50 ohm row in rail volts: the least negative - rail at which the row still holds (bisection, weak + rail)
    if p is None:
        e_at = lambda vn_: max(swing_err({}, 'r50', vm, R_DS_WEAK[0], vn_, -1)[1] for vm in (1.55, 1.685))
        lo_, hi_ = (-2.10, -1.40) if BUFV else (-2.10, -1.90)          # lo_ passes, hi_ fails (checked below)
        if e_at(lo_) * 1e3 <= 0.62 and e_at(hi_) * 1e3 > 0.62:
            for _ in range(10):
                mid = (lo_ + hi_) / 2
                if e_at(mid) * 1e3 <= 0.62: lo_ = mid
                else: hi_ = mid
            res['r50_rail_limit'] = lo_
        else:
            res['r50_rail_limit'] = None
    OUT['swing'] = res
    return res


# --------------------------------------------------------------- bandwidth, AW-3
def case_bw():
    res = {}
    for op in ('OPA365', 'OPA354', 'OPA356'):
        f, h = ac_resp(P(opamp=op), tag='bw'); s = bw_stats(f, h); res[op] = s
    s = res['OPA365']
    add('AW-3/SM-3', 'stage -3 dB bandwidth, OPA365, nominal, into 1 Mohm || 15 pF', '>= 8 MHz',
        f'{s["f3db"]/1e6:.1f} MHz', f'{s["f3db"]/1e6-8:+.1f} MHz', s['f3db'] >= 8e6, f'peaking {s["peak_db"]:.2f} dB')
    # in-band flatness: the -3 dB rows cannot see a mis-compensated attenuator (Ca, Cb against Rb||Rx), which is a gain step
    # between DC and a few hundred kHz; reported, the host calibrates the frequency response (CA-1)
    fl = {}
    for cp in (0.5e-12, 1.5e-12, 3.5e-12):
        f, h = ac_resp(P(Cpar_p=cp), tag='fl'); g = np.abs(h) / abs(h[0]); m = (f >= 1e4) & (f <= 8e6)
        fl[cp] = (float(g[m].min()), float(g[m].max()))
    res['flatness_10k_8M'] = {f'{k*1e12:g}pF': v for k, v in fl.items()}
    lo_, hi_ = min(v[0] for v in fl.values()), max(v[1] for v in fl.values())
    add('AW-3 info', 'gain 10 kHz-8 MHz relative to DC, V+ parasitic 0.5 / 1.5 / 3.5 pF (attenuator compensation Ca, Cb)', 'info (host calibrates, CA-1)',
        f'{fl[1.5e-12][0]:.3f}..{fl[1.5e-12][1]:.3f} nominal, {lo_:.3f}..{hi_:.3f} over the three', '', True)
    # corners: parasitic C at V+ 0.5..3.5 pF, Ca/Cb/Cf +/-5 %
    worst = (1e12, 0); pk = 0
    for cp in (0.5e-12, 3.5e-12):
        for ka in (0.95, 1.05):
            for kb in (0.95, 1.05):
                for kf in (0.95, 1.05):
                    f, h = ac_resp(P(Cpar_p=cp, Ca=FINAL['Ca'] * ka, Cb=FINAL['Cb'] * kb, Cf=FINAL['Cf'] * kf), tag='bwc')
                    st = bw_stats(f, h)
                    worst = (min(worst[0], st['f3db']), max(worst[1], st['f3db'])); pk = max(pk, st['peak_db'])
    w50 = 1e12
    for cp in (0.5e-12, 3.5e-12):
        for k in (0.95, 1.05):
            f, h = ac_resp(P(Cpar_p=cp, Ca=FINAL['Ca'] * k, Cb=FINAL['Cb'] * k, Cf=FINAL['Cf'] * k, load='r50'), tag='bwc')
            w50 = min(w50, bw_stats(f, h)['f3db'])
    res['corners'] = dict(f3db_min=worst[0], f3db_max=worst[1], peak_max_db=pk, f3db_min_r50=w50)
    add('AW-3/AW-4', 'bandwidth into 50 ohm over capacitor/parasitic corners', '>= 8 MHz', f'{w50/1e6:.1f} MHz', f'{w50/1e6-8:+.1f} MHz', w50 >= 8e6)
    add('AW-3/SM-3', 'bandwidth over 16 capacitor/parasitic corners', '>= 8 MHz', f'{worst[0]/1e6:.1f}..{worst[1]/1e6:.1f} MHz',
        f'{worst[0]/1e6-8:+.1f} MHz', worst[0] >= 8e6, f'max peaking {pk:.2f} dB')
    if BUFV:   # the buffer's own load (normal operation: calibration and playback do not run together, PA-3)
        bb = {}
        for cbo in (5e-12, 10e-12, 30e-12):
            for ld in ('hiz', 'r50'):
                f, h = ac_resp(P(Cbo=cbo, load=ld), tag='bwb'); bb[f'{cbo*1e12:g}pF/{ld}'] = bw_stats(f, h)
        res['buf_cbo'] = bb
        wb = min(v['f3db'] for v in bb.values()); pb = max(v['peak_db'] for v in bb.values())
        add('AW-3/SM-3', 'bandwidth with the buffer output at 5 / 10 / 30 pF, hi-Z and 50 ohm', '>= 8 MHz', f'{wb/1e6:.1f} MHz',
            f'{wb/1e6-8:+.1f} MHz', wb >= 8e6, f'max peaking {pb:.2f} dB')
    # DAC output impedance sweep (unknown): bandwidth and DC gain
    rr = {}
    for ro in (0, 100, 300, 1000, 3000):
        f, h = ac_resp(P(rout=ro), tag='bwr'); st = bw_stats(f, h); rr[ro] = st
    res['rout'] = rr
    ro_max = max([ro for ro in rr if rr[ro]['f3db'] >= 8e6 and 1.10 <= rr[ro]['dc'] <= 1.20] or [0])
    res['rout_max_ok'] = ro_max
    add('AW-3/AW-7', 'DAC output impedance tolerated (swept 0-3k; datasheet gives none)', 'gain 1.10-1.20 and BW >= 8 MHz',
        f'ok up to {ro_max} ohm of {list(rr)}', '', ro_max >= 1000, 'unknown *(check)*, closed by VT-6')
    # AN-3: what the DAC pin sees at high frequency (1 kohm test source impedance)
    t = build(P(rout=1000.0), ".ac dec 20 1e5 1e8\n", ac=('dac',))
    r = ng('zin', t, vecs='v(dac)')
    ff = r['frequency'].real; H = r['v(dac)']
    Z = 1000.0 * H / (1 - H)
    res['dac_pin_Zin'] = {f'{x/1e6:g}M': [float(abs(np.interp(x, ff, Z.real) + 1j * np.interp(x, ff, Z.imag))),
                                           float(-1 / (2 * np.pi * x * np.interp(x, ff, Z.imag)) * 1e12)] for x in (1e6, 8e6)}
    OUT['bw'] = res
    return res


# --------------------------------------------------------------- AN-1 phase margin
def case_pm():
    res = {}
    for op in ('OPA365', 'OPA354', 'OPA356'):
        for ld in ('hiz', 'r50', 'cable_open', 'short'):
            pm = phase_margin(P(opamp=op, load=ld), tag='pm')
            res[f'{op}/{ld}'] = dict(pm=pm['pm'], fc=pm['fc'], T0=pm['T0'])
    worst = min(v['pm'] for k, v in res.items() if k.startswith('OPA365'))
    add('AN-1', 'phase margin, OPA365, 4 loads, +2 pF at the inverting node', '>= 45 deg', f'{worst:.1f} deg', f'{worst-45:+.1f} deg', worst >= 45)
    w2 = min(v['pm'] for k, v in res.items() if k.startswith('OPA354'))
    res['OPA354_min'] = w2
    OUT['pm'] = res
    return res


# --------------------------------------------------------------- AN-1 for the DAC0 buffer (buffered variant only)
def pm_from_T(f, T):
    """Phase margin at the first |T| = 1 crossing, T the loop gain with the inversion removed (T > 0 at DC)."""
    mag = np.abs(T)
    i = np.where((mag[:-1] >= 1) & (mag[1:] < 1))[0]
    if not len(i): return dict(pm=float('nan'), fc=float('nan'), T0=float(mag[0]))
    i = i[0]
    a = (np.log(1) - np.log(mag[i])) / (np.log(mag[i + 1]) - np.log(mag[i]))
    fc = np.exp(np.log(f[i]) + a * (np.log(f[i + 1]) - np.log(f[i])))
    ph = np.unwrap(np.angle(T)); phc = ph[i] + a * (ph[i + 1] - ph[i])
    pm = (180 + np.degrees(phc) + 180) % 360 - 180
    return dict(pm=float(pm), fc=float(fc), T0=float(mag[0]))


def phase_margin_buf(p, mode='break', tag='pmb'):
    """The DAC0 follower's loop gain in the circuit.  'break': sim/awg's loop break (1 GH in series with -IN, AC 1 into -IN
    through 1000 F), T = -v(bo) / v(bfb); the output keeps its real load (attenuator, Cbo) and Crep replicates -IN's own
    load on it.  'mid': sim/loop's Middlebrook voltage injection between the output pin and the load, T = -v(boo) / v(bo)."""
    q = P(**dict(dict(bmode=mode), **p))
    t = build(q, ".ac dec 200 1k 2G\n", ac=())
    if mode == 'break':
        r = ng(tag, t, vecs='v(bo) v(bfb)'); f = r['frequency'].real; T = -r['v(bo)'] / r['v(bfb)']
    else:
        r = ng(tag, t, vecs='v(bo) v(boo)'); f = r['frequency'].real; T = -r['v(boo)'] / r['v(bo)']
    out = pm_from_T(f, T); out['f'] = f; out['T'] = T
    return out


# datasheet Figure 7-15 (SBOS365G p10), G = +1, RL 10 k, VS +/-2.5 V: overshoot (%) against CL (pF), read off the plot by eye
# from a 400 dpi render of models/opa365/opa365.pdf (log axis 10 pF to 1 nF) *(check: graph reading, about +/-2 points)*
DS_OVERSHOOT = {10: 6.0, 30: 7.5, 40: 10.0, 70: 20.0, 100: 28.0, 200: 42.0, 300: 49.5}
# Figure 7-16 (same page, same conditions, no CL stated, so the probe's): a 200 mV small-signal step overshoots about 13 %
# (26 mV on 50 mV/div) and rings at about 50 MHz, read by eye *(check)*.  It disagrees with Figure 7-15's 6 % at its left end.
DS_716 = 13.0


def follower_alone(cl, mode='tran', step=0.2, rl=10e3, vs=2.5, crep=0.0, tag='fa'):
    """The OPA365 macromodel alone as the datasheet's Figure 7-15 test: G = +1, RL to ground, CL, +/-vs supplies."""
    h = f".include {MODELS['OPA365']}\nVp vcc 0 {vs}\nVn vee 0 {-vs}\nRl out 0 {rl}\nCl out 0 {max(cl, 1e-18)}\n"
    if mode == 'tran':
        t = h + f"Vi in 0 DC 0 PWL(0 0 200n 0 201n {step} 3u {step})\nX1 in out vcc vee out OPA365\n.tran 0.05n 1.5u\n"
        r = ng(tag, t, vecs='v(out)'); tm = r['time'].real; v = r['v(out)'].real
        fin = float(np.mean(v[tm > 1.3e-6])); base = float(np.mean(v[(tm > 100e-9) & (tm < 190e-9)]))
        return dict(overshoot=float((v[tm > 200e-9].max() - fin) / (fin - base)))
    t = h + (f"Vi in 0 DC 0\nX1 in fb vcc vee out OPA365\nLb out fb 1G\nCb s fb 1000\nVs s 0 DC 0 AC 1\n"
             + (f"Cr out 0 {crep}\n" if crep else '') + ".ac dec 200 1k 2G\n")
    r = ng(tag, t, vecs='v(out) v(fb)')
    return pm_from_T(r['frequency'].real, -r['v(out)'] / r['v(fb)'])


def os_from_pm(pm):
    """Overshoot of a two-pole loop with this phase margin (unity feedback): an order-of-magnitude companion, not a fit."""
    zs = np.linspace(0.01, 0.99, 2000)
    pms = np.degrees(np.arctan(2 * zs / np.sqrt(np.sqrt(1 + 4 * zs ** 4) - 2 * zs ** 2)))
    z = float(np.interp(pm, pms, zs))
    return float(np.exp(-np.pi * z / np.sqrt(1 - z * z)))


# The buffer's capacitive loads (every figure an assumption *(check)* until a layout exists): the trace at the buffer pin
# 5-10 pF (15 pF for margin); the injection branch (build(): inj, Rinj, Rsh) carries 10 pF of trace and each TMUX1119's 10 pF
# source side, and an on switch adds Ron 3.7 ohm, 10 pF on its drain side, and node N as 4.5 kohm to Vmid + 2 pF.


def buf_pm_worst(cbo, extra=None, tag='pmb'):
    """Worst loop-break PM over the DAC operating point (0.578 / 1.65 / 2.771 V) and the + rail (3.23 / 3.37 V)."""
    w = None; grid = {}
    for vd in (0.578, 1.65, 2.771):
        for vp_ in (3.23, 3.37):
            pm = phase_margin_buf(dict(dict(Cbo=cbo, vdac=vd, vp=vp_), **(extra or {})), tag=tag)
            grid[f'{vd}/{vp_}'] = round(pm['pm'], 2)
            if w is None or pm['pm'] < w['pm']: w = dict(pm=pm['pm'], fc=pm['fc'], vdac=vd, vp=vp_)
    w['grid'] = grid
    return w


def case_buf():
    """AN-1 for the DAC0 follower, and the validation of the method that reads it."""
    res = {}
    # 1. the model against the datasheet: Figure 7-15's overshoot against CL, the same test
    sim = {c: follower_alone(c * 1e-12, tag='fa_os')['overshoot'] * 100 for c in DS_OVERSHOOT}
    pm_alone = {c: follower_alone(c * 1e-12, mode='break', tag='fa_pm')['pm'] for c in DS_OVERSHOOT}
    res['fig7_15'] = {c: dict(datasheet=DS_OVERSHOOT[c], sim=sim[c], pm_break=pm_alone[c], os_from_pm=os_from_pm(pm_alone[c]) * 100)
                      for c in DS_OVERSHOOT}
    dev = max(abs(sim[c] - DS_OVERSHOOT[c]) for c in DS_OVERSHOOT)
    add('model', 'OPA365 follower overshoot against CL, the datasheet test (G = +1, RL 10 k, +/-2.5 V, 200 mV step): model vs Fig 7-15 at '
        + '/'.join(str(c) for c in DS_OVERSHOOT) + ' pF', 'within +/-10 points at every CL',
        ' / '.join(f'{sim[c]:.0f}({DS_OVERSHOOT[c]:.0f})' for c in DS_OVERSHOOT) + ' % sim(datasheet)', f'{10-dev:+.1f} points', dev <= 10)
    o716 = {c: follower_alone(c * 1e-12, tag='fa_os')['overshoot'] * 100 for c in (0.0, 10.0, 20.0)}
    res['fig7_16'] = o716
    d716 = min(abs(v - DS_716) for v in o716.values())
    add('model', 'OPA365 follower, 200 mV step, model at CL 0 / 10 / 20 pF (a probe) vs Fig 7-16 (about 13 %, no CL stated)', 'one of them within +/-5 points',
        ' / '.join(f'{v:.1f}' for v in o716.values()) + f' % ({DS_716:.0f})', f'{5-d716:+.1f} points', d716 <= 5)
    # the alone-follower 1 nF point: the datasheet says stable to about 1 nF in unity gain (Sec 8.3.3)
    pm1n = follower_alone(1e-9, mode='break', tag='fa_pm')
    res['alone_1nF'] = pm1n
    add('model info', 'OPA365 follower alone, 1 nF, loop-break PM (datasheet Sec 8.3.3: stable to about 1 nF in unity gain)', 'info',
        f'{pm1n["pm"]:.1f} deg at {pm1n["fc"]/1e6:.1f} MHz', '', True)
    # 2. the loop break against the simulated closed loop, in the circuit, at the calibration load
    for crep in (0.0, 6e-12):
        q = dict(Cbo=52e-12, Crep=crep, inj=None, Rsh=0.0, Rinj=0.0)
        pm = phase_margin_buf(q, tag='pmb_v')
        r = ng('bufcl', build(P(Cbo=52e-12, inj=None, Rsh=0.0, Rinj=0.0), ".ac dec 200 1k 2G\n", ac=('dac',)), vecs='v(bo) v(bin)')
        f = r['frequency'].real; cl = np.abs(r['v(bo)'] / r['v(bin)'])
        pred = np.abs(pm['T'] / (1 + pm['T']))
        sel = (pm['f'] > 1e4) & (pm['f'] < 3e7)
        res[f'clcheck_Crep{crep*1e12:g}'] = float(np.max(np.abs(np.interp(pm['f'][sel], f, cl) / pred[sel] - 1)))
    err = res['clcheck_Crep0']; err6 = res['clcheck_Crep6']
    add('model', 'buffer loop break: |T/(1+T)| against the simulated closed loop bin -> bo, 52 pF load, 10 kHz-30 MHz (no -IN replica; with a 6 pF replica)',
        'agree within 10 %', f'{err*100:.1f} % ({err6*100:.1f} % with 6 pF)', f'{(0.10-err)*100:+.1f} %', err <= 0.10)
    # 3. the design's buffer load (2026-11-11: the PA-3 injection branch is gone, replaced by a BNC-tee calibration): the
    # attenuator (Ra + Rb, 2.05 kohm) and the PCB trace at the buffer pin, 5-10 pF assumed *(check)*, 15-30 pF for margin
    g = {cp: buf_pm_worst(cp, tag='pmb') for cp in (5e-12, 10e-12, 15e-12, 20e-12, 30e-12)}
    res['pm'] = {f'{c*1e12:g}pF': dict(pm=v['pm'], fc=v['fc'], vdac=v['vdac'], vp=v['vp'], grid=v['grid']) for c, v in g.items()}
    wn = min(g[c]['pm'] for c in (5e-12, 10e-12)); w15 = g[15e-12]['pm']
    lab = 'no injection branch'
    add('AN-1', f'DAC0 buffer phase margin [{lab}]: attenuator + pin trace 5-10 pF, DAC 0.578/1.65/2.771 V, + rail 3.23/3.37 V',
        '>= 45 deg (target 50)', f'{wn:.1f} deg', f'{wn-45:+.1f} deg', wn >= 45)
    add('AN-1 target', f'DAC0 buffer [{lab}]: the design target with a 15 pF pin trace (the 5-10 pF assumption + 50 %)',
        '>= 50 deg', f'{w15:.1f} deg', f'{w15-50:+.1f} deg', w15 >= 50)
    add('AN-1 info', f'DAC0 buffer [{lab}]: 20 / 30 pF at its pin', 'info (>= 45 deg)', f"{g[20e-12]['pm']:.1f} / {g[30e-12]['pm']:.1f} deg", '', True)
    lo_, hi_ = 1e-12, 1e-9
    if buf_pm_worst(lo_)['pm'] >= 45 and buf_pm_worst(hi_)['pm'] < 45:
        for _ in range(9):
            mid = (lo_ * hi_) ** 0.5
            if buf_pm_worst(mid)['pm'] >= 45: lo_ = mid
            else: hi_ = mid
        res['cbo_at_45deg_pF'] = lo_ * 1e12
    else:
        res['cbo_at_45deg_pF'] = None
    add('AN-1 info', f'DAC0 buffer [{lab}]: largest trace capacitance at its pin that keeps 45 deg (worst operating point)', 'info',
        f'{res["cbo_at_45deg_pF"]:.0f} pF' if res['cbo_at_45deg_pF'] else 'not bracketed', '', True)
    # 4. the known-unstable case: 1 nF straight on the buffer output must fail the same check
    k1 = buf_pm_worst(1e-9, extra=dict(inj=None, Rsh=0.0, Rinj=0.0))
    res['known_unstable_1nF'] = k1
    # 5. the method sim/loop used, on the same circuit: Middlebrook voltage injection
    nb = dict(inj=None, Rsh=0.0, Rinj=0.0)     # the earlier lumped loads, so the comparison stays the same circuit
    mid = {c: phase_margin_buf(dict(Cbo=c, **nb), mode='mid', tag='pmb_m')['pm'] for c in (10e-12, 52e-12, 1e-9)}
    brk = {c: phase_margin_buf(dict(Cbo=c, **nb), tag='pmb_b')['pm'] for c in mid}
    res['mid_vs_break'] = {f'{c*1e12:g}pF': dict(mid=mid[c], brk=brk[c]) for c in mid}
    add('AN-1 info', "sim/loop's Middlebrook injection on the same circuit, DAC 1.65 V, 3.3 V: 10 / 52 / 1000 pF (loop break in brackets)",
        'info (why the loop run saw no capacitive-load effect)', ' / '.join(f'{mid[c]:.1f} ({brk[c]:.1f})' for c in mid) + ' deg', '', True)
    # 6. transient small-signal overshoot of the buffer pin in the circuit (info)
    ov = {}
    for cp in (10e-12, 15e-12):
        pwl = "0 1.60 1u 1.60 1.001u 1.70 5u 1.70"
        r = ng('bufos', build(P(dac_pwl=pwl, vdac=1.60, Cbo=cp), ".tran 0.05n 2.5u\n"), vecs='v(bo)')
        tm = r['time'].real; v = r['v(bo)'].real
        fin = float(np.mean(v[tm > 2.2e-6])); base = float(np.mean(v[(tm > 0.8e-6) & (tm < 0.99e-6)]))
        ov[f'{cp*1e12:g}pF'] = float((v[tm > 1e-6].max() - fin) / (fin - base))
    res['tran_overshoot'] = ov
    add('AN-1 info', f'DAC0 buffer [{lab}], 100 mV step at 1.6 V: pin overshoot at 10 / 15 pF', 'info',
        ' / '.join(f'{v*100:.1f}' for v in ov.values()) + ' %', '', True)
    OUT['buf'] = res
    return res


# --------------------------------------------------------------- loads, AW-4
def case_loads():
    res = {}
    for ld in ('open', 'hiz', 'r50', 'cable_open', 'cable_r50', 'cable_scope'):
        f, h = ac_resp(P(load=ld), vec='v(bnc)', tag='ld')
        res[ld] = dict(dc=float(abs(h[0])), f3db=bw_stats(f, h)['f3db'], peak_db=bw_stats(f, h)['peak_db'])
    ratio = res['r50']['dc'] / res['open']['dc']
    res['r50_over_open'] = ratio
    zt = P()['Rs'] + P()['R2']
    ideal = 50 / (50 + zt)
    add('AW-4', f'amplitude into 50 ohm / into high-Z: total series {zt:.1f} ohm (accuracy cost of the protection, host calibrates it)', f'ideal {ideal:.4f} for the resistors', f'{ratio:.4f}', f'{(ratio/ideal-1)*100:+.2f} % from ideal', abs(ratio / ideal - 1) < 0.01)
    add('AW-1', 'into 50 ohm: BNC amplitude when the hi-Z amplitude is +/-1.0 V (<= 92 % of the window)', '+/-0.5 V (AW-1 second clause)', f'+/-{1.0*ratio:.3f} V', f'{(ratio-0.5)*1.0:+.3f} V', ratio >= 0.4995,
        'cost of Zout > 50 ohm: reaching 0.5 V into 50 ohm would need the op-amp at 1.25 V, 102 % of the window')
    for ld in ('hiz', 'cable_open', 'cable_r50', 'cable_scope', 'r50'):
        add('AW-3/AW-4', f'-3 dB bandwidth into {ld}', '>= 8 MHz', f'{res[ld]["f3db"]/1e6:.1f} MHz', f'{res[ld]["f3db"]/1e6-8:+.1f} MHz', res[ld]['f3db'] >= 8e6, f'peaking {res[ld]["peak_db"]:.2f} dB')
    # output impedance seen from the BNC
    f, ho = ac_resp(P(load='open'), tag='zo1'); _, h5 = ac_resp(P(load='r50'), tag='zo2')
    z = (np.abs(ho) / np.abs(h5) - 1) * 50
    res['zout'] = {f'{x/1e6:g}M': float(np.interp(x, f, z)) for x in (1e3, 1e5, 1e6, 8e6, 16e6)}
    OUT['loads'] = res
    return res


# --------------------------------------------------------------- transient edges, AW-3/AW-4
def edge_metrics(t, v, t0, step, tr_in):
    v = np.asarray(v)
    base = float(np.interp(t0 - 20e-9, t, v)); fin = float(np.interp(t[-1] - 50e-9, t, v))
    amp = fin - base
    if abs(amp) < 1e-9: return dict(amp=amp)
    n = (v - base) / amp
    k = np.where(t >= t0)[0]
    t10 = t[k][np.argmax(n[k] >= 0.1)]; t90 = t[k][np.argmax(n[k] >= 0.9)]
    over = float(n[k].max() - 1)
    out_of_band = np.where(np.abs(n[k] - 1) > 0.01)[0]
    settle = float(t[k][out_of_band[-1]] - t0) if len(out_of_band) else 0.0
    return dict(amp=amp, rise_10_90=float(t90 - t10), overshoot=over, settle_1pct=settle)


def run_step(p, tag, edge, half, tend=3e-6, node='bnc', rs=None):
    t0 = 0.5e-6
    c = 1.65
    pwl = f"0 {c-half} {t0} {c-half} {t0+edge} {c+half} 10u {c+half}"
    pp = P(dac_pwl=pwl, vdac=c - half, **p)
    t = build(pp, f".tran 0.5n {tend}\n")
    r = ng(tag, t, vecs=f'v({node}) v(out)')
    tm = r['time'].real
    return tm, r[f'v({node})'].real, r['v(out)'].real, t0


def cable_ov_corners(kw, cps=(0.5e-12, 1.5e-12, 3.5e-12)):
    """Far-end overshoot of the 42 ns edge into the open 1 m cable, per V+ parasitic capacitance."""
    out = {}
    for cp in cps:
        tm, v, vo, t0 = run_step(dict(kw, load='cable_open', Cpar_p=cp), 'st3', 52e-9, 0.25, tend=1.5e-6, node='far')
        out[f'{cp*1e12:g}pF'] = edge_metrics(tm, v, t0, 0.5, 52e-9)['overshoot']
    return out


def case_step():
    res = {}
    # 5 V/us class DAC edge: 1.9 V full-window step in 375 ns (10-90 % = 300 ns, the measured DAC edge)
    for ld in ('hiz', 'r50', 'cable_open', 'cable_r50', 'cable_scope'):
        tm, v, vo, t0 = run_step(dict(load=ld), 'st', 375e-9, 0.95, node='bnc' if ld in ('hiz', 'r50') else 'far')
        res[f'dac_edge/{ld}'] = edge_metrics(tm, v, t0, 1.9, 375e-9)
    # a fast edge, 52 ns (42 ns 10-90, the equivalent-time floor in docs/ets-pam.md), 0.5 V DAC step
    for ld in ('cable_open', 'cable_r50'):
        for rs in (49.9, 0.001):
            tm, v, vo, t0 = run_step(dict(load=ld, Rs=rs), 'st2', 52e-9, 0.25, tend=1.5e-6, node='far')
            res[f'fast/{ld}/Rs{rs}'] = edge_metrics(tm, v, t0, 0.5, 52e-9)
    ideal = {}
    for rs in (49.9, 0.001):
        t = (".include models/awg_behavioural.lib\nVs a 0 PWL(0 0 10n 0 12n 1 5u 1)\n"
             f"Rs a b {rs}\nT1 b 0 far 0 Z0=50 TD=5n\nRl far 0 1G\n.tran 0.1n 300n\n")
        r = ng('ideal_edge', t, vecs='v(far)')
        v = r['v(far)'].real
        ideal[rs] = float((v.max() - v[-1]) / v[-1]) if v[-1] > 0 else float('nan')
        # distinct steps visible after the first arrival: ringing = variation after 40 ns
        tt = r['time'].real; late = v[tt > 60e-9]
        ideal[f'{rs}_ring'] = float((late.max() - late.min()) / v[-1])
    res['ideal_edge_open_cable'] = ideal
    ov = ideal[49.9]
    zt = P()['Rs'] + P()['R2']
    ideal[f'{zt:.1f}_ring'] = ring_ideal(zt)
    add('AW-4 info', f'1 m (5 ns) open cable, ideal 2 ns edge (stricter than any signal this stage can make): ringing after 60 ns, source {zt:.1f} ohm', 'info (reflection coefficient (Zs-50)/(Zs+50))', f'{ideal[f"{zt:.1f}_ring"]*100:.1f} % ring', '', True, f'0 % at 49.9 ohm, {ideal["0.001_ring"]*100:.0f} % with no resistor')
    # the attenuator compensation (Ca against Rb||Rx and the V+ capacitance) sets this overshoot, so it is read over the V+ parasitic corners
    ovc = cable_ov_corners({})
    res['fast/cable_open/Rs49.9/Cpar_corners'] = ovc
    ov = max(ovc.values())
    add('AW-4', 'same cable open, real stage, 42 ns DAC-class edge: far-end overshoot, worst of V+ parasitic 0.5 / 1.5 / 3.5 pF', '<= 5 %', f'{ov*100:.1f} % ({" / ".join(f"{v*100:.1f}" for v in ovc.values())})', f'{(0.05-ov)*100:+.1f} %', ov <= 0.05, f'with Rs shorted: {res["fast/cable_open/Rs0.001"]["overshoot"]*100:.1f} % (a 42 ns edge is slow against 10 ns round trip)')
    ov = res['fast/cable_r50/Rs49.9']['overshoot']
    add('AW-4', 'same cable terminated in 50 ohm: overshoot', '<= 5 %', f'{ov*100:.1f} %', f'{(0.05-ov)*100:+.1f} %', ov <= 0.05)
    for ld in ('hiz', 'cable_scope'):
        m = res[f'dac_edge/{ld}']
        add('AW-3', f'5 V/us DAC edge into {ld}: 10-90 % rise, overshoot', 'overshoot <= 5 %', f'{m["rise_10_90"]*1e9:.0f} ns, {m["overshoot"]*100:.1f} %', f'{(0.05-m["overshoot"])*100:+.1f} %', m['overshoot'] <= 0.05)
    OUT['step'] = res
    return res


# --------------------------------------------------------------- noise, AW-6 / PW-2 / AN-5
def tf_to_bnc(p, src, f_probe=None):
    t = build(p, ".ac dec 40 10 1G\n", ac=(src,))
    r = ng('tf', t, vecs='v(bnc)')
    return r['frequency'].real, np.abs(r['v(bnc)'])


def case_noise():
    res = {}
    for op in ('OPA365', 'OPA354', 'OPA356'):
        n = noise_split(P(opamp=op), tag='nz')
        f = n.pop('_f'); n.pop('_tot2')
        res[op] = n
    n = res['OPA365']
    # contributors outside the circuit-level .noise: supply (datasheet density, flat, both rails),
    # Vmid buffer (allowance), 2 MHz ripple and harmonics
    p = P()
    f, tfp = tf_to_bnc(p, 'vcc'); _, tfn = tf_to_bnc(p, 'vee'); _, tfm = tf_to_bnc(p, 'vmid')
    dens = 22e-6 / np.sqrt(1e5 - 10)     # V/rtHz, 22 uV rms over 10 Hz-100 kHz, assumed flat to the stage bandwidth
    supply = (integ(f, (tfp * dens) ** 2) + integ(f, (tfn * dens) ** 2)) ** 0.5
    vm_int = integ(f, tfm ** 2) ** 0.5       # sqrt(integral of TF^2) -> volts per (V/rtHz)
    vm_assumed = 10e-9
    vmid_noise = vm_int * vm_assumed
    rl = ripple_ldo(p, tag='rl'); rlf = ripple_ldo(p, flat=True, tag='rlf')
    ripple_rms = rl['rms']
    res['extra'] = dict(supply_uV=supply * 1e6, vmid_uV=vmid_noise * 1e6, vmid_allow_nV_for_10uV=10e-6 / vm_int * 1e9,
                        ripple_uV=ripple_rms * 1e6, ripple_flat_harmonics_uV=rlf['rms'] * 1e6, ripple_worst_fs=rl['fs'],
                        rail_ripple_2MHz_mV=(rl['rail_pos_2MHz_mV'], rl['rail_neg_2MHz_mV']),
                        tf_supply_dB_at_2MHz=float(20 * np.log10(np.interp(2e6, f, tfp))),
                        tf_vmid_int=vm_int)
    tot = np.sqrt((n['total_uV'] * 1e-6) ** 2 + supply ** 2 + vmid_noise ** 2 + ripple_rms ** 2) * 1e6
    res['AW6_total_uV'] = float(tot)
    add('AW-6', 'added noise, quiet DC source, OPA365: circuit .noise 10 Hz-100 MHz', '<= 100 uV rms', f'{n["total_uV"]:.1f} uV', f'{100-n["total_uV"]:+.1f} uV', n['total_uV'] <= 100)
    add('AW-6/PW-2', 'sum with supply noise, 2 MHz ripple and harmonics, Vmid buffer (10 nV/rtHz assumed)', '<= 100 uV rms', f'{tot:.1f} uV', f'{100-tot:+.1f} uV', tot <= 100,
        f'supply {supply*1e6:.2f}, ripple {ripple_rms*1e6:.2f}, Vmid {vmid_noise*1e6:.2f} uV')
    add('AW-6/PW-2', 'LM27762 ripple at the AWG output alone (5 mV / n on the LDO 2.2 uF, behind 0.8 uH; 1.7-2.3 MHz worst; both rails in phase; sim/powercal P4-b method)',
        '<= 20 uV rms (powercal P4-b allocation, 20 % of AW-6)', f'{ripple_rms*1e6:.2f} uV at {rl["fs"]/1e6:.1f} MHz (rails {rl["rail_pos_2MHz_mV"]:.2f} / {rl["rail_neg_2MHz_mV"]:.2f} mV at 2 MHz); flat 5 mV harmonics {rlf["rms"]*1e6:.2f} uV',
        f'{20-ripple_rms*1e6:+.2f} uV', ripple_rms <= 20e-6)
    cmp_ = {}
    for lab_, eb_ in (('one nominal 10 uF, 10 mohm, no ESL', 0.01), ('one nominal 10 uF, 20 mohm, no ESL', 0.02)):
        cmp_[lab_] = ripple_ldo(dict(p, esr_bulk=eb_), tag='rlc')['rms'] * 1e6
    res['extra']['ripple_earlier_assumptions_uV'] = cmp_
    add('AW-6/PW-2 info', 'the same with the earlier rail assumptions: ' + ' / '.join(cmp_), 'info (20 uV)', ' / '.join(f'{v:.2f}' for v in cmp_.values()) + ' uV', '', True)
    for alt in ('OPA354', 'OPA356'):
        o4 = res[alt]['total_uV']
        add('AW-6', f'same circuit with {alt} at its own bandwidth (circuit .noise only)', '<= 100 uV rms', f'{o4:.1f} uV', f'{100-o4:+.1f} uV', o4 <= 100, 'alternative part, not recommended')
    # the DAC's own noise, reported not guaranteed
    f, tfd = tf_to_bnc(p, 'dac')
    enbw = integ(f, (tfd / tfd[0]) ** 2, 10, 1e9)
    res['dac_total'] = dict(gain=float(tfd[0]), enbw_MHz=enbw / 1e6,
                            scope_20mV_x_gain_mV=20.0 * float(tfd[0]),
                            adc_bound_0p5code_mV=0.5 * 3.27 / 4096 * 1e3 * float(tfd[0]))
    OUT['noise'] = res
    return res


def case_ripple_tran():
    """Cross-check of the ripple transfer function: 2 MHz, 5 mV on both rails in a transient."""
    p = P(ripple=5e-3)
    t = build(p, ".tran 1n 20u\n")
    r = ng('rip', t, vecs='v(bnc)')
    tm = r['time'].real; v = r['v(bnc)'].real
    m = tm > 10e-6
    th = 2 * np.pi * 2e6 * tm[m]
    M = np.vstack([np.sin(th), np.cos(th), np.ones(m.sum())]).T
    c = np.linalg.lstsq(M, v[m], rcond=None)[0]
    amp = float(np.hypot(c[0], c[1]))
    f, tfp = tf_to_bnc(P(), 'vcc'); _, tfn = tf_to_bnc(P(), 'vee')
    pred = float(np.interp(2e6, f, tfp) + np.interp(2e6, f, tfn)) * 5e-3   # worst-case in-phase sum
    OUT['ripple_tran'] = dict(amp_uV=amp * 1e6, pred_inphase_uV=pred * 1e6)
    return OUT['ripple_tran']


# --------------------------------------------------------------- short, PW-3
def case_short():
    res = {}
    RTOT = P()['Rs'] + P()['R2']
    for name, vd in (('+1V', 1.65 + 1.0 / GAIN_NOM), ('mid', 1.65), ('window top 2.771', 2.771), ('window bottom 0.578', 0.578)):
        t = build(P(load='short', vdac=vd), ".op\n")
        r = ng('sh', t, vecs='v(out) v(vccx) v(veex) i(visp) i(visn) v(bnc) v(inv)' + (' i(visb)' if BUFV else ''))
        vo = r['v(out)'][0]; ip = r['i(visp)'][0]; inn = r['i(visn)'][0]
        ib = float(r['i(visb)'][0]) if BUFV else 0.0
        iout = vo / RTOT + (vo - r['v(inv)'][0]) / D['Rf']
        psup = r['v(vccx)'][0] * ip + r['v(veex)'][0] * inn
        pamp = psup - vo * iout
        res[name] = dict(vdac=vd, vout=float(vo), i_short_mA=float(vo / RTOT * 1e3), i_pos_mA=float(ip * 1e3),
                         i_neg_mA=float(-inn * 1e3), p_amp_mW=float(pamp * 1e3))
        if BUFV: res[name]['i_buf_mA'] = ib * 1e3
    top = max(abs(v['i_short_mA']) for v in res.values())
    atpm1 = res['+1V']['i_short_mA']
    add('PW-3', 'short to ground at +/-1 V commanded: output current', f'<= {PW3_LIM:g} mA', f'{atpm1:.1f} mA', f'{PW3_LIM-atpm1:+.1f} mA', abs(atpm1) <= PW3_LIM)
    tol_hi = top * 49.8 / (49.8 * 0.99)
    add('PW-3', 'short at the DAC window ends: output current', f'<= {PW3_LIM:g} mA', f'{top:.2f} mA', f'{PW3_LIM-top:+.2f} mA', top <= PW3_LIM, f'with both resistors 1 % low: {tol_hi:.2f} mA')
    itot = max(v['i_pos_mA'] for v in res.values()) + 0
    itot = max(v['i_pos_mA'] + v['i_neg_mA'] for v in res.values())
    add('PW-3/PW-1', 'op-amp supply current in the short (+ and - pins summed), AFE total limit 100 mA', '<= 100 mA', f'{itot:.1f} mA', f'{100-itot:+.1f} mA', itot <= 100, 'the rest of the AFE adds its own')
    if BUFV:
        ibm = max(v['i_buf_mA'] for v in res.values())
        OUT['short_buf'] = sb_ = dict(buf_supply_mA_max=ibm)
        # PW-1 normal operation (a short is a load AW-4 allows): the AFE's quiescent total (powercal) + the buffer at its
        # datasheet maximum, 5 mA (the +5 mA of the variant), + the AWG op-amp's increase in the worst short.  The idle
        # increase is taken against the mid-scale operating point, so the AWG op-amp's own quiescent is not counted twice.
        idle = res['mid']['i_pos_mA'] + res['mid']['i_neg_mA']
        inc = itot - idle
        tot5 = AFE_POWERCAL_MA + BUF_ADD_MA + inc
        bl = ' (incl. the DAC0 buffer at 5 mA)' if BUF_IN_POWERCAL else f' + buffer {BUF_IQ_MA:g} mA'
        add('PW-1', f'AFE in normal operation, AWG shorted (AW-4 allows it): powercal {AFE_POWERCAL_MA:.1f} mA{bl} + AWG increase {inc:.1f} mA', '<= 100 mA',
            f'{tot5:.1f} mA', f'{100-tot5:+.1f} mA', tot5 <= 100)
        # the same with the buffer's own load current added to its 5 mA: the model's buffer current is its typical Iq plus the
        # attenuator's 2.05 kohm, so the load share is the model's current minus its own Iq at no load (case_short reads both)
        tq = build(P(vdac=1.65, load='hiz', Ra=1e9, Rb=1e9), ".op\n"); iq0 = float(ng('shq', tq, vecs='i(visb)')['i(visb)'][0]) * 1e3
        ild = ibm - iq0
        sb_['buf_iq_model_mA'] = iq0; sb_['buf_load_mA'] = ild
        tot6 = tot5 + ild
        add('PW-1', f'same, buffer at 5 mA + its attenuator load {ild:.2f} mA (model Iq {iq0:.2f} mA, worst buffer current {ibm:.2f} mA)', '<= 100 mA',
            f'{tot6:.1f} mA', f'{100-tot6:+.1f} mA', tot6 <= 100)
    pm_ = max(v['p_amp_mW'] for v in res.values())
    add('PW-3', 'op-amp dissipation in the short', 'OPA365 SOT-23 limit *(check)*', f'{pm_:.0f} mW', '', pm_ < 200, 'package limit not read from datasheet *(check)*')
    OUT['short'] = res
    return res


# --------------------------------------------------------------- AW-8 reset/boot
def boot_levels(p=None, vmids=(1.55, 1.65, 1.685), levels=None):
    """DC output for a DAC pin that is floating, at 0 V, at its code-0 level (0.578 V) and at
    the window ends / rail.  Floating = 1 Gohm source impedance, pin held at 0 V behind it.
    Returns {label: (min, max)} over the Vmid values."""
    levels = levels or {'floating': (0.0, 1e9), '0 V': (0.0, 0.001), 'code 0 (0.578 V)': (0.578, 0.001),
                        'mid 1.67 V': (1.67, 0.001), 'window top 2.771 V': (2.771, 0.001), '3.3 V': (3.3, 0.001)}
    out = {}
    for lab, (vd, ro) in levels.items():
        vals = []
        for vm in vmids:
            for vp_, vn_ in RAILS:     # rail corners (+/-5 % on the - rail)
                t = build(P(vdac=vd, rout=ro, vmid=vm, vp=vp_, vn=vn_, **(p or {})), ".op\n")
                r = ng('boot', t, vecs='v(bnc)')
                vals.append(float(r['v(bnc)'][0]))
        out[lab] = (min(vals), max(vals))
    return out


def case_boot():
    """AW-8 (owner, 2026-11-11): DAC0 anywhere 0..3.3 V during reset/boot, unknown source impedance:
    output within +/-2.1 V, and back to the commanded value without exceeding +/-2.1 V."""
    L8 = 2.1
    res = {}
    lv = boot_levels(levels={'floating': (0.0, 1e9), '0 V': (0.0, 0.001), 'post-boot -0.1 V': (-0.1, 0.001), 'post-boot +0.2 V': (0.2, 0.001),
                             'code 0 (0.578 V)': (0.578, 0.001), 'mid 1.67 V': (1.67, 0.001), 'window top 2.771 V': (2.771, 0.001), '3.3 V': (3.3, 0.001)})
    res['dc_levels'] = lv
    for lab, (lo, hi) in lv.items():
        w = max(abs(lo), abs(hi))
        add('AW-8', f'DAC0 pin {lab}: output (Vmid 1.55..1.685, rails +3.23..3.37 / {R_WEAK[1]:.2f}..{R_STRONG[1]:.2f})', f'|out| <= {L8} V', f'{lo:+.3f}..{hi:+.3f} V', f'{L8-w:+.3f} V', w <= L8)
    # whole 0..3.3 V sweep, stiff source, both loads, the worst corners
    worst = 0.0
    for ld in ('hiz', 'r50'):
        for vm, (vp_, vn_) in ((1.55, R_STRONG), (1.685, R_STRONG), (1.55, R_WEAK), (1.685, R_WEAK)):
            for vd in np.arange(0.0, 3.301, 0.1):
                t = build(P(vdac=float(vd), vmid=vm, vp=vp_, vn=vn_, load=ld), ".op\n")
                r = ng('sweep', t, vecs='v(bnc)'); worst = max(worst, abs(float(r['v(bnc)'][0])))
    res['sweep_worst'] = worst
    add('AW-8', 'DAC0 pin swept 0..3.3 V in 0.1 V steps, 2 loads, 4 Vmid/rail corners', f'|out| <= {L8} V', f'{worst:.3f} V', f'{L8-worst:+.3f} V', worst <= L8)
    # the ~1.4 s ramp scaled 10^4 faster (the stage's time constants are ns): 3.3 V at reset, linear to 0 V, rest, then the commanded value
    pwl = "0 1.65 1u 1.65 1.1u 3.3 140u 0.0 200u 0.0 200.1u 1.65 300u 1.65"
    t = build(P(dac_pwl=pwl, vdac=1.65, vmid=1.685, vn=R_STRONG[1], vp=3.37), ".tran 0.1u 300u\n")
    r = ng('ramp', t, vecs='v(bnc)')
    tm = r['time'].real; v = r['v(bnc)'].real
    pk = float(np.abs(v).max()); fin = float(v[-1])
    res['ramp'] = dict(peak=pk, final=fin, after_return_peak=float(np.abs(v[tm > 200.1e-6]).max()))
    add('AW-8', 'reset ramp: DAC0 jumps to 3.3 V, falls linearly to 0 V, rests, returns to 1.65 V (time scaled 1e4)', f'|out| <= {L8} V throughout', f'peak {pk:.3f} V, after return {res["ramp"]["after_return_peak"]:.3f} V, final {fin*1e3:+.0f} mV', f'{L8-pk:+.3f} V', pk <= L8)
    # start-up ordering of the rails with the DAC floating
    st = {}
    for name, ramp in (('+3.3 first, - rail after 200 us', (0, 200e-6, 100e-6)), ('- rail first, +3.3 after 200 us', (200e-6, 0, 100e-6)),
                       ('simultaneous 1 ms ramp', (0, 0, 1e-3)), ('simultaneous 10 us ramp', (0, 0, 10e-6))):
        t = build(P(ramp=ramp, vp=3.37, vn=R_STRONG[1], ripple=rip_tr(), rout=1e9, vdac=0.0, vmid=1.685, load='hiz'), ".tran 0.2u 2.2m\n")
        r = ng('startup', t, vecs='v(vccx) v(veex) v(bnc) v(vm)')
        d = r['v(vccx)'].real - r['v(veex)'].real
        st[name] = dict(max_supply_V=float(d.max()), bnc_min=float(r['v(bnc)'].real.min()), bnc_max=float(r['v(bnc)'].real.max()))
    res['startup'] = st
    if True:
        # the buffer rides the + rail ramp; DAC0 floating, at 0 V or at 3.3 V (the reset level) through the ramp, and Vmid
        # either present from t = 0 or rising with the + rail (its OPA365 is on +3.3 V_A too)
        sb = {}
        for name, ramp in (('+3.3 first', (0, 200e-6, 100e-6)), ('- rail first', (200e-6, 0, 100e-6)),
                           ('simultaneous 1 ms', (0, 0, 1e-3)), ('simultaneous 10 us', (0, 0, 10e-6))):
            for dl, (vd, ro) in (('DAC floating', (0.0, 1e9)), ('DAC 0 V', (0.0, 0.001)), ('DAC 3.3 V', (3.3, 0.001))):
                for vml, vmr in (('Vmid at t=0', None), ('Vmid with + rail', (ramp[0], ramp[2]))):
                    for vm in (1.55, 1.685):
                        q = P(ramp=ramp, vp=3.37, vn=R_STRONG[1], ripple=rip_tr(), rout=ro, vdac=vd, vmid=vm, load='hiz', vm_ramp=vmr)
                        r = ng('startupb', build(q, ".tran 0.2u 2.2m\n"), vecs='v(vccx) v(veex) v(bnc)' + (' v(bvcx)' if BUFV else ''))
                        b = r['v(bnc)'].real
                        sb[f'{name}/{dl}/{vml}/{vm}'] = dict(bnc_min=float(b.min()), bnc_max=float(b.max()), bnc_end=float(b[-1]),
                                                              buf_pins=float(r['v(bvcx)'].real.max()) if BUFV else 0.0,
                                                              max_supply_V=float((r['v(vccx)'].real - r['v(veex)'].real).max()))
        res['startup_buf'] = sb
        exb = max(max(abs(v['bnc_min']), abs(v['bnc_max'])) for v in sb.values())
        kx = max(sb, key=lambda k: max(abs(sb[k]['bnc_min']), abs(sb[k]['bnc_max'])))
        add('AW-8', '4 start-up orders x DAC0 floating / 0 V / 3.3 V x Vmid at t=0 or rising with the + rail x Vmid 1.55 / 1.685 V (48 runs)',
            f'|out| <= {L8} V', f'{exb:.3f} V ({kx})', f'{L8-exb:+.3f} V', exb <= L8)
        # power-up in real time: Vmid from the PW-7 divider (tau 1.65 s, sim/powercal P8-h), rails up in 1 ms, and DAC0 either
        # following the measured reset trace (3.3 V, linear to 0 V over 1.4 s, afe.md 4.1) or held at 3.3 V / 0 V; Vmid 1.55 / 1.685
        pu = {}
        if D.get('vm_div'):   # the AWG's own Vmid follows +3.3 V_A: the first 60 ms at fine steps, soft-start 20 us / 2 ms, both + rail corners
            arms = [(f'{dl}/soft-start {ss*1e3:g} ms/+{vp_}', pwl, dict(ramp=(0, 0, ss), vp=vp_, vn=vn_), ".tran 2u 60m 0 5u\n")
                    for dl, pwl in (('reset trace', '0 3.3 1.4 0.0'), ('3.3 V held', '0 3.3 1.4 3.3'), ('0 V held', '0 0 1.4 0'))
                    for ss in (20e-6, 2e-3) for vp_, vn_ in ((3.37, R_STRONG[1]), (3.23, R_WEAK[1]))]
            pu_lab = 'power-up with the AWG\'s own Vmid (330k / 330k, 12 pF tap) on +3.3 V_A, soft-start 20 us / 2 ms, DAC0 on the reset trace / 3.3 V / 0 V, both + rail corners, first 60 ms'
        else:
            arms = [(f'{dl}/{vm}', pwl, dict(ramp=(0, 0, 1e-3), vp=3.37, vn=R_STRONG[1], vmid=vm, vm_tau=1.65), ".tran 1m 3 0 1m\n")
                    for dl, pwl in (('reset trace', '0 3.3 1.4 0.0 3 0.0'), ('3.3 V held', '0 3.3 3 3.3'), ('0 V held', '0 0 3 0')) for vm in (1.55, 1.685)]
            pu_lab = 'power-up, Vmid charging with the PW-7 tau 1.65 s, DAC0 on the measured reset trace / 3.3 V / 0 V, 3 s real time'
        for key, pwl, kw_, an in arms:
            if True:
                q = P(dac_pwl=pwl, vdac=float(pwl.split()[1]), load='hiz', **kw_)
                r = ng('powerup', build(q, an), vecs='v(bnc) v(vm)')
                t_ = r['time'].real; b = r['v(bnc)'].real
                over = t_[np.abs(b) > L8]
                pu[key] = dict(peak=float(np.abs(b).max()), t_over_s=float(over[-1] - over[0]) if len(over) else 0.0,
                                         vm_at_end=float(r['v(vm)'].real[-1]))
        res['powerup_slow_vmid'] = pu
        pk = max(v['peak'] for v in pu.values()); kk = max(pu, key=lambda k: pu[k]['peak'])
        add('AW-8', pu_lab,
            f'|out| <= {L8} V', f'{pk:.3f} V ({kk}; over {L8} V for {pu[kk]["t_over_s"]:.2f} s)', f'{L8-pk:+.3f} V', pk <= L8)
        bp = max(v['buf_pins'] for v in sb.values())
        (add if BUFV else (lambda *a_, **k_: None))('AN/PR (abs max)', 'DAC0 buffer supply pins during the 48 start-up runs (V- at ground)', '< 5.5 V (OPA365 abs max)', f'{bp:.3f} V', f'{5.5-bp:+.3f} V', bp < 5.5)
    mx = max(v['max_supply_V'] for v in st.values())
    add('AN/PR (abs max)', f'op-amp supply pins, +3.37/{R_STRONG[1]:.2f} V + the calibrated LDO ripple, 4 start-up orders: max V+ minus V-', '< 5.5 V (OPA365 abs max)', f'{mx:.3f} V', f'{5.5-mx:+.3f} V', mx < 5.5, 'LM27762 start-up overshoot not modelled (gap)')
    add('AN/PR (abs max)', f'bare rails (no Schottky) at the LM27762 datasheet maxima: VFB+ 1.218 V, VFB- -1.238 V (Sec 5.5), 0.1 % dividers: {R_DS_STRONG[0]:+.3f} / {R_DS_STRONG[1]:+.3f} V', '< 5.5 V (OPA365 abs max)',
        f'{BARE_MAX:.3f} V', f'{5.5-BARE_MAX:+.3f} V', BARE_MAX < 5.5, 'DC only: no start-up overshoot (datasheet gives none, VT-8)')
    ex = max(max(abs(v['bnc_min']), abs(v['bnc_max'])) for v in st.values())
    add('AW-8', 'output during the four start-up orders, DAC floating, Vmid present from t=0', f'|out| <= {L8} V', f'{ex:.3f} V', f'{L8-ex:+.3f} V', ex <= L8)
    OUT['boot'] = res
    return res


# --------------------------------------------------------------- PR-4 / PR-3: protection at the BNC
ARR0 = {   # label: parameters.  One 50 ohm resistor Rs from the op-amp to the BNC; clamp 'cat' = 'out' (op-amp side) or 'bnc' (load side)
    'S0 49.9, no clamp':                       dict(Rs=49.9, R2=0.0),
    'S1 49.9, 3-diode stacks, op-amp side':    dict(Rs=49.9, R2=0.0, clamp='gnd3', cat='out'),
    'S2 49.9, 3-diode stacks, BNC side':       dict(Rs=49.9, R2=0.0, clamp='gnd3', cat='bnc'),
    'S3 49.9, 2-diode stacks, op-amp side':    dict(Rs=49.9, R2=0.0, clamp='gnd2', cat='out'),
    'S4 49.9, 2-diode stacks, BNC side':       dict(Rs=49.9, R2=0.0, clamp='gnd2', cat='bnc'),
    'H 49.9 + 24.9, 2-diode stacks (rejected: Zout 75)': dict(Rs=49.9, R2=24.9, clamp='gnd2'),
}
ARR = {k: dict(dict(clamp='none', R2=0.0), **v) for k, v in ARR0.items()}   # unspecified = no clamp, no second resistor
REC = 'S1 49.9, 3-diode stacks, op-amp side'
# AFE quiescent total at datasheet maxima (OPA365 scope), read from sim/powercal/results.json (P3 items) so a powercal change reaches here
_PC_ITEMS = json.load(open(os.path.join(HERE, '../powercal/results.json')))['p3_items']
AFE_POWERCAL_MA = sum(_PC_ITEMS.values())
# buffered variant: the DAC0 buffer at 5 mA max (SBOS365G), unless powercal already carries it (it does from 2026-11-11 12:27,
# item 'DAC0 buffer ...'; the file is read at run time and moves with sim/powercal), plus its attenuator load at the DAC
# window top, 2.771 V / (Ra + Rb) = 1.35 mA, which powercal does not carry
BUF_IN_POWERCAL = any('DAC0 buffer' in k for k in _PC_ITEMS)
BUF_ADD_MA = 0.0 if BUF_IN_POWERCAL else BUF_IQ_MA
AFE_BASE_MA = AFE_POWERCAL_MA + ((BUF_ADD_MA + 2.771 / (D['Ra'] + D['Rb']) * 1e3) if BUFV else 0.0)
ISC = 65e-3         # OPA365 short-circuit current, +/-65 mA typical, datasheet p7 (models/datasheet-facts.md); no maximum is given *(check)*
RTOL = 0.001        # the series resistor is 0.1 %
STATED_LEVEL = 1.8  # PR-4: the level this design states, V; case_level derives and checks it
BAV99_PKG_W = 0.25  # BAV99 package rating, recalled *(check)*; per diode, because each carries its own current
PWR = {'0603': 0.1, '0805': 0.125, '1206': 0.25, '2010': 0.5, '2512': 1.0}      # resistor power ratings, W *(check each, vendor derating)*


def fault(p, vext, tag='f'):
    """Forced voltage vext at the BNC (ideal source).  iop = current the op-amp output delivers (resistor current plus the
    clamp's, when the clamp sits on the op-amp side); iclamp = current in the clamp stacks; p_clamp_W = their total power."""
    q = dict(D); q.update(P(**dict(dict(load='none', iso=True), **p)))
    t = build(q, ".op\n", extra=f"Vx bnc 0 DC {vext}")
    has_m = bool(q.get('R2', D['R2']))
    stk = q.get('clamp', 'none') in ('gnd2', 'gnd3')
    vecs = 'v(out) v(vccx) v(veex) v(vcc) v(vee) v(bnc) i(vx) i(visp) i(visn)' + (' v(m)' if has_m else '') + (' i(vca) i(vcb)' if stk else '')
    r = ng(tag, t, vecs=vecs)
    g = lambda k: float(r[k][0])
    d = dict(D); d.update(q)
    m = g('v(m)') if has_m else g('v(bnc)')
    ir = (g('v(out)') - m) / d['Rs']                    # current through the op-amp-side resistor, out -> load
    iext = -g('i(vx)')
    icl_net = (g('i(vca)') + g('i(vcb)')) if stk else 0.0   # node -> ground through the stacks
    icl = (abs(g('i(vca)')) + abs(g('i(vcb)'))) if stk else 0.0
    cn_out = (not has_m) and q.get('cat', 'bnc') == 'out'
    iop = ir + (icl_net if cn_out else 0.0)
    vcl = g('v(out)') if cn_out else (m if has_m else g('v(bnc)'))     # voltage at the clamp node
    return dict(vext=vext, iext_mA=iext * 1e3, iop_mA=abs(iop) * 1e3, ir_mA=abs(ir) * 1e3, vout=g('v(out)'), vm=m,
                vpins=g('v(vccx)') - g('v(veex)'), v_vcc_pin=g('v(vccx)'), v_vee_pin=g('v(veex)'),
                p_Rs_W=ir ** 2 * d['Rs'], p_R2_W=iext ** 2 * d['R2'],
                i_clamp_mA=icl * 1e3, v_clamp_node=vcl, p_clamp_W=icl * abs(vcl),
                i_sup_mA=(g('i(visp)') + g('i(visn)')) * 1e3,
                v_rail_pos=g('v(vcc)'), v_rail_neg=g('v(vee)'))


def unpowered(p, vext, tag='u'):
    q = P(**dict(dict(load='none', iso=True, vp=0, vn=0, vmid=0, vdac=0, rp=1e9, rn=1e9, esd_only=True), **p))
    t = build(q, ".op\n", extra=f"Vx bnc 0 DC {vext}")
    stk = q.get('clamp', 'none') in ('gnd2', 'gnd3')
    r = ng(tag, t, vecs='v(vcc) v(vee) v(vccx) v(veex) i(vx) i(visp) i(visn) v(dac) v(vp) v(out)' + (' i(vca) i(vcb)' if stk else '')
           + (' v(sp) v(bvcx) v(bo) v(bin) i(visb)' if BUFV else ''))
    g = lambda k: float(r[k][0])
    icl = (abs(g('i(vca)')) + abs(g('i(vcb)'))) if stk else 0.0
    iext = abs(g('i(vx)'))
    d = dict(vext=vext, v_rail_pos=g('v(vcc)'), v_rail_neg=g('v(vee)'), pin_pos=g('v(vccx)'), pin_neg=g('v(veex)'),
             i_ext_mA=-g('i(vx)') * 1e3, i_into_pos_rail_uA=-g('i(visp)') * 1e6, i_into_neg_rail_uA=g('i(visn)') * 1e6,
             v_dac=g('v(dac)'), v_out=g('v(out)'), i_clamp_mA=icl * 1e3,
             i_esd_mA=max(0.0, iext - icl) * 1e3)      # what is left for the op-amp's own ESD diodes (the model's, *(check)*)
    if BUFV:     # the DAC0 buffer: its rail (+3.3 V_A, 'sp') and the current back into it through its BAT54
        d.update(v_sp=g('v(sp)'), buf_pins=g('v(bvcx)'), v_bo=g('v(bo)'), v_bin=g('v(bin)'), i_into_buf_rail_uA=-g('i(visb)') * 1e6)
        d['v_rail_pos'] = max(d['v_rail_pos'], d['v_sp'], key=abs)
        d['i_into_pos_rail_uA'] += d['i_into_buf_rail_uA']
    return d


def stack_current(n, v):
    """Current in an n-diode BAV99-model stack alone at v volts (A): the clamp's own knee."""
    d = ''.join(f"Dk{i} {'n' if i == 1 else f'k{i-1}'} {'0' if i == n else f'k{i}'} DBAV99\n" for i in range(1, n + 1))
    t = f".include models/awg_behavioural.lib\nVk n 0 DC {v}\n{d}.op\n"
    return abs(float(ng('knee', t, vecs='i(vk)')['i(vk)'][0]))


def stack_knee(n):
    """Voltage at which the stack carries 1 mA (A bisection on the model)."""
    lo, hi = 0.2, 4.0
    for _ in range(30):
        mid = (lo + hi) / 2
        if stack_current(n, mid) < 1e-3: lo = mid
        else: hi = mid
    return hi


def case_protect():
    res = {}
    for lab, a in ARR.items():
        pw = [dict(fault(dict(a, vdac=vd), vx), vdac=vd) for vd in (0.578, 1.65, 2.771) for vx in (5.0, -5.0, 3.0, -3.0)]
        up = [unpowered(a, vx) for vx in (5.0, -5.0, 3.0, -3.0)]
        rr = {}
        f, h = ac_resp(P(**a, load='hiz'), tag='pb'); rr['bw_hiz'] = bw_stats(f, h)['f3db']
        f, h = ac_resp(P(**a, load='r50'), tag='pb'); rr['bw_r50'] = bw_stats(f, h)['f3db']
        _, ho = ac_resp(P(**a, load='open'), tag='pb'); rr['r50_over_open'] = float(abs(h[0]) / abs(ho[0]))
        tm, v, vo, t0 = run_step(dict(a, load='cable_open'), 'pst', 52e-9, 0.25, tend=1.5e-6, node='far')
        rr['cable_overshoot_42ns'] = edge_metrics(tm, v, t0, 0.5, 52e-9)['overshoot']
        rr['noise_uV'] = noise_split(P(**a), tag='pnz')['total_uV']
        res[lab] = dict(powered=pw, unpowered=up, **rr)
    OUT['protect'] = res
    idle = fault(dict(vdac=1.65), 0.0, tag='f')['i_sup_mA']
    for lab, v in res.items():
        big = lambda k, vx: [x for x in v['powered'] if abs(abs(x['vext']) - vx) < 1e-9]
        b5, b3 = big('', 5.0), big('', 3.0)
        mx = lambda L, k: max(x[k] for x in L)
        v['summary'] = dict(
            iop5_mA=mx(b5, 'iop_mA'), iext5_mA=max(abs(x['iext_mA']) for x in b5), iclamp5_mA=mx(b5, 'i_clamp_mA'),
            pclamp5_W=max(x['p_clamp_W'] for x in b5), pRs5_W=mx(b5, 'p_Rs_W'), pR2_5_W=mx(b5, 'p_R2_W'),
            iop3_mA=mx(b3, 'iop_mA'), iext3_mA=max(abs(x['iext_mA']) for x in b3), iclamp3_mA=mx(b3, 'i_clamp_mA'),
            vpins=mx(v['powered'], 'vpins'), supply_increase_mA=mx(b5, 'i_sup_mA') - idle,
            rail_pos_max=mx(v['powered'], 'v_rail_pos'), rail_neg_min=min(x['v_rail_neg'] for x in v['powered']),
            afe_total_in_fault_mA=AFE_BASE_MA + mx(b5, 'i_sup_mA') - idle,
            unpowered_rail_V=max(max(abs(x['v_rail_pos']), abs(x['v_rail_neg'])) for x in v['unpowered']),
            unpowered_into_rails_uA=max(abs(x['i_into_pos_rail_uA']) + abs(x['i_into_neg_rail_uA']) for x in v['unpowered']),
            unpowered_ext_mA=max(abs(x['i_ext_mA']) for x in v['unpowered'] if abs(x['vext']) == 5.0),
            unpowered_clamp_mA=max(x['i_clamp_mA'] for x in v['unpowered'] if abs(x['vext']) == 5.0),
            unpowered_esd_mA=max(x['i_esd_mA'] for x in v['unpowered'] if abs(x['vext']) == 5.0),
            unpowered_pin_V=max(max(abs(x['pin_pos']), abs(x['pin_neg'])) for x in v['unpowered']))
        if lab != REC:
            continue
        S = v['summary']
        add('PR-4', f'[{lab}] +/-5 V (3 commanded levels): op-amp supply pins, max V+ minus V-', '< 5.5 V', f'{S["vpins"]:.2f} V', f'{5.5-S["vpins"]:+.2f} V', S['vpins'] < 5.5)
        add('PR-4', f'[{lab}] +/-5 V for 10 s: series resistor power (assumed 2010, 0.5 W; its current is the macromodel limit, 65 mA typ in the part)', '<= 0.5 W', f'{S["pRs5_W"]:.3f} W', f'{0.5-S["pRs5_W"]:+.3f} W', S['pRs5_W'] <= 0.5)
        add('PR-4', f'[{lab}] +/-5 V: clamp power per diode (BAV99 package 250 mW *(check)*)', '<= 0.25 W', f'{S["pclamp5_W"]/3*1e3:.1f} mW (clamp {S["iclamp5_mA"]:.1f} mA)', '', S['pclamp5_W'] / 3 <= BAV99_PKG_W)
        add('PW-1/PR-4', f'[{lab}] +/-5 V powered: AFE total = {AFE_BASE_MA:.1f} mA (powercal, datasheet maxima{((" incl. the DAC0 buffer's 5 mA" if BUF_IN_POWERCAL else " + DAC0 buffer 5 mA") + " + its 1.35 mA load") if BUFV else ""}) + supply increase {S["supply_increase_mA"]:.0f} mA; Due 300 mA + AFE (PR-4: a fault is judged against the PW-1 450 mA limit, docs/afe.md)', '<= 450 mA', f'{300+S["afe_total_in_fault_mA"]:.0f} mA', f'{450-300-S["afe_total_in_fault_mA"]:+.0f} mA', 300 + S['afe_total_in_fault_mA'] <= 450)
        cap = S['supply_increase_mA'] * min(1.0, 65.0 / S['iop5_mA'])      # estimate: the real part limits at ISC typ (65 mA), the macromodel at S['iop5_mA']
        S['afe_total_isc_capped_mA'] = AFE_BASE_MA + cap
        add('PW-1/PR-4', f'[{lab}] +/-5 V powered, estimate only: supply increase scaled to the 65 mA typical ISC (the macromodel conducts {S["iop5_mA"]:.0f} mA): AFE {AFE_BASE_MA+cap:.0f} mA', '<= 450 mA total (PR-4) *(check, estimate)*', f'{300+AFE_BASE_MA+cap:.0f} mA', f'{450-300-AFE_BASE_MA-cap:+.0f} mA', 300 + AFE_BASE_MA + cap <= 450)
        add('PR-4', f'[{lab}] +/-5 V powered: AFE supply rails stay in (max +, min -); the Due 3.3 V pin is only sensed, nothing returns to it', 'info (op-amp pin-to-pin < 5.5 V above)', f'{S["rail_pos_max"]:+.2f} / {S["rail_neg_min"]:+.2f} V', '', True)
        add('PR-4/PR-3', f'[{lab}] unpowered +/-5 V (supply-pin Schottkys + 4.7 k bleed): AFE rails and current into the rails', 'rails < 0.5 V, <= 100 uA', f'{S["unpowered_rail_V"]*1e3:.0f} mV, {S["unpowered_into_rails_uA"]:.2f} uA', f'{0.5-S["unpowered_rail_V"]:+.3f} V', S['unpowered_rail_V'] < 0.5 and S['unpowered_into_rails_uA'] <= 100)
    return res


def case_level():
    """PR-4: derive the level, then check it in the circuit.  Current through the resistor = (Vforced + Vcommanded)/R when the
    forced voltage opposes the output; the datasheet rating is ISC = 65 mA typical."""
    Rmin = P()['Rs'] * (1 - RTOL)
    lv = boot_levels(levels={'window top 2.771 V': (2.771, 0.001), 'code 0 (0.578 V)': (0.578, 0.001)})
    vo_win = max(max(abs(a), abs(b)) for a, b in lv.values())     # worst commanded output at a DAC window end, all Vmid/rail corners
    vo_norm = 1.15
    lev = dict(Rmin=Rmin, vo_win=vo_win, vo_norm=vo_norm, isc=ISC,
               level_norm=ISC * Rmin - vo_norm, level_win=ISC * Rmin - vo_win, level_aw8=ISC * Rmin - 2.1, stated=STATED_LEVEL)
    OUT['level'] = lev
    # simulation: forced +/-stated at the BNC, DAC at both window ends, the Vmid/rail corners, resistor 0.1 % low; and the same with the clamp removed
    worst = {}
    for tag, extra in (('clamp', {}), ('no clamp', dict(clamp='none'))):
        w = 0.0; wc = 0.0
        for vm, (vp_, vn_) in ((1.55, R_STRONG), (1.685, R_STRONG), (1.55, R_WEAK), (1.685, R_WEAK)):
            for vd in (0.578, 2.771):
                for vx in (STATED_LEVEL, -STATED_LEVEL):
                    r = fault(dict(Rs=Rmin, vdac=vd, vmid=vm, vp=vp_, vn=vn_, **extra), vx, tag='lv')
                    w = max(w, r['iop_mA']); wc = max(wc, r['i_clamp_mA'])
        worst[tag] = (w, wc)
    # normal range: the output at +/-1.15 V commanded and the opposite forced voltage of the 2.0 V level
    wn = 0.0
    for sgn in (1, -1):
        vd = 1.65 + sgn * vo_norm / GAIN_NOM
        r = fault(dict(Rs=Rmin, vdac=vd), -sgn * 2.0, tag='lv')
        wn = max(wn, r['iop_mA'])
    lev['sim'] = dict(worst, norm2V=wn)
    add('PR-4', f'stated level +/-{STATED_LEVEL} V (>= +/-1.5 V): derived 65 mA x {Rmin:.2f} ohm - {vo_win:.3f} V (worst commanded, DAC window end)', '>= 1.5 V and <= derived', f'{STATED_LEVEL} V <= {lev["level_win"]:.3f} V', f'{lev["level_win"]-STATED_LEVEL:+.3f} V', 1.5 <= STATED_LEVEL <= lev['level_win'])
    add('PR-4', f'forced +/-{STATED_LEVEL} V, DAC at either window end, 4 corners, resistor {Rmin:.2f} ohm: op-amp output current, clamp present', '<= 65 mA (ISC typ) *(check)*', f'{worst["clamp"][0]:.1f} mA (clamp {worst["clamp"][1]:.2f} mA)', f'{65-worst["clamp"][0]:+.1f} mA', worst['clamp'][0] <= 65)
    add('PR-4', f'same, clamp removed (the clamps not conducting)', '<= 65 mA (ISC typ) *(check)*', f'{worst["no clamp"][0]:.1f} mA', f'{65-worst["no clamp"][0]:+.1f} mA', worst['no clamp'][0] <= 65)
    add('PR-4', f'normal range: output at +/-1.15 V commanded, forced +/-2.0 V of the opposite sign: op-amp output current', '<= 65 mA (ISC typ) *(check)*', f'{wn:.1f} mA', f'{65-wn:+.1f} mA', wn <= 65)
    # clamp knee, the stack alone
    kn = {n: stack_knee(n) for n in (2, 3)}
    ik = {(n, x): stack_current(n, x) for n in (2, 3) for x in (1.0, 1.15, 1.38, 2.0, 2.1)}
    lev['knee'] = kn; lev['stack_I'] = {f'{n}/{x}': v for (n, x), v in ik.items()}
    add('PR-4/AW-8', '3-diode stack: voltage at which it carries 1 mA (model, recalled figures *(check)*)', '>= 2.1 V (AW-8 limit; above the level)', f'{kn[3]:.2f} V (2-diode stack {kn[2]:.2f} V)', f'{kn[3]-2.1:+.2f} V', kn[3] >= 2.1)
    add('AW-7', '3-diode stack: current at the op-amp output at 1.0 / 1.15 / 1.38 V', 'info', f'{ik[(3,1.0)]*1e6:.3f} / {ik[(3,1.15)]*1e6:.2f} / {ik[(3,1.38)]*1e6:.1f} uA', '', True)
    # accuracy: BNC voltage with the clamp against without it, over the DAC window, hi-Z and 50 ohm
    dmax = {}
    for ld in ('hiz', 'r50'):
        m = 0.0
        for vm, (vp_, vn_) in ((1.55, R_STRONG), (1.685, R_WEAK)):
            for vd in np.arange(0.578, 2.7711, 0.1):
                a = ng('cfx', build(P(vdac=float(vd), vmid=vm, vp=vp_, vn=vn_, load=ld), ".op\n"), vecs='v(bnc)')['v(bnc)'][0]
                b = ng('cfx', build(P(vdac=float(vd), vmid=vm, vp=vp_, vn=vn_, load=ld, clamp='none'), ".op\n"), vecs='v(bnc)')['v(bnc)'][0]
                m = max(m, abs(float(a - b)))
        dmax[ld] = m
    lev['clamp_error_mV'] = {k: v * 1e3 for k, v in dmax.items()}
    e = max(dmax.values())
    add('AW-7', 'output error caused by the clamp, DAC over its window, hi-Z and 50 ohm, 2 Vmid/rail corners', '<= 0.62 mV (one DAC code, AW-2; chosen allocation)', f'{e*1e3:.4f} mV', f'{0.62-e*1e3:+.3f} mV', e * 1e3 <= 0.62)
    return lev


def case_ext5():
    """The recommended circuit's full PR-4 / PR-3 / PR-2 grid (powered and unpowered, DAC driving and high-Z)."""
    res = {}
    for vx in ((5.0, -5.0, 1.8, -1.8) if BUFV else (5.0, -5.0)):
        res[f'powered/{vx:+g}'] = fault(dict(vdac=1.65), vx)
        res[f'unpowered/{vx:+g}'] = unpowered(dict(), vx)
        res[f'unpowered, DAC high-Z/{vx:+g}'] = unpowered(dict(rout=1e9), vx)
    OUT['ext5'] = res
    for k, v in res.items():
        if k.startswith('unpowered'):
            ok = -0.2 <= v['v_dac'] <= 3.45 and abs(v['v_rail_pos']) < 0.5 and abs(v['v_rail_neg']) < 0.5 and (abs(v['i_into_pos_rail_uA']) + abs(v['i_into_neg_rail_uA'])) <= 100
            if not BUFV:
                add('PR-4/PR-3/PR-2', f'recommended circuit, {k}: rails, current into rails, DAC pin', 'rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V',
                    f'rails {v["v_rail_pos"]*1e3:+.0f}/{v["v_rail_neg"]*1e3:+.0f} mV, into rails {v["i_into_pos_rail_uA"]:+.2f}/{v["i_into_neg_rail_uA"]:+.2f} uA, DAC pin {v["v_dac"]:+.2f} V, op-amp pins {v["pin_pos"]:+.2f}/{v["pin_neg"]:+.2f} V', '', ok)
            else:
                add('PR-4/PR-3/PR-2', f'buffered circuit, {k}: rails (incl. the buffer\'s +3.3 V_A), current into rails, DAC pin', 'rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V',
                    f'rails {v["v_rail_pos"]*1e3:+.0f}/{v["v_rail_neg"]*1e3:+.0f} mV, into rails {v["i_into_pos_rail_uA"]:+.2f}/{v["i_into_neg_rail_uA"]:+.2f} uA, DAC pin {v["v_dac"]:+.3f} V, '
                    f'buffer out/in {v["v_bo"]:+.2f}/{v["v_bin"]:+.3f} V, buffer pins {v["buf_pins"]:+.2f} V, op-amp pins {v["pin_pos"]:+.2f}/{v["pin_neg"]:+.2f} V', '', ok)
    return res


def buf_backfeed(vd, extra=None, tag='bf'):
    """AFE unpowered (rails 0, Vmid 0: its buffer is on +3.3 V_A too), the Due driving DAC0 at vd into the dead buffer through
    680 ohm.  ESD-only buffer (as the main op-amp is treated unpowered), optionally with a resistor across its supply pins."""
    q = P(**dict(dict(vdac=vd, vmid=0.0, vp=0, vn=0, iso=True, rp=1e9, rn=1e9, esd_only=True), **(extra or {})))
    r = ng(tag, build(q, ".op\n"), vecs='v(dac) v(bin) v(bo) v(bvcx) v(sp) v(vcc) v(vee) i(visb) i(visp) i(visn)')
    g = lambda k: float(r[k][0])
    return dict(vdac=vd, i_dac_uA=(g('v(dac)') - g('v(bin)')) / (extra or {}).get('Rbin', D['Rbin']) * 1e6, v_bin=g('v(bin)'), v_bo=g('v(bo)'), buf_pins=g('v(bvcx)'),
                v_sp=g('v(sp)'), v_vcc=g('v(vcc)'), v_vee=g('v(vee)'),
                i_into_rails_uA=abs(g('i(visb)')) * 1e6 * (g('i(visb)') < 0) + abs(g('i(visp)')) * 1e6 + abs(g('i(visn)')) * 1e6)


def case_sense():
    """The precision ADC's sense divider on the AWG output (sim/powercal owns it; 100k + 100k to Vmid or 3.0 V, 1 nA/V): the tap
    voltage the ADC input sees at AW-8's excursions and in PR-4's faults.  Information for powercal's input-protection check."""
    res = {}
    if not P().get('sense'):
        return res
    for ref, sres in (('vm', (200e3, 100e3)), ('3.0', (200e3, 100e3)), ('vm', (100e3, 200e3)), ('3.0', (100e3, 200e3))):
        w8 = []
        for vd in (0.0, 3.3):
            for vp_, vn_ in RAILS:
                r = ng('sns', build(P(vdac=vd, vp=vp_, vn=vn_, load='hiz', sense_ref=ref, sense_r=sres), ".op\n"), vecs='v(stp) v(bnc)')
                w8.append((float(r['v(bnc)'][0]), float(r['v(stp)'][0])))
        pr = {}
        for vx in (5.0, -5.0, 1.8, -1.8):
            for vd in (0.578, 2.771):
                r = ng('sns', build(P(**dict(dict(load='none', iso=True, vdac=vd, sense_ref=ref, sense_r=sres))), ".op\n", extra=f"Vx bnc 0 DC {vx}"), vecs='v(stp)')
                pr[f'powered/{vx:+g}/{vd}'] = float(r['v(stp)'][0])
            q = P(**dict(dict(load='none', iso=True, vp=0, vn=0, vmid=0, vdac=0, rp=1e9, rn=1e9, esd_only=True, sense_ref=ref, sense_r=sres)))
            r = ng('sns', build(q, ".op\n", extra=f"Vx bnc 0 DC {vx}"), vecs='v(stp)')
            pr[f'unpowered/{vx:+g}'] = float(r['v(stp)'][0])
        des = sres == (200e3, 100e3)
        res[f'{ref}/{sres[0]/1e3:g}k-{sres[1]/1e3:g}k'] = dict(aw8=w8, pr4=pr)
        t8 = [t for _, t in w8]
        lab = ('Vmid' if ref == 'vm' else '3.0 V') + ('; the design, k = 1/3: 200k BNC-tap, 100k tap-far end' if des else
                                                     '; comparison only, k = 2/3: 100k BNC-tap, 200k tap-far end')
        add('AW-8 info', f'sense-divider tap (far end at {lab}) at AW-8\'s DC excursions (DAC0 0 V / 3.3 V, rail corners): output {min(o for o, _ in w8):+.3f}..{max(o for o, _ in w8):+.3f} V',
            'info (the ADC input; powercal checks its limits)', f'tap {min(t8):+.3f}..{max(t8):+.3f} V', '', True)
        pv = {k: v for k, v in pr.items() if k.startswith('powered')}; uv = {k: v for k, v in pr.items() if k.startswith('unpowered')}
        add('PR-4 info', f'sense-divider tap (far end at {lab}), AWG output forced to +/-1.8 and +/-5 V: powered / unpowered',
            'info (the ADC input; powercal checks its limits)', f'powered {min(pv.values()):+.3f}..{max(pv.values()):+.3f} V; unpowered {min(uv.values()):+.3f}..{max(uv.values()):+.3f} V', '', True)
    OUT['sense'] = res
    return res


TSYM = 28 * 2 / 90e6      # one symbol at 1.6 Msym/s (DAC RC 28 at 90 MHz), 622.2 ns
DAC_SLEW = 6.0e6          # V/s: the DAC's measured slew, about 6 V/us (sim/loop's fit to linux-x1's edges, docs/ets-mode.md)


def pam_settle(rout, ld, v1, v2, p=None, tag='pam'):
    """A PAM step from v1 to v2 at the DAC's slew; the AWG output's error against the ideal (the DAC waveform times the stage's
    DC gain) at the symbol's centre (0.5 T) and worst over the middle fifth (0.4-0.6 T), in output codes."""
    t0 = 0.5e-6; edge = abs(v2 - v1) / DAC_SLEW
    pwl = f"0 {v1} {t0} {v1} {t0+edge} {v2} 10u {v2}"
    node = 'far' if ld.startswith('cable') else 'bnc'; td = 5e-9 if node == 'far' else 0.0
    q = dict(dict(dac_pwl=pwl, vdac=v1, rout=rout, load=ld), **(p or {}))
    r = ng(tag, build(P(**q), f".tran 0.25n {t0 + 1.6e-6}\n"), vecs=f'v({node})')
    tm = r['time'].real; v = r[f'v({node})'].real
    a0 = float(np.interp(t0 - 20e-9, tm, v)); a1 = float(np.interp(tm[-1] - 20e-9, tm, v))
    g = (a1 - a0) / (v2 - v1)
    # a constant delay only shifts the fold's time axis, so the stage's own delay (at the 50 % crossing) is taken out
    n_ = (v - a0) / (a1 - a0); k_ = np.where((tm > t0) & (n_ >= 0.5))[0][0]
    td = float(tm[k_] - (t0 + 0.5 * edge))
    ideal = lambda t: a0 + (a1 - a0) * np.clip((t - td - t0) / edge, 0, 1)
    lsb = abs(g) * (2.771 - 0.578) / 4095
    e = lambda t: abs(float(np.interp(t, tm, v)) - float(ideal(t))) / lsb
    win = np.linspace(t0 + 0.4 * TSYM, t0 + 0.6 * TSYM, 41)
    return dict(centre=e(t0 + 0.5 * TSYM), window=max(e(t) for t in win), lsb_mV=lsb * 1e3, gain=g, delay_ns=td * 1e9)


def pam_baseline(rout, v1, v2, tag='pamb'):
    """DAC0 alone into the Due's ADC input (sim/loop's sample-and-hold model: 2 pF pin, 3.8 kohm, 6 pF, tracking), its
    6 V/us ramp: the error against the DAC waveform at the symbol centre in DAC codes, the delay taken out as for the AWG."""
    t0 = 0.5e-6; edge = abs(v2 - v1) / DAC_SLEW
    t = (f"* DAC0 into the ADC model\nVd a 0 DC {v1} PWL(0 {v1} {t0} {v1} {t0+edge} {v2} 10u {v2})\nRo a pin {max(rout, 1e-3)}\n"
         f"Cp pin 0 2p\nRon pin cs 3.8k\nCs cs 0 6p\n.tran 0.25n {t0 + 1.6e-6}\n")
    r = ng(tag, t, vecs='v(cs)'); tm = r['time'].real; v = r['v(cs)'].real
    n_ = (v - v1) / (v2 - v1); k_ = np.where((tm > t0) & (n_ >= 0.5))[0][0]; td = float(tm[k_] - (t0 + 0.5 * edge))
    ideal = lambda x: v1 + (v2 - v1) * np.clip((x - td - t0) / edge, 0, 1)
    lsb = (2.771 - 0.578) / 4095
    return dict(centre=abs(float(np.interp(t0 + 0.5 * TSYM, tm, v)) - float(ideal(t0 + 0.5 * TSYM))) / lsb, delay_ns=td * 1e9)


def case_pam():
    """AW-3: the 1.6 Msym/s patterns are not shaped: a PAM16 step (1.5 V swing at the DAC) must settle at the AWG output to
    within 1 code of the DAC waveform at the symbol's sampling point, over DAC0's unknown output impedance 0-1 kohm."""
    res = {}
    steps = (('full 0.9 -> 2.4 V', 0.9, 2.4), ('full 2.4 -> 0.9 V', 2.4, 0.9), ('one level 1.6 -> 1.7 V', 1.6, 1.7))
    for ro in (0.0, 100.0, 300.0, 1000.0):
        for ld in ('hiz', 'cable_scope'):
            for lab, v1, v2 in steps:
                res[f'{ro:g}/{ld}/{lab}'] = pam_settle(ro, ld, v1, v2)
    OUT['pam'] = res
    for ro in (0.0, 100.0, 300.0, 1000.0):
        sub = {k: v for k, v in res.items() if k.startswith(f'{ro:g}/')}
        wc = max(v['centre'] for v in sub.values()); ww = max(v['window'] for v in sub.values())
        bl = {lab: pam_baseline(ro, v1, v2)['centre'] for lab, v1, v2 in steps}
        res[f'baseline/{ro:g}'] = bl
        one = max(v['centre'] for k, v in sub.items() if 'one level' in k)
        # information (owner, 2026-11-11: SM-5 dropped; AW-3 sets no settling limit)
        add('AW-3 info', f'PAM16 step at 1.6 Msym/s (1.5 V at the DAC, 6 V/us), DAC0 output impedance {ro:g} ohm, high-Z and 1 m cable to a scope: '
            f'AFE-added error against the DAC waveform at the symbol centre, full-scale / one-level step', 'info (AW-3 sets no settling limit)',
            f'{wc:.2f} / {one:.2f} codes', '', True)
        add('AW-3 info', f'baseline, DAC0 alone into the ADC model (2 pF, 3.8 kohm, 6 pF), output impedance {ro:g} ohm: error at the symbol centre, full-scale / one-level step',
            'info (DAC codes)', f"{max(bl[k] for k in bl if 'full' in k):.2f} / {bl['one level 1.6 -> 1.7 V']:.2f} codes", '', True)
    return res


def case_vmidbuf():
    """What the AWG's Vmid follower must do, so a cheaper part (half of a dual) can be chosen: a behavioural follower of GBW
    1-50 MHz (A0 1e5, 50 ohm open-loop output resistance, 20 mA limit) in place of the OPA365, against the rows it touches."""
    res = {}
    for gbw in (1e6, 3e6, 10e6, 50e6):
        ex = dict(vm_beh=(gbw, 50.0, 20e-3))
        f, h = ac_resp(P(load='hiz', **ex), tag='vb'); bwh = bw_stats(f, h)
        f, h5 = ac_resp(P(load='r50', **ex), tag='vb'); bw5 = bw_stats(f, h5)
        pm = phase_margin(P(**ex), tag='vbpm')['pm']
        pam = max(pam_settle(0.0, ld, a, b, ex, 'vbp')['centre'] for ld in ('hiz',) for a, b in ((0.9, 2.4), (2.4, 0.9)))
        isink = 0.0
        for vd in (0.0, 0.578, 2.771, 3.3):
            r = ng('vbop', build(P(vdac=vd, load='short', **ex), ".op\n"), vecs='i(vvmac)')
            isink = max(isink, abs(float(r['i(vvmac)'][0])))
        res[f'{gbw/1e6:g}MHz'] = dict(bw_hiz=bwh['f3db'], peak=bwh['peak_db'], bw_r50=bw5['f3db'], pm=pm, pam=pam, i_mA=isink * 1e3)
    OUT['vmidbuf'] = res
    for k, v in res.items():
        add('AW info', f'AWG Vmid follower as a {k} GBW part (behavioural): AW-3 bandwidth hi-Z / 50 ohm (peaking); AN-1 of the gain stage; PAM step at the centre; '
            f'its worst output current (AWG shorted, DAC0 0 / 0.578 / 2.771 / 3.3 V)', 'info (8 MHz, 45 deg, 1 code)',
            f"{v['bw_hiz']/1e6:.1f} / {v['bw_r50']/1e6:.1f} MHz ({v['peak']:.2f} dB); {v['pm']:.1f} deg; {v['pam']:.2f} codes; {v['i_mA']:.2f} mA", '', True)
    return res


def case_unpowered():
    if BUFV:
        return case_unpowered_buf()
    res = {}
    for vd in (0.578, 1.65, 2.771):
        t = build(P(vdac=vd, vmid=1.65, vp=0, vn=0, iso=True, rp=1e9, rn=1e9, esd_only=True), ".op\n")
        r = ng('unp', t, vecs='v(vp) v(dac) v(out) v(vccx) v(veex) i(visp) i(visn)')
        g = lambda k: float(r[k][0])
        i_dac = (g('v(dac)') - g('v(vp)')) / D['Ra']
        res[str(vd)] = dict(vdac=vd, v_vplus=g('v(vp)'), i_dac_uA=i_dac * 1e6, v_out=g('v(out)'))
    OUT['unpowered'] = res
    w = max(abs(v['i_dac_uA']) for v in res.values())
    add('PR-2/AN-3', 'AFE rails off, Due drives DAC0 over its window: DAC pin voltage', '-0.2..3.45 V', 'the Due drives the pin: 0.578..2.771 V', '', True, 'pin is held by the DAC, the AFE only loads it')
    add('AN-3/AW-5', 'AFE rails off, DAC0 over its window: current drawn from the DAC pin (clamp conduction)', 'info (0.1 mA is the powered limit)', f'{w:.0f} uA', f'{100-w:+.0f} uA', True, 'informational')
    return res


def case_unpowered_buf():
    """PR-2, PR-3, AN-3 for the buffered variant with the AFE unpowered: DAC0 driving the dead buffer through 680 ohm."""
    res = {}
    vds = (0.578, 1.65, 2.771, 3.3)          # the window and the reset level (afe.md 4.1)
    res['esd'] = {str(vd): buf_backfeed(vd) for vd in vds}
    w = max(abs(v['i_dac_uA']) for v in res['esd'].values())
    rl = max(max(abs(v['v_sp']), abs(v['v_vcc']), abs(v['v_vee'])) for v in res['esd'].values())
    ir = max(v['i_into_rails_uA'] for v in res['esd'].values())
    bp = max(v['buf_pins'] for v in res['esd'].values())
    add('PR-2/AN-3', 'AFE rails off, Due drives DAC0 0.578..3.3 V: DAC pin voltage', '-0.2..3.45 V', 'the Due drives the pin: 0.578..3.3 V', '', True, 'pin held by the DAC; the AFE loads it')
    add('AN-3/AW-5', 'AFE rails off, DAC0 0.578..3.3 V into the dead buffer (ESD diodes only) through 680 ohm: current from the DAC pin', '<= 0.1 mA (AW-5\'s value; the datasheet gives none)',
        f'{w:.1f} uA (buffer supply pin charged to {bp:.2f} V)', f'{100-w:+.1f} uA', w <= 100)
    add('PR-3', 'same: AFE rails (+3.3 V_A, + and - op-amp rails) and current into them through the Schottkys', 'rails < 0.5 V, <= 100 uA',
        f'{rl*1e3:.1f} mV, {ir:.3f} uA', f'{0.5-rl:+.3f} V', rl < 0.5 and ir <= 100)
    # bounds the ESD-only model cannot exclude: a dead CMOS op-amp whose supply pin is lifted through its input diode can draw
    # current (phantom powering).  Its datasheet does not say; a resistor across its supply pins bounds it: 440 ohm is 5 mA at
    # 2.2 V (its quiescent maximum at its minimum supply), 1 ohm the hard limit set by the 680 ohm alone.
    for bq in (440.0, 1.0):
        bb = {str(vd): buf_backfeed(vd, dict(bq=bq), tag='bfq') for vd in vds}
        res[f'bq{bq:g}'] = bb
        wb = max(abs(v['i_dac_uA']) for v in bb.values())
        add('AN-3 info', f'bound: the dead buffer drawing current as {bq:g} ohm across its supply pins, DAC0 0.578..3.3 V: current from the DAC pin',
            'info (0.1 mA is AW-5\'s powered value)', f'{wb/1e3:.2f} mA (supply pin {max(v["buf_pins"] for v in bb.values()):.2f} V)', f'{100-wb:+.0f} uA', True,
            'phantom powering is not in any model here *(check, VT-5)*')
    # the series resistor's trade: back-feed bound against bandwidth, Rbin 680 / 1k / 2 x 680 (types in the BOM), with and without
    # 4 pF more at the buffer input (about 6 pF in all with the model's own input capacitance)
    tr = {}
    for rb in (680.0, 1000.0, 1360.0):
        d_ = dict(Rbin=rb)
        i1 = max(abs(buf_backfeed(vd, dict(d_, bq=1.0), tag='bft')['i_dac_uA']) for vd in (2.771, 3.3))
        i4 = max(abs(buf_backfeed(vd, dict(d_, bq=440.0), tag='bft')['i_dac_uA']) for vd in (2.771, 3.3))
        bw = {}
        for cb in (0.0, 4e-12):
            for ld in ('hiz', 'r50'):
                f, h = ac_resp(P(Rbin=rb, Cbin=cb, load=ld), tag='bft'); bw[f'{cb*1e12:g}pF/{ld}'] = bw_stats(f, h)['f3db']
        g = dc_mc(3.2, 'B', n=5000, p=d_)
        tr[f'{rb:g}'] = dict(i_short_mA=i1 / 1e3, i_440_mA=i4 / 1e3, bw=bw, gain_min=float(g['gain'].min()))
    res['rbin_trade'] = tr
    add('AN-3 info', 'trade, DAC0 at 2.771 / 3.3 V into a dead buffer modelled as a short (as 440 ohm) across its supply: Rbin 680 / 1k / 1360',
        'info (0.1 mA AW-5; bandwidth >= 8 MHz AW-3)',
        ' / '.join(f'{v["i_short_mA"]:.2f} ({v["i_440_mA"]:.2f}) mA' for v in tr.values()) + '; BW 50 ohm, +4 pF at the input: '
        + ' / '.join(f'{v["bw"]["4pF/r50"]/1e6:.1f}' for v in tr.values()) + ' MHz; hi-Z '
        + ' / '.join(f'{v["bw"]["4pF/hiz"]/1e6:.1f}' for v in tr.values()) + ' MHz', '', True)
    OUT['unpowered'] = res
    return res


# --------------------------------------------------------------- model validation
def case_models():
    res = {}
    # 1. noise of each op-amp model against its datasheet density (models/datasheet-facts.md)
    chk = {'OPA365': (1e5, 4.5), 'OPA354': (1e6, 6.5)}
    for op, (fx, ds) in chk.items():
        t = (f".include {MODELS[op]}\nVp vcc 0 2.5\nVn vee 0 -2.5\nVi vp 0 DC 0 AC 1\nX1 vp out vcc vee out {op}\nRl out 0 10k\n"
             ".noise v(out) Vi dec 20 1 10Meg\n")
        r = ng('val', t, plot='noise1')
        f = r['frequency'].real; d = r['onoise_spectrum'].real
        sim = float(np.interp(fx, f, d)) * 1e9
        res[f'{op}_noise'] = dict(f=fx, sim_nV=sim, datasheet_nV=ds)
        add('model', f'{op} model input noise density at {fx/1e3:g} kHz vs datasheet', f'{ds} nV/rtHz +/-15 %', f'{sim:.2f} nV/rtHz', f'{(0.15-abs(sim/ds-1))*100:+.0f} %', abs(sim / ds - 1) <= 0.15)
    # 2. input capacitance at V+: follower with 100 kohm source, pole -> C
    t = (f".include {MODELS['OPA365']}\nVp vcc 0 3.3\nVn vee 0 {VN}\nVi in 0 DC 0.5 AC 1\nRi in vp 100k\n"
         "X1 vp out vcc vee out OPA365\n.ac dec 100 1k 1G\n")
    r = ng('cin', t, vecs='v(out)')
    f = r['frequency'].real; g = np.abs(r['v(out)'])
    f3 = float(f[np.where(g < g[0] / np.sqrt(2))[0][0]])
    res['OPA365_cin_pF'] = 1 / (2 * np.pi * 100e3 * f3) * 1e12
    # 3. loop-gain method against the closed loop: |CL| from V+ to out must equal |T/(1+T)| / |beta|
    p = P()
    pm = phase_margin(p, tag='lgchk')
    t = build(p, ".ac dec 100 1k 2G\n", ac=('vos',))
    r = ng('clchk', t, vecs='v(out) v(vp)')
    f = r['frequency'].real; cl = np.abs(r['v(out)'] / r['v(vp)'])   # out / the pin's own voltage, independent of the source network
    Tf, T = pm['f'], pm['T']
    d = dict(D); d.update(p)
    zf = 1 / (1 / d['Rf'] + 1j * 2 * np.pi * Tf * d['Cf'])
    zg = 1 / (1 / d['Rg'] + 1j * 2 * np.pi * Tf * (d['Cpar_n'] + d.get('Cin_n', 5.4e-12)))
    beta = zg / (zf + zg)
    pred = np.abs(T / (1 + T) / beta)
    sel = (Tf > 1e4) & (Tf < 5e7)
    err = float(np.max(np.abs(np.interp(Tf[sel], f, cl) / pred[sel] - 1)))
    res['loopgain_vs_closedloop_maxerr'] = err
    add('model', 'loop-gain setup: |T/(1+T)/beta| against the simulated closed loop, 10 kHz-30 MHz', 'agree within 10 %', f'{err*100:.1f} %', f'{(0.10-err)*100:+.1f} %', err <= 0.10)
    OUT['models'] = res
    return res


# --------------------------------------------------------------- guards: break the target, watch the check fail
def ring_ideal(rs):
    t = (".include models/awg_behavioural.lib\nVs a 0 PWL(0 0 10n 0 12n 1 5u 1)\n"
         f"Rs a b {rs}\nT1 b 0 far 0 Z0=50 TD=5n\nRl far 0 1G\n.tran 0.1n 300n\n")
    r = ng('ideal_edge', t, vecs='v(far)')
    v = r['v(far)'].real; tt = r['time'].real; late = v[tt > 60e-9]
    return float((late.max() - late.min()) / v[-1])


def case_guards():
    G = []
    def guard(name, target, fn, broken, restored, desc):
        vb, okb = fn(broken); vr, okr = fn(restored)
        good = (not okb) and okr
        G.append(dict(name=name, target=target, broken=desc, value_broken=vb, check_when_broken='FAIL' if not okb else 'PASS (guard is blind)',
                      value_restored=vr, check_when_restored='PASS' if okr else 'FAIL', guard_ok=good))
        add('guard', f'{name}: {target}', 'fails broken, passes restored', f'broken: {vb}; restored: {vr}', '', good)

    def f_off(kw):
        ex = dict(vmid=1.65 + kw['err'])
        if D.get('vm_div'):   # the AWG's own Vmid: move its divider ratio by the same voltage at a 3.3 V rail
            rt, rb, ct = D['vm_div']; k_ = (1.65 + kw['err']) / 3.3; ex = dict(vm_div=(rt, rt * k_ / (1 - k_), ct))
        t = build(P(vdac=1.65, **ex), ".op\n"); r = ng('g', t, vecs='v(bnc)'); v = float(r['v(bnc)'][0])
        return f'{v*1e3:+.1f} mV', abs(v) <= 0.060
    guard('wrong Vmid', 'AW-7 offset check (limit 60 mV)', f_off, dict(err=0.070), dict(err=0.0), 'Vmid 70 mV off the DAC window centre')

    def f_bw(kw):
        f, h = ac_resp(P(**kw), tag='g'); b = bw_stats(f, h)['f3db']; return f'{b/1e6:.1f} MHz', b >= 8e6
    guard('slow stage', 'AW-3 bandwidth check (8 MHz)', f_bw, dict(Cf=100e-12), dict(), 'Cf 100 pF instead of none')

    def f_ring(kw):
        v = ring_ideal(kw['rs']); return f'{v*100:.0f} % ring', v <= 0.02
    guard('50 ohm removed', 'AW-4 reflection check, 1 m open cable', f_ring, dict(rs=0.001), dict(rs=49.9), 'Rs = 1 mohm instead of 49.9 ohm')

    def f_boot(kw):
        t = build(P(vdac=3.3, vmid=1.55, vp=3.37, vn=R_STRONG[1], load='open', **kw), ".op\n"); r = ng('g', t, vecs='v(bnc)'); v = float(r['v(bnc)'][0])
        return f'{v:+.3f} V', abs(v) <= 2.1
    if BUFV:   # the top of AW-8 is now the buffer's swing times the slope: raise the slope (Rb = Rf, so the zero stays at Vmid)
        guard('slope raised', 'AW-8 DAC0-at-3.3 V output check (2.1 V)', f_boot, dict(Rb=1.4 * RB_BUF, Rf=1.4 * RB_BUF, clamp='none'), dict(),
              'Rb = Rf = 1.4 x 1099.5 ohm (slope 1.62) and no clamp')
    else:
        guard('rails raised', 'AW-8 DAC0-at-3.3 V output check (2.1 V)', f_boot, dict(Rf=(800.0 if LOWV else 500.0), clamp='none'), dict(),
              f'Rf {(800 if LOWV else 500)} ohm and no clamp')

    def f_i(kw):
        m = dc_mc(3.3, 'A', n=5000, p=kw); i = float(max(np.abs(m['i_top']).max(), np.abs(m['i_bot']).max()))
        return f'{i*1e6:.0f} uA', i <= 100e-6
    if BUFV:
        guard('buffer bias resistor too small', 'AW-5 DAC-load check (0.1 mA)', f_i, dict(Rbpl=10e3), dict(), 'Rbpl 10 k instead of 330 k')
    else:
        guard('Ra too small', 'AW-5 DAC-load check (0.1 mA)', f_i, dict(Ra=(6e3 if LOWV else 9.09e3)), dict(), f'Ra = {(6 if LOWV else 9.09)} k')

    def f_noise(kw):
        n = noise_split(P(**kw), tag='g')['total_uV']; return f'{n:.0f} uV', n <= 100
    if BUFV:   # Cf 12 pF across Rf x 40 would band-limit the noise it adds: scale Cf down by the same 40 (same corner)
        guard('noisy resistors', 'AW-6 noise check (100 uV)', f_noise, dict(Rf=40 * D['Rf'], Rg=40 * D['Rg'], Cf=D['Cf'] / 40), dict(), 'Rf/Rg x40 and Cf / 40 (same gain, same Rf.Cf)')
    else:
        guard('noisy resistors', 'AW-6 noise check (100 uV)', f_noise, dict(Rf=40 * D['Rf'], Rg=40 * D['Rg']), dict(), 'Rf/Rg x40 (same gain)')

    def f_pm(kw):
        q = pm = phase_margin(P(**kw), tag='g')['pm']; return f'{pm:.0f} deg', pm >= 45
    guard('no feedback capacitor', 'AN-1 phase-margin check (45 deg)', f_pm, dict(Rf=20 * D['Rf'], Rg=20 * D['Rg'], Cpar_n=6e-12, Cf=0.0), dict(),
          'Rf/Rg x20, 6 pF at the inverting node and Cf = 0 (the design has Cf 12 pF)' if BUFV else 'Rf/Rg x20 and 6 pF at the inverting node (Cf = 0 in both)')

    def f_sh(kw):
        t = build(P(load='short', vdac=1.65 + 1.0 / GAIN_NOM, **kw), ".op\n"); r = ng('g', t, vecs='v(out)')
        i = abs(float(r['v(out)'][0])) / (kw.get('Rs', P()['Rs']) + kw.get('R2', P()['R2'])) * 1e3
        return f'{i:.0f} mA', i <= 20.5
    guard('Rs removed (short)', 'PW-3 short-current check (20 mA)', f_sh, dict(Rs=0.5, R2=0.5), dict(), 'both series resistors 0.5 ohm')
    def f_lev(kw):
        a = [fault(dict(kw, vdac=vd, Rs=kw.get('Rs', P()['Rs'] * (1 - RTOL))), vx, tag='g') for vd in (0.578, 2.771) for vx in (STATED_LEVEL, -STATED_LEVEL)]
        i = max(x['iop_mA'] for x in a); return f'{i:.0f} mA', i <= 65
    guard('series resistor 24.9 ohm', 'PR-4 level check: op-amp current at the stated +/-1.8 V (65 mA)', f_lev, dict(Rs=24.9), dict(), 'one 24.9 ohm instead of 49.9 ohm')

    def f_knee(kw):
        k = stack_knee(kw['n']); return f'{k:.2f} V', k >= 2.1
    def f_swing(kw):
        e = max(swing_err(kw, 'hiz', 1.65, 3.3, kw.get('vn', VN), sg)[1] for sg in (1, -1))
        return f'{e*1e3:.1f} mV', e * 1e3 <= 0.62
    if BUFV:   # the 2.05 kohm feedback network loads the output less, so -1.5 V still swings; break the rail further
        guard('negative rail at -1.2 V', 'AW-1 circuit-swing check into high-Z (one code)', f_swing, dict(vn=-1.2), dict(), f'LM27762 negative rail -1.2 V instead of {VN:.3f} V')
    else:
        guard('negative rail at -1.5 V', 'AW-1 circuit-swing check into high-Z (one code)', f_swing, dict(vn=-1.5), dict(), f'LM27762 negative rail -1.5 V instead of {VN:.3f} V')

    def f_swing50(kw):
        vp_, vn = kw['weak']                       # the weak rail corner, as case_swing uses it
        e = max(swing_err({}, 'r50', vm, vp_, vn, -1)[1] for vm in (1.55, 1.685))
        return f'{e*1e3:.2f} mV at {vn:+.3f} V', e * 1e3 <= 0.62
    guard('negative rail back at -1.8 V', 'AW-1 circuit-swing check into 50 ohm, datasheet weak rail corner (one code)', f_swing50,
          dict(weak=ds_rails(47.5e3, 100e3)[0]), dict(weak=R_DS_WEAK),
          f'LM27762 OUT- -1.8 V (47.5k / 100k) instead of {VN:.3f} V (768k||330k / 330k), both at the datasheet weak corner')
    if False:   # with the BAT54S model both designs pass the 50 ohm row at the blanket corner, so the pass no longer rests on the basis
      guard('blanket 5 % weak corner', 'AW-1 circuit-swing check into 50 ohm: the weak-corner basis (one code)', f_swing50,
          dict(weak=RAILS[1]), dict(weak=R_DS_WEAK),
          f'weak corner at 95 % of the {VN:.3f} V setting and +3.23 V (the old basis) instead of the datasheet corner')

    def f_bare(kw):
        (_, _), (vp_, vn_) = ds_rails(kw['r3'], kw['r4']); s = vp_ - vn_
        return f'{s:.3f} V', s < 5.5
    guard('negative rail back at -2.156 V', 'abs-max check: bare rails at the datasheet maxima (5.5 V)', f_bare,
          dict(r3=330e3 * 100e3 / 430e3, r4=100e3), dict(r3=R3_N, r4=R4_N), 'LM27762 OUT- divider 330k||100k / 100k (-2.156 V) instead of 768k||330k / 330k')

    def f_comp(kw):
        o = max(cable_ov_corners(kw).values()); return f'{o*100:.1f} %', o <= 0.05
    if BUFV:   # no Ca/Cb in the design: a 100 pF Ca across the 953 ohm Ra over-compensates the 510 ohm attenuator
        guard('over-compensated attenuator', 'AW-4 cable overshoot check over the V+ parasitic corners (5 %)', f_comp, dict(Ca=100e-12), dict(),
              'Ca 100 pF across Ra instead of none')
    else:
        guard('over-compensated attenuator', 'AW-4 cable overshoot check over the V+ parasitic corners (5 %)', f_comp, dict(Ca=33e-12, Cb=22e-12), dict(),
              'Ca 33 pF / Cb 22 pF (flat at 1.5 pF, over-compensated at 0.5 pF) instead of 20 / 12 pF')

    guard('clamp stack of 2', 'PR-4/AW-8 clamp-knee check (1 mA at >= 2.1 V)', f_knee, dict(n=2), dict(n=3), '2 diodes per stack instead of 3')

    def f_side(kw):
        r = [fault(dict(kw), x, tag='g') for x in (5.0, -5.0)]
        p = max(a['p_clamp_W'] for a in r) / 3 * 1e3
        return f'{p:.0f} mW per diode', p <= BAV99_PKG_W * 1e3
    guard('clamp on the load side', 'PR-4 clamp power check (250 mW per diode at +/-5 V)', f_side, dict(clamp='gnd3', cat='bnc', vdac=0.578), dict(vdac=0.578), 'the stacks on the BNC side of the resistor')

    def f_iso(kw):
        v = [unpowered(kw, x) for x in (5.0, -5.0)]
        w = max(max(abs(a['v_rail_pos']), abs(a['v_rail_neg'])) for a in v)
        return f'{w*1e3:.0f} mV', w < 0.5
    guard('supply-pin Schottkys removed', 'PR-3 unpowered rails < 0.5 V check, +/-5 V on the BNC', f_iso, dict(iso=False), dict(iso=True), 'op-amp pins wired straight to the rails')

    def f_clamp(kw):
        r = [fault(dict(kw), x, tag='g') for x in (5.0, -5.0)]
        pins = max(a['vpins'] for a in r)
        return f'{pins:.2f} V', pins < 4.5
    guard('clamps to the op-amp rails', 'PR-4 op-amp pin-to-pin margin check (< 4.5 V, 1 V under abs max)', f_clamp, dict(clamp='rails', cat='bnc', vdac=0.578), dict(vdac=0.578), 'Schottkys from the BNC to the op-amp rails instead of the ground stacks')
    def f_ldo(kw):
        # the ripple source alone on the LDO's 2.2 uF (20 mohm): must read the datasheet's 5 mV at 2 MHz (Fig 5-1's condition)
        a_ = LDO_RIP_A1 * kcal_ldo(2e6) if kw['cal'] else LDO_RIP_A1
        zs = f"Rs a b {LDO_ZS_R}\nLs b c {LDO_ZS_L}" if kw['cal'] else "Rs a c 0.2"   # broken: the old 5 mV behind 0.2 ohm
        # small-signal at 2 MHz: a transient would carry the 0.8 uH / 2.2 uF resonance (120 kHz) the source excites at t = 0
        t = f"* LM27762 ripple calibration\nVr a 0 DC 0 AC {a_}\n{zs}\nCl c d {LDO_C}\nRl d 0 {LDO_C_ESR}\n.ac lin 1 2Meg 2Meg\n"
        r = ng('g', t, vecs='v(c)'); amp = float(abs(r['v(c)'][0]))
        return f'{amp*1e3:.3f} mV', abs(amp / LDO_RIP_A1 - 1) <= 0.03
    guard('ripple source uncalibrated', 'LM27762 ripple calibration: the source reads 5 mV +/-3 % on the LDO 2.2 uF alone at 2 MHz', f_ldo,
          dict(cal=False), dict(cal=True), "sim/awg's earlier source: 5 mV behind 0.2 ohm, no inductance")
    if BUFV:
        guards_buf(guard)
    guards_vmid(guard)
    OUT['guards'] = G
    return G


def guards_vmid(guard):
    """The two start-up checks: the design is their broken arm when Vmid lags, so these show each check can also pass."""
    def f_st(kw):
        q = P(**dict(dict(ramp=(0, 0, 10e-6), vp=3.37, vn=R_STRONG[1], ripple=rip_tr(), rout=0.001, vdac=3.3, vmid=1.55, load='hiz'), **kw))
        b = ng('g', build(q, ".tran 0.2u 2.2m\n"), vecs='v(bnc)')['v(bnc)'].real
        w = float(np.abs(b).max()); return f'{w:.3f} V', w <= 2.1
    if D.get('vm_div'):
        rt, rb, ct = D['vm_div']
        guard('AWG Vmid tap slowed (start-up)', 'AW-8 start-up check, worst arm (simultaneous 10 us, DAC0 3.3 V)', f_st,
              dict(vm_div=(rt, rb, 100e-9)), dict(), f'100 nF at the AWG Vmid tap instead of {ct*1e12:g} pF')
        def f_pu2(kw):
            q = P(**dict(dict(ramp=(0, 0, 20e-6), vp=3.37, vn=R_STRONG[1], dac_pwl='0 3.3 1.4 0.0', vdac=3.3, load='hiz'), **kw))
            b = ng('g', build(q, ".tran 2u 60m 0 5u\n"), vecs='v(bnc)')['v(bnc)'].real; w = float(np.abs(b).max())
            return f'{w:.3f} V', w <= 2.1
        guard('AWG Vmid tap slowed (power-up)', 'AW-8 power-up check (20 us soft-start, DAC0 reset trace)', f_pu2,
              dict(vm_div=(rt, rb, 100e-9)), dict(), f'100 nF at the AWG Vmid tap instead of {ct*1e12:g} pF')
        return
    guard('Vmid lagging the + rail (the check can pass)', 'AW-8 start-up check, its worst arm (simultaneous 10 us, DAC0 3.3 V, 1.55 V)', f_st,
          dict(vm_ramp=(0, 10e-6)), dict(vm_ramp=None), 'Vmid rising with the + rail behind 1 ohm and 10 uF, against Vmid present from t = 0; the design is the broken arm')

    def f_pu(kw):
        q = P(ramp=(0, 0, 1e-3), vp=3.37, vn=R_STRONG[1], dac_pwl='0 3.3 1.4 0.0 3 0.0', vdac=3.3, vmid=1.55, vm_tau=kw['tau'], load='hiz')
        b = ng('g', build(q, ".tran 1m 3 0 1m\n"), vecs='v(bnc)')['v(bnc)'].real; w = float(np.abs(b).max())
        return f'{w:.3f} V', w <= 2.1
    guard('Vmid slow at power-up (the check can pass)', 'AW-8 power-up check, reset-trace arm (2.1 V)', f_pu, dict(tau=1.65), dict(tau=1e-4),
          'Vmid tau 1.65 s (the PW-7 divider) against 0.1 ms; here the design is the broken arm, so this shows the check can pass')



def guards_buf(guard):
    """The buffered variant's new checks, each broken on purpose."""
    def f_pam(kw):
        e = pam_settle(0.0, 'hiz', 1.6, 1.7, kw, 'g')['centre']; return f'{e:.2f} codes', e <= 1
    guard('slow stage (PAM)', 'AW-3 information: the one-level PAM step settles to 1 code at the symbol centre', f_pam, dict(Cf=100e-12), dict(), 'Cf 100 pF')
    def f_reg(kw):
        e = max(swing_err(dict(rp=kw['r'], rn=kw['r']), 'r50', 1.6, 3.235, -2.038, sg)[1] for sg in (1, -1))
        return f'{e*1e3:.2f} mV', e * 1e3 <= 0.62
    guard('rail load regulation 200 uV/mA', 'AW-1 50 ohm check at the datasheet load regulation (one code)', f_reg, dict(r=0.2), dict(r=0.034),
          'the model rails (0.2 ohm) instead of 34 uV/mA')

    def f_bpm(kw):
        w = buf_pm_worst(kw['c'], extra=dict(inj=None, Rsh=0.0, Rinj=0.0) if kw['c'] > 100e-12 else None, tag='g')['pm']; return f'{w:.1f} deg', w >= 45
    guard('1 nF on the buffer output (known unstable)', 'AN-1 DAC0-buffer phase-margin check (45 deg), the loop break', f_bpm, dict(c=1e-9), dict(c=10e-12),
          '1 nF straight on the buffer output instead of the 10 pF trace (the datasheet puts unity-gain stability at about 1 nF)')

    def f_716(kw):
        o = [follower_alone(c * 1e-12, tag='g')['overshoot'] * 100 for c in kw['cl']]
        d = min(abs(v - DS_716) for v in o); return ' / '.join(f'{v:.1f}' for v in o) + ' %', d <= 5
    guard('wrong load against Fig 7-16', 'model-vs-datasheet check (overshoot within 5 points of 13 %)', f_716, dict(cl=(100.0, 200.0, 300.0)), dict(cl=(0.0, 10.0, 20.0)),
          'the model read at 100 / 200 / 300 pF instead of 0 / 10 / 20 pF')

    def f_cl(kw):
        nb = dict(inj=None, Rsh=0.0, Rinj=0.0)
        pm = phase_margin_buf(dict(Cbo=kw['ct'], **nb), tag='g')
        r = ng('g', build(P(Cbo=kw['cc'], **nb), ".ac dec 200 1k 2G\n", ac=('dac',)), vecs='v(bo) v(bin)')
        f = r['frequency'].real; cl = np.abs(r['v(bo)'] / r['v(bin)']); pred = np.abs(pm['T'] / (1 + pm['T']))
        sel = (pm['f'] > 1e4) & (pm['f'] < 3e7); e = float(np.max(np.abs(np.interp(pm['f'][sel], f, cl) / pred[sel] - 1)))
        return f'{e*100:.1f} %', e <= 0.10
    guard('loop break on the wrong load', 'buffer loop-break self-check (10 %)', f_cl, dict(ct=10e-12, cc=52e-12), dict(ct=52e-12, cc=52e-12),
          'T taken at 10 pF against the closed loop at 52 pF')

    def f_bf(kw):
        w = max(abs(buf_backfeed(vd, kw, tag='g')['i_dac_uA']) for vd in (2.771, 3.3)); return f'{w:.0f} uA', w <= 100
    guard('buffer bias resistor 10 k', 'AN-3 unpowered DAC-current check (0.1 mA)', f_bf, dict(Rbpl=10e3), dict(), 'Rbpl 10 k instead of 330 k')

    def f_bfr(kw):
        v = [buf_backfeed(vd, kw, tag='g') for vd in (2.771, 3.3)]
        rl = max(max(abs(a['v_sp']), abs(a['v_vcc'])) for a in v); return f'{rl*1e3:.0f} mV', rl < 0.5
    guard("buffer's BAT54 removed", 'PR-3 unpowered rail check with DAC0 driving (0.5 V)', f_bfr, dict(biso=False), dict(), 'the buffer supply pin straight on +3.3 V_A')

    def f_pw1(kw):
        a = [build(P(load='short', vdac=vd, **kw), ".op\n") for vd in (0.578, 2.771)]
        i = max(sum(abs(float(ng('g', t, vecs='i(visp) i(visn)')[k][0])) for k in ('i(visp)', 'i(visn)')) for t in a) * 1e3
        tq = ng('g', build(P(vdac=1.65), ".op\n"), vecs='i(visp) i(visn)')
        idle = (abs(float(tq['i(visp)'][0])) + abs(float(tq['i(visn)'][0]))) * 1e3
        tot = AFE_POWERCAL_MA + BUF_ADD_MA + i - idle
        return f'{tot:.1f} mA', tot <= 100
    guard('series resistor 0.5 ohm', 'PW-1 normal-operation total with the AWG shorted (100 mA)', f_pw1, dict(Rs=0.5), dict(), 'the 49.9 ohm output resistor 0.5 ohm')

    def f_bpin(kw):
        q = P(**dict(dict(ramp=(0, 0, 10e-6), vn=R_STRONG[1], ripple=rip_tr(), rout=0.001, vdac=3.3, vmid=1.55, load='hiz'), **kw))
        v = float(ng('g', build(q, ".tran 0.2u 2.2m\n"), vecs='v(bvcx)')['v(bvcx)'].real.max()); return f'{v:.3f} V', v < 5.5
    guard('buffer on a 6 V rail', 'abs-max check on the DAC0 buffer supply pins (5.5 V)', f_bpin, dict(vp=6.0), dict(vp=3.37), '+ rail 6.0 V instead of 3.37 V')

    def f_bbw(kw):
        f, h = ac_resp(P(**kw), tag='g'); b = bw_stats(f, h)['f3db']; return f'{b/1e6:.1f} MHz', b >= 8e6
    guard('slow stage, buffer loaded', 'AW-3 bandwidth check with the buffer at 30 pF (8 MHz)', f_bbw, dict(Cbo=30e-12, Cf=100e-12), dict(Cbo=30e-12), 'Cf 100 pF')


# --------------------------------------------------------------- driver
ORDER = ['models', 'dc', 'swing', 'bw', 'pm', 'loads', 'step', 'noise', 'ripple_tran', 'short', 'boot', 'protect', 'level', 'ext5', 'unpowered', 'sense', 'pam', 'guards']
if LOWV:
    ORDER = ORDER + ['vmidbuf']
REQUIRED = ['AW-1', 'AW-2', 'AW-3', 'AW-4', 'AW-5', 'AW-6', 'AW-7', 'AW-8', 'PR-4', 'PW-2', 'PW-3', 'AN-1', 'AN-3', 'AN-5']
if BUFV:
    ORDER = ORDER[:5] + ['buf'] + ORDER[5:]
    REQUIRED = REQUIRED + ['PW-1', 'PR-2', 'PR-3']


def _run_case(n):
    """One case in a worker: its own netlist directory, its own rows (the parent merges them in ORDER)."""
    global NETDIR, RAWDIR, ROWS, OUT
    NETDIR = os.path.join(NETDIR, n); RAWDIR = os.path.join(RAWDIR, 'w_' + n)
    ROWS, OUT = [], {}
    globals()['case_' + n]()
    return n, ROWS, OUT


def main(argv):
    names = argv or ORDER
    if JOBS > 1:
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=JOBS, mp_context=mp.get_context('fork')) as ex:
            done = {n: (rw, ou) for n, rw, ou in ex.map(_run_case, names)}
        for n in names:
            print(f'[{n}]', flush=True)
            ROWS.extend(done[n][0]); OUT.update(done[n][1])
    else:
        for n in names:
            print(f'[{n}]', flush=True)
            globals()['case_' + n]()
    # a check that did not run is not a check that passed: every required ID must have produced a row
    if not argv:
        seen = ' '.join(r['req'] for r in ROWS)
        missing = [q for q in REQUIRED if q not in seen and not (q == 'AN-5' and 'AW-6' in seen)]
        if missing:
            print('MISSING REQUIREMENT ROWS:', missing); OUT['missing'] = missing
    OUT['rows'] = ROWS
    OUT['design'] = {k: v for k, v in dict(D, **FINAL).items() if not callable(v)}
    OUT['ngspice'] = subprocess.run(['ngspice', '-v'], capture_output=True, text=True).stdout.strip().split('\n')[1:3]
    OUT['models_sha256'] = {k: hashlib.sha256(open(os.path.join(HERE, v), 'rb').read()).hexdigest() for k, v in MODELS.items()}
    OUT['models_sha256']['models/awg_behavioural.lib'] = hashlib.sha256(open(os.path.join(HERE, 'models/awg_behavioural.lib'), 'rb').read()).hexdigest()
    # a partial run writes its own file, so it never overwrites the full set
    with open(os.path.join(RAWDIR, 'results.json' if not argv else 'results_' + '_'.join(argv) + '.json'), 'w') as fh:
        json.dump(OUT, fh, indent=1, default=lambda o: o.tolist() if hasattr(o, 'tolist') else str(o))
    print('\n%-6s %-14s %s' % ('', 'ID', 'case | limit | worst | margin'))
    for r in ROWS:
        print('%-6s %-14s %s | %s | %s | %s' % ('PASS' if r['ok'] else 'FAIL', r['req'], r['case'], r['limit'], r['worst'], r['margin']))
    nf = sum(not r['ok'] for r in ROWS)
    print(f'\n{len(ROWS)} rows, {nf} FAIL')
    return 1 if nf else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
