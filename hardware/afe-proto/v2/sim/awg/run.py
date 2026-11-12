#!/usr/bin/env python3
"""v2 AWG output stage: every number in design.md and report_table.md.

    cd hardware/afe-proto/v2/sim/awg && python3 -I run.py          # about 3-6 minutes; writes raw/results.json,
                                                                    # netlists/*.cir, raw/*.log, report_table.md
    python3 -I run.py guards                                        # only the checks-broken-on-purpose rows

Needs ngspice-47 and numpy.  The vendor op-amp model is read from ../../../whatif/tph2502/models (local, never copied or
committed); core.py checks its sha256.  Models/tph2502.inc is the only file that has to change to swap the op-amp.
"""
import json, os, subprocess, sys, itertools
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core, design
from core import D, RAILS

ROWS = []
OUT = {}


def add(id_, case, limit, result, margin, ok, note=''):
    ROWS.append(dict(id=id_, case=case, limit=limit, result=result, margin=margin, ok=bool(ok), note=note))
    print(('PASS' if ok else 'FAIL'), id_, case, '|', limit, '|', result, '|', margin, '|', note, flush=True)


def info(id_, case, result, note=''):
    ROWS.append(dict(id=id_, case=case, limit='information', result=result, margin='', ok=True, note=note, info=True))
    print('INFO', id_, case, '|', result, '|', note, flush=True)


V = design.VALUES
AW6_UV = 300.0       # AW-6 (D22, 2026-11-12): 0.3 mV rms
TRAN_OPT = '.options method=gear reltol=3e-3 abstol=1e-11 gmin=1e-10'     # the macro's diodes stall the default tolerances at tiny steps
LIM_NOTE_DS = 'datasheet-scaled'


# ---------------------------------------------------------------------------------------------------- model checks
def case_model():
    b = core.build(dict(topo='Single', load='open'), analysis='')
    # the model's supply current does not follow the load current: 0 mA and 30 mA of load
    cur = []
    for load in ('open', 'r50'):
        txt = (f"* model supply current vs load\n{core.model_text().replace('@VENDOR@', os.path.relpath(core.VENDOR, core.NETDIR))}\n"
               f"Vp vcc 0 3.3\nVn vee 0 -2.073\nVi in 0 1.0\nXA in vo vcc vee vo TPH2502\nRl vo 0 {'1G' if load == 'open' else '33'}\n")
        h, d, log = core.wr('m_iq', txt, 'op', ['i(Vp)', 'v(vo)'])
        cur.append((-d[0, 1] * 1e3, d[0, 2]))
    info('model', 'TPH2501_simplify supply current at 0 and 30 mA of output load (V+ source)',
         f'{cur[0][0]:.2f} mA at {cur[0][1]:.2f} V out, {cur[1][0]:.2f} mA at {cur[1][1]:.2f} V out ({cur[1][1]/33*1e3:.0f} mA load)',
         'the macromodel draws no supply current for its output current; supply-pin current is therefore added analytically (IQ + I out)')
    # closed-loop G=1 bandwidth, RF 25 ohm, VS 5 V, as the datasheet table and whatif smoke/g1.cir
    txt = (f"* G=1 RF 25\n{core.model_text().replace('@VENDOR@', os.path.relpath(core.VENDOR, core.NETDIR))}\n"
           "Vp vp 0 5\nVm vm 0 2.5\nVin in vm dc 0 ac 1\nXU in fb vp 0 out TPH2502\nRF out fb 25\nRL out vm 1k\n")
    h, d, log = core.wr('m_g1', txt, 'ac dec 60 1e4 2e9', ['v(out)'])
    f = d[:, 0]; g = np.abs(d[:, 1] + 1j * d[:, 2]); g /= g[0]
    f3 = f[np.where(g < 1 / np.sqrt(2))[0][0]]
    info('model', 'G=+1, RF 25 ohm, VS 5 V small-signal -3 dB', f'{f3/1e6:.0f} MHz (datasheet 250 MHz typ)', 'model is slower than the part: conservative for bandwidth, and the closed-loop results below are for the model')
    # noise density at 1 MHz
    f, n = core.noise('m_nz', dict(topo='Single', Cout=0, Rf=1.0, Rg1=1e9, Rg2=1e9, Rvr=1.0, Cf=0.0, Rbin=1e-3, Rbpl=1e12), f1=1e3, f2=1e8)
    OUT['model_en_1M_nV'] = float(np.interp(1e6, f, n) * 1e9)


# ------------------------------------------------------------------------------------------------------------ DC
def spice_dc(p, vds, load='hiz'):
    b = core.build(dict(p, load=load), analysis='')
    h, d, log = core.wr('dc', b, 'dc Vdac 0.5 2.9 0.0025', ['v(bnc)'])
    return np.interp(vds, d[:, 0], d[:, 1])


def analytic_out(p, vd, vrail):
    """design.py's map evaluated for one parameter set (no tolerance), as ngspice's DC.  vos taken as 0."""
    Rg2 = p['Rg2'] + p['Rvr']
    Gs0 = 1 + p['Rf'] * (1 / p.get('Rg1', float('inf')) + 1 / Rg2)
    kin = p['Rbpl'] / (p['Rbin'] + p['Rbpl'])
    return Gs0 * kin * vd - p['Rf'] / Rg2 * vrail


def case_dc():
    p = dict(Rf=D['Rf'], Rg1=D['Rg1'], Rg2=D['Rg2'], Rvr=D['Rvr'], Rbin=D['Rbin'], Rbpl=D['Rbpl'])
    vds = (1.1, 1.4, 1.6745, 2.0, 2.4)
    sp = spice_dc(dict(rails='nom'), vds)
    an = np.array([analytic_out(p, v, D['vref']) for v in vds])
    err = np.abs(sp - an).max()
    add('DC', 'ngspice DC transfer against the closed-form map (design.py), 5 DAC levels, nominal rails', '<= 2 mV',
        f'{err*1e3:.2f} mV', f'{2-err*1e3:+.2f} mV', err < 2e-3,
        f'outputs {", ".join(f"{x:.3f}" for x in sp)} V at DAC {", ".join(str(v) for v in vds)} V')
    OUT['dc_nom'] = dict(vd=list(vds), out=[float(x) for x in sp])
    gain = (sp[-1] - sp[0]) / (vds[-1] - vds[0])
    h2, d2, _ = core.wr('dcfull', core.build(dict(rails='weak'), analysis=''), 'dc Vdac 0.5 2.9 0.0025', ['v(bnc)'])
    info('AW-1', 'ngspice DC transfer at the measured window ends, weak rails, nominal parts', f'DAC 0.578 V -> {np.interp(0.578, d2[:,0], d2[:,1]):.3f} V, 2.771 V -> {np.interp(2.771, d2[:,0], d2[:,1]):.3f} V', 'nominal window, AREF 3.27 V; the corners are the Monte Carlo and hard-corner rows below')
    lo_, hi_ = np.interp(0.578, d2[:, 0], d2[:, 1]), np.interp(2.771, d2[:, 0], d2[:, 1])
    info('AW-1', 'nominal board (AREF 3.27 V, measured window, nominal parts, REF3030E 3.000 V offset), commandable ends with 4 % of the window kept free at each end', f'{lo_+0.04*(hi_-lo_):+.3f} V to {hi_-0.04*(hi_-lo_):+.3f} V into high impedance',
         'the nominal board reaches more than the guaranteed +%s V; the window ends are the weak-rail ngspice figures above' % design.OUT_HI)
    info('AW-7', 'ngspice nominal gain and centre output (DAC at 1.6745 V)', f'gain {gain:.4f}, centre {sp[2]*1e3:.0f} mV', 'nominal AREF 3.27 V window; the Monte Carlo below carries the tolerances')


