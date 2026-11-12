#!/usr/bin/env python3
"""AFE plan step 2c: AWG output simulation.  Regenerates every number in report.md.

    python3 -I run.py            # all cases, writes raw/results.json and prints a table
    python3 -I run.py CASE ...   # selected cases (names are the keys of CASES)

numpy only.  ngspice 47 is run in batch mode; netlists are written to netlists/.
The vendor op-amp models are referenced by relative path from ../../models and are
never copied (TI terms, models/SOURCES.md).
"""
import json, os, re, subprocess, sys, hashlib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = {
    'OPA365': '../../models/opa365/OPA365_PSPICE.lib',
    'OPA354': '../../models/opa354/OPA354_PSPICE.lib',
    'OPA356': '../../models/opa356/OPA356_PSPICE.LIB',
}
# what-if copy (whatif/awg-rab): absolute includes so several variants run in parallel, each in its own out/<variant>/
MODELS_ABS = {k: os.path.normpath(os.path.join(HERE, v)) for k, v in MODELS.items()}
BEH = os.path.join(HERE, 'models/awg_behavioural.lib')
VNAME = os.environ.get('AWG_VARIANT', 'base')
WORK = os.path.join(HERE, 'out', VNAME)
KT4 = 4 * 1.380649e-23 * 300.15

# ---------------------------------------------------------------- the design
# Negative rail (AW-1 into 50 ohm, revision 6): LM27762 OUT- = -1.22 V x (R3 + R4)/R4 (SNVSAF7C Sec 7.2.2.3, Eq. 3;
# VFB- -1.238..-1.202 V over temperature, Sec 5.5; R4 >= 50 kohm; adjustable -1.5..-5 V).
# R3 = 768k || 330k, R4 = 330k: BOM types only (the scope's R1/R3 and R2 types, 0.1 %).  -2.073 V (owner, 2026-11-11):
# the bare rails at the datasheet tolerance maxima stay under the OPA365's 5.5 V (-2.156 V, 330k||100k / 100k, gave 5.532 V).
# -1.8 V (47.5k / 100k) left the op-amp's -V pin near -1.14 V at 19 mA (BAT54 + 10 ohm) and failed AW-1 into 50 ohm.
R3_N, R4_N = 768e3 * 330e3 / (768e3 + 330e3), 330e3
VN = -1.22 * (R3_N + R4_N) / R4_N                  # -2.073 V
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
)


# ================================================================= what-if variants (whatif/awg-rab)
# A network spec: a number = one part; a list = parts in series; a tuple = parts in parallel (nestable).
# Resistor tolerance by value: the BOM's 10k and 4.7k are 1 % thick film (100 ppm/K); 953, 249, 49.9, 330k, 768k,
# 13.7k and 15.8k are the 0.1 % types; 22 ohm (the filter candidate) 1 % assumed *(check)*.
RTOL_BY_VALUE = {10e3: 0.01, 4.7e3: 0.01, 22.0: 0.01, 953.0: 0.001, 249.0: 0.001, 49.9: 0.001, 330e3: 0.001,
                 768e3: 0.001, 13.7e3: 0.001, 15.8e3: 0.001}
CTOL = 0.05                     # C0G 5 %
# Layout parasitic of every node a series combination adds (a pad pair and a short trace to the ground plane):
# 0.3 pF at the nominal 1.5 pF V+ corner, scaled with the V+ corner (0.1 / 0.3 / 0.7 pF at 0.5 / 1.5 / 3.5 pF) *(check)*.
CNODE = 0.3e-12


def r_val(spec, f=lambda v: 1.0):
    if isinstance(spec, list): return sum(r_val(x, f) for x in spec)
    if isinstance(spec, tuple): return 1.0 / sum(1.0 / r_val(x, f) for x in spec)
    return spec * f(spec)


def c_val(spec, f=lambda v: 1.0):
    if isinstance(spec, list): return 1.0 / sum(1.0 / c_val(x, f) for x in spec)
    if isinstance(spec, tuple): return sum(c_val(x, f) for x in spec)
    return spec * f(spec)


def r_tol(spec):
    """Composite tolerance with every part at its own limit in one direction (the extreme of a monotone network)."""
    n = r_val(spec)
    return max(r_val(spec, lambda v: 1 + RTOL_BY_VALUE[v]) / n - 1, 1 - r_val(spec, lambda v: 1 - RTOL_BY_VALUE[v]) / n)


def count(spec):
    """(parts, added internal nodes)"""
    if isinstance(spec, list):
        a = [count(x) for x in spec]; return sum(p for p, _ in a), sum(n for _, n in a) + len(spec) - 1
    if isinstance(spec, tuple):
        a = [count(x) for x in spec]; return sum(p for p, _ in a), sum(n for _, n in a)
    return 1, 0


def net(spec, kind, name, a, b, scale, cnode, L, ctr):
    """Netlist lines for spec between nodes a and b; every internal node gets cnode to ground (and, for capacitors, 1 Tohm
    to ground so the operating point has a DC path)."""
    if isinstance(spec, list):
        nodes = [a] + [f'{name.lower()}n{next(ctr)}' for _ in spec[:-1]] + [b]
        for x, (u, v) in zip(spec, zip(nodes, nodes[1:])):
            net(x, kind, name, u, v, scale, cnode, L, ctr)
        for nd in nodes[1:-1]:
            L.append(f"C{nd}p {nd} 0 {cnode}")
            if kind == 'C': L.append(f"R{nd}dc {nd} 0 1e12")
    elif isinstance(spec, tuple):
        for x in spec: net(x, kind, name, a, b, scale, cnode, L, ctr)
    else:
        L.append(f"{name}_{next(ctr)} {a} {b} {spec * scale}")


