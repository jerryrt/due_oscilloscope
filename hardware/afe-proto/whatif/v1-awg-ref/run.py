#!/usr/bin/env python3
"""Version 1's AWG output stage redone the way version 2's is (no DAC0 buffer, no Vmid follower, no series Schottkys, offset from the REF3030E):
every number in design.md and report_table.md.  Adapted from kvm_02's v2/sim/awg/run.py (read-only there); the cases keep its names.

    cd hardware/afe-proto/whatif/v1-awg-ref && TPH2502_DIR=../tph2502 python3 -I run.py          # about 3-6 minutes; writes raw/results.json,
                                                                    # netlists/*.cir, raw/*.log, report_table.md
    python3 -I run.py guards                                        # only the checks-broken-on-purpose rows

Needs ngspice-47 and numpy.  The vendor op-amp model is read from ../tph2502/models (local, never copied or
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
            w = worst.setdefault(scen, dict(use=0, edge=0, lsb=0, g=[9, 0], off=[9, -9], o1=[9, -9], top=-9, topmin=9, bot=9, botmax=-9, reach=0.0, tg=[]))
            w['use'] = max(w['use'], m['use'].max()); w['edge'] = max(w['edge'], m['edge'].max())
            w['lsb'] = max(w['lsb'], m['lsb'].max())
            w['g'] = [min(w['g'][0], m['gain'].min()), max(w['g'][1], m['gain'].max())]
            w['off'] = [min(w['off'][0], m['off'].min()), max(w['off'][1], m['off'].max())]
            w['o1'] = [min(w['o1'][0], m['o167'].min()), max(w['o1'][1], m['o167'].max())]
            span = m['out_hi'] - m['out_lo']
            w['top'] = max(w['top'], m['out_hi'].max()); w['topmin'] = min(w['topmin'], m['out_hi'].min())
            w['bot'] = min(w['bot'], m['out_lo'].min()); w['botmax'] = max(w['botmax'], m['out_lo'].max())
            w['tg'].append((m['out_hi'] - 0.04 * span)); w['botg'] = max(w.get('botg', -9), (m['out_lo'] + 0.04 * span).max())
    for scen, nm in (('A', 'window theory 1/6..5/6 AREF, +-30 mV centring'), ('B', 'measured board window 0.578..2.771 V at 3.27 V, scaled with AREF, +-5 mV')):
        w = worst[scen]
        tg = np.concatenate(w['tg'])
        add('AW-1', f'window top end (output at the DAC window maximum), 1 % parts, REF3030E offset 2.994..3.006 V, AREF 3.20..3.30 V [{scen}: {nm}]', f'<= {lim_top:.4f} V (supply pin)', f'{w["top"]:.3f} V', f'{lim_top-w["top"]:+.3f} V', w['top'] <= lim_top, f'{n} draws x 3 AREF; the supply-pin limit')
        add('AW-1', f'window use, width, same draws [{scen}] (+-1.0 V)', '<= 92 %', f'{w["use"]*100:.1f} %', f'{(0.92-w["use"])*100:+.1f} %', w['use'] <= 0.92, f'range {design.OUT_LO} V to +{design.OUT_HI} V (AW-1)')
        add('AW-1', f'window use, position-aware (+{design.OUT_HI} / {design.OUT_LO} V ends against the window ends, 4 % kept at each end) [{scen}]', '<= 92 %', f'{w["edge"]*100:.1f} %', f'{(0.92-w["edge"])*100:+.1f} %', w['edge'] <= 0.92, 'the 92 % band: 4 % of the window kept free at each end')
        info('AW-1', f'highest top the stage can command with 4 % of the window kept free, every draw [{scen}]', f'{tg.min():.3f} V at the worst draw; window top end {w["topmin"]:.3f}..{w["top"]:.3f} V', f'{(tg >= design.OUT_HI).mean()*100:.1f} % of draws reach {design.OUT_HI} V inside the 92 % band; each board\'s actual top is measured at calibration')
        add('AW-1', f'window bottom end against the negative rail reach (-1.917 V, weak rail -2.005 V) [{scen}]', f'>= {design.RAIL_REACH_LO} V', f'{w["bot"]:.3f} V', f'{w["bot"]-design.RAIL_REACH_LO:+.3f} V', w['bot'] >= design.RAIL_REACH_LO, 'a window bottom below this clips codes that are outside the commanded range')
        add('AW-1', f'commanded bottom {design.OUT_LO} V stays inside the window with 4 % kept at its bottom end [{scen}]', f'<= {design.OUT_LO} V', f'{w["botg"]:.3f} V (highest window bottom + 4 % of the window)', f'{design.OUT_LO-w["botg"]:+.3f} V', w['botg'] <= design.OUT_LO, 'the position-aware row\'s other half')
        add('AW-2', f'one DAC code at the output, ideal 12-bit [{scen}]', '<= 1.0 mV (AW-2)', f'{w["lsb"]*1e3:.3f} mV', f'{(1.0e-3-w["lsb"])*1e3:+.3f} mV', w['lsb'] <= 1.0e-3)
        add('AW-7', f'gain as built, Monte Carlo [{scen}]', '1.10 .. 1.20', f'{w["g"][0]:.3f} .. {w["g"][1]:.3f}', f'{w["g"][0]-1.10:+.3f} / {1.20-w["g"][1]:+.3f}', w['g'][0] >= 1.10 and w['g'][1] <= 1.20, 'the window of the brief and of budget/afe_budget.py; the spec text itself asks only for AW-1')
        add('AW-7', f'output at Vdac = 1.67 V (the offset of Vout = G (Vdac - 1.67)), Monte Carlo [{scen}]', '+-60 mV (the brief)', f'{w["o1"][0]*1e3:+.0f} .. {w["o1"][1]*1e3:+.0f} mV', f'{60-max(abs(w["o1"][0]), abs(w["o1"][1]))*1e3:+.0f} mV', max(abs(w['o1'][0]), abs(w['o1'][1])) <= 0.060, 'the spec text asks only that offset keep AW-1; the host calibrates it')
        info('AW-7', f'output at the window centre (not at 1.67 V) [{scen}]', f'centre {w["off"][0]*1e3:.0f}..{w["off"][1]*1e3:.0f} mV', 'the window centre is 1.6745 V on the measured board and AREF/2 +- 30 mV in the theory scenario')
    OUT['mc'] = {k: dict(use=float(v['use']), edge=float(v['edge']), lsb=float(v['lsb']), g=[float(x) for x in v['g']], off=[float(x) for x in v['off']], top=float(v['top']), topmin=float(v['topmin']), bot=float(v['bot'])) for k, v in worst.items()}
    # hard corners: every resistor at +-1 %, rail, AREF, centring shift and VOS at both limits, both scenarios
    e = design.corner_stats(V)
    add('AW-1', 'window top end, hard corners (five resistors at +-1 %, rail, AREF, centring and VOS at both limits, both scenarios)', f'<= {lim_top:.4f} V (supply pin)', f'{e["top"]:.3f} V', f'{lim_top-e["top"]:+.3f} V', e['top'] <= lim_top, 'the stack of every tolerance at once; the binding row of the design')
    add('AW-1', 'window use, width, hard corners', '<= 92 %', f'{e["use"]*100:.1f} %', f'{(0.92-e["use"])*100:+.1f} %', e['use'] <= 0.92, f'range {design.OUT_LO} V to +{design.OUT_HI} V')
    add('AW-1', 'window use, position-aware, hard corners', '<= 92 %', f'{e["edge"]*100:.1f} %', f'{(0.92-e["edge"])*100:+.1f} %', e['edge'] <= 0.92, f'{e["tg"]:.4f} V is the commandable top with 4 % kept free at the worst corner, {e["botg"]:.4f} V the commandable bottom; {e["topmin"]:.4f} V is the lowest window top end, no band kept')
    add('AW-1', 'window bottom end against the negative rail (weak rail -2.005 V), hard corners: the stage must reach the window bottom end or the codes below it clip', f'>= {design.RAIL_REACH_LO} V (weak rail -2.005 V less the 88 mV reach v2 measured)', f'{e["bot"]:.3f} V', f'{e["bot"]-design.RAIL_REACH_LO:+.3f} V', e['bot'] >= design.RAIL_REACH_LO)
    add('AW-7', 'gain as built, hard corners (every resistor +-1 %)', '1.10 .. 1.20', f'{e["gmin"]:.3f} .. {e["gmax"]:.3f}', f'{e["gmin"]-1.10:+.3f} / {1.20-e["gmax"]:+.3f}', e['gmin'] >= 1.10 and e['gmax'] <= 1.20)
    add('AW-7', 'output at Vdac = 1.67 V, hard corners (five resistors, reference, VOS)', '+-60 mV (the brief)', f'{e["o167min"]*1e3:+.0f} .. {e["o167max"]*1e3:+.0f} mV', f'{60-max(abs(e["o167min"]), abs(e["o167max"]))*1e3:+.1f} mV', max(abs(e['o167min']), abs(e['o167max'])) <= 0.060, 'every tolerance stacked at its worst limit at once; the spec text asks only that the offset keep AW-1')
    add('PW-3', 'window top end / 49.5 ohm = the short-circuit current of the stage output at the window top, hard corners', '<= 30 mA (PW-3)', f'{e["top"]/49.5*1e3:.1f} mA (top end {e["top"]:.3f} V); bottom {-e["bot"]/49.5*1e3:.1f} mA', f'{30-max(e["top"], -e["bot"])/49.5*1e3:+.1f} mA', max(e['top'], -e['bot'])/49.5 <= 0.030, 'version 1 read 27.14 mA (whatif/v1-basic/values.md)')
    add('AW-1', 'the offset filter\'s gain shelf: an AC waveform (a pulse train with its mean at the window bottom, peaks at the top code) is amplified by (1 + Rf/Rg2) / (1 + Rf/(Rg2 + 100)) from the DC bottom; AC top end, hard corners', f'<= {lim_top:.4f} V (supply pin)', f'{e["actop"]:.3f} V (shelf {(e["shelfmax"]-1)*100:.2f} % at its largest; the DC top end is {e["top"]:.3f} V)', f'{lim_top-e["actop"]:+.3f} V', e['actop'] <= lim_top, 'above about 114 Hz (corner 1/(2 pi 100 ohm 14 uF) = 114 Hz) the capacitor shorts the 100 ohm')
    add('PW-3', 'short at the AC top end: supply-pin current = AC top end / 49.5 ohm + 15 mA IQ max', '<= 60 mA', f'{e["actop"]/49.5*1e3+15:.1f} mA (short {e["actop"]/49.5*1e3:.1f} mA)', f'{60-e["actop"]/49.5*1e3-15:+.1f} mA', e['actop'] / 49.5 * 1e3 + 15 <= 60, 'the DC top end row is the short row below; an AC peak is the larger')
    add('PW-3', 'short at the AC top end against PW-3\'s own 30 mA', '<= 30 mA', f'{e["actop"]/49.5*1e3:.1f} mA', f'{30-e["actop"]/49.5*1e3:+.1f} mA', e['actop'] / 49.5 <= 0.030, 'an AC peak at the shelf gain')
    add('AW-7', 'AC gain as built (DC gain x shelf), hard corners', '1.10 .. 1.20', f'{e["gmin"]:.3f} .. {e["gacmax"]:.3f}', f'{e["gmin"]-1.10:+.3f} / {1.20-e["gacmax"]:+.3f}', e['gmin'] >= 1.10 and e['gacmax'] <= 1.20, 'the host calibrates the DC gain; the shelf is a frequency-dependent gain change of at most the shelf figure above')
    add('AW-2', 'one DAC code, hard corners', '<= 1.0 mV (AW-2)', f'{e["lsb"]*1e3:.3f} mV', f'{(1.0e-3-e["lsb"])*1e3:+.3f} mV', e['lsb'] <= 1.0e-3)
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
    vecs = ['v(vo)', 'v(bnc)', '@rba[i]'] + (['@rbb[i]'] if p.get('topo', D['topo']) == 'Par' else [])
    h, d, log = core.wr('sat', b, 'op', vecs)
    return np.append(d[0, 1:], [0.0] * (4 - len(d[0, 1:])))


def vd_for(out, rails_v, p=None):
    """DAC pin voltage that commands `out` at the stage output (nominal parts, no offset voltage), from design.py's map."""
    q = dict(D); q.update(p or {})
    Rg2 = q['Rg2'] + q['Rvr']
    Gs0 = 1 + q['Rf'] * (1 / q['Rg1'] + 1 / Rg2); kin = q['Rbpl'] / (q['Rbin'] + q['Rbpl'])
    return (out + q['Rf'] / Rg2 * rails_v) / (Gs0 * kin)