def case_mc():
    n = 200000
    lim_top = design.TOP_END_LIM
    worst = {}
    for scen in 'AB':
        for aref in (3.20, 3.25, 3.30):
            m = design.dc_mc(V, scen, aref, n=n, seed=11)
            w = worst.setdefault(scen, dict(use=0, edge=0, lsb=0, g=[9, 0], off=[9, -9], top=-9, topmin=9, bot=9, botmax=-9, reach=0.0, tg=[]))
            w['use'] = max(w['use'], m['use'].max()); w['edge'] = max(w['edge'], m['edge'].max())
            w['lsb'] = max(w['lsb'], m['lsb'].max())
            w['g'] = [min(w['g'][0], m['gain'].min()), max(w['g'][1], m['gain'].max())]
            w['off'] = [min(w['off'][0], m['off'].min()), max(w['off'][1], m['off'].max())]
            span = m['out_hi'] - m['out_lo']
            w['top'] = max(w['top'], m['out_hi'].max()); w['topmin'] = min(w['topmin'], m['out_hi'].min())
            w['bot'] = min(w['bot'], m['out_lo'].min()); w['botmax'] = max(w['botmax'], m['out_lo'].max())
            w['tg'].append((m['out_hi'] - 0.04 * span)); w['botg'] = max(w.get('botg', -9), (m['out_lo'] + 0.04 * span).max())
    for scen, nm in (('A', 'window theory 1/6..5/6 AREF, +-30 mV centring'), ('B', 'measured board window 0.578..2.771 V at 3.27 V, scaled with AREF, +-5 mV')):
        w = worst[scen]
        tg = np.concatenate(w['tg'])
        add('AW-1', f'window top end (output at the DAC window maximum), 1 % parts, REF3030E offset 2.994..3.006 V, AREF 3.20..3.30 V [{scen}: {nm}]', f'<= {lim_top:.4f} V (D-V2-7)', f'{w["top"]:.3f} V', f'{lim_top-w["top"]:+.3f} V', w['top'] <= lim_top, f'{n} draws x 3 AREF; the supply-pin limit')
        add('AW-1', f'window use, width, same draws [{scen}]', '<= 92 %', f'{w["use"]*100:.1f} %', f'{(0.92-w["use"])*100:+.1f} %', w['use'] <= 0.92, f'range {design.OUT_LO} V to +{design.OUT_HI} V, the guaranteed range (D-V2-12)')
        add('AW-1', f'window use, position-aware (+{design.OUT_HI} / {design.OUT_LO} V ends against the window ends, 4 % kept at each end) [{scen}]', '<= 92 %', f'{w["edge"]*100:.1f} %', f'{(0.92-w["edge"])*100:+.1f} %', w['edge'] <= 0.92, 'the guaranteed range is the one this row passes at; +2.05 V would not')
        info('AW-1', f'highest top the stage can command with 4 % of the window kept free, every draw [{scen}]', f'{tg.min():.3f} V at the worst draw; window top end {w["topmin"]:.3f}..{w["top"]:.3f} V', f'{(tg >= design.OUT_HI).mean()*100:.1f} % of draws reach {design.OUT_HI} V inside the 92 % band; each board\'s actual top is measured at calibration')
        info('AW-1', f'window bottom end against the negative rail reach into high impedance ({design.RAIL_REACH_LO:.4f} V, ngspice, weak rail -1.9549 V) [{scen}]', f'{w["bot"]:.3f} V ({w["bot"]-design.RAIL_REACH_LO:+.3f} V)',
             'information (spec lead, rail-corner decision): the last unused window codes clip on the weak rail; AW-1 is judged on the commanded -1.5 V into 50 ohm (row below)')
        add('AW-1', f'commanded bottom -1.5 V stays inside the window with 4 % kept at its bottom end [{scen}]', '<= -1.5 V', f'{w["botg"]:.3f} V (highest window bottom + 4 % of the window)', f'{-1.5-w["botg"]:+.3f} V', w['botg'] <= -1.5, 'the position-aware row\'s other half')
        add('AW-2', f'one DAC code at the output, ideal 12-bit [{scen}]', '<= 1.5 mV', f'{w["lsb"]*1e3:.3f} mV', f'{(1.5e-3-w["lsb"])*1e3:+.3f} mV', w['lsb'] <= 1.5e-3)
        info('AW-7', f'gain and output at the window centre [{scen}]', f'gain {w["g"][0]:.3f}..{w["g"][1]:.3f}, centre {w["off"][0]*1e3:.0f}..{w["off"][1]*1e3:.0f} mV', 'no calibration; the precision ADC calibrates both (AW-7)')
    OUT['mc'] = {k: dict(use=float(v['use']), edge=float(v['edge']), lsb=float(v['lsb']), g=[float(x) for x in v['g']], off=[float(x) for x in v['off']], top=float(v['top']), topmin=float(v['topmin']), bot=float(v['bot'])) for k, v in worst.items()}
    # hard corners: every resistor at +-1 %, rail, AREF, centring shift and VOS at both limits, both scenarios
    e = design.corner_stats(V)
    add('AW-1', 'window top end, hard corners (five resistors at +-1 %, rail, AREF, centring and VOS at both limits, both scenarios)', f'<= {lim_top:.4f} V (D-V2-7)', f'{e["top"]:.3f} V', f'{lim_top-e["top"]:+.3f} V', e['top'] <= lim_top, 'the stack of every tolerance at once; the binding row of the design')
    add('AW-1', 'window use, width, hard corners', '<= 92 %', f'{e["use"]*100:.1f} %', f'{(0.92-e["use"])*100:+.1f} %', e['use'] <= 0.92, f'range {design.OUT_LO} V to +{design.OUT_HI} V')
    add('AW-1', 'window use, position-aware, hard corners', '<= 92 %', f'{e["edge"]*100:.1f} %', f'{(0.92-e["edge"])*100:+.1f} %', e['edge'] <= 0.92, f'the guaranteed top: {e["tg"]:.4f} V is the commandable top with 4 % kept free at the worst corner (+{design.OUT_HI} V is it rounded down); {e["topmin"]:.4f} V is the lowest window top end, no band kept')
    info('AW-1', 'window bottom end against the negative rail reach into high impedance, hard corners', f'{e["bot"]:.3f} V against {design.RAIL_REACH_LO:.4f} V ({e["bot"]-design.RAIL_REACH_LO:+.3f} V)',
         'information: codes below about -1.923 V clip on the weak rail; the calibration sweep drops any level whose sense reading stops following the DAC code')
    add('AW-2', 'one DAC code, hard corners', '<= 1.5 mV', f'{e["lsb"]*1e3:.3f} mV', f'{(1.5e-3-e["lsb"])*1e3:+.3f} mV', e['lsb'] <= 1.5e-3)
    OUT['mc_corner'] = {k: float(x) for k, x in e.items() if not isinstance(x, dict)}
    OUT['mc_corner_arg'] = {k: (x if not isinstance(x, dict) else {a: float(b) for a, b in x.items()}) for k, x in e['corner'].items()}
    # ngspice cross-check of the Monte Carlo: 60 random parts draws, output against the closed form
    rg = np.random.default_rng(5)
    errs = []
    names = ['Rf', 'Rg2', 'Rvr', 'Rbin', 'Rbpl']
    for k in range(60):
        pp = {nm: V[nm] * (1 + rg.uniform(-0.01, 0.01)) for nm in names}
        vr_ = rg.uniform(*design.VREF3030)
        vds = (1.1, 2.4)
        b = core.build(dict(pp, vref=vr_, load='hiz'), analysis='')
        h, d, log = core.wr('mcx', b, 'dc Vdac 1.1 2.4 1.3', ['v(bnc)'])
        an = np.array([analytic_out(pp, v, vr_) for v in vds])
        errs.append(np.abs(d[:, 1] - an).max())
    e_ = max(errs)
    add('AW-7', 'Monte Carlo transfer map against ngspice, 60 random parts/rail draws, DAC 1.1 and 2.4 V (inside the rails for every draw)', '<= 2 mV', f'{e_*1e3:.2f} mV', f'{2-e_*1e3:+.2f} mV', e_ < 2e-3, 'the closed form that the 200000-draw Monte Carlo uses reproduces the netlist')
    OUT['mc_xcheck_mV'] = float(e_ * 1e3)


# ---------------------------------------------------------------------------------------------------- swing, short
def sat_op(p, load, dac, extra_vecs=()):
    b = core.build(dict(p, sat=True, load=load, dac=dac), analysis='')
    vecs = ['v(vo)', 'v(bnc)', '@rba[i]'] + (['@rbb[i]'] if p.get('topo', 'Par') == 'Par' else [])
    h, d, log = core.wr('sat', b, 'op', vecs)
    return np.append(d[0, 1:], [0.0] * (4 - len(d[0, 1:])))


def vd_for(out, rails_v, p=None):
    """DAC pin voltage that commands `out` at the stage output (nominal parts, no offset voltage), from design.py's map."""
    q = dict(D); q.update(p or {})
    Rg2 = q['Rg2'] + 2.2
    Gs0 = 1 + q['Rf'] * (1 / q['Rg1'] + 1 / Rg2); kin = q['Rbpl'] / (q['Rbin'] + q['Rbpl'])
    return (out + q['Rf'] / Rg2 * rails_v) / (Gs0 * kin)


def reach_bottom(vn, load):
    """Stage output at the negative-rail clip (DAC at 0 V, derived 11.5 ohm per rail), weak +rail, negative rail vn."""
    h, d, _ = core.wr('reach', core.build(dict(sat=True, rails=(RAILS['weak'][0], vn), load=load, dac=0.0), analysis=''), 'op', ['v(vo)'])
    return float(d[0, 1])