VARIANTS = {
    'base':  dict(desc='current design: Ra 13.7k, Rb 15.8k (0.1 %), Ca 20 pF, Cb 12 pF', Ra=13.7e3, Rb=15.8e3),
    'c1':    dict(desc='Ra 10k + 4.7k, Rb (4.7k||4.7k) + 10k + 4.7k (1 %)', Ra=[10e3, 4.7e3], Rb=[10e3, 4.7e3, (4.7e3, 4.7e3)]),
    'c2':    dict(desc='Ra 10k + 4.7k, Rb 10k + 4.7k + 953 + 953 (953 0.1 %)', Ra=[10e3, 4.7e3], Rb=[10e3, 4.7e3, 953.0, 953.0]),
    'c3':    dict(desc='Ra 953 + 249 + 10k + 4.7k, Rb (10k||4.7k) + 10k + 4.7k', Ra=[10e3, 4.7e3, 953.0, 249.0], Rb=[10e3, 4.7e3, (10e3, 4.7e3)]),
    'ca39':  dict(desc='current Ra/Rb, Ca 39 pF + 39 pF in series (19.5 pF)', Ra=13.7e3, Rb=15.8e3, Ca=[39e-12, 39e-12]),
    'c1ca39': dict(desc='c1 Ra/Rb, Ca 39 pF + 39 pF in series (19.5 pF)', Ra=[10e3, 4.7e3], Rb=[10e3, 4.7e3, (4.7e3, 4.7e3)], Ca=[39e-12, 39e-12]),
    'c2ca39': dict(desc='c2 Ra/Rb, Ca 39 pF + 39 pF in series (19.5 pF)', Ra=[10e3, 4.7e3], Rb=[10e3, 4.7e3, 953.0, 953.0], Ca=[39e-12, 39e-12]),
    'a4k7free': dict(desc='Ra 768k||330k||(10k + 10k), Rb 953 + 10k + 10k (no 4.7k)', Ra=(768e3, 330e3, [10e3, 10e3]), Rb=[10e3, 10e3, 953.0]),
    'b22':   dict(desc='current design, supply filter 10R -> 22R||22R (11 ohm)', Ra=13.7e3, Rb=15.8e3, rflt=(22.0, 22.0)),
    # no-10k variants (4.7k 1 %, 249 0.1 %), supply filter 22R||22R; c2r11 = c2 on the same filter
    'n1':    dict(desc='Ra (4.7k||4.7k)+4.7k+4.7k+4.7k, Rb 4.7k x4, rflt 22||22', Ra=[(4.7e3, 4.7e3), 4.7e3, 4.7e3, 4.7e3],
                  Rb=[4.7e3, 4.7e3, 4.7e3, 4.7e3], rflt=(22.0, 22.0)),
    'n2':    dict(desc='Ra 4.7k x3 + 249, Rb (4.7k||4.7k)+4.7k x3, rflt 22||22', Ra=[4.7e3, 4.7e3, 4.7e3, 249.0],
                  Rb=[(4.7e3, 4.7e3), 4.7e3, 4.7e3, 4.7e3], rflt=(22.0, 22.0)),
    'c2r11': dict(desc='c2 Ra/Rb, rflt 22||22', Ra=[10e3, 4.7e3], Rb=[10e3, 4.7e3, 953.0, 953.0], rflt=(22.0, 22.0)),
}
_extra = json.loads(os.environ.get('AWG_VARIANT_JSON', 'null'))      # ad-hoc variants (capacitor search): JSON with lists for series
if _extra:
    def _t(x): return [_t(y) for y in x] if isinstance(x, list) else (tuple(_t(y) for y in x['par']) if isinstance(x, dict) else x)
    VARIANTS[VNAME] = {k: (_t(v) if k in ('Ra', 'Rb', 'Ca', 'Cb', 'rflt') else v) for k, v in _extra.items()}
V = dict(dict(Ca=20e-12, Cb=12e-12, rflt=10.0), **VARIANTS[VNAME])
D['Ra'] = r_val(V['Ra']); D['Rb'] = r_val(V['Rb'])
D['Ra_spec'] = V['Ra']; D['Rb_spec'] = V['Rb']; D['Ca_spec'] = V['Ca']; D['Cb_spec'] = V['Cb']
TOLS = dict(Ra=r_tol(V['Ra']), Rb=r_tol(V['Rb']), Rx=0.001, Rf=0.001, Rg=0.001)