def case_swing():
    """AW-1 reach with the derived output saturation (TPH2502_SAT, 11.5 ohm per rail, *(check)*): at version 1's window the output
    never gets near a rail, and these rows show it: the output with saturation equals the output of the unsaturated model."""
    e = design.corner_stats(V)
    cmds = (('top', design.OUT_HI, f'+{design.OUT_HI} V'), ('wtop', e['top'], f'{e["top"]:.3f} V (the window top end, hard corners)'),
            ('bot', design.OUT_LO, f'{design.OUT_LO} V'), ('wbot', e['bot'], f'{e["bot"]:.3f} V (the window bottom end, hard corners)'))
    res = {}
    for rails in ('weak', 'strong'):
        for rout in (49.5, 50.0, 50.5):
            for load in ('hiz', 'r50'):
                for tag, cmd, _ in cmds:
                    vd = vd_for(cmd, D['vref'])
                    r = sat_op(dict(rails=rails, Rout=rout), load, vd)
                    ideal = core.wr('ideal', core.build(dict(rails=rails, Rout=rout, load=load, dac=vd), analysis=''), 'op', ['v(vo)', 'v(bnc)'])[1][0, 1:]
                    res[(rails, rout, load, tag)] = (r, ideal)
    def worst_dev(load, tag):
        return max(abs(v[0][1] - v[1][1]) for k, v in res.items() if k[2] == load and k[3] == tag)
    for load, nm in (('hiz', 'high impedance'), ('r50', '50 ohm')):
        for tag, cmd, lab in cmds:
            dev = worst_dev(load, tag)
            add('AW-1', f'reach into {nm}: DAC commanding {lab}, both rail corners, Rout 49.5..50.5: output with the derived saturation against the unsaturated model', '<= 5 mV difference (saturation does not bind)',
                f'{dev*1e3:.2f} mV', f'{5-dev*1e3:+.2f} mV', dev < 5e-3, 'saturation 11.5 ohm per rail is derived from the datasheet text *(check: no swing-versus-current curve)*' if load == 'r50' else '')
    r = res[('weak', 49.5, 'r50', 'wtop')][0]
    vo, bnc, ia, ib = r
    info('AW-1', 'op-amp output at the window top end into 50 ohm (weak rail, Rout 49.5 ohm)', f'{vo:.3f} V at {(ia+ib)*1e3:.1f} mA, {RAILS["weak"][0]-vo:.2f} V under the +rail', f'BNC {bnc:.3f} V')
    r = res[('weak', 49.5, 'r50', 'bot')][0]
    info('AW-1', 'op-amp output at the commanded bottom -1.0 V into 50 ohm (weak negative rail)', f'{r[0]:.3f} V at {-(r[2]+r[3])*1e3:.1f} mA sunk, {r[0]-RAILS["weak"][1]:.2f} V above the -rail', f'BNC {r[1]:.3f} V')
    OUT['swing'] = {f'{k[0]}|{k[1]}|{k[2]}|{k[3]}': [[float(x) for x in v[0]], [float(x) for x in v[1]]] for k, v in res.items()}
    s = sat_op(dict(rails='weak', topo='Par', Rb=1.0), 'r50', vd_for(e['top'], D['vref']))
    info('AW-1', 'for comparison, BOTH halves paralleled (the earlier version of this design) into 50 ohm at the window top end (weak rail)', f'BNC {s[1]:.3f} V (op-amp output {s[0]:.3f} V)', 'the design is now one half: the saturation rows above are for one half')


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
    add('PW-3', 'indefinite short to ground at the BNC, DAC at the highest window code at the worst hard corner (Rout 49.5 ohm): output current', 'information (the 30 mA PW-3 row is the one above)',
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
    add('PW-3', 'indefinite short, ngspice, DAC at the highest window code at the worst hard corner (Rout 49.5 ohm): the current in the back-termination (stage output / 49.5 ohm)', '<= 30 mA (PW-3; version 1 read 27.14 mA)',
        f'{t["vo"]/49.5*1e3:.1f} mA', f'{30-t["vo"]/49.5*1e3:+.1f} mA', t['vo'] / 49.5 <= 0.030, 'the output current of the pair is larger by the current in Rf (the feedback node follows the + input)')
    add('PW-3', 'the same at the lowest window code (window bottom end, weak negative rail)', '<= 30 mA', f'{abs(bt["vo"])/49.5*1e3:.1f} mA (stage output {bt["vo"]:.3f} V)', f'{30-abs(bt["vo"])/49.5*1e3:+.1f} mA', abs(bt['vo']) / 49.5 <= 0.030, '')
    # the reset state: DAC0 at 3.3 V (AW-8) with the short: the stage commands G (3.3 - 1.67) = 1.9 V, inside the rails
    rr = []
    for rails in ('weak', 'strong'):
        rr.append((rails,) + tuple(float(x) for x in sat_op(dict(rails=rails, Rout=49.5), 'short', 3.3)))
    rmax = max(r[3] + r[4] for r in rr)
    add('PW-3', 'indefinite short while DAC0 sits at 3.3 V (the Due reset level, AW-8): supply-pin current, strong rail, Rout 49.5 ohm (version 1\'s window puts the commanded 1.9 V inside the rails, so nothing saturates and no clamp is needed)', '<= 60 mA',
        f'{(IQ + rmax)*1e3:.0f} mA ({IQ*1e3:.0f} mA + {rmax*1e3:.0f} mA, stage output {max(r[1] for r in rr):.2f} V)', f'{60-(IQ+rmax)*1e3:+.0f} mA', IQ + rmax <= 0.060,
        'the reset level lasts 0.2-0.3 s above the window (records/dac0-reset-montreal5.json, *(check)*); the 60 mA rating states no duration *(check)*; PW-3\'s own 30 mA applies at the window ends only')
    rr0 = [sat_op(dict(rails=rails, Rout=49.5), 'short', 0.0) for rails in ('weak', 'strong')]
    i0 = max(abs(r[2] + r[3]) for r in rr0)
    add('PW-3', 'indefinite short while DAC0 sits at 0 V (boot level): supply-pin current on the -pin, Rout 49.5 ohm', '<= 60 mA',
        f'{(IQ + i0)*1e3:.0f} mA ({IQ*1e3:.0f} mA + {i0*1e3:.0f} mA, stage output {min(r[0] for r in rr0):.2f} V)', f'{60-(IQ+i0)*1e3:+.0f} mA', IQ + i0 <= 0.060, 'the stage commands -1.9 V and sits at the derived saturation')
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
    # component spread and the + input stray on the 8 MHz, op-amp model unchanged
    cr = []
    for cp in (0.0, 3e-12):
        for rs in (-1, 1):
            for cf in (-1, 1):
                for rd in (-1, 1):
                    cr.append(bw(dict(Cf=10e-12 * (1 + 0.05 * cf), Rout=50 * (1 + 0.01 * rs), cpv=1.5e-12 + cp, Rbin=51e3 * (1 + 0.01 * rd), Rbpl=126e3 * (1 - 0.01 * rd), cbin=10e-12 * (1 + 0.05 * rd)), 'hiz')[1])
    f_hiz = min(res[('hiz', r)][1] for r in ('weak', 'strong')) / 1e6
    f_hiz_c = min(cr) / 1e6
    add('AW-3', 'small-signal -3 dB bandwidth, DAC pin to BNC, 1 Mohm || 15 pF load, both rail corners', '>= 8 MHz', f'{f_hiz:.2f} MHz', f'{f_hiz-8:+.2f} MHz', f_hiz >= 8)
    add('AW-3', 'the same with Cf 10 pF +-5 %, the 50 ohm +-1 %, the divider resistors +-1 % in opposite senses and the compensation capacitor +-5 % with them, and 0 or 3 pF of layout stray *(check)* added at the + input', '>= 8 MHz', f'{f_hiz_c:.2f} MHz', f'{f_hiz_c-8:+.2f} MHz', f_hiz_c >= 8, f'range {f_hiz_c:.2f}..{max(cr)/1e6:.2f} MHz')
    f50 = min(res[('r50', r)][1] for r in ('weak', 'strong')) / 1e6
    add('AW-3', 'bandwidth into 50 ohm (amplitude is half; -3 dB relative to its own DC)', '>= 8 MHz', f'{f50:.1f} MHz', f'{f50-8:+.1f} MHz', f50 >= 8)
    fcap = min(res[('cap100', r)][1] for r in ('weak', 'strong')) / 1e6
    add('AW-3', 'bandwidth into 100 pF (about 1 m of RG-58 *(check)*) open at the far end', '>= 8 MHz (information for a cable)', f'{fcap:.2f} MHz', f'{fcap-8:+.2f} MHz', True,
        'there is no output pole: the load capacitance meets only the 50 ohm back-termination')
    pk = max(res[(l, r)][2] for l in ('hiz', 'r50', 'cap100') for r in ('weak', 'strong'))
    info('AW-3', 'peaking of the small-signal response', f'{20*np.log10(pk):.3f} dB', 'flat to the pole; no peaking')
    g_hiz = res[('hiz', 'weak')][0]
    info('AW-7', 'small-signal gain at low frequency, nominal parts', f'{g_hiz:.4f} hi-Z, {res[("r50", "weak")][0]:.4f} into 50 ohm', 'the 50 ohm row is the exact half')
    hs, ds_, _ = core.wr('shelf', core.build(dict(load='hiz', rails='nom'), analysis='', ac=('dac',)), 'ac dec 20 1 1e5', ['v(bnc)'])
    gs = np.abs(ds_[:, 1] + 1j * ds_[:, 2]); fs = ds_[:, 0]
    g1, g10k = float(np.interp(1.0, fs, gs)), float(np.interp(1e4, fs, gs))
    info('AW-7', 'the offset filter\'s gain shelf in ngspice (nominal parts, hi-Z): gain at 1 Hz and at 10 kHz', f'{g1:.4f} and {g10k:.4f} (+{(g10k/g1-1)*100:.2f} %)', f'closed form: (1 + Rf/Rg2) / (1 + Rf/(Rg2 + 100)) = {(1+V["Rf"]/V["Rg2"])/(1+V["Rf"]/(V["Rg2"]+V["Rvr"])):.4f}; version 2\'s 3k/3k pair reads +1.64 %')
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
    add('AW-4', 'the same into a 1 m (5 ns) 50 ohm line (ten LC sections) open at the far end, BNC end: overshoot', '<= 5 % (the AW-4 overshoot row of whatif/v1-basic)', f'{overc:.2f} % (settle {(tsetc-0.5e-6)*1e9:.0f} ns)', f'{5-overc:+.2f} %', overc <= 5.0, 'the 50 ohm back-termination absorbs the reflection')
    # ideal 2 ns edge into the cable: reflection absorbed -> overshoot
    t, vb, vd = tran(dict(), 'ladder_open', 'tr_cab2', tr=5e-9, t1=1e-6, step=1e-9, v0=1.0, v1=1.5, t0=0.2e-6)
    far = None
    v0c, v1c, tr10c, overc, tsetc = edge_metrics(t, vb, 0.2e-6, 2e-9)
    info('AW-4', '5 ns, 0.5 V step at the DAC pin into the open line (ten LC sections), BNC-end overshoot', f'{overc:.2f} % (no output pole)', '')
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
    K_ = D['Rf'] / (D['Rg2'] + D['Rvr'])
    fc_x = 1 / (2 * np.pi * D['Rvr'] * D['Cx'])
    ref_u = 51e-6 * K_      # unfiltered: REF3030E 51 uV rms, 10 Hz-10 kHz (ref30.pdf 6.5) x K
    ref_n = 1.4e-6 * np.sqrt(fc_x * np.pi / 2) * K_     # filtered: the density of Fig 6-13 at its worst (1.4 uV/rtHz at 10 Hz, taken flat) through the 100 ohm + Cx corner (first order)
    tot_ref = np.sqrt(tot_rp ** 2 + ref_n ** 2)
    add('AW-6', f'the pessimistic-PSRR sum plus the REF3030E noise through the offset filter (100 ohm + {D["Cx"]*1e6:.0f} uF, corner {fc_x:.0f} Hz): 1.4 uV/rtHz (Fig 6-13 worst, flat) over the filter\'s noise bandwidth x K', f'<= {AW6_UV:g} uV rms', f'{tot_ref*1e6:.1f} uV', f'{AW6_UV-tot_ref*1e6:+.1f} uV', tot_ref <= AW6_UV * 1e-6,
        f'reference term {ref_n*1e6:.1f} uV filtered against {ref_u*1e6:.1f} uV unfiltered (51 uV x K); the 100 ohm adds 1.3 nV/rtHz at the node, inside the .noise rows above. Noise above 10 kHz is a graph and is *(check)*')
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
                    tend = max(tp, tn) + tr * 6 + 10e-6 + (3e-3 if refmode == 'late' else 0) + 5 * D['Rvr'] * D['Cx']      # the offset filter settles in 5 tau
                    h, d, log = core.wr('su', b, f'tran {tend/4000:.3e} {tend}', ['v(bnc)', 'v(vpx)', 'v(vnx)'])
                    v = d[:, 1]
                    # excursion against the rails present at that time
                    over_hi = (v - d[:, 2]).max()
                    under = (d[:, 3] - v).max()           # rail minus output, positive when the output is below the negative rail
                    rows.append((rails, order, tr, dacmode + '/' + refmode, float(v.max()), float(v.min()), float(over_hi), float(under)))
    mx = max(r[4] for r in rows); mn = min(r[5] for r in rows)
    ovr = max(r[6] for r in rows); und = max(r[7] for r in rows)
    add('AW-8', 'through rail ramps (3 orders x 20 us / 2 ms), the REF3030E following the +rail or 2 ms late, with DAC0 at 0 V, 3.3 V, floating and a reset trace, hi-Z: output extremes, both rail corners', 'within the AFE rails at every instant (at most 10 mV beyond; rails about -2.1..+3.3 V; V2 AW-8)', f'{mn:.3f}..{mx:.3f} V', f'beyond the +rail {max(ovr, 0)*1e3:.0f} mV, beyond the -rail {max(und, 0)*1e3:.0f} mV', ovr <= 0.010 and und <= 0.010,
        '48 start-up cases per rail corner; derived output saturation')
    OUT['startup'] = [list(r) for r in rows]
    for rm, nm in (('follows', 'the REF3030E following the +rail'), ('late', 'the REF3030E arriving 2 ms after the +rail (datasheet turn-on to 0.1 % at 1 uF)')):
        sel = [r for r in rows if r[3].endswith(rm)]
        hi_ = max(r[4] for r in sel); lo_ = min(r[5] for r in sel)
        wc = max(sel, key=lambda r: r[4]) if hi_ > -lo_ else min(sel, key=lambda r: r[5])
        add('AW-8', f'output within +-2.1 V through the rail ramps and every DAC0 state (0 V, 3.3 V, floating, reset trace), {nm}', '|Vout| <= 2.1 V', f'{lo_:.3f} .. {hi_:.3f} V', f'{2.1-max(hi_, -lo_):+.3f} V', max(hi_, -lo_) <= 2.1,
            f'worst case: {wc[0]} rails, {wc[1]} order, {wc[2]*1e6 if wc[2] < 1e-3 else wc[2]*1e3:g} {"us" if wc[2] < 1e-3 else "ms"} ramp, DAC0 {wc[3]}')
    # a Due reset with the AFE already powered (rails and reference up): the static output for DAC0 anywhere in 0 .. 3.3 V, hard corners
    ext = [9, -9]
    for sg in itertools.product((-1, 1), repeat=4):
        Rf_, Rg2_, Rbin_, Rbpl_ = [V[k] * (1 + 0.01 * s_) for k, s_ in zip(('Rf', 'Rg2', 'Rbin', 'Rbpl'), sg)]
        Rg2_ += V['Rvr'] * (1 - 0.01 * sg[1])
        Gs0_ = 1 + Rf_ / Rg2_; kin_ = Rbpl_ / (Rbin_ + Rbpl_); K_ = Rf_ / Rg2_
        for vo_ in design.VREF3030:
            for vs_ in (-1, 1):
                for vd_ in (0.0, 3.3):
                    o_ = Gs0_ * (kin_ * vd_ + vs_ * 1e-3) - K_ * vo_
                    ext[0] = min(ext[0], o_); ext[1] = max(ext[1], o_)
    sp = [float(sat_op(dict(rails=r_), 'hiz', dd)[1]) for r_ in ('weak', 'strong') for dd in (0.0, 3.3)]
    add('AW-8', 'Due reset or boot with the AFE already powered (rails and reference up): DAC0 anywhere 0 .. 3.3 V (3.3 V at the reset, about 0 V for seconds after boot), static output, hard corners; ngspice at 0 and 3.3 V, weak and strong rails: ' + ' / '.join(f'{x:.3f}' for x in sp) + ' V',
        '|Vout| <= 2.1 V', f'{ext[0]:.3f} .. {ext[1]:.3f} V', f'{2.1-max(ext[1], -ext[0]):+.3f} V', max(ext[1], -ext[0]) <= 2.1,
        'the reset case of AW-8 passes; the -1.96 V end is below what the stage can reach at the weak rail (about -1.92 V, row AW-1), so it clips there, inside the limit. The two power-up rows above are a different event: the AFE\'s own rails ramping while DAC0 sits at 3.3 V')
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
                h, d, log = core.wr('forced', b, 'op', ['v(bnc)', '@rba[i]', '@rba[i]', '@rfrc[i]', 'v(vo)', 'v(fb)'])
                ia = d[0, 2]; ifr = d[0, 4]
                rows.append((level, pw, dac, float(ia), float(ifr), float(d[0, 5]), float(d[0, 6])))
    def imax(lv, pw): return max(abs(r[3]) for r in rows if r[1] == pw and abs(r[0] - lv) < 1e-9)
    add('PR-4', f'forced +{lev_pos:.2f} V at the BNC (the restated positive level), powered, DAC at the commanded ends and mid: pair output current', f'<= {I_PIN*1e3:.0f} mA (60 mA supply pin less 15 mA IQ)', f'{imax(lev_pos, "powered")*1e3:.0f} mA',
        f'{I_PIN*1e3-imax(lev_pos, "powered")*1e3:+.0f} mA', imax(lev_pos, 'powered') <= I_PIN, 'the rule of docs/afe.md with the rating that binds here')
    lv = -max(lev_neg, 0.0)
    add('PR-4', f'forced {lv:.2f} V at the BNC (the restated negative level), powered: pair output current', f'<= {I_PIN*1e3:.0f} mA', f'{imax(lv, "powered")*1e3:.0f} mA', f'{I_PIN*1e3-imax(lv, "powered")*1e3:+.0f} mA', imax(lv, 'powered') <= I_PIN,
        'an output at the window top end and a forced level of this size is the same current as the short through the pair')
    i18 = max(imax(1.8, 'powered'), imax(-1.8, 'powered'))
    add('PR-4', 'forced +-1.8 V (PR-4 as written: 10 s, powered, recovers) at the BNC, powered, DAC at the commanded ends and mid: pair output current against the supply-pin rating less IQ (the OPA365 figure of PR-4, 65 mA, becomes this)', f'<= {I_PIN*1e3:.0f} mA', f'{i18*1e3:.0f} mA', f'{I_PIN*1e3-i18*1e3:+.0f} mA', i18 <= I_PIN,
        f'does NOT hold for the TPH2502: the level that does is +{lev_pos:.2f} V / -{lev_neg:.2f} V (the rows above, which pass by construction); a decision for the spec lead *(the 60 mA rating states no duration, check)*; forced +-5 V (may damage): {max(imax(5.0, "powered"), imax(-5.0, "powered"))*1e3:.0f} mA')
    iun = max(imax(1.8, 'unpowered'), imax(-1.8, 'unpowered'))
    add('PR-4', 'forced +-1.8 V at the BNC, unpowered rails (0 V): current through the 50 ohm into the op-amp output', '<= 160 mA (abs max output current)', f'{iun*1e3:.0f} mA', f'{(160-iun*1e3):+.0f} mA', iun <= 0.160,
        '*(check)* the macromodel clamps the output to the rails through its diodes; the real output structure is not in the datasheet; the supply-pin limit does not apply with no supply, the input and ESD structures do')
    info('PR-4', 'level restated by the rule: 45 mA x 49.5 ohm minus the largest output the stage commands at the opposite end (positive: the lowest commanded -1.5 V / window bottom end; negative: the commanded top / window top end)',
         f'+{lev_pos_c:.2f} V (+{lev_pos:.2f} V with the window bottom end {e["bot"]:.2f} V) and {-lev_neg_c:+.2f} V (-{lev_neg:.2f} V with the window top end {e["top"]:.3f} V)', 'against version 1\'s +-1.8 V: the supply-pin rating of the TPH2502 binds where version 1\'s OPA365 output rating did' )
    OUT['forced'] = [list(r) for r in rows]
    OUT['pr4'] = dict(lev_pos=float(lev_pos), lev_neg=float(lev_neg), lev_pos_c=float(lev_pos_c), lev_neg_c=float(lev_neg_c))


def esd_run(order, dac, tr=2e-3):
    """DAC0 into the divider with the op-amp's input structure modelled as a diode from the + input to V+ and one from V- to the + input
    (Vf about 0.5 V at 1 mA: an ASSUMPTION *(check: the TPH2502 datasheet gives the clamp only in a note)*).  order: 'both' | '+first' |
    '-first' | 'neither' (rails held at 0 V: the unpowered AFE, a worst case for the clamp) | 'full' (both rails up the whole time).  Returns
    (max current into the AFE from the DAC pin, max current out of the pin into the DAC, lowest + input voltage)."""
    vp_, vn_ = RAILS['strong']
    t0p = {'both': 0.0, '+first': 0.0, '-first': 4 * tr}.get(order, 0.0)
    t0n = {'both': 0.0, '+first': 4 * tr, '-first': 0.0}.get(order, 0.0)
    if order == 'neither':
        vs = "Vvp vpx 0 DC 0\nVvn vnx 0 DC 0"
    elif order == 'full':
        vs = f"Vvp vpx 0 DC {vp_}\nVvn vnx 0 DC {vn_}"
    else:
        vs = (f"Vvp vpx 0 PWL(0 0 {t0p} 0 {t0p+tr} {vp_} 1 {vp_})\nVvn vnx 0 PWL(0 0 {t0n} 0 {t0n+tr} {vn_} 1 {vn_})")
    extra = ".model DESD D(IS=1e-12 N=1 RS=20)\nDpu bin vcc DESD\nDnd vee bin DESD\n"
    b = core.build(dict(dac=dac, load='hiz', dacsrc=f"Vdac dacs 0 DC {dac}\nRdacs dacs dac 1m"), analysis='', supply='src:' + vs, extra=extra)
    tend = (4 * tr + tr + 1e-3) if order in ('+first', '-first') else (tr + 1e-3)
    h, d, log = core.wr('esd', b, f'tran {tend/3000:.3e} {tend}', ['i(Vdac)', 'v(bin)'])
    i_in = -d[:, 1]
    return float(i_in.max()), float(-i_in.min()), float(d[:, 2].min())


def case_pins():
    i = {x: abs(core.wr('pin', core.build(dict(dac=x), analysis=''), 'op', ['i(Vdac)'])[1][0, 1]) for x in (0.578, 2.75, 2.80, 3.3)}
    add('AW-5', 'DAC pin load at the DAC\'s own highest code (2.80 V: AREF 3.30 V, window top 2.771 V scaled, +5 mV; 51 kohm + (51 + 75) kohm to ground; the op-amp input is high impedance)', '<= 0.1 mA', f'{i[2.80]*1e6:.1f} uA', f'{100-i[2.80]*1e6:+.1f} uA', i[2.80] <= 100e-6, 'judged at the DAC\'s own output codes; the 1 % parts add 1 %')
    add('AW-5', 'the same at the 1 % worst case (both resistors -1 %)', '<= 0.1 mA', f'{2.80/(0.99*177e3)*1e6:.1f} uA', f'{100-2.80/(0.99*177e3)*1e6:+.1f} uA', 2.80 / (0.99 * 177e3) <= 100e-6, 'arithmetic')
    add('AW-5', 'DAC pin load at 3.3 V (the Due reset level, outside the DAC window)', '<= 0.1 mA', f'{i[3.3]*1e6:.1f} uA', f'{100-i[3.3]*1e6:+.1f} uA', i[3.3] <= 100e-6, 'version 2\'s divider read 112 uA here and was accepted; this one passes outright')
    rows = {}
    for order in ('full', 'both', '+first', '-first', 'neither'):
        for dac in (0.0, 1.67, 2.80, 3.3, -0.2):
            rows[(order, dac)] = esd_run(order, dac)
    OUT['esd'] = {f'{k[0]}|{k[1]}': list(v) for k, v in rows.items()}
    imax = max(v[0] for v in rows.values()); iout = max(v[1] for v in rows.values())
    vmin = min(v[2] for k, v in rows.items() if k[1] >= 0)
    i_un = max(v[0] for k, v in rows.items() if k[0] == 'neither')
    add('PR-2', 'DAC0 (0, 1.67, 2.80 and the 3.3 V reset level) into the divider, the + input modelled with diodes to both rails (Vf about 0.5 V *(check)*), rails in every start order (both, +3.3 V first, -rail first, 4 x 2 ms apart; both up; neither = unpowered, rails at 0 V): the largest current the AFE draws from the DAC pin', '<= 3.8 mA (VT-5 bound; version 1 with 680 ohm)',
        f'{imax*1e3:.3f} mA (unpowered case {i_un*1e3:.3f} mA)', f'{3.8-imax*1e3:+.2f} mA', imax <= 3.8e-3, f'version 1\'s 680 ohm gives (3.3 - 0.5) / 0.68 kohm = {(3.3-0.5)/680*1e3:.1f} mA at the same point; this divider is {51e3/680:.0f}x higher')
    add('PR-2', 'the same rows, DAC0 at 0 V, 1.67, 2.80 and 3.3 V: current out of the AFE into the pin (DAC0 as the load), the pin voltage it can pull down is this current times the DAC output impedance, which the datasheet does not give *(check)*', '<= 100 uA (= 0.1 V into 1 kohm; the pin must stay above -0.2 V)',
        f'{iout*1e6:.1f} uA', f'{100-iout*1e6:+.1f} uA', iout <= 100e-6, 'with DAC0 at 0 V the + input sits at 0 V: nothing in the AFE drives it below ground except a clamp to a negative rail, and no clamp conducts above rail - 0.5 V')
    add('PR-2', 'lowest voltage the + input reaches, DAC0 at 0 V or above, every start order', '>= -0.2 V (the pin rule, as an upper bound on what DAC0 can see)', f'{vmin:.3f} V', f'{vmin+0.2:+.3f} V', vmin >= -0.2, 'the divider\'s own ground reference keeps the node at or above ground; DAC0 at -0.2 V (the lowest the repository records after boot, -0.1 to 0.2 V) is the next row')
    vneg = min(v[2] for k, v in rows.items() if k[1] < 0)
    ineg = max(v[1] for k, v in rows.items() if k[1] < 0)
    info('PR-2', 'DAC0 at -0.2 V (the bottom of the PR-2 range), every start order: the + input voltage and the current out of the pin', f'{vneg:.3f} V, {ineg*1e6:.1f} uA', 'the divider carries -0.2 V x 0.714 and the clamp does not conduct (the negative rail is -2.0 V or 0 V unpowered)')
    info('PR-2', 'DAC pin voltage', 'held by the Due between 0.578 and 3.3 V; the AFE never drives the pin', 'only the 51 kohm connects it to the AFE')


def case_power():
    b = core.build(dict(load='r50', dac=1.6745), analysis='')
    h, d, log = core.wr('pw', b, 'op', ['i(Vvp)', 'i(Vvn)'])
    info('PW-1', 'supply currents, from the macromodel (it under-counts: no load current in its supply pins)', f'+rail {-d[0,1]*1e3:.1f} mA, -rail {d[0,2]*1e3:.1f} mA (nominal, 50 ohm load, DAC centre)', 'see the analytic budget in design.md')


# ------------------------------------------------------------------------------------------------------- the reference
ZREF = np.array([(10, 1), (100, 4), (200, 6), (300, 9), (500, 17), (700, 26), (1000, 45), (1300, 65), (1600, 95), (1900, 115), (2300, 100), (2700, 70), (3200, 40), (4000, 20), (6000, 8), (10000, 3)], float)   # REF30E Fig 6-14 open-load curve read by eye (kvm_02, origin/main v2/sim/awg/run.py) *(check)*


def ref_move(dV, Rg2, Rflt, C, mode='graph'):
    """Peak movement (V p-p) of the REF3030E output from the AWG's offset current, 10 Hz-10 kHz (method of kvm_02's run.py): the current through Rg2 from the filter node
    (Rflt to the reference, C to ground); the reference sees the part that goes through Rflt.  mode graph | bound110 | loaded28."""
    f = np.logspace(1, 4, 800)
    if C > 0 and Rflt > 0:
        Zc = 1 / (2j * np.pi * f * C); Zn = Rflt * Zc / (Rflt + Zc)
        i = dV / np.abs(Rg2 + Zn); share = np.abs(Zc / (Rflt + Zc))
    else:
        i = dV / (Rg2 + Rflt) * np.ones_like(f); share = np.ones_like(f)
    if mode == 'graph': Z = np.interp(np.log(f), np.log(ZREF[:, 0]), ZREF[:, 1])
    elif mode == 'bound110': Z = np.where((f >= 1000) & (f <= 3000), 110.0, 0.0)
    else: Z = np.where((f >= 1000) & (f <= 3000), 28.0, 0.0)
    m = i * share * Z
    k = int(np.argmax(m))
    return float(m[k]), float(f[k]), float(i[k] * share[k])


def case_ref():
    """The AWG offset comes from the REF3030E: its load, and what that load does to the reference (PA-2, SC-7, SC-9)."""
    kin_n = V['Rbpl'] / (V['Rbin'] + V['Rbpl'])
    cur = {}
    for dac in (0.0, 0.55, 2.80, 3.3):
        h, d, _ = core.wr('refi', core.build(dict(dac=dac, load='hiz'), analysis=''), 'op', ['i(Vrf)'])
        cur[dac] = float(-d[0, 1])
    kin_hi = V['Rbpl'] * 1.01 / (V['Rbin'] * 0.99 + V['Rbpl'] * 1.01)
    kin_lo = V['Rbpl'] * 0.99 / (V['Rbin'] * 1.01 + V['Rbpl'] * 0.99)
    iref = lambda vd, tol, vref, kin: (vref - kin * vd) / ((V['Rg2'] + V['Rvr']) * (1 + tol))
    i_src = iref(0.0, -0.01, design.VREF3030[1], kin_hi)
    i_snk = min(iref(3.3, +0.01, design.VREF3030[0], kin_hi), iref(3.3, -0.01, design.VREF3030[0], kin_hi))
    i_win_lo = iref(0.55, -0.01, design.VREF3030[1], kin_hi); i_win_hi = iref(2.80, +0.01, design.VREF3030[0], kin_hi)
    # the other loads of version 1 (derived; whatif/v1-basic/values.md section 7 for the ladder): ladder 2.12 mA at all -1 %, two scope centres
    # R3 330 kohm (at most (3.006 + 0.3 V clamp) / 330 kohm each), the AWG sense tie R7 + R8 100 kohm each to VREF (BNC down to -1.4 V),
    # the ADS1115 inputs 3 x 3 uA *(check: SBAS444 input current not read here)*
    others = 2.12e-3 + 2 * (3.006 + 0.3) / 330e3 + (3.006 + 1.4) / 200e3 + 9e-6
    info('PA-2', 'AWG offset current out of the REF3030E, ngspice nominal, DAC 0 / 0.55 / 2.80 / 3.3 V', ' / '.join(f'{cur[x]*1e3:.2f}' for x in (0.0, 0.55, 2.80, 3.3)) + ' mA', 'the current flows into Rg2 toward the inverting node, which follows the + input')
    add('PA-2', 'REF3030E source current with every load at once: the AWG offset at its worst (DAC at 0 V: boot or floating; Rg2 -1 %, reference +0.2 %) plus the ladder (2.12 mA, 8 x 270 ohm at -1 %), both scope centres (R3 330 kohm), the AWG sense tie (R7 + R8) and the ADS1115 inputs', '<= 10 mA (REF30E "High output current +-10 mA", ref30.pdf 1)',
        f'{(i_src+others)*1e3:.2f} mA ({i_src*1e3:.2f} AWG + {others*1e3:.2f} others)', f'{10-(i_src+others)*1e3:+.2f} mA', i_src + others <= 10e-3, 'the other loads are derived here, the ADS1115 input current is *(check)*; the supply is the +3.3 V rail through the reference')
    add('PA-2', 'REF3030E sink current: the AWG at DAC 3.3 V (the + node then sits at 0.714 x 3.3 = 2.36 V, below 3.0 V): the AWG still SOURCES', '<= 10 mA, and must not sink', f'{i_snk*1e3:+.2f} mA (positive = source)', f'{i_snk*1e3:+.2f} mA of source', i_snk > 0, 'the AWG never sinks into the reference in normal states; a forced output (PR-4) does not change it, the inverting node follows the + input')
    dI = i_win_lo - i_win_hi
    dv = dI * 1e3 * 15e-6 * 3.0
    dI1 = kin_n * (2.0 / 1.176) / (V['Rg2'] + V['Rvr'])
    add('SC-7', 'the reference moves with the AWG level: change of the AWG offset current over the DAC window (0.55 to 2.80 V) x 15 ppm/mA x 3.0 V (REF30E load regulation, source, ref30.pdf 6.5: "0mA < ILOAD < 10mA, VIN = VOUT + 500mV", 3 typ, 15 max ppm/mA)', '<= 3.0 mV (0.1 % fit share of 3 V, SC-7 / powercal)', f'{dI*1e3:.2f} mA -> {dv*1e6:.0f} uV ({dv/3.0*1e6:.0f} ppm)', f'{(3e-3-dv)*1e6:+.0f} uV', dv <= 3e-3,
        f'at +-1 V of output (2 V p-p, I swing {dI1*1e3:.2f} mA p-p): {dI1*1e3*15e-6*3.0*1e6:.0f} uV. The test condition is VIN - VOUT = 0.5 V; this board has 0.20..0.39 V *(check)*. Static shift at {i_src*1e3:.2f} mA: {i_src*1e3*15e-6*3.0*1e6:.0f} uV (calibrated out)')
    info('PA-2', 'offset filter at DC: the 100 ohm in series with Rg2 drops the AWG offset current (worst 0.60 mA at DAC 0 V) by', f'{i_src*V["Rvr"]*1e3:.0f} mV (in the transfer as Rg2 + 100 ohm; the closed form absorbs it); time constant {V["Rvr"]*D["Cx"]*1e3:.2f} ms with {D["Cx"]*1e6:.0f} uF (two C15850, 10 uF X5R 0805 25 V, about 7 uF each at 3 V DC bias *(check: the figure given in the brief, not re-read here)*), corner {1/(2*np.pi*V["Rvr"]*D["Cx"]):.0f} Hz', 'the reference sees 1.1 uF + 100 nF only; stable 0.1-22 uF (ref30.pdf 7.3)')
    zdc = 0.045
    fac = 0.543                      # scope centre: Rp / R3 with R1 770k, R2 800k, R3 330k (kicad/design.py scope block): the share of VREF at the follower
    ac = dI * zdc
    info('SC-9', 'AWG-to-scope coupling through the reference at DC (0.045 ohm = 15 ppm/mA x 3 V): the offset current swing over the window at the reference output impedance, then through the scope centre network (R3 330 kohm; centre factor %.3f)' % fac,
         f'{ac*1e3:.3f} mV p-p at the reference, {ac*fac*1e3:.3f} mV at the scope follower = {ac*fac/(3.3/4096):.2f} ADC codes (3.3 V / 4096)', 'against SC-9\'s 2 LSB; the high-frequency impedance is the open item, next rows')
    # high frequency: ref30.pdf Fig 6-14 (output impedance vs frequency, typical, VIN 5 V, 5 V part; the load capacitor is not stated): about 28 ohm peak
    # with a 1 kohm load and about 110 ohm with the output open, both near 1-3 kHz.  The signal current of the AWG enters node X; X has Cx to ground and
    # the 100 ohm to the reference (whose output impedance in series is Zref, taken resistive, with the 1.1 uF there in parallel with the reference).
    gac = 1 + V['Rf'] / V['Rg2']
    dV = (design.OUT_HI - design.OUT_LO) / gac           # p-p voltage on the inverting node for the +-1 V commanded swing at the AC gain
    res = {}
    for lab, (Rg2_, Rflt_, C_, mode) in {'chosen (100 ohm + two 10 uF, 14 uF at 3 V), graph': (V['Rg2'], V['Rvr'], D['Cx'], 'graph'), 'chosen, 110 ohm flat bound': (V['Rg2'], V['Rvr'], D['Cx'], 'bound110'),
                                         'chosen, 28 ohm loaded': (V['Rg2'], V['Rvr'], D['Cx'], 'loaded28'), 'one 10 uF (7 uF at 3 V), graph': (V['Rg2'], V['Rvr'], 7e-6, 'graph'),
                                         'no filter, graph': (V['Rg2'], 0.0, 0.0, 'graph'), 'no filter, 110 ohm flat bound': (V['Rg2'], 0.0, 0.0, 'bound110'),
                                         'Rg2 3 kohm (kvm_02\'s value) with this +-1 V swing and 2 x 10 uF, graph': (3000.0, V['Rvr'], 14e-6, 'graph')}.items():
        m, fpk, ipk = ref_move(dV, Rg2_, Rflt_, C_, mode)
        res[lab] = (m, fpk, ipk, m * fac, m * fac / (3.3 / 4096))
    r = res['chosen (100 ohm + two 10 uF, 14 uF at 3 V), graph']
    add('SC-9', 'AWG-to-scope coupling through the reference, 10 Hz-10 kHz, the full commanded swing (%.2f V pp at the inverting node), REF3030E output impedance as the graph of Fig 6-14 as kvm_02 read it (peak 115 ohm at 1.9 kHz), with the offset filter (100 ohm + two 10 uF, 14 uF at 3 V)' % dV,
        '<= 2 LSB', f'{r[0]*1e3:.3f} mV on the reference at {r[1]:.0f} Hz, {r[3]*1e3:.3f} mV at the scope follower = {r[4]:.2f} ADC codes', f'{2-r[4]:+.2f} codes', r[4] <= 2.0,
        'Fig 6-14 is for the 1.25 V and 5 V parts, load and output capacitance unstated *(check)*; v1 scope centre factor 0.543 (R3 330k, Rp = 179 kohm), follower gain 1')
    for lab in list(res)[1:]:
        q = res[lab]
        info('SC-9', f'the same, {lab}', f'{q[0]*1e3:.3f} mV on the reference, {q[3]*1e3:.3f} mV at the scope follower = {q[4]:.2f} ADC codes', 'the flat 110 ohm bound is the spec lead\'s conservative reading of the same graph' if 'bound' in lab else '')
    rows_hf = [(0, 0, 0, res[k][0], 0, 0, 0) for k in res]
    OUT['ref_hf'] = [list(map(float, r)) for r in rows_hf]
    OUT['ref'] = dict(cur={str(k): v for k, v in cur.items()}, i_src=float(i_src), i_snk=float(i_snk), dI=float(dI), dv=float(dv), others=float(others), dI1=float(dI1))
    # headroom: the +3.3 V rail minimum less the reference output, against the dropout of ref30.pdf Fig 6-11 (read from the graph, 5 V part)
    head = design.RAIL_P[0] - design.VREF3030[1]
    info('PA-2', 'reference input headroom: the +3.3 V rail at its lowest (3.2095 V, 1 % feedback) less the highest reference output (3.006 V) against the dropout the datasheet gives', f'{head*1e3:.0f} mV; dropout 20 typ / 200 mV max at no load (ref30.pdf 6.5); Fig 6-11 reads about 100 mV at 10 mA and 25 C, about 190 mV at 59 C, 370 mV at 125 C (the 5 V part, read off the graph)',
         f'the total load is {(i_src+others)*1e3:.1f} mA; Fig 6-11 reads about 60 mV at 5 mA and 25 C (130 mV at 59 C, 295 mV at 125 C), so 15 to 35 C (EN-1) is inside the margin and a hot enclosure would not be *(check: measure on a board; whatif/v1-basic had 210 mV against 200 mV max at 2 mA)*')


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
    guard('noise', 'feedback network 100x (Rf 330k, Rg2 499k, no Cf) must fail AW-6 at 300 uV; 3.3 k / 4.99 k with Cf passes',
          g_noise, dict(Rf=330e3, Rg2=499e3, Cf=0.0), dict(Rf=3300.0, Rg2=4990.0, Cf=10e-12))

    def g_bw(cbin):
        return bw(dict(cbin=cbin), 'hiz')[1] >= 8e6
    guard('bandwidth, divider compensation', 'the divider without its 10 pF across Rbin must fail 8 MHz (7.8 MHz) and 10 pF passes', g_bw, dict(cbin=0.0), dict(cbin=10e-12))

    def g_bwstray(cpv):
        return bw(dict(cpv=cpv), 'hiz')[1] >= 8e6
    guard('bandwidth, + input stray', 'a 12 pF stray at the + input (compensation then 10 pF against a 12 pF load) must fail 8 MHz; 1.5 pF passes', g_bwstray, dict(cpv=12e-12), dict(cpv=1.5e-12))

    def g_pm(Cf):
        return min(core.phase_margin(dict(Cf=Cf, model='BEH60', cfb=cfb, rails='strong'), load, tag='g_pm')[1] for load in ('hiz', 'cable_open') for cfb in (2e-12, 10e-12)) >= 45
    guard('phase margin', 'Cf removed must fail 45 deg on BEH60 (hi-Z and the open cable, 2 / 10 pF at the inverting node)', g_pm, dict(Cf=0.0), dict(Cf=10e-12))

    def g_pm2(cfb):
        return core.phase_margin(dict(cfb=cfb, model='BEH60', rails='strong'), 'hiz', tag='g_pm')[1] >= 45
    guard('phase margin, node', '400 pF at the inverting node must fail 45 deg on BEH60 with Cf in place (the 3.3 k / 5.1 k pair tolerates 100 pF, min 51 deg, so the layout rule LR-4 has a 10x margin)', g_pm2, dict(cfb=400e-12), dict(cfb=10e-12))

    def g_edge(Rf, Rg2, Rbin, Rbpl):
        v = dict(V); v.update(Rf=Rf, Rg2=Rg2, Rbin=Rbin, Rbpl=Rbpl)
        return design.corner_stats(v)['edge'] <= 0.92
    guard('AW-1 position-aware', 'Rbpl 100 k in place of 126 k (output centred 120 mV low) reads 109 % and must fail 92 %; 51 k + 75 k (91.2 %) passes', g_edge, dict(Rf=3300.0, Rg2=4990.0, Rbin=51e3, Rbpl=100e3), dict(Rf=3300.0, Rg2=4990.0, Rbin=51e3, Rbpl=126e3))

    def g_tol(tol):
        return design.corner_stats(V, tol=tol)['edge'] <= 0.92
    guard('tolerance', '5 % resistors must fail the position-aware 92 % that 1 % passes', g_tol, dict(tol=0.05), dict(tol=0.01))

    def g_gain(Rf, Rg2, Rbin, Rbpl):
        v = dict(V); v.update(Rf=Rf, Rg2=Rg2, Rbin=Rbin, Rbpl=Rbpl)
        e = design.corner_stats(v)
        return e['gmin'] >= 1.10 and e['gmax'] <= 1.20
    guard('AW-7 gain', 'version 2\'s values (470 / 510 / 2.4 k / 27 k, gain 1.76) on version 1\'s window must fail the 1.10..1.20 gain', g_gain, dict(Rf=470.0, Rg2=510.0, Rbin=2400.0, Rbpl=27e3), dict(Rf=3300.0, Rg2=4990.0, Rbin=51e3, Rbpl=126e3))

    def g_off(Rf, Rg2, Rbin, Rbpl):
        v = dict(V); v.update(Rf=Rf, Rg2=Rg2, Rbin=Rbin, Rbpl=Rbpl)
        e = design.corner_stats(v)
        return max(abs(e['o167min']), abs(e['o167max'])) <= 0.060
    guard('AW-7 offset', 'the 3.3 k / 5.1 k / 33 k / 82 k set (the earlier design, +81.8 mV at Vdac = 1.67 V with the 100 ohm in Rg2) must fail the +-60 mV; the chosen set (+54.4 mV, margin 5.6) passes', g_off, dict(Rf=3300.0, Rg2=5100.0, Rbin=33e3, Rbpl=82e3), dict(Rf=3300.0, Rg2=4990.0, Rbin=51e3, Rbpl=126e3))

    def g_sc9(C, Rflt):
        dV = 2.0 / (1 + V['Rf'] / V['Rg2'])
        return ref_move(dV, V['Rg2'], Rflt, C, 'graph')[0] * 0.543 / (3.3 / 4096) <= 2.0
    guard('SC-9 offset filter', 'no filter (and one 10 uF = 7 uF, 100 ohm) must fail the graph-based 2 LSB; 100 ohm + 14 uF passes', g_sc9, dict(C=0.0, Rflt=0.0), dict(C=14e-6, Rflt=100.0))

    def g_rout(rout):
        e = design.corner_stats(V)
        return max(e['top'], -e['bot']) / rout <= 0.030
    guard('short-circuit current', 'a 45 ohm back-termination (10 % low) must fail PW-3\'s 30 mA; 49.5 ohm passes', g_rout, dict(rout=45.0), dict(rout=49.5))

    def g_ref(Rg2):
        return design.VREF3030[1] / (Rg2 * 0.99) + 2.17e-3 <= 10e-3
    guard('reference load', 'Rg2 300 ohm loads the REF3030E past its 10 mA rating; 4.99 kohm does not (0.6 mA)', g_ref, dict(Rg2=300.0), dict(Rg2=4990.0))

    def g_range(th, tl):
        return design.corner_stats(V, th=th, tl=tl)['edge'] <= 0.92
    guard('AW-1 range', 'commanding +-1.2 V must fail the position-aware 92 %; +-1.0 V passes', g_range, dict(th=1.2, tl=-1.2), dict(th=1.0, tl=-1.0))

    def g_short_sim(cmd):
        w = design.corner_stats(V)['corner']
        s_ = sat_op(dict(rails=RAILS['nom'], vref=w['vo'], Rout=49.5), 'short', vd_for(cmd, w['vo']))
        return s_[0] / 49.5 <= 0.030
    guard('short-circuit current, simulated', 'ngspice short with the stage commanded to +2.0 V must read over 30 mA; commanded to the window top end it passes', g_short_sim, dict(cmd=2.0), dict(cmd=design.corner_stats(V)['top']))

    def g_esd2(Rbin):
        old = D['Rbin']
        try:
            D['Rbin'] = Rbin; return esd_run('neither', 3.3)[0] <= 0.5e-3
        finally:
            D['Rbin'] = old
    guard('unpowered DAC0 current', 'Rbin 1 kohm (a version 1-like series resistor, 2.2 mA unpowered at 3.3 V) must fail the 0.5 mA this design reads (0.06 mA); 51 kohm passes', g_esd2, dict(Rbin=1e3), dict(Rbin=51e3))


def write_outputs():
    open(os.path.join(core.HERE, 'awg.cir'), 'w').write(core.build(dict(load='hiz'), analysis='.op'))
    q = D
    parts = [
        ('R1,R2 (parallel)', '100 ohm 1 % 1206', 'C17901', 'AW-4 50 ohm back-termination: two in parallel = 50.0 ohm +-1 %; 20 mW each (40 mW in the pair) at the 28 mA short, rated 250 mW each', 2),
        ('R3', f'{q["Rf"]/1e3:g} kohm 1 % 0603', 'C22978', 'Rf, feedback', 1),
        ('R4', f'{q["Rg2"]/1e3:g} kohm 1 % 0603', 'C23046', 'Rg2, inverting node to the offset-filter node X; no Rg1', 1),
        ('R5', f'{q["Rvr"]:g} ohm 1 % 0603', 'C22775', 'offset filter: REF3030E output to node X (kvm_02 version 2 uses the same 100 ohm)', 1),
        ('C5,C6', '10 uF X5R 10 % 0805 25 V', 'C15850', 'offset filter: node X to GND, two in parallel, about 14 uF at 3 V DC bias *(check)*', 2),
        ('R6', f'{q["Rbin"]/1e3:g} kohm 1 % 0603', 'C23196', 'Rbin: DAC0 series resistor (unpowered current limit, PR-2) and the divider upper arm', 1),
        ('R7', '51 kohm 1 % 0603', 'C23196', 'Rbpl, part 1 of 2 in series (51k + 75k = 126k): divider lower arm; an undriven DAC0 commands ground', 1),
        ('R8', '75 kohm 1 % 0603', 'C23242', 'Rbpl, part 2 of 2 in series', 1),
        ('C1', '10 pF C0G 5 % 0603', 'C1634', 'Cf across Rf: phase margin (AN-1); the smallest Basic C0G', 1),
        ('C4', '10 pF C0G 5 % 0603', 'C1634', 'Cbin across Rbin: compensates the divider against the + input capacitance (AW-3); the same type as Cf', 1),
        ('C2,C3', '100 nF X7R 10 % 0603', 'C14663', 'supply decoupling at the op-amp, one per supply pin', 2),
        ('U3', 'TPH2502-SR dual op-amp SOP-8', 'C118223', 'half A is the gain stage (pins 1 OUT, 2 -IN, 3 +IN); half B is tied off locally (pin 5 +IN to GND, pin 6 -IN to pin 7 OUT); V- pin 4, V+ pin 8', 1),
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