def case_swing():
    """AW-1 reach with the derived output saturation (TPH2502_SAT, 11.5 ohm per rail, *(check)*): the top is no longer limited by the
    swing, and these rows show it: the output with saturation equals the output of the unsaturated model."""
    lim = design.TOP_END_LIM
    res = {}
    for rails in ('weak', 'strong'):
        vp_, vn_ = RAILS[rails]
        for rout in (49.5, 50.0, 50.5):
            for load in ('hiz', 'r50'):
                for tag, cmd in (('top', design.OUT_HI), ('wtop', lim), ('bot', design.OUT_LO)):
                    vd = vd_for(cmd, D['vref'])
                    r = sat_op(dict(rails=rails, Rout=rout), load, vd)
                    ideal = core.wr('ideal', core.build(dict(rails=rails, Rout=rout, load=load, dac=vd), analysis=''), 'op', ['v(vo)', 'v(bnc)'])[1][0, 1:]
                    res[(rails, rout, load, tag)] = (r, ideal)
    # reach: output at the command into high impedance, against the same circuit with the output stage unsaturated
    def worst_dev(load, tag):
        return max(abs(v[0][1] - v[1][1]) for k, v in res.items() if k[2] == load and k[3] == tag)
    for load, nm in (('hiz', 'high impedance'), ('r50', '50 ohm')):
        for tag, cmd, lab in (('top', design.OUT_HI, f'{design.OUT_HI} V'), ('wtop', lim, f'{lim:.4f} V (the window top end)'), ('bot', design.OUT_LO, f'{design.OUT_LO} V')):
            dev = worst_dev(load, tag)
            add('AW-1', f'reach into {nm}: DAC commanding {lab}, both rail corners, Rout 49.5..50.5: output with the derived saturation against the unsaturated model', '<= 5 mV difference (saturation does not bind)',
                f'{dev*1e3:.2f} mV', f'{5-dev*1e3:+.2f} mV', dev < 5e-3, 'saturation 11.5 ohm per rail is derived from the datasheet text *(check: no swing-versus-current curve)*' if load == 'r50' else '')
    # headroom into 50 ohm at the window top end, weak rail, the stage output and its current
    r = res[('weak', 49.5, 'r50', 'wtop')][0]
    vo, bnc, ia, ib = r
    iout = ia + ib
    info('AW-1', 'op-amp output at the window top end into 50 ohm (weak rail, Rout 49.5 ohm)', f'{vo:.3f} V at {iout*1e3:.1f} mA, {RAILS["weak"][0]-vo:.2f} V under the +rail (the 50 ohm swing limit, D-V2-8, no longer binds)', f'BNC {bnc:.3f} V')
    r = res[('weak', 49.5, 'r50', 'bot')][0]
    info('AW-1', 'op-amp output at the commanded bottom -1.5 V into 50 ohm (weak negative rail)', f'{r[0]:.3f} V at {-(r[2]+r[3])*1e3:.1f} mA sunk, {r[0]-RAILS["weak"][1]:.2f} V above the -rail', f'BNC {r[1]:.3f} V')
    OUT['swing'] = {f'{k[0]}|{k[1]}|{k[2]}|{k[3]}': [[float(x) for x in v[0]], [float(x) for x in v[1]]] for k, v in res.items()}
    # negative-rail reach on the 1 % feedback corners (../powercal/design.md), and the proposal that restores the window bottom
    reach = reach_bottom
    r50 = reach(RAILS['weak'][1], 'r50')
    add('AW-1', 'commanded bottom -1.5 V reachable into 50 ohm at the weak negative rail -1.9549 V: the stage output clips at', f'<= {design.OUT_LO} V', f'{r50:.3f} V', f'{design.OUT_LO-r50:+.3f} V', r50 <= design.OUT_LO,
        'the pass/fail row for the bottom end (spec lead): 11.5 ohm per rail is derived *(check)*; into high impedance the clip is -1.923 V')
    info('AW-1', 'negative-rail reach of the stage output at the weak rail -1.9549 V (derived 11.5 ohm per rail): high impedance / into 50 ohm', f'{reach(RAILS["weak"][1], "hiz"):.3f} V / {reach(RAILS["weak"][1], "r50"):.3f} V',
         f'commanded -1.5 V needs {abs(design.OUT_LO):.1f} V: {design.OUT_LO-reach(RAILS["weak"][1], "r50"):+.2f} V to spare into 50 ohm; the power stream\'s -1.69 V into 50 ohm figure used 22 mA and no macro offset')
    vn_prop = -1.22 * (1 + 0.66) * (1.9549 / 2.0032)     # PROPOSAL, not the design: R3 = 56k + 10k = 66k (nominal -2.0252 V), weak corner scaled as the power stream's
    info('AW-1', 'PROPOSAL (not in the design): LM27762 R3 = 56k + 10k = 66k (nominal V- -2.0252 V): weak rail %.4f V, strong %.4f V, strong sum with +3.4172 V = %.4f V' % (vn_prop, -1.22 * 1.66 * (2.0525 / 2.0032), 3.4172 + 1.22 * 1.66 * (2.0525 / 2.0032)),
         f'reach into high impedance {reach(vn_prop, "hiz"):.4f} V (window bottom {design.corner_stats(V)["bot"]:.3f} V: {design.corner_stats(V)["bot"]-reach(vn_prop, "hiz"):+.3f} V), into 50 ohm {reach(vn_prop, "r50"):.3f} V', 'restores the window-bottom rows; costs 22 mV of the 5.5 V sum margin (30 mV -> 7.6 mV); the weak +rail and PR-2 are unchanged')
    s = sat_op(dict(rails='weak', topo='Single'), 'r50', vd_for(lim, D['vref']))
    info('AW-1', 'for comparison, ONE half alone into 50 ohm at the window top end (weak rail)', f'BNC {s[1]:.3f} V (op-amp output {s[0]:.3f} V, {(s[0]-s[1]) / 49.5 * 1e3:.1f} mA)', 'one half alone would now also reach the top end (the swing no longer needs two); both halves stay because V2-2 leaves no spare half and the paralleled outputs share the short current')


def case_short():
    """PW-3: an indefinite short at the BNC.  The current is the stage output divided by the back-termination, so the window top end
    (the output when the DAC is at the window's top code) sets it; the corner that gives the highest top end is simulated in ngspice."""
    e = design.corner_stats(V)
    cT, cB = e['corner'], e['corner_lo']
    IQ = 0.015            # TPH2502 IQ max, two halves, datasheet p4
    res = {}
    for tag, c in (('top', cT), ('bottom', cB)):
        w = c['w']
        p = dict(Rf=w['Rf'], Rg2=w['Rg2'], Rvr=w['Rvr'], Rbin=w['Rbin'], Rbpl=w['Rbpl'], Rout=49.5, vref=c['vo'], rails=RAILS['nom'] if tag == 'top' else RAILS['weak'])
        kin = w['Rbpl'] / (w['Rbin'] + w['Rbpl'])
        dac = (c['hi'] if tag == 'top' else c['lo']) + c['vos'] / kin       # the op-amp offset voltage as a DAC shift
        vo, bnc, ia, ib = sat_op(p, 'short', dac)
        res[tag] = dict(vo=float(vo), i=float(ia + ib), vp=float(RAILS['nom'][0]), win=float(c['top'] if tag == 'top' else c['bot']))
    t, bt = res['top'], res['bottom']
    add('PW-3', 'indefinite short to ground at the BNC, DAC at the highest window code at the worst hard corner (Rout 49.5 ohm): output current', 'information (sets the supply-pin row)',
        f'{t["i"]*1e3:.1f} mA at stage output {t["vo"]:.3f} V (window top end {t["win"]:.3f} V / 49.5 ohm = {t["win"]/49.5*1e3:.1f} mA)', '', True, 'the 11.5 ohm per rail saturation *(check)* leaves the output at its commanded value at this current')
    isup = IQ + t['i']
    add('PW-3', 'indefinite short: current through the +supply pin at that corner, IQ max (2 x 7.5 mA) plus the output current, against "Current at Supply Pins +-60 mA"', '<= 60 mA',
        f'{isup*1e3:.1f} mA ({IQ*1e3:.0f} mA + {t["i"]*1e3:.1f} mA)', f'{60-isup*1e3:+.1f} mA', isup <= 0.060, 'D-V2-7 sets it: the window top end row above, in mA; the datasheet states no duration for the rating *(check)*')
    isb = IQ + abs(bt['i'])
    add('PW-3', 'indefinite short: current through the -supply pin at the lowest window bottom end (weak negative rail, Rout 49.5 ohm)', '<= 60 mA',
        f'{isb*1e3:.1f} mA ({IQ*1e3:.0f} mA + {abs(bt["i"])*1e3:.1f} mA, stage output {bt["vo"]:.3f} V)', f'{60-isb*1e3:+.1f} mA', isb <= 0.060, 'the stage reaches the bottom end into the short only if the 11.5 ohm per rail saturation holds *(check)*')
    vpl = t['vp']
    p_amp = (vpl - t['vo']) * t['i']
    p_q = (vpl - RAILS['nom'][1]) * IQ
    tj = 25 + 158 * (p_amp + p_q)
    add('PW-3', 'indefinite short at the top-end corner: op-amp dissipation plus quiescent at IQ max, junction at 25 C ambient, SOP-8 158 C/W', '<= 150 C (abs max junction)',
        f'{tj:.0f} C ({p_amp*1e3:.0f} mW output + {p_q*1e3:.0f} mW quiescent)', f'{150-tj:+.0f} K', tj <= 150, 'thermal shutdown also exists (datasheet), not modelled; VT-6 logs the package temperature')
    # the reset state: DAC0 at 3.3 V (AW-8) with the short: the stage saturates near the rail
    rr = []
    for rails in ('weak', 'strong'):
        rr.append((rails,) + tuple(float(x) for x in sat_op(dict(rails=rails, Rout=49.5), 'short', 3.3)))
    rmax = max(r[1] and (r[3] + r[4]) for r in rr)
    add('PW-3', 'indefinite short while DAC0 sits at 3.3 V (the Due reset level, AW-8): supply-pin current, strong rail, Rout 49.5 ohm; ACCEPTED as a transient (D-V2-12)', 'accepted transient: 60 mA rating exceeded for the reset fall only',
        f'{(IQ + rmax)*1e3:.0f} mA ({IQ*1e3:.0f} mA + {rmax*1e3:.0f} mA, stage output {max(r[1] for r in rr):.2f} V)', f'{60-(IQ+rmax)*1e3:+.0f} mA', True,
        'accepted (D-V2-12). Duration: not milliseconds. records/dac0-reset-montreal5.json (montreal5): DAC0 jumps to 3.3 V, then falls about linearly to 0 V over about 1.4 s; its trace envelope is above the 2.8 V window top for about 0.2 to 0.3 s (derived from the 0.1 s envelope steps) *(check)*; the rating states no duration')
    rr0 = [sat_op(dict(rails=rails, Rout=49.5), 'short', 0.0) for rails in ('weak', 'strong')]
    i0 = max(abs(r[2] + r[3]) for r in rr0)
    add('PW-3', 'indefinite short while DAC0 sits at 0 V (boot level): supply-pin current on the -pin, Rout 49.5 ohm', '<= 60 mA',
        f'{(IQ + i0)*1e3:.0f} mA ({IQ*1e3:.0f} mA + {i0*1e3:.0f} mA, stage output {min(r[0] for r in rr0):.2f} V)', f'{60-(IQ+i0)*1e3:+.0f} mA', IQ + i0 <= 0.060, 'the stage clips at the negative rail; the same derived saturation')
    OUT['short'] = dict(res=res, reset=rr, boot=[[float(x) for x in r] for r in rr0], tj=float(tj), isup=float(isup), isb=float(isb))