def build(p, analysis, ac=(), extra='', start=''):
    """Netlist text.  ac: names of sources given AC 1 (dac, vcc, vee, vmid, vos)."""
    q = dict(D); q.update(p)
    A = lambda n: 1 if n in ac else 0
    L = [f"* AFE AWG output, generated by run.py ({q['opamp']})",
         f".include {MODELS_ABS[q['opamp']]}", f".include {BEH}"]
    if q.get('dac_pwl'):
        L.append(f"Vdp dsrc 0 DC {q['vdac']} PWL({q['dac_pwl']})\nRdo dsrc dac {max(q['rout'], 1e-3)}")
    else:
        L.append(f"Xdac dac 0 DAC0_SRC params: v={q['vdac']} rout={q['rout']} acmag={A('dac')}")
    ra_in = 'dac'
    if q['sw']:
        ra_in = 'dacs'
        ctl = f"DC {q['swv']}" + (f" PWL({q['sw_pwl']})" if q['sw_pwl'] else '')
        L.append(f"Ssw dac dacs swc 0 SWM\nVswc swc 0 {ctl}\nCsw1 dac 0 10p\nCsw2 dacs 0 10p")
    cn_ = CNODE * q['Cpar_p'] / 1.5e-12
    import itertools as _it
    ctr = _it.count(1)
    sa, sb = q.get('Ra_spec', q['Ra']), q.get('Rb_spec', q['Rb'])
    net(sa, 'R', 'Ra', ra_in, 'vp0', q['Ra'] / r_val(sa), cn_, L, ctr)          # overrides of Ra/Rb scale every part
    if q['Ca']:
        sc = q.get('Ca_spec', q['Ca']); net(sc, 'C', 'Ca', ra_in, 'vp0', q['Ca'] / c_val(sc), cn_, L, ctr)
    net(sb, 'R', 'Rb', 'vp0', '0', q['Rb'] / r_val(sb), cn_, L, ctr)
    if q['Rx']: L.append(f"Rx vp0 vm {q['Rx']}")
    L.append(f"Cpp vp0 0 {q['Cpar_p']}")
    if q['Cb']:
        sc = q.get('Cb_spec', q['Cb']); net(sc, 'C', 'Cb', 'vp0', '0', q['Cb'] / c_val(sc), cn_, L, ctr)
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
    L.append(f"Xvm vms 0 VMID_BUF params: v={q['vmid']} rout={q['rvm']} acmag={A('vmid')}")
    L.append(f"Rvmx vms vm 1m\nCvm1 vm vmc {q['cvm']}\nRe1 vmc 0 0.02\nCvm2 vm vmd 100n\nRe2 vmd 0 0.05")
    if q.get('ramp'):
        rp_ = q['ramp']
        L.append(f"Xsup sp sn 0 LM27762_RAMP params: vp={q['vp']} vn={q['vn']} rp={q['rp']} rn={q['rn']} "
                 f"rsink={q['rsink']} rbl={q['rbl']} tdp={rp_[0]} tdn={rp_[1]} tr={rp_[2]} ripple={q['ripple']}")
    else:
        L.append(f"Xsup sp sn 0 LM27762_BEH params: vp={q['vp']} vn={q['vn']} rp={q['rp']} rn={q['rn']} "
                 f"rsink={q['rsink']} rbl={q['rbl']} acp={A('vcc')} acn={A('vee')} ripple={q['ripple']}")
    L.append(f"Cb1 sp cb1 {q['cbulk']}\nRcb1 cb1 0 0.02\nCb2 sn cb2 {q['cbulk']}\nRcb2 cb2 0 0.02")
    rspec = q.get('rflt_spec') if q.get('rflt_spec') is not None and q['rflt'] == r_val(q['rflt_spec']) else max(q['rflt'], 1e-3)
    net(rspec, 'R', 'Rfp', 'sp', 'vcc', 1.0, 0.0, L, ctr); net(rspec, 'R', 'Rfn', 'sn', 'vee', 1.0, 0.0, L, ctr)
    L.append(f"Cp1 vcc cp1 {q['cpin']}\nRcp1 cp1 0 0.05\nCp2 vee cp2 {q['cpin']}\nRcp2 cp2 0 0.05")
    if q['iso']:
        L.append("Dsp vcc vcc2 DBAT54\nVisp vcc2 vccx 0\nDsn veex vee3 DBAT54\nVisn vee3 vee 0")
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
        L.append(f"Dcp {cn} vcc DBAT54\nDcn vee {cn} DBAT54")
    elif cl == 'tvs33':
        L.append(f"Dt1 {cn} tm DTVS33\nDt2 0 tm DTVS33")
    elif cl == 'tvs50':
        L.append(f"Dt1 {cn} tm DTVS50\nDt2 0 tm DTVS50")
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
    os.makedirs(f'{WORK}/netlists', exist_ok=True)
    os.makedirs(f'{WORK}/raw', exist_ok=True)
    cir = f'{WORK}/netlists/{name}.cir'
    raw = f'{WORK}/raw/{name}.raw'
    body = text.replace('.end\n', '')
    ctl = ['.control', 'set filetype=ascii', 'set noaskquit', 'run']
    if plot: ctl.append(f'setplot {plot}')
    ctl.append(f'write {raw} {vecs}')
    ctl.append('.endc')
    open(cir, 'w').write(body + '\n' + '\n'.join(ctl) + '\n.end\n')
    r = subprocess.run(['ngspice', '-b', cir], capture_output=True, text=True, cwd=WORK)
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
    g = lambda n: (r['onoise_' + n].real ** 2 if 'onoise_' + n in r else
                   sum((r[k].real ** 2 for k in r if re.fullmatch(f'onoise_{n}_\\d+', k)), np.zeros_like(r['frequency'].real)))
    # the behavioural supply's own bleed resistors and diodes are model artefacts (the real
    # rail noise is added separately from its datasheet density and a transfer function)
    art = sum(g(n) for n in ('r.xsup.rbn', 'r.xsup.rbp', 'r.xsup.rno', 'r.xsup.rpo', 'r.xsup.rsn',
                             'r.xsup.rsp', 'd.xsup.dn', 'd.xsup.dp'))
    tot2 = tot2 - art
    parts = {'Ra': g('ra'), 'Rb': g('rb'), 'Rx': g('rx'), 'Rf': g('rf'), 'Rg': g('rg'),
             'Rs': g('rs') + (g('rs2') if 'onoise_rs2' in r else 0), 'Rout(DAC)': g('r.xdac.ro'), 'Rl': g('rl')}
    parts['supply/Vmid network R'] = sum(g(n) for n in ('rfp', 'rfn', 'rcb1', 'rcb2', 'rcp1', 'rcp2',
                                                        're1', 're2', 'rvmx', 'r.xvm.ro'))
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
FINAL = dict(Ca=c_val(V['Ca']), Cb=c_val(V['Cb']), Cf=0.0, rflt=r_val(V['rflt']), rflt_spec=V['rflt'], Rs=49.9, R2=0.0, clamp='gnd3', cat='out', iso=True)   # the recommended set: Cf = 0, no deliberate band limit (owner decision, SC-5/MC-6); protection: ONE 49.9 ohm 0.1 % resistor (AW-4) and a 3-diode stack each way to ground on the op-amp side (see case_protect)
_S = 1 / D['Ra'] + 1 / D['Rb'] + 1 / D['Rx']
GAIN_NOM = (1 + D['Rf'] / D['Rg']) / (D['Ra'] * _S)     # DAC pin to output, nominal parts (1.1529)
ROWS = []      # pass/fail table rows
OUT = {}       # everything, written to raw/results.json