# ------------------------------------------------------------------------------------------------- AC: bandwidth, PM
def bw(p, load, ac=('dac',)):
    b = core.build(dict(p, load=load), analysis='', ac=ac)
    h, d, log = core.wr('bw', b, 'ac dec 80 1e3 1e9', ['v(bnc)'])
    f = d[:, 0]; g = np.abs(d[:, 1] + 1j * d[:, 2]); g0 = g[0]
    i = np.where(g < g0 / np.sqrt(2))[0][0]
    w = (np.log(1 / np.sqrt(2)) - np.log(g[i - 1] / g0)) / (np.log(g[i] / g0) - np.log(g[i - 1] / g0))
    f3 = np.exp(np.log(f[i - 1]) + w * (np.log(f[i]) - np.log(f[i - 1])))
    return g0, f3, g.max() / g0


def case_ac():
    res = {}
    for load in ('hiz', 'r50', 'cap100', 'cable_scope'):
        for rails in ('weak', 'strong'):
            res[(load, rails)] = bw(dict(rails=rails), load)
    # component spread on the output pole and the 8 MHz: C0G 330 pF +-5 %, Rout +-1 %, op-amp model unchanged
    cr = []
    for cs in (-1, 1):
        for rs in (-1, 1):
            for cf in (-1, 1):
                cr.append(bw(dict(Cout=330e-12 * (1 + 0.05 * cs), Rout=50 * (1 + 0.01 * rs), Cf=10e-12 * (1 + 0.05 * cf)), 'hiz')[1])
    f_hiz = min(res[('hiz', r)][1] for r in ('weak', 'strong')) / 1e6
    f_hiz_c = min(cr) / 1e6
    add('AW-3', 'small-signal -3 dB bandwidth, DAC pin to BNC, 1 Mohm || 15 pF load, both rail corners', '>= 8 MHz', f'{f_hiz:.2f} MHz', f'{f_hiz-8:+.2f} MHz', f_hiz >= 8)
    add('AW-3', 'the same with C0G 330 pF +-5 %, Cf 10 pF +-5 % and the 50 ohm +-1 % at their worst corners (the output pole is theirs)', '>= 8 MHz', f'{f_hiz_c:.2f} MHz', f'{f_hiz_c-8:+.2f} MHz', f_hiz_c >= 8, f'range {f_hiz_c:.2f}..{max(cr)/1e6:.2f} MHz')
    f50 = min(res[('r50', r)][1] for r in ('weak', 'strong')) / 1e6
    add('AW-3', 'bandwidth into 50 ohm (amplitude is half; -3 dB relative to its own DC)', '>= 8 MHz', f'{f50:.1f} MHz', f'{f50-8:+.1f} MHz', f50 >= 8)
    fcap = min(res[('cap100', r)][1] for r in ('weak', 'strong')) / 1e6
    add('AW-3', 'bandwidth into 100 pF (about 1 m of RG-58 *(check)*) open at the far end', '>= 8 MHz (information for a cable)', f'{fcap:.2f} MHz', f'{fcap-8:+.2f} MHz', True,
        'the output pole is 50 ohm x (330 pF + load): a cable lowers it; version 1 had no such pole (BW 15 MHz); see design.md "what the pole costs"')
    pk = max(res[(l, r)][2] for l in ('hiz', 'r50', 'cap100') for r in ('weak', 'strong'))
    info('AW-3', 'peaking of the small-signal response', f'{20*np.log10(pk):.3f} dB', 'flat to the pole; no peaking')
    g_hiz = res[('hiz', 'weak')][0]
    info('AW-7', 'small-signal gain at low frequency, nominal parts', f'{g_hiz:.4f} hi-Z, {res[("r50", "weak")][0]:.4f} into 50 ohm', 'the 50 ohm row is the exact half')
    OUT['bw'] = {f'{k[0]}|{k[1]}': [float(x) for x in v] for k, v in res.items()}
    OUT['bw_corner'] = [float(x) for x in cr]


def case_pm():
    """AN-1 on the vendor macro and on the datasheet-fitted behavioural models (kvm_01 / whatif/tph2502/beh): BEH21 and BEH60 are
    the ones that count, the macro is optimistic (open-loop PM 69.5 deg against about 56 deg traced from the datasheet)."""
    allrows = {}
    for model in ('vendor', 'BEH21', 'BEH60'):
        rows = []
        for load in ('hiz', 'r50', 'cable_open', 'cap330', 'cap1n'):
            for rails in ('weak', 'strong'):
                for cfb in (2e-12, 6e-12, 10e-12):
                    fc, pmv, gm, a0, _ = core.phase_margin(dict(rails=rails, cfb=cfb, model=model), load, tag='pm')
                    rows.append((load, rails, cfb, fc, pmv))
        allrows[model] = rows
        w = min(rows, key=lambda r: r[4])
        add('AN-1', f'phase margin of the gain stage (loop broken at the inverting pins), {model}: loads hi-Z+15 pF / 50 ohm / 5 ns cable open / 330 pF / 1 nF behind the 50 ohm, rails both corners, 2 / 6 / 10 pF at the inverting node', '>= 45 deg',
            f'{w[4]:.1f} deg ({w[0]}, {w[1]}, {w[2]*1e12:.0f} pF, crossover {w[3]:.1f} MHz)', f'{w[4]-45:+.1f} deg', w[4] >= 45,
            'with Cf 10 pF across Rf (design.md); the cap at the inverting node is the parasitic: LR-4 keeps it short' if model != 'vendor' else 'the vendor macro is optimistic; the BEH rows govern')
    OUT['pm'] = {m: [[r[0], r[1], r[2], float(r[3]), float(r[4])] for r in rr] for m, rr in allrows.items()}
    # the choice of the stability component, on BEH21 and BEH60 over every load, rail and node case (design.md "stability")
    scan = {}
    for lab, pp in (('none', dict()), ('Cpx 10 pF (+IN to ground)', dict(cpx=10e-12)), ('Cf 10 pF (across Rf)', None), ('Cf 9.5 pF (-5 % tolerance)', 'cf95')):
        pmin = 99
        for model in ('BEH21', 'BEH60'):
            for load in ('hiz', 'r50', 'cable_open', 'cap330', 'cap1n'):
                for cfb in (2e-12, 6e-12, 10e-12):
                    q = dict(model=model, cfb=cfb, rails='strong', Cf=0.0)
                    if pp is None: q['Cf'] = 10e-12
                    elif pp == 'cf95': q['Cf'] = 9.5e-12
                    else: q.update(pp)
                    pmin = min(pmin, core.phase_margin(q, load, tag='pms')[1])
        if lab.startswith('Cf'):
            bwv = bw(dict(rails='weak', Cf=9.5e-12 if pp == 'cf95' else 10e-12), 'hiz')[1] / 1e6
        else:
            bwv = bw(dict(rails='weak', Cf=0.0, **(pp or {})), 'hiz')[1] / 1e6
        scan[lab] = (float(pmin), float(bwv))
    OUT['stab_scan'] = scan
    info('AN-1', 'the stability component, minimum PM over BEH21+BEH60, every load, rails strong, 2/6/10 pF; -3 dB bandwidth hi-Z in the same parts', '; '.join(f'{k}: {v[0]:.1f} deg, {v[1]:.2f} MHz' for k, v in scan.items()),
         '10 pF is the smallest Basic C0G; Cpx costs the 8 MHz (it fails it), Cf does not')
    fc, pmv, gm, a0, _ = core.phase_margin(dict(Rf=1.0, Rg1=1e9, Rg2=1e9, Rvr=1.0, Cout=0.0, topo='Single', Cf=0.0, Rbin=1e-3, Rbpl=1e12), 'cap1n', tag='pm1')
    info('AN-1', 'a unity-gain follower of the same op-amp (vendor macro) into 1 nF behind the 50 ohm (a worse noise gain than the design), for scale', f'{pmv:.1f} deg', f'the design has noise gain {1 + D["Rf"]/D["Rg2"]:.2f}')


# ---------------------------------------------------------------------------------------------------------- transient
def tran(p, load, name, t1=1.0e-6, step=0.5e-9, v0=0.578, v1=2.771, tr=375e-9, t0=0.5e-6):
    src = f"Vdac dacs 0 PWL(0 {v0} {t0} {v0} {t0+tr} {v1} 10 {v1})"
    pp = dict(p, load=load, dacsrc=src + "\nRdacs dacs dac 1m", dac=v0)
    b = core.build(pp, analysis='', extra=TRAN_OPT)      # the default trapezoidal rule stalls on the lossless line; see TRAN_OPT
    h, d, log = core.wr(name, b, f'tran {step} {t1} 0 2n', ['v(bnc)', 'v(dac)'])
    tt = np.arange(0, t1, 0.5e-9)
    return tt, np.interp(tt, d[:, 0], d[:, 1]), np.interp(tt, d[:, 0], d[:, 2])


def edge_metrics(t, v, t0, tr):
    v0, v1 = v[(t < t0 * 0.9)].mean(), v[-1]
    lo, hi = v0 + 0.1 * (v1 - v0), v0 + 0.9 * (v1 - v0)
    ts = t[np.argmax(v >= lo)], t[np.argmax(v >= hi)]
    over = (v.max() - v1) / (v1 - v0) * 100 if v1 > v0 else (v1 - v.min()) / (v0 - v1) * 100
    band = 0.5e-3 / abs(v1 - v0) * 1  # 0.5 mV
    out = np.where(np.abs(v - v1) > 1.5e-3)[0]
    tset = t[out[-1]] if len(out) else t0
    return v0, v1, ts[1] - ts[0], over, tset


def case_tran():
    dac_sl = 2.193 / 375e-9 / 1e6                         # 5.85 V/us, the measured DAC edge (full window in 375 ns)
    tr = 1.2 / (dac_sl * 1e6)
    t, vb, vd = tran(dict(), 'hiz', 'tr_hiz', v0=1.1, v1=2.3, tr=tr)
    v0, v1, tr10, over, tset = edge_metrics(t, vb, 0.5e-6, tr)
    k = 10
    sl = np.max(np.abs((vb[k:] - vb[:-k]) / (t[k:] - t[:-k]))) / 1e6       # slope over 5 ns windows
    gain = (v1 - v0) / 1.2
    info('AW-3', 'slew the stage must carry: DAC edge 5.85 V/us *(check: 2.193 V in 375 ns, docs/hardware.md)* x the stage gain', f'{dac_sl*gain:.1f} V/us (gain {gain:.3f})', 'the datasheet slew is 180 V/us typ, the vendor macro 199 V/us: about 6 % of it is used')
    add('AW-3', 'slew: peak output slew (5 ns slope) for a 1.2 V DAC step at the measured DAC edge rate 5.85 V/us, against the model slew (199 V/us, whatif smoke/sr.cir)', 'no slew limiting: output slope within 10 % of DAC edge x gain',
        f'peak {sl:.1f} V/us against DAC edge x gain {dac_sl*gain:.1f} V/us', f'{sl/(dac_sl*gain):.2f} of the ideal', abs(sl / (dac_sl * gain) - 1) < 0.10, 'the peak is the DAC edge times the gain, about 8 % of the available slew')
    info('AW-3', 'DAC window step, hi-Z 15 pF: output 10-90 % rise, overshoot, settle to 1.5 mV (one code)', f'{tr10*1e9:.0f} ns, {over:.2f} %, {(tset-0.5e-6)*1e9:.0f} ns from the edge start', '1.2 V step at 5.85 V/us; settling to 1.5 mV is measured from the edge start')
    t, vb, vd = tran(dict(), 'ladder_open', 'tr_cab', v0=1.1, v1=2.3, tr=tr)
    v0c, v1c, tr10c, overc, tsetc = edge_metrics(t, vb, 0.5e-6, tr)
    info('AW-4', 'the same into a 1 m (5 ns) 50 ohm line (ten LC sections) open at the far end, BNC end', f'overshoot {overc:.2f} %, settle {(tsetc-0.5e-6)*1e9:.0f} ns', 'the 50 ohm back-termination absorbs the reflection')
    # ideal 2 ns edge into the cable: reflection absorbed -> overshoot
    t, vb, vd = tran(dict(), 'ladder_open', 'tr_cab2', tr=5e-9, t1=1e-6, step=1e-9, v0=1.0, v1=1.5, t0=0.2e-6)
    far = None
    v0c, v1c, tr10c, overc, tsetc = edge_metrics(t, vb, 0.2e-6, 2e-9)
    info('AW-4', '5 ns, 0.5 V step at the DAC pin into the open line (ten LC sections), BNC-end overshoot', f'{overc:.2f} % (the output pole sets a 25-30 ns edge here)', '')
    OUT['tran'] = dict(rise_ns=float(tr10*1e9), over=float(over), slew=float(sl))


# ---------------------------------------------------------------------------------------------------------------- noise
def noise_case():
    f, n = core.noise('nz', dict(), f1=10, f2=1e9, ppd=25)
    tot100 = core.integ(f, n ** 2, hi=100e6)
    tot1g = core.integ(f, n ** 2)
    dens = float(np.interp(1e6, f, n) * 1e9)
    # resistor-only part: replace the op-amp by a noiseless ideal (VCVS with GBW pole) with the same resistors
    txt = core.build(dict(), analysis='', ac=('dac',))
    # ideal op-amp: swap the model include for a subckt with the same pins
    ideal = (".subckt TPH2502 inp inn vp vn out\nEg a 0 inp inn 1e5\nRp1 a b 1k\nCp1 b 0 1.33u\nEb c 0 b 0 1\nRo c out 1\n.ends TPH2502\n")
    txt = txt.replace(core.model_text().replace('@VENDOR@', os.path.relpath(core.VENDOR, core.NETDIR)), ideal)
    ctl = ".control\nset wr_vecnames\nset wr_singlescale\nnoise v(bnc) Vdac dec 25 10 1G 1\nsetplot noise1\nwrdata @OUT@ onoise_spectrum\n.endc\n"
    t2 = txt.replace('.end\n', '') + ctl + '.end\n'
    out, log = core.run('nz_res', t2, None)
    d = np.loadtxt(out, skiprows=1)
    rres = core.integ(d[:, 0], d[:, 1] ** 2, hi=100e6)
    ratio = 6.5 / OUT.get('model_en_1M_nV', 9.33)
    amp_model = np.sqrt(max(tot100 ** 2 - rres ** 2, 0))
    ds100 = np.sqrt(rres ** 2 + (amp_model * ratio) ** 2)
    # LM27762 output noise 22 uV rms (10 Hz..100 kHz, flat; sim/awg report) through the offset path (Rg2 -> filter) and the op-amp PSRR
    # rail ripple 2 MHz class: transfer from each rail node to the BNC by ngspice, source amplitudes borrowed from sim/awg (check)
    xf = {}
    for src in ('vp', 'vn'):
        b = core.build(dict(), analysis='', ac=(src,))
        h, dd, log = core.wr('psrr', b, 'ac dec 40 100 1e9', ['v(bnc)'])
        xf[src] = (dd[:, 0], np.abs(dd[:, 1] + 1j * dd[:, 2]))
    def gat(s, fr): return float(np.interp(np.log(fr), np.log(xf[s][0]), xf[s][1]))
    ripple = 0.0
    amp = {'vp': 0.49e-3, 'vn': 0.38e-3}
    worst_f = None
    for f0 in (1.7e6, 2.0e6, 2.3e6):
        pw = 0.0
        for s in ('vp', 'vn'):
            for hm in range(1, 6):
                pw += (amp[s] / hm * gat(s, hm * f0)) ** 2 / 2
        if pw > ripple ** 2:
            ripple = np.sqrt(pw); worst_f = f0
    # LF rail noise: 22 uV rms flat 10 Hz-100 kHz on each rail, through the same transfers (flat at low f, taken at 1 kHz)
    lf = np.sqrt(sum((22e-6 * gat(s, 1e3)) ** 2 for s in ('vp', 'vn')))
    sup = np.sqrt(ripple ** 2 + lf ** 2)
    total_model = np.sqrt(tot100 ** 2 + sup ** 2)
    total_ds = np.sqrt(ds100 ** 2 + sup ** 2)
    add('AW-6', 'AFE-added noise at the BNC, quiet DC DAC, circuit .noise 10 Hz-100 MHz, the vendor model as it is (9.3 nV/rtHz op-amp)', f'<= {AW6_UV:g} uV rms', f'{tot100*1e6:.1f} uV', f'{AW6_UV-tot100*1e6:+.1f} uV', tot100 <= AW6_UV*1e-6,
        f'to 1 GHz {tot1g*1e6:.1f} uV; density at 1 MHz {dens:.1f} nV/rtHz; resistors alone {rres*1e6:.1f} uV')
    add('AW-6', 'the same with the op-amp noise scaled to the datasheet 6.5 nV/rtHz (x0.70), resistors unchanged', f'<= {AW6_UV:g} uV rms', f'{ds100*1e6:.1f} uV', f'{AW6_UV-ds100*1e6:+.1f} uV', ds100 <= AW6_UV*1e-6, '*(check)* the datasheet gives one point (1 MHz) and a graph to 10 MHz')
    add('AW-6', 'sum with rail noise: 22 uV rms per rail, and ripple 0.49 / 0.38 mV at 1.7-2.3 MHz with 1/n harmonics (sim/awg values *(check)*) through the simulated transfers, model noise', f'<= {AW6_UV:g} uV rms', f'{total_model*1e6:.1f} uV', f'{AW6_UV-total_model*1e6:+.1f} uV', total_model <= AW6_UV*1e-6,
        f'rails contribute {sup*1e6:.1f} uV (ripple {ripple*1e6:.1f}, LF {lf*1e6:.1f}), worst fundamental {worst_f/1e6 if worst_f else 0:.1f} MHz; datasheet-scaled total {total_ds*1e6:.1f} uV')
    OUT['noise'] = dict(model100=float(tot100), model1g=float(tot1g), ds100=float(ds100), res=float(rres), sup=float(sup), ripple=float(ripple), lf=float(lf),
                        total_model=float(total_model), total_ds=float(total_ds), dens1M=dens,
                        psrr_vp_2M=gat('vp', 2e6), psrr_vn_2M=gat('vn', 2e6))
    # a real op-amp's PSRR falls with its open-loop gain: ripple at the output ~ ripple x noise gain / A(f), A(f) = GBW / f
    # the rail's ripple reaches the supply PIN through the local filter (Rvp, Cdec): measured from the netlist, not assumed 1
    hpin = {}
    for s_, node in (('vp', 'vcc'), ('vn', 'vee')):
        b_ = core.build(dict(), analysis='', ac=(s_,))
        h_, d_, log_ = core.wr('pin_' + s_, b_, 'ac dec 40 100 1e9', [f'v({node})'])
        hpin[s_] = (d_[:, 0], np.abs(d_[:, 1] + 1j * d_[:, 2]))
    gpin = lambda s_, fr: float(np.interp(np.log(fr), np.log(hpin[s_][0]), hpin[s_][1]))
    OUT['noise']['pin_atten_2M'] = {s_: gpin(s_, 2e6) for s_ in ('vp', 'vn')}
    NG = 1 + D['Rf'] / (D['Rg2'] + D['Rvr'])        # noise gain, 1.83
    rp = 0.0
    for f0 in (1.7e6, 2.0e6, 2.3e6):
        pw = 0.0
        for s_ in ('vp', 'vn'):
            for hm in range(1, 6):
                pw += (amp[s_] / hm * gpin(s_, hm * f0) * NG / (120e6 / (hm * f0))) ** 2 / 2
        rp = max(rp, np.sqrt(pw))
    tot_rp = np.sqrt(tot100 ** 2 + lf ** 2 + rp ** 2)
    add('AW-6', 'sum again with the rail ripple through an op-amp-like PSRR (ripple x noise gain / A(f), A = 120 MHz / f), model noise', f'<= {AW6_UV:g} uV rms', f'{tot_rp*1e6:.1f} uV', f'{AW6_UV-tot_rp*1e6:+.1f} uV', tot_rp <= AW6_UV*1e-6, f'ripple term {rp*1e6:.1f} uV; the datasheet gives PSRR at DC and over temperature only *(check)*')
    OUT['noise']['ripple_opamp_like'] = float(rp)
    K_ = D['Rf'] / D['Rg2']
    ref_n = 51e-6 * K_      # REF3030E 51 uV rms, 10 Hz-10 kHz (E grade, ref30.pdf 6.5; models/ref3030_beh.lib) through the offset path, no filter
    tot_ref = np.sqrt(tot_rp ** 2 + ref_n ** 2)
    add('AW-6', 'the pessimistic-PSRR sum plus the REF3030E noise 51 uV rms (10 Hz-10 kHz) x K through Rg2 with no offset filter', f'<= {AW6_UV:g} uV rms', f'{tot_ref*1e6:.1f} uV', f'{AW6_UV-tot_ref*1e6:+.1f} uV', tot_ref <= AW6_UV * 1e-6,
        f'reference term {ref_n*1e6:.1f} uV; its noise above 10 kHz is a graph (ref30.pdf Fig. 6-13) and is *(check)*: it would take {np.sqrt(AW6_UV**2 - (tot_rp*1e6)**2)/K_/np.sqrt(10e6)*1e3:.0f} nV/rtHz flat to 10 MHz to use the rest of the margin')
    tot_rp_ds = np.sqrt(ds100 ** 2 + lf ** 2 + rp ** 2)
    info('AW-6', 'the same sum with the op-amp noise at the datasheet 6.5 nV/rtHz', f'{tot_rp_ds*1e6:.1f} uV', 'passes with the datasheet noise as well as with the model noise, which is 43 % high')
    info('AW-6', 'rail-to-output transfer at 2 MHz in the model (V/V)', f'+rail {gat("vp", 2e6):.2e}, -rail {gat("vn", 2e6):.2e}', 'the macromodel PSRR is not frequency-shaped like a real op-amp *(check)*: a real part is worse above its first pole')
    # loopback context: SC-6/AW-6 widen the Due's 0.64 mV floor
    due = 0.64e-3
    info('AW-6', 'effect on the Due floor (0.64 mV) of this noise through the AWG alone, amplified by 1 (loopback at the board input)', f'{(np.sqrt(due**2 + total_model**2)/due - 1)*100:.1f} % widening (model), {(np.sqrt(due**2 + total_ds**2)/due - 1)*100:.1f} % (datasheet-scaled)', 'docs/afe.md AW-6 reasoning')