def add(req, case, limit, worst, margin, ok, note=''):
    ROWS.append(dict(req=req, case=case, limit=limit, worst=worst, margin=margin, ok=bool(ok), note=note))


def P(**kw):
    q = dict(FINAL); q.update(kw); return q


def rng_(seed=20261111): return np.random.default_rng(seed)


# --------------------------------------------------------------- DC, AW-1/2/5/7
def dc_mc(aref, scen, n=40000, p=None, seed=1, tol=None):
    """Monte Carlo of the DC map.  scen 'A': DAC window theory 1/6..5/6 of AREF, Vmid-to-window
    centring error uniform +/-30 mV.  scen 'B': the measured board window 0.578-2.771 V (scaled
    with AREF from 3.27 V), centre 39.5 mV above AREF/2, residual +/-5 mV.  Parts: 0.1 % (the stocked grade)."""
    q = dict(D); q.update(p or {})
    r = np.random.default_rng(seed)
    tl = (lambda k: TOLS[k]) if tol is None else (lambda k: tol)
    t = lambda x, k: x * (1 + r.uniform(-tl(k), tl(k), n))
    Ra, Rb, Rx, Rf, Rg = t(q['Ra'], 'Ra') + q['rout'] + (8.8 if q.get('sw') else 0.0), t(q['Rb'], 'Rb'), t(q['Rx'], 'Rx') if q['Rx'] else np.full(n, 1e12), t(q['Rf'], 'Rf'), t(q['Rg'], 'Rg')
    G = 1 + Rf / Rg
    if scen == 'A':
        lo, hi = aref / 6, 5 * aref / 6
        vmid = aref / 2 + r.uniform(-0.030, 0.030, n)
    else:
        k = aref / 3.27
        lo, hi = 0.578 * k, 2.771 * k
        vmid = aref / 2 + r.uniform(-0.005, 0.005, n)
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
        add('AW-7 info', f'as built (AW-7 is after calibration): gain [{sc}], old 1.10-1.20 row', 'info (was 1.10..1.20)', f'{g[0]:.4f}..{g[1]:.4f}', f'{min(g[0]-1.10, 1.20-g[1]):+.4f}', True)
        o = max(r['off'] for r in rows)
        add('AW-7 info', f'as built (AW-7 is after calibration): offset at window centre [{scen}], old 60 mV row', 'info (was <= 60 mV)', f'{o*1e3:.1f} mV', f'{(0.060-o)*1e3:+.1f} mV', True)
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
    S = 1 / d['Ra'] + 1 / d['Rb'] + 1 / d['Rx']; G = 1 + d['Rf'] / d['Rg']
    pred = G * ((2.5 / d['Ra'] + 1.65 / d['Rx']) / S) - (G - 1) * 1.65
    OUT['dc_xcheck'] = dict(spice=float(r['v(out)'][0]), analytic=pred)
    r0 = ng('dc_mid', build(P(vdac=1.65, vmid=1.65), ".op\n"), vecs='v(out)')
    v0 = float(r0['v(out)'][0]); OUT['dc_offset_nominal_V'] = v0
    add('AW-7 info', 'nominal parts, DAC at Vmid (1.65 V): output (zero-offset pick Rf/Rg = Rb/Ra + Rb/Rx)', 'info (a few mV)', f'{v0*1e3:+.2f} mV', '', True)
    return OUT['dc_xcheck']


# --------------------------------------------------------------- what-if: AW-1 / AW-5 at the tolerance corners (not Monte Carlo)
def dc_corner(aref, scen, tols, p=None):
    """Every corner of Ra, Rb, Rx, Rf, Rg at +/- their composite tolerance, x Vmid centring at its two limits x op-amp Vos at its two
    limits; the same metrics as dc_mc."""
    import itertools as _it
    q = dict(D); q.update(p or {})
    K = ('Ra', 'Rb', 'Rx', 'Rf', 'Rg')
    combos = np.array(list(_it.product((-1, 1), repeat=7)), dtype=float)
    Ra, Rb, Rx, Rf, Rg = (q[k] * (1 + combos[:, i] * tols[k]) for i, k in enumerate(K))
    if scen == 'A':
        lo, hi = aref / 6, 5 * aref / 6; vmid = aref / 2 + 0.030 * combos[:, 5]
    else:
        k_ = aref / 3.27; lo, hi = 0.578 * k_, 2.771 * k_; vmid = aref / 2 + 0.005 * combos[:, 5]
    vos = 0.2e-3 * combos[:, 6]
    G = 1 + Rf / Rg; S = 1 / Ra + 1 / Rb + 1 / Rx; gain = G / (Ra * S)
    vplus = lambda vd: (vd / Ra + vmid / Rx) / S
    out = lambda vd: G * (vplus(vd) + vos) - (G - 1) * vmid
    c = (lo + hi) / 2; span = hi - lo; off0 = out(0.0)
    vd_hi, vd_lo = (1.0 - off0) / gain, (-1.0 - off0) / gain
    return dict(gain=gain, off=out(c), use=(vd_hi - vd_lo) / span,
                edge=np.maximum(np.abs(vd_hi - c), np.abs(vd_lo - c)) / (span / 2),
                i=np.maximum(np.abs((hi - vplus(hi)) / Ra), np.abs((lo - vplus(lo)) / Ra)))


AREFS_REQ = (3.20, 3.225, 3.25, 3.275, 3.30)
# 100 ppm/K (the 1 % types) or 25 ppm/K (the 0.1 % types) over an assumed +/-40 K *(check: AW-1/AW-7 state no temperature range)*
def tols_temp():
    t = {}
    for k in ('Ra', 'Rb'):
        spec = D[k + '_spec']
        has1 = any(RTOL_BY_VALUE[v] >= 0.01 for v in _leaves(spec))
        t[k] = TOLS[k] + (0.004 if has1 else 0.001)
    for k in ('Rx', 'Rf', 'Rg'): t[k] = TOLS[k] + 0.001
    return t