# --------------------------------------------------------------------------------------------- start-up, forced, pins
def case_startup():
    """AW-8: rails ramp (orders and speeds), DAC0 floating/0/3.3 V and the reset trace; output extremes against the rails."""
    worst = dict(hi=-9, lo=9, case=None)
    rows = []
    for rails in ('weak', 'strong'):
        vp_, vn_ = RAILS[rails]
        for order, (tp, tn) in {'both': (0, 0), '+first': (0, 50e-6), '-first': (50e-6, 0)}.items():
            for tr in (20e-6, 2e-3):
              for refmode in ('follows', 'late'):
                for dacmode in ('0V', '3.3V', 'float', 'reset'):
                    if dacmode == '0V': src = "Vdac dacs 0 DC 0\nRdacs dacs dac 1m"
                    elif dacmode == '3.3V': src = "Vdac dacs 0 DC 3.3\nRdacs dacs dac 1m"
                    elif dacmode == 'float': src = "Vdac dacs 0 DC 0\nRdacs dacs dac 1G"
                    else: src = f"Vdac dacs 0 PWL(0 0 {tp+tr*0.2} 3.3 {tp+tr*0.8} 3.3 {tp+tr*0.8+tr} 0 {tp+tr*0.8+tr*3} 0 {tp+tr*0.8+tr*3+1e-9} 1.6745 10 1.6745)\nRdacs dacs dac 1m"
                    vsrc = (f"Vvp vpx 0 PWL(0 0 {tp} 0 {tp+tr} {vp_} 1 {vp_})\nVvn vnx 0 PWL(0 0 {tn} 0 {tn+tr} {vn_} 1 {vn_})")
                    # the REF3030E is powered from the +rail: 'follows' tracks it (3.0/3.3 of the ramp), 'late' starts when the rail has finished and takes 2 ms (datasheet turn-on to 0.1 % at 1 uF)
                    if refmode == 'follows': rs = f"Vrf vrfs 0 PWL(0 0 {tp} 0 {tp+tr} 3.0 1 3.0)"
                    else: rs = f"Vrf vrfs 0 PWL(0 0 {tp+tr} 0 {tp+tr+2e-3} 3.0 1 3.0)"
                    rs += "\nRzr vrfs vref 0.05\nCzr vref 0 1.1u"
                    b = core.build(dict(rails=rails, dacsrc=src, load='hiz', sat=True, refsrc=rs), analysis='', supply='src:' + vsrc, extra=TRAN_OPT)
                    tend = max(tp, tn) + tr * 6 + 10e-6 + (3e-3 if refmode == 'late' else 0)
                    h, d, log = core.wr('su', b, f'tran {tend/4000:.3e} {tend}', ['v(bnc)', 'v(vpx)', 'v(vnx)'])
                    v = d[:, 1]
                    # excursion against the rails present at that time
                    over_hi = (v - d[:, 2]).max()
                    under = (d[:, 3] - v).max()           # rail minus output, positive when the output is below the negative rail
                    rows.append((rails, order, tr, dacmode + '/' + refmode, float(v.max()), float(v.min()), float(over_hi), float(under)))
    mx = max(r[4] for r in rows); mn = min(r[5] for r in rows)
    ovr = max(r[6] for r in rows); und = max(r[7] for r in rows)
    add('AW-8', 'through rail ramps (3 orders x 20 us / 2 ms), the REF3030E following the +rail or 2 ms late, with DAC0 at 0 V, 3.3 V, floating and a reset trace, hi-Z: output extremes, both rail corners', 'within the AFE rails at every instant (at most 10 mV beyond; rails -2.05..+3.42 V at the 1 % feedback corners; V2 AW-8)', f'{mn:.3f}..{mx:.3f} V', f'beyond the +rail {max(ovr, 0)*1e3:.0f} mV, beyond the -rail {max(und, 0)*1e3:.0f} mV', ovr <= 0.010 and und <= 0.010,
        '48 start-up cases per rail corner; derived output saturation')
    OUT['startup'] = [list(r) for r in rows]
    st = [r for r in rows if r[1] == 'both' and r[3] == '3.3V/follows' and r[0] == 'strong']
    info('AW-8', 'DAC0 held at 3.3 V (reset level) with rails up: steady output', f'{max(r[4] for r in st):.3f} V', 'the output clips under the +rail: the stage gain times 3.3 V is far above the rail')
    return rows