def _leaves(spec):
    if isinstance(spec, (list, tuple)):
        for x in spec: yield from _leaves(x)
    else: yield spec


def corner_summary(tols, p=None):
    out = {}
    for scen in ('A', 'B'):
        ms = [dc_corner(a, scen, tols, p) for a in AREFS_REQ]
        out[scen] = dict(use=max(float(m['use'].max()) for m in ms), edge=max(float(m['edge'].max()) for m in ms),
                         i=max(float(m['i'].max()) for m in ms), off=max(float(np.abs(m['off']).max()) for m in ms),
                         gain=(min(float(m['gain'].min()) for m in ms), max(float(m['gain'].max()) for m in ms)))
    return out


def swing_at(q, ld, vm, vp, vn, vd):
    v = lambda x: float(ng('swingc', build(P(**dict(q, vdac=x, vmid=vm, vp=vp, vn=vn, load=ld)), ".op\n"), vecs='v(bnc)')['v(bnc)'][0])
    c = v(vm); k = (v(vm + 0.01) - v(vm - 0.01)) / 0.02; a = v(vd)
    return a, abs(a - (c + k * (vd - vm)))


def case_corners():
    res = {}
    res['tols'] = dict(TOLS); res['tols_temp'] = tols_temp()
    for lab, tl in (('part-tolerance corners', TOLS), ('corners + temperature (100 / 25 ppm/K x 40 K, assumed)', tols_temp())):
        cs = corner_summary(tl); res[lab] = cs
        info = lab != 'part-tolerance corners'
        tag = ', '.join(f'{k} {tl[k]*100:.2f} %' for k in ('Ra', 'Rb', 'Rx', 'Rf', 'Rg'))
        for scen in ('A', 'B'):
            c = cs[scen]
            add('AW-1' + (' info' if info else ''), f'[{lab}] window use, width [{scen}] ({tag})', '<= 92 %', f'{c["use"]*100:.1f} %', f'{(0.92-c["use"])*100:+.1f} %', info or c['use'] <= 0.92)
            add('AW-1' + (' info' if info else ''), f'[{lab}] window use, position-aware [{scen}]', '<= 92 %', f'{c["edge"]*100:.1f} %', f'{(0.92-c["edge"])*100:+.1f} %', info or c['edge'] <= 0.92)
            add('AW-5' + (' info' if info else ''), f'[{lab}] DAC pin load at window ends [{scen}]', '<= 0.1 mA', f'{c["i"]*1e6:.1f} uA', f'{(100e-6-c["i"])*1e6:+.1f} uA', info or c['i'] <= 100e-6)
            add('AW-7 info', f'[{lab}] as built (calibrated out): gain, offset at window centre [{scen}]', 'info (after calibration)', f'{c["gain"][0]:.4f}..{c["gain"][1]:.4f}, {c["off"]*1e3:.1f} mV', '', True)
    if info: pass
    # analytic nominal offset at the window centre (Vdac = Vmid = 1.65 V), resistors nominal
    d = dict(D); S = 1 / d['Ra'] + 1 / d['Rb'] + 1 / d['Rx']; G = 1 + d['Rf'] / d['Rg']
    res['nominal'] = dict(slope=d['Rb'] / d['Ra'], gain=G / (d['Ra'] * S), off_mV=1e3 * (G * 1.65 * (1 / d['Ra'] + 1 / d['Rx']) / S - (G - 1) * 1.65),
                          Rf_over_Rg_required=d['Rb'] / d['Ra'] + d['Rb'] / d['Rx'])
    # AW-1 into 50 ohm with Ra, Rb at their composite corners: the DAC level that commands +/-1.0 V (hi-Z) on that corner's own map
    worst = 0.0; least = 9.0; rows = {}
    for sa in (-1, 1):
        for sb in (-1, 1):
            Ra = D['Ra'] * (1 + sa * TOLS['Ra']); Rb = D['Rb'] * (1 + sb * TOLS['Rb'])
            S = 1 / Ra + 1 / Rb + 1 / D['Rx']; G = 1 + D['Rf'] / D['Rg']
            for vm in (1.55, 1.685):
                for vp_, vn_ in RAILS_AW1_50['datasheet']:
                    for sg in (1, -1):
                        # out(vd) = G (vd/Ra + vm/Rx)/S - (G-1) vm = sg
                        vd = ((sg + (G - 1) * vm) * S / G - vm / D['Rx']) * Ra
                        a, e = swing_at(dict(Ra=Ra, Rb=Rb), 'r50', vm, vp_, vn_, vd)
                        rows[f'{sa:+d}{sb:+d}/{vm}/{vn_:.3f}/{sg:+d}'] = dict(vd=vd, v=a, err=e)
                        worst = max(worst, e); least = min(least, abs(a))
    res['swing_r50_corners'] = dict(err_max=worst, least=least, rows=rows)
    add('AW-1', f'[part-tolerance corners] circuit swing into r50: Ra/Rb at +/-{TOLS["Ra"]*100:.2f} / {TOLS["Rb"]*100:.2f} %, DAC at the corner\'s own +/-1.0 V level, 2 Vmid x 3 rails, weak {R_DS_WEAK[0]:+.3f} / {R_DS_WEAK[1]:+.3f} V (datasheet)',
        '<= 0.62 mV (one DAC code)', f'{worst*1e3:.2f} mV (smallest |v(bnc)| {least:.4f} V)', f'{0.62-worst*1e3:+.2f} mV', worst * 1e3 <= 0.62)
    # PW-3 (short at the DAC window ends, 26 mA) with Ra/Rb at their corners
    ws = 0.0
    for sa in (-1, 1):
        for sb in (-1, 1):
            for vd in (0.578, 2.771):
                r = ng('shc', build(P(load='short', vdac=vd, Ra=D['Ra'] * (1 + sa * TOLS['Ra']), Rb=D['Rb'] * (1 + sb * TOLS['Rb'])), ".op\n"), vecs='v(out)')
                ws = max(ws, abs(float(r['v(out)'][0])) / P()['Rs'] * 1e3)
    res['pw3_corners_mA'] = ws
    add('PW-3', '[part-tolerance corners] short at the DAC window ends (0.578 / 2.771 V), Ra/Rb at their corners: output current', '<= 26 mA', f'{ws:.2f} mA', f'{26-ws:+.2f} mA', ws <= 26)
    # guard: 5 % Ra/Rb must break the corner window check
    def f_win(tl):
        cs = corner_summary(tl); e = max(max(c['edge'], c['use']) for c in cs.values()); return f'{e*100:.1f} %', e <= 0.92
    t5 = dict(TOLS, Ra=0.05, Rb=0.05)
    vb, okb = f_win(t5); vr, okr = f_win(TOLS)
    add('guard', 'Ra/Rb at 5 %: AW-1 corner window check (92 %)', 'fails broken, passes restored', f'broken: {vb}; restored: {vr}', '', (not okb) and okr)
    res['guard_5pct'] = dict(broken=vb, restored=vr, ok=(not okb) and okr)
    OUT['corners'] = res
    return res


# --------------------------------------------------------------- AW-1 swing in the circuit (the rows above are the linear map only)
def swing_err(kw, ld, vm, vp, vn, sg):
    """v(bnc) with the DAC at Vmid + sg/GAIN_NOM (+/-1.0 V at high-Z), and its error against the linear map through Vmid."""
    v = lambda vd: float(ng('swing', build(P(**dict(dict(vdac=vd, vmid=vm, vp=vp, vn=vn, load=ld), **{k: x for k, x in kw.items() if k not in ('vp', 'vn')})), ".op\n"), vecs='v(bnc)')['v(bnc)'][0])
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
        add('AW-1', f'circuit swing: output at +/-1.0 V commanded (high-Z level), into {ld}, 2 Vmid x 3 rail corners, weak corner {wk[0]:+.3f} / {wk[1]:+.3f} V ({basis}): error against the linear map',
            '<= 0.62 mV (one DAC code, AW-2)', f'{worst*1e3:.2f} mV (smallest |v(bnc)| {least:.4f} V, target {tgt} V)', f'{0.62-worst*1e3:+.2f} mV', worst * 1e3 <= 0.62)
    # the margin of the 50 ohm row in rail volts: the least negative - rail at which the row still holds (bisection, weak + rail)
    if p is None:
        e_at = lambda vn_: max(swing_err({}, 'r50', vm, R_DS_WEAK[0], vn_, -1)[1] for vm in (1.55, 1.685))
        lo_, hi_ = -2.10, -1.90          # lo_ passes, hi_ fails (checked below)
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
        t = (f".include {BEH}\nVs a 0 PWL(0 0 10n 0 12n 1 5u 1)\n"
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
    ripple_pk = 5e-3
    rip = {}
    for h in (1, 2, 3, 4):
        fh = 2e6 * h
        rip[h] = float(np.interp(fh, f, tfp) * ripple_pk / np.sqrt(2) + np.interp(fh, f, tfn) * ripple_pk / np.sqrt(2))
    ripple_rms = float(np.sqrt(sum(v ** 2 for v in rip.values())))
    res['extra'] = dict(supply_uV=supply * 1e6, vmid_uV=vmid_noise * 1e6, vmid_allow_nV_for_10uV=10e-6 / vm_int * 1e9,
                        ripple_uV=ripple_rms * 1e6, ripple_by_harmonic_uV={h: v * 1e6 for h, v in rip.items()},
                        tf_supply_dB_at_2MHz=float(20 * np.log10(np.interp(2e6, f, tfp))),
                        tf_vmid_int=vm_int)
    tot = np.sqrt((n['total_uV'] * 1e-6) ** 2 + supply ** 2 + vmid_noise ** 2 + ripple_rms ** 2) * 1e6
    res['AW6_total_uV'] = float(tot)
    add('AW-6', 'added noise, quiet DC source, OPA365: circuit .noise 10 Hz-100 MHz', '<= 100 uV rms', f'{n["total_uV"]:.1f} uV', f'{100-n["total_uV"]:+.1f} uV', n['total_uV'] <= 100)
    add('AW-6/PW-2', 'sum with supply noise, 2 MHz ripple and harmonics, Vmid buffer (10 nV/rtHz assumed)', '<= 100 uV rms', f'{tot:.1f} uV', f'{100-tot:+.1f} uV', tot <= 100,
        f'supply {supply*1e6:.2f}, ripple {ripple_rms*1e6:.2f}, Vmid {vmid_noise*1e6:.2f} uV')
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
        r = ng('sh', t, vecs='v(out) v(vccx) v(veex) i(visp) i(visn) v(bnc) v(inv)')
        vo = r['v(out)'][0]; ip = r['i(visp)'][0]; inn = r['i(visn)'][0]
        iout = vo / RTOT + (vo - r['v(inv)'][0]) / D['Rf']
        psup = r['v(vccx)'][0] * ip + r['v(veex)'][0] * inn
        pamp = psup - vo * iout
        res[name] = dict(vdac=vd, vout=float(vo), i_short_mA=float(vo / RTOT * 1e3), i_pos_mA=float(ip * 1e3),
                         i_neg_mA=float(-inn * 1e3), p_amp_mW=float(pamp * 1e3))
    top = max(abs(v['i_short_mA']) for v in res.values())
    atpm1 = res['+1V']['i_short_mA']
    add('PW-3', 'short to ground at +/-1 V commanded: output current', '<= 26 mA', f'{atpm1:.1f} mA', f'{26-atpm1:+.1f} mA', abs(atpm1) <= 26)
    tol_hi = top * 49.8 / (49.8 * 0.99)
    add('PW-3', 'short at the DAC window ends: output current', '<= 26 mA', f'{top:.2f} mA', f'{26-top:+.2f} mA', top <= 26, f'with both resistors 1 % low: {tol_hi:.2f} mA')
    itot = max(v['i_pos_mA'] for v in res.values()) + 0
    itot = max(v['i_pos_mA'] + v['i_neg_mA'] for v in res.values())
    add('PW-3/PW-1', 'op-amp supply current in the short (+ and - pins summed), AFE total limit 100 mA', '<= 100 mA', f'{itot:.1f} mA', f'{100-itot:+.1f} mA', itot <= 100, 'the rest of the AFE adds its own')
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
        t = build(P(ramp=ramp, vp=3.37, vn=R_STRONG[1], ripple=5e-3, rout=1e9, vdac=0.0, vmid=1.685, load='hiz'), ".tran 0.2u 2.2m\n")
        r = ng('startup', t, vecs='v(vccx) v(veex) v(bnc) v(vm)')
        d = r['v(vccx)'].real - r['v(veex)'].real
        st[name] = dict(max_supply_V=float(d.max()), bnc_min=float(r['v(bnc)'].real.min()), bnc_max=float(r['v(bnc)'].real.max()))
    res['startup'] = st
    mx = max(v['max_supply_V'] for v in st.values())
    add('AN/PR (abs max)', f'op-amp supply pins, +3.37/{R_STRONG[1]:.2f} V + 5 mV ripple, 4 start-up orders: max V+ minus V-', '< 5.5 V (OPA365 abs max)', f'{mx:.3f} V', f'{5.5-mx:+.3f} V', mx < 5.5, 'LM27762 start-up overshoot not modelled (gap)')
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
AFE_BASE_MA = sum(json.load(open(os.path.join(HERE, '../../sim/powercal/results.json')))['p3_items'].values())
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
    r = ng(tag, t, vecs='v(vcc) v(vee) v(vccx) v(veex) i(vx) i(visp) i(visn) v(dac) v(vp) v(out)' + (' i(vca) i(vcb)' if stk else ''))
    g = lambda k: float(r[k][0])
    icl = (abs(g('i(vca)')) + abs(g('i(vcb)'))) if stk else 0.0
    iext = abs(g('i(vx)'))
    return dict(vext=vext, v_rail_pos=g('v(vcc)'), v_rail_neg=g('v(vee)'), pin_pos=g('v(vccx)'), pin_neg=g('v(veex)'),
                i_ext_mA=-g('i(vx)') * 1e3, i_into_pos_rail_uA=-g('i(visp)') * 1e6, i_into_neg_rail_uA=g('i(visn)') * 1e6,
                v_dac=g('v(dac)'), v_out=g('v(out)'), i_clamp_mA=icl * 1e3,
                i_esd_mA=max(0.0, iext - icl) * 1e3)      # what is left for the op-amp's own ESD diodes (the model's, *(check)*)


def stack_current(n, v):
    """Current in an n-diode BAV99-model stack alone at v volts (A): the clamp's own knee."""
    d = ''.join(f"Dk{i} {'n' if i == 1 else f'k{i-1}'} {'0' if i == n else f'k{i}'} DBAV99\n" for i in range(1, n + 1))
    t = f".include {BEH}\nVk n 0 DC {v}\n{d}.op\n"
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
        add('PW-1/PR-4', f'[{lab}] +/-5 V powered: AFE total = {AFE_BASE_MA:.1f} mA (powercal, datasheet maxima) + supply increase {S["supply_increase_mA"]:.0f} mA; Due 300 mA + AFE (PR-4: a fault is judged against the PW-1 450 mA limit, docs/afe.md)', '<= 450 mA', f'{300+S["afe_total_in_fault_mA"]:.0f} mA', f'{450-300-S["afe_total_in_fault_mA"]:+.0f} mA', 300 + S['afe_total_in_fault_mA'] <= 450)
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
    for vx in (5.0, -5.0):
        res[f'powered/{vx:+g}'] = fault(dict(vdac=1.65), vx)
        res[f'unpowered/{vx:+g}'] = unpowered(dict(), vx)
        res[f'unpowered, DAC high-Z/{vx:+g}'] = unpowered(dict(rout=1e9), vx)
    OUT['ext5'] = res
    for k, v in res.items():
        if k.startswith('unpowered'):
            ok = -0.2 <= v['v_dac'] <= 3.45 and abs(v['v_rail_pos']) < 0.5 and abs(v['v_rail_neg']) < 0.5 and (abs(v['i_into_pos_rail_uA']) + abs(v['i_into_neg_rail_uA'])) <= 100
            add('PR-4/PR-3/PR-2', f'recommended circuit, {k}: rails, current into rails, DAC pin', 'rails < 0.5 V, <= 100 uA, pin -0.2..3.45 V',
                f'rails {v["v_rail_pos"]*1e3:+.0f}/{v["v_rail_neg"]*1e3:+.0f} mV, into rails {v["i_into_pos_rail_uA"]:+.2f}/{v["i_into_neg_rail_uA"]:+.2f} uA, DAC pin {v["v_dac"]:+.2f} V, op-amp pins {v["pin_pos"]:+.2f}/{v["pin_neg"]:+.2f} V', '', ok)
    return res


def case_unpowered():
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


# --------------------------------------------------------------- model validation
def case_models():
    res = {}
    # 1. noise of each op-amp model against its datasheet density (models/datasheet-facts.md)
    chk = {'OPA365': (1e5, 4.5), 'OPA354': (1e6, 6.5)}
    for op, (fx, ds) in chk.items():
        t = (f".include {MODELS_ABS[op]}\nVp vcc 0 2.5\nVn vee 0 -2.5\nVi vp 0 DC 0 AC 1\nX1 vp out vcc vee out {op}\nRl out 0 10k\n"
             ".noise v(out) Vi dec 20 1 10Meg\n")
        r = ng('val', t, plot='noise1')
        f = r['frequency'].real; d = r['onoise_spectrum'].real
        sim = float(np.interp(fx, f, d)) * 1e9
        res[f'{op}_noise'] = dict(f=fx, sim_nV=sim, datasheet_nV=ds)
        add('model', f'{op} model input noise density at {fx/1e3:g} kHz vs datasheet', f'{ds} nV/rtHz +/-15 %', f'{sim:.2f} nV/rtHz', f'{(0.15-abs(sim/ds-1))*100:+.0f} %', abs(sim / ds - 1) <= 0.15)
    # 2. input capacitance at V+: follower with 100 kohm source, pole -> C
    t = (f".include {MODELS_ABS['OPA365']}\nVp vcc 0 3.3\nVn vee 0 {VN}\nVi in 0 DC 0.5 AC 1\nRi in vp 100k\n"
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
    t = (f".include {BEH}\nVs a 0 PWL(0 0 10n 0 12n 1 5u 1)\n"
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
        t = build(P(vdac=1.65, vmid=1.65 + kw['err']), ".op\n"); r = ng('g', t, vecs='v(bnc)'); v = float(r['v(bnc)'][0])
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
    guard('rails raised', 'AW-8 DAC0-at-3.3 V output check (2.1 V)', f_boot, dict(Rf=500.0, clamp='none'), dict(), 'Rf 500 ohm (slope 3.6) and no clamp')

    def f_i(kw):
        m = dc_mc(3.3, 'A', n=5000, p=kw); i = float(max(np.abs(m['i_top']).max(), np.abs(m['i_bot']).max()))
        return f'{i*1e6:.0f} uA', i <= 100e-6
    guard('Ra too small', 'AW-5 DAC-load check (0.1 mA)', f_i, dict(Ra=0.6 * D['Ra'], Rb=0.6 * D['Rb']), dict(), 'Ra and Rb x 0.6 (same slope)')

    def f_noise(kw):
        n = noise_split(P(**kw), tag='g')['total_uV']; return f'{n:.0f} uV', n <= 100
    guard('noisy resistors', 'AW-6 noise check (100 uV)', f_noise, dict(Rf=40 * D['Rf'], Rg=40 * D['Rg']), dict(), 'Rf/Rg x40 (same gain)')

    def f_pm(kw):
        q = pm = phase_margin(P(**kw), tag='g')['pm']; return f'{pm:.0f} deg', pm >= 45
    guard('no feedback capacitor', 'AN-1 phase-margin check (45 deg)', f_pm, dict(Rf=20 * D['Rf'], Rg=20 * D['Rg'], Cpar_n=6e-12), dict(), 'Rf/Rg x20 and 6 pF at the inverting node (Cf = 0 in both)')

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
    guard('negative rail at -1.5 V', 'AW-1 circuit-swing check into high-Z (one code)', f_swing, dict(vn=-1.5), dict(), f'LM27762 negative rail -1.5 V instead of {VN:.3f} V')

    def f_swing50(kw):
        vp_, vn = kw['weak']                       # the weak rail corner, as case_swing uses it
        e = max(swing_err({}, 'r50', vm, vp_, vn, -1)[1] for vm in (1.55, 1.685))
        return f'{e*1e3:.2f} mV at {vn:+.3f} V', e * 1e3 <= 0.62
    guard('negative rail back at -1.8 V', 'AW-1 circuit-swing check into 50 ohm, datasheet weak rail corner (one code)', f_swing50,
          dict(weak=ds_rails(47.5e3, 100e3)[0]), dict(weak=R_DS_WEAK),
          f'LM27762 OUT- -1.8 V (47.5k / 100k) instead of {VN:.3f} V (768k||330k / 330k), both at the datasheet weak corner')
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
    guard('over-compensated attenuator', 'AW-4 cable overshoot check over the V+ parasitic corners (5 %)', f_comp, dict(Ca=33e-12, Cb=22e-12), dict(),
          'Ca 33 pF / Cb 22 pF (flat at 1.5 pF, over-compensated at 0.5 pF) instead of 20 / 12 pF')

    guard('Ca over-compensated (39 pF)', 'AW-4 cable overshoot check over the V+ parasitic corners (5 %)', f_comp, dict(Ca=39e-12), dict(),
          f'Ca 39 pF instead of {FINAL["Ca"]*1e12:.1f} pF, Cb unchanged')

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
    OUT['guards'] = G
    return G


# --------------------------------------------------------------- driver
ORDER = ['models', 'dc', 'corners', 'swing', 'bw', 'pm', 'loads', 'step', 'noise', 'ripple_tran', 'short', 'boot', 'protect', 'level', 'ext5', 'unpowered', 'guards']
REQUIRED = ['AW-1', 'AW-2', 'AW-3', 'AW-4', 'AW-5', 'AW-6', 'AW-7', 'AW-8', 'PR-4', 'PW-2', 'PW-3', 'AN-1', 'AN-3', 'AN-5']


def main(argv):
    names = argv or ORDER
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
    with open(os.path.join(WORK, 'results.json'), 'w') as fh:
        json.dump(OUT, fh, indent=1, default=lambda o: o.tolist() if hasattr(o, 'tolist') else str(o))
    print('\n%-6s %-14s %s' % ('', 'ID', 'case | limit | worst | margin'))
    for r in ROWS:
        print('%-6s %-14s %s | %s | %s | %s' % ('PASS' if r['ok'] else 'FAIL', r['req'], r['case'], r['limit'], r['worst'], r['margin']))
    nf = sum(not r['ok'] for r in ROWS)
    print(f'\n{len(ROWS)} rows, {nf} FAIL')
    return 1 if nf else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