def case_forced():
    """PR-4: a source forced onto the BNC through nothing but the cable.  The rule of docs/afe.md (the level at which the output stage
    stays within its rating through the 49.9 ohm with the output at the largest a DAC code commands) restated with this design's
    rating: the supply pin, 60 mA less the 15 mA quiescent, i.e. 45 mA, through 49.5 ohm (the back-termination at its low tolerance)."""
    I_PIN = 0.060 - 0.015
    top_c, bot_c = design.OUT_HI, design.OUT_LO
    e = design.corner_stats(V)
    # forced + level: the output sinks (Vf - Vout)/R; worst with the output at its lowest, the window bottom end of the worst corner
    lev_pos = I_PIN * 49.5 + e['bot']            # e['bot'] negative
    lev_neg = I_PIN * 49.5 - e['top']            # output sources (Vout - Vf)/R; worst with the output at its window top end
    lev_pos_c = I_PIN * 49.5 + bot_c
    lev_neg_c = I_PIN * 49.5 - top_c
    rows = []
    for level in (1.8, -1.8, 5.0, -5.0, lev_pos, -max(lev_neg, 0.0)):
        for pw in ('powered', 'unpowered'):
            for dac in ((vd_for(design.OUT_LO, D['vref']), vd_for(0.75, D['vref']), vd_for(design.OUT_HI, D['vref'])) if pw == 'powered' else (0.0,)):
                p = dict(sat=True, dac=dac, rails='strong')
                b = core.build(dict(p, load='open', Rout=49.5), analysis='', supply='dc' if pw == 'powered' else 'off',
                               extra=f"Vforce frc 0 DC {level}\nRfrc frc bnc 1m")
                h, d, log = core.wr('forced', b, 'op', ['v(bnc)', '@rba[i]', '@rbb[i]', '@rfrc[i]', 'v(vo)', 'v(fb)'])
                ia = d[0, 2] + d[0, 3]; ifr = d[0, 4]
                rows.append((level, pw, dac, float(ia), float(ifr), float(d[0, 5]), float(d[0, 6])))
    def imax(lv, pw): return max(abs(r[3]) for r in rows if r[1] == pw and abs(r[0] - lv) < 1e-9)
    add('PR-4', f'forced +{lev_pos:.2f} V at the BNC (the restated positive level), powered, DAC at the commanded ends and mid: pair output current', f'<= {I_PIN*1e3:.0f} mA (60 mA supply pin less 15 mA IQ)', f'{imax(lev_pos, "powered")*1e3:.0f} mA',
        f'{I_PIN*1e3-imax(lev_pos, "powered")*1e3:+.0f} mA', imax(lev_pos, 'powered') <= I_PIN, 'the rule of docs/afe.md with the rating that binds here')
    lv = -max(lev_neg, 0.0)
    add('PR-4', f'forced {lv:.2f} V at the BNC (the restated negative level), powered: pair output current', f'<= {I_PIN*1e3:.0f} mA', f'{imax(lv, "powered")*1e3:.0f} mA', f'{I_PIN*1e3-imax(lv, "powered")*1e3:+.0f} mA', imax(lv, 'powered') <= I_PIN,
        'the level is zero because the window top end is at the limit (D-V2-7): an output at the top end and a forced ground is the short')
    i18 = max(imax(1.8, 'powered'), imax(-1.8, 'powered'))
    info('PR-4', 'forced +-1.8 V (version 1 level) at the BNC, powered, DAC at the commanded ends and mid: pair output current', f'{i18*1e3:.0f} mA against {I_PIN*1e3:.0f} mA',
        f'not held, and the restated level above replaces it (accepted, D-V2-12); forced +-5 V (may damage): {max(imax(5.0, "powered"), imax(-5.0, "powered"))*1e3:.0f} mA')
    iun = max(imax(1.8, 'unpowered'), imax(-1.8, 'unpowered'))
    add('PR-4', 'forced +-1.8 V at the BNC, unpowered rails (0 V): current through the 50 ohm into the op-amp output', '<= 160 mA (abs max output current)', f'{iun*1e3:.0f} mA', f'{(160-iun*1e3):+.0f} mA', iun <= 0.160,
        '*(check)* the macromodel clamps the output to the rails through its diodes; the real output structure is not in the datasheet; the supply-pin limit does not apply with no supply, the input and ESD structures do')
    info('PR-4', 'level restated by the rule: 45 mA x 49.5 ohm minus the largest output the stage commands at the opposite end (positive: the lowest commanded -1.5 V / window bottom end; negative: the commanded top / window top end)',
         f'+{lev_pos_c:.2f} V (+{lev_pos:.2f} V with the window bottom end {e["bot"]:.2f} V) and {-lev_neg_c:+.2f} V (0 at the window top end {e["top"]:.3f} V)', 'against version 1\'s +-1.8 V: the lowered top end took the headroom the rule spends; accepted (D-V2-12). At the earlier +2.05 V top the figures were +0.73 / -0.18 V; at the guaranteed top they are +0.73 / %.2f V' % (-lev_neg_c))
    OUT['forced'] = [list(r) for r in rows]
    OUT['pr4'] = dict(lev_pos=float(lev_pos), lev_neg=float(lev_neg), lev_pos_c=float(lev_pos_c), lev_neg_c=float(lev_neg_c))


def case_pins():
    i = {x: abs(core.wr('pin', core.build(dict(dac=x), analysis=''), 'op', ['i(Vdac)'])[1][0, 1]) for x in (0.578, 2.75, 2.80, 3.3)}
    add('AW-5', 'DAC pin load at the DAC\'s own highest code (2.80 V: AREF 3.30 V, window top 2.771 V scaled, +5 mV; 2.4 kohm + 27 kohm to ground; the op-amp input is high impedance)', '<= 0.1 mA', f'{i[2.80]*1e6:.1f} uA', f'{100-i[2.80]*1e6:+.1f} uA', i[2.80] <= 100e-6, 'judged at the DAC\'s own output codes (D-V2-12); the 1 % parts add 1.5 %')
    info('AW-5', 'DAC pin load at 3.3 V (the Due reset level, outside the DAC window)', f'{i[3.3]*1e6:.1f} uA ({(i[3.3]/100e-6-1)*100:+.0f} % against 0.1 mA)', 'not a code the DAC can output in operation; accepted with the rows above (D-V2-12)')
    # PR-2: unpowered AFE, DAC0 driven: current through the 1.5 kohm into an input protection diode, hand calculation
    for v in (2.771, 3.3, 3.45):
        info('PR-2', f'unpowered AFE, DAC0 at {v} V: current into the input ESD diodes through 1.5 kohm', f'{(v-0.5)/1500*1e3:.1f} mA (diode drop 0.5 V assumed)', 'datasheet Note 3: input current limited to 10 mA beyond 0.5 V past a supply; the model has no input-to-supply diodes, so this is arithmetic *(check)*')
    info('PR-2', 'DAC pin voltage', 'held by the Due between 0.578 and 3.3 V; the AFE never drives the pin', 'the pin stays inside -0.2..3.45 V in every state because only the 1.5 kohm connects it')


def case_power():
    b = core.build(dict(load='r50', dac=1.6745), analysis='')
    h, d, log = core.wr('pw', b, 'op', ['i(Vvp)', 'i(Vvn)'])
    info('PW-1', 'supply currents, from the macromodel (it under-counts: no load current in its supply pins)', f'+rail {-d[0,1]*1e3:.1f} mA, -rail {d[0,2]*1e3:.1f} mA (nominal, 50 ohm load, DAC centre)', 'see the analytic budget in design.md')


# ------------------------------------------------------------------------------------------------------- the reference
def case_ref():
    """The AWG offset comes from the REF3030E (D-V2-12): its load, and what that load does to the reference (PA-2, SC-7)."""
    names = ['Rf', 'Rg2', 'Rbin', 'Rbpl']
    kin_n = V['Rbpl'] / (V['Rbin'] + V['Rbpl'])
    # ngspice: current out of the reference at DAC 0 V (boot, floating), the window ends, 3.3 V (reset)
    cur = {}
    for dac in (0.0, 0.55, 2.80, 3.3):
        h, d, _ = core.wr('refi', core.build(dict(dac=dac, load='hiz'), analysis=''), 'op', ['i(Vrf)'])
        cur[dac] = float(-d[0, 1])
    # worst corner: Rg2 -1 %, reference +0.2 %, vos +1 mV, kin high at the sink end
    def iref(vd, tol, vref, kin):
        return (vref - kin * vd) / (V['Rg2'] * (1 + tol))
    kin_hi = V['Rbpl'] * 1.01 / (V['Rbin'] * 0.99 + V['Rbpl'] * 1.01)
    i_src = iref(0.0, -0.01, design.VREF3030[1], kin_hi)
    i_snk = -iref(3.3, +0.01, design.VREF3030[0], kin_hi) if iref(3.3, 0.01, design.VREF3030[0], kin_hi) < 0 else 0.0
    i_win_lo = iref(0.55, -0.01, design.VREF3030[1], kin_hi); i_win_hi = iref(2.80, +0.01, design.VREF3030[0], kin_hi)
    others = 1.736e-3      # sim/powercal/report.md REF/src: ladder, both scope centres at -12 V, the sense default tie, ADS inputs (ladder alone 1.53 mA, scope 5.4 uA each)
    info('PA-2', 'AWG offset current out of the REF3030E, ngspice nominal, DAC 0 / 0.55 / 2.80 / 3.3 V', ' / '.join(f'{cur[x]*1e3:.2f}' for x in (0.0, 0.55, 2.80, 3.3)) + ' mA', 'the current flows into Rg2 toward the inverting node, which follows the + input')
    add('PA-2', 'REF3030E source current with every load at once: the AWG offset at its worst (DAC at 0 V: boot or floating; Rg2 -1 %, reference +0.2 %) plus the ladder, both scope centres, the sense default tie and the ADS inputs (sim/powercal REF/src 1.736 mA, of which ladder 1.53 mA and scope 2 x 5.4 uA)', '<= 10 mA (datasheet rating, source and sink)',
        f'{(i_src+others)*1e3:.2f} mA ({i_src*1e3:.2f} AWG + {others*1e3:.2f} others)', f'{10-(i_src+others)*1e3:+.2f} mA', i_src + others <= 10e-3, 'the powercal figure already carries a 0.165 mA AWG sense tie; it is counted once there and not removed here (conservative)')
    add('PA-2', 'REF3030E sink current: the AWG at DAC 3.3 V (reset level; the + node then sits above 3.0 V) plus the clamped scope inputs and the forced sense case (powercal 80 uA)', '<= 10 mA', f'{(i_snk+80e-6)*1e3:.2f} mA', f'{10-(i_snk+80e-6)*1e3:+.2f} mA', i_snk + 80e-6 <= 10e-3,
        'sink load regulation 150 ppm/mA against 15 ppm/mA source: at this current it moves the output by 0.5 to 2 ppm')
    dI = i_win_lo - i_win_hi
    dv = dI * 1e3 * 15e-6 * 3.0
    add('SC-7', 'the reference moves with the AWG level: change of the AWG offset current over the DAC window (0.55 to 2.80 V) x 15 ppm/mA x 3.0 V', '<= 3.0 mV (0.1 % fit share of 3 V, powercal)', f'{dI*1e3:.2f} mA -> {dv*1e6:.0f} uV', f'{(3e-3-dv)*1e6:+.0f} uV', dv <= 3e-3,
        'the host reads the reference with every reading; this is the movement between two readings. Static shift at 5.95 mA: %.0f uV (calibrated out)' % (i_src * 1e3 * 15e-6 * 3.0 * 1e6))
    zref = 0.05
    ac = dI * zref
    info('SC-9', 'AWG-to-scope coupling through the reference: the offset current swings %.2f mA over the window; at the REF output impedance %.2f ohm (15 ppm/mA x 3 V, DC; the high-frequency impedance is not in the datasheet text *(check)*) it moves the reference' % (dI * 1e3, zref), f'{ac*1e3:.2f} mV peak to peak, {ac*0.3725/0.4622*1e3:.2f} mV at the scope input (centre factor 0.3725, gain 0.4622 from sim/scope/design.md)', 'about 0.1 LSB of the scope ADC against SC-9\'s 2 LSB; no offset filter is fitted')
    OUT['ref'] = dict(cur={str(k): v for k, v in cur.items()}, i_src=float(i_src), i_snk=float(i_snk), dI=float(dI), dv=float(dv))


# -------------------------------------------------------------------------------------------------------------- guards
GUARDS = []


def guard(name, what, fn, broken, good):
    """Run fn(**broken) -> bool ok (must be False) and fn(**good) (must be True); record both."""
    rb, rg = fn(**broken), fn(**good)
    GUARDS.append(dict(name=name, what=what, broken_ok=bool(rb), good_ok=bool(rg)))
    print(('guard ok  ' if (not rb and rg) else 'GUARD BAD'), name, '| broken ->', rb, '| restored ->', rg, flush=True)
    assert (not rb) and rg, f'guard {name} does not discriminate'


def run_guards():
    def g_noise(Rf, Rg2, Cf):
        f, n = core.noise('g_nz', dict(Rf=Rf, Rg2=Rg2, Cf=Cf), f1=10, f2=1e9, ppd=15)
        return core.integ(f, n ** 2, hi=100e6) <= AW6_UV * 1e-6
    guard('noise', 'feedback network 100x (Rf 39k, Rg2 47k, no Cf) must fail AW-6 at 300 uV (it reads 617 uV); the output pole alone no longer decides AW-6',
          g_noise, dict(Rf=39e3, Rg2=47e3, Cf=0.0), dict(Rf=390.0, Rg2=470.0, Cf=10e-12))

    def g_bw(Cout):
        return bw(dict(Cout=Cout), 'hiz')[1] >= 8e6
    guard('bandwidth', 'Cout 1 nF must fail 8 MHz', g_bw, dict(Cout=1e-9), dict(Cout=330e-12))

    def g_bwcpx(cpx):
        return bw(dict(Cf=0.0, cpx=cpx), 'hiz')[1] >= 8e6
    guard('bandwidth, +IN capacitor', 'the rejected stability fix, Cpx 10 pF from +IN to ground (6.1 MHz), must fail 8 MHz; no Cpx passes', g_bwcpx, dict(cpx=10e-12), dict(cpx=0.0))

    def g_pm(Cf):
        return core.phase_margin(dict(Cf=Cf, model='BEH60', cfb=10e-12, rails='strong'), 'hiz', tag='g_pm')[1] >= 45
    guard('phase margin', 'Cf removed must fail 45 deg on BEH60 (10 pF at the inverting node, hi-Z)', g_pm, dict(Cf=0.0), dict(Cf=10e-12))

    def g_pm2(cfb):
        return core.phase_margin(dict(cfb=cfb, model='BEH60', rails='strong'), 'hiz', tag='g_pm')[1] >= 45
    guard('phase margin, node', '30 pF at the inverting node must fail 45 deg on BEH60 with Cf in place', g_pm2, dict(cfb=30e-12), dict(cfb=10e-12))

    lim = design.TOP_END_LIM

    def g_topend(Rbpl):
        v = dict(V); v['Rbpl'] = Rbpl
        return design.corner_stats(v)['top'] <= lim
    guard('window top end', 'Rbpl 30 kohm (the divider one Basic step up from 27 kohm) must fail the 2.2275 V top end (2.242 V); 27 kohm passes', g_topend, dict(Rbpl=30e3), dict(Rbpl=27e3))

    def g_tol(tol):
        return design.corner_stats(V, tol=tol)['top'] <= lim
    guard('tolerance', '5 % resistors must fail the top end that 1 % passes', g_tol, dict(tol=0.05), dict(tol=0.01))

    def g_rout(rout):
        # the top-end limit rewritten as the supply-pin row: current = top end / Rout + 15 mA IQ max <= 60 mA, with the Rout the board has
        return design.corner_stats(V)['top'] / rout + 0.015 <= 0.060 + 1e-9
    guard('supply-pin current, Rout', 'a 45 ohm back-termination (wrong Rout, 10 % low) must fail the 60 mA row that 49.5 ohm passes', g_rout, dict(rout=45.0), dict(rout=49.5))

    def g_ref(Rg2):
        v = dict(V); v['Rg2'] = Rg2
        return design.VREF3030[1] / (Rg2 * 0.99) + 1.736e-3 <= 10e-3
    guard('reference load', 'Rg2 300 ohm loads the REF3030E past its 10 mA rating; 510 ohm does not', g_ref, dict(Rg2=300.0), dict(Rg2=510.0))

    def g_range(th):
        return design.corner_stats(V, th=th)['edge'] <= 0.92
    guard('guaranteed range', 'commanding +1.86 V (the lowest window top end, no 4 % kept) must fail the position-aware 92 %; the guaranteed +1.71 V passes', g_range, dict(th=1.86), dict(th=1.71))

    def g_reach(vn):
        return reach_bottom(vn, 'r50') <= design.OUT_LO
    guard('bottom reach', 'a negative rail that does not reach -1.5 V into 50 ohm (-1.6 V: clips at -1.455 V) must fail the commanded-bottom row; the 1 % weak rail -1.9549 V passes', g_reach, dict(vn=-1.6), dict(vn=-1.9549))

    OLD = dict(Rf=560.0, Rg1=1000.0, Rg2=510.0, Rvr=2.2, Rbin=680.0, Rbpl=330e3)     # version 1's values, the +3.0 V top
    def g_oldtop(vals):
        return design.corner_stats(vals)['top'] / 49.5 + 0.015 <= 0.060
    guard('supply-pin current, old top', 'version 1 values (+3.0 V top, 3.1 V window top end) must fail the supply-pin row that the new values pass', g_oldtop, dict(vals=OLD), dict(vals=V))

    def g_short_sim(cmd):
        w = design.corner_stats(V)['corner']
        s_ = sat_op(dict(rails=RAILS['nom'], vref=w['vo'], Rout=49.5), 'short', vd_for(cmd, w['vo']))
        return 0.015 + s_[2] + s_[3] <= 0.060
    guard('supply-pin current, simulated', 'ngspice short with the stage commanded to +3.0 V must fail 60 mA; commanded to the 2.2275 V window top end it passes', g_short_sim, dict(cmd=3.0), dict(cmd=lim - 0.015))


def write_outputs():
    # the reference netlist (nominal, hi-Z load) and the parts list generated from the same dictionary
    open(os.path.join(core.HERE, 'awg.cir'), 'w').write(core.build(dict(load='hiz'), analysis='.op'))
    q = D
    parts = [
        ('R1,R2 (parallel)', '100 ohm 1 % 1206', 'C17901', 'AW-4 50 ohm back-termination: vo-side Rout, two in parallel = 50.0 ohm +-1 %, 110 mW each at the 44 mA short top (rated 250 mW)', 2),
        ('R3', f'{q["Rf"]:g} ohm 1 % 0603', 'C23179', 'Rf, feedback', 1),
        ('R4', f'{q["Rg2"]:g} ohm 1 % 0603', 'C23193', 'Rg2, inverting node straight to the REF3030E output (D-V2-12): no offset filter; there is no Rg1', 1),
        ('R5', f'{q["Rbin"]/1e3:g} kohm 1 % 0603', 'C22940', 'DAC0 series resistor: back-feed limit and the upper arm of the divider', 1),
        ('R6', f'{q["Rbpl"]/1e3:g} kohm 1 % 0603', 'C22967', 'DAC0 divider lower arm: attenuates the DAC by 0.918 so the offset path can pull the window down (design.md), and an undriven DAC0 commands ground', 1),
        ('R7,R8', '1 ohm 1 % 0603', 'C22936', 'output balancing resistors of the two halves', 2),
        ('C1', '10 pF C0G 5 % 0603', 'C1634', 'Cf, across Rf: the stability capacitor (AN-1, design.md); the smallest Basic C0G', 1),
        ('C2', '330 pF C0G 5 % 0603', 'C1664', 'output pole, from the BNC to ground (bandwidth corner and AW-4 edge, design.md)', 1),
        ('C3,C4', '100 nF X7R 10 % 0603', 'C14663', 'supply decoupling at the op-amp, one per supply pin (the 1 uF pair was dropped, AW-6 0.3 mV)', 2),
        ('U1', 'TPH2502-SR dual op-amp SOP-8', 'C118223', 'both halves paralleled as one gain stage', 1),
    ]
    with open(os.path.join(core.HERE, 'parts.csv'), 'w') as f:
        f.write('refs,value,lcsc,role,qty\n')
        for p in parts:
            f.write(','.join(f'"{x}"' for x in p) + '\n')


def main():
    only = [a for a in sys.argv[1:]]
    if only == ['guards']:
        run_guards(); return
    ver = subprocess.run(['ngspice', '-v'], capture_output=True, text=True).stdout.split('\n')[1].strip() if True else ''
    OUT['header'] = dict(ngspice=ver, vendor=core.VENDOR, vendor_sha=core.VENDOR_SHA)
    for fn in (case_model, case_dc, case_mc, case_swing, case_short, case_ac, case_pm, case_tran, noise_case, case_startup, case_forced, case_pins, case_power, case_ref):
        if only and fn.__name__ not in only and fn.__name__.replace('case_', '') not in only:
            continue
        fn()
    run_guards()
    OUT['rows'] = ROWS; OUT['guards'] = GUARDS
    write_outputs()
    json.dump(OUT, open(os.path.join(core.RAWDIR, 'results.json'), 'w'), indent=1, default=float)
    nfail = sum(1 for r in ROWS if not r['ok'])
    print(f'\n{len(ROWS)} rows, {nfail} FAIL')


if __name__ == '__main__':
    main()
