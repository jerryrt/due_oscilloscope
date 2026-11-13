#!/usr/bin/env python3
"""v1 scope + AWG study with the extracted strays: thin driver over v2's harnesses (model.py patches them to v1's circuit).

    python3 -I run_study.py [--out DIR] [--work DIR] [scope] [awg]        (default: both; results/*.json under --out)

Run in the PCB image (docker/pcb/run.sh).  Needs the vendor macro (models/tph2501/TPH2501.mdl, local, MC-6).  Writes
scope_{baseline,A,B}.json and awg.json; nothing else is written beside the code."""
import os, sys, json, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import model


def scope_case(case, out, work):
    R, NL = model.scope_setup(case, os.path.join(work, 'out_scope_' + case), os.path.join(work, 'scope_' + case))
    R.check_model()
    p0 = R.pp()
    res = dict(case=case, params=dict(zip(('Cn_par_pF', 'Cx_pF', 'Cxp_pF', 'Cxin_pF', 'Cwire_pF'), model.CASES[case])))
    r1, r2, r3 = (NL.rsum(NL.P0[k]) for k in ('R1', 'R2', 'R3'))
    res['Rdc_series_ohm'] = r1 + 1 / (1 / r2 + 1 / r3)
    ac = R.sec_ac()                                      # SC-5 (-3 dB, shelf), SC-3 (zin: R and C)
    res['ac'] = {k: v for k, v in ac.items() if not isinstance(v, (list, dict)) or k == 'zin'}
    lsb = R.LSB(R.AREF_LO)

    def xt(p, f0):                                       # v2's sec_xtalk.run: 1 V at A, 6 Vpp equivalent
        t = NL.header('xt') + NL.rails(p) + 'Vsa asrc 0 dc 1.0 ac 1\nVsb bsrc 0 dc 1.0\n' + NL.chan(p, 'a') + NL.chan(p, 'b') + NL.coupling(p) + f"""
.control
ac lin 1 {f0} {f0}
wrdata {NL.wr('xt', 'x')} v(apin) v(bpin)
.endc
.end
"""
        NL.run_ng('xt', t)
        d = NL.load('xt', 'x')
        ha = abs(d[0, 1] + 1j * d[0, 2]); hb = abs(d[0, 4] + 1j * d[0, 5])
        return float(hb / ha * 3.0 * ha / lsb)
    p = R.pp()
    res['sc9_lsb_6Vpp'] = {f'{int(f / 1e6)}MHz': xt(p, f) for f in (5e6, 10e6)}
    base10 = res['sc9_lsb_6Vpp']['10MHz']
    for key, par in (('N_N', 'Cx'), ('pad_pad', 'Cxp'), ('IN_IN', 'Cxin')):          # fF per LSB at 10 MHz, from +0.1 pF
        k = xt(R.pp(**{par: p[par] + 0.1e-12}), 10e6) - base10
        res[f'{key}_fF_per_LSB_10MHz'] = 100.0 * max(1 - base10, 0) / k if k > 0 else None
    res['pm'] = {}
    for m in R.MODELS:
        with R.use_model(m):
            res['pm'][m] = R.loop_pm(R.pp())
    return res


def awg_case(work):
    import numpy as np
    core = model.awg_setup(os.path.join(work, 'awg'))
    out = {}
    loads = ('hiz', 'r50', 'cable_open', 'cap330', 'cap1n')

    def worst(cfb, cbin, models=('vendor', 'BEH21', 'BEH60')):
        core.CBIN[0] = cbin
        w = {}
        for m in models:
            rows = [dict(load=l, rails=r, pm=float(core.phase_margin(dict(core.V1, rails=r, cfb=cfb * 1e-12, model=m), l, tag='pm')[1]),
                         fc_MHz=float(core.phase_margin(dict(core.V1, rails=r, cfb=cfb * 1e-12, model=m), l, tag='pm')[0]))
                    for l in loads for r in ('weak', 'strong')]
            w[m] = min(rows, key=lambda r: r['pm'])
        return w
    out['an1'] = {name: dict(cfb_pF=c, worst=worst(c, model.PARAMS['AWG Cbin'][0])) for name, c in model.AWG_CASES.items()}

    def bw(cpad, cbin, cvr=None):                       # DAC pin to BNC, -3 dB, hi-Z load, weak rails (v2's bw)
        core.CBIN[0] = cbin
        q = dict(core.V1, rails='weak', model='vendor', cfb=2e-12)
        if cvr:
            q['Cvr'] = cvr
        extra = f'Cpad bin 0 {cpad * 1e-12:.6g}\n' if cpad else ''
        b = core.build(dict(q, load='hiz'), analysis='', ac=('dac',), extra=extra)
        h, d, log = core.wr('bw', b, 'ac dec 80 1e3 1e9', ['v(bnc)'])
        f = d[:, 0]; g = np.abs(d[:, 1] + 1j * d[:, 2]); g0 = g[0]
        i = np.where(g < g0 / np.sqrt(2))[0][0]
        w = (np.log(1 / np.sqrt(2)) - np.log(g[i - 1] / g0)) / (np.log(g[i] / g0) - np.log(g[i - 1] / g0))
        f3 = float(np.exp(np.log(f[i - 1]) + w * (np.log(f[i]) - np.log(f[i - 1]))))
        j = np.argmin(abs(f - 1e5)); k = np.argmin(abs(f - 3e6))
        return dict(g_dc=float(g0), f3dB_MHz=f3 / 1e6, g_100kHz_over_dc=float(g[j] / g0), g_3MHz_over_dc=float(g[k] / g0), peak=float(g.max() / g0))
    out['c304_bandwidth'] = {f'Cpad_{c}pF': dict(with_C304=bw(c, model.PARAMS['AWG Cbin'][0]), without_C304=bw(c, 0.0)) for c in (0.0, 2.0, 4.0, 8.0)}
    out['c304_pm_baseline'] = dict(with_C304=worst(2.0, model.PARAMS['AWG Cbin'][0], ('BEH21', 'BEH60')), without_C304=worst(2.0, 0.0, ('BEH21', 'BEH60')))
    core.V1['Cvr'] = 14e-6                                # the two 10 uF X5R at 3 V bias, v2's derating: 14 uF effective
    out['cvr_14uF_effective'] = worst(2.0 + model.STRAYS['AWG_INV_top'], model.PARAMS['AWG Cbin'][0], ('BEH21', 'BEH60'))
    core.V1['Cvr'] = model.PARAMS['AWG Cvr'][0]

    # ---- AW-3 threshold: the largest AWG_BIN stray at which DAC pin to BNC -3 dB is still >= 8 MHz, C304 modelled.
    # +IN-node strays as the harness defines the node: Cpad = AWG_BIN to ground (the variable), Cbpl = AWG_BPL (the divider's middle
    # node) at its extracted top of bar, the op-amp's own input capacitance inside the macro; Cfb (inverting node) at case A (2 + 0.61 pF)
    # and case B (0.61 pF); vendor macro, hi-Z load (v2's AW-3 row), both rail corners; the figure is the worst of the four.
    def f3(cpad, cbpl, cfb):
        res = []
        for rails in ('weak', 'strong'):
            core.EXTRA[0] = f'Cpad bin 0 {cpad * 1e-12:.6g}\nCbpl bpl 0 {cbpl * 1e-12:.6g}\n'
            b = core.build(dict(core.V1, rails=rails, model='vendor', cfb=cfb * 1e-12, load='hiz'), analysis='', ac=('dac',))
            h, d, log = core.wr('bw', b, 'ac dec 80 1e3 1e9', ['v(bnc)'])
            f = d[:, 0]; g = np.abs(d[:, 1] + 1j * d[:, 2]); g0 = g[0]
            i = np.where(g < g0 / np.sqrt(2))[0][0]
            w = (np.log(1 / np.sqrt(2)) - np.log(g[i - 1] / g0)) / (np.log(g[i] / g0) - np.log(g[i - 1] / g0))
            res.append(float(np.exp(np.log(f[i - 1]) + w * (np.log(f[i]) - np.log(f[i - 1]))) / 1e6))
        core.EXTRA[0] = ''
        return min(res)
    cfbs = {'A': 2.0 + model.STRAYS['AWG_INV_top'], 'B': model.STRAYS['AWG_INV_top']}
    cbpl = model.STRAYS['AWG_BPL_top']

    def worst4(cpad):
        return min(f3(cpad, cbpl, c) for c in cfbs.values())
    lo, hi, tol, log = 0.0, 20.0, 0.01, []
    log.append(dict(cpad_pF=lo, f3dB_MHz=worst4(lo))); log.append(dict(cpad_pF=hi, f3dB_MHz=worst4(hi)))
    assert log[0]['f3dB_MHz'] >= 8.0 > log[1]['f3dB_MHz'], log
    while hi - lo > tol:
        mid = round((lo + hi) / 2, 6)
        v = worst4(mid)
        log.append(dict(cpad_pF=mid, f3dB_MHz=v))
        lo, hi = (mid, hi) if v >= 8.0 else (lo, mid)
    top = model.STRAYS['AWG_BIN_top']
    out['aw3_threshold'] = dict(limit_MHz=8.0, threshold_pF=lo, tolerance_pF=tol, bracket_pF=[lo, hi], bisection_log=log,
                                assumed=dict(Cbpl_pF=cbpl, Cfb_pF=cfbs, rails='weak and strong', model='vendor', load='hiz', C304_pF=model.PARAMS['AWG Cbin'][0] * 1e12),
                                extracted_top_of_bar_pF=top,
                                at_extracted_top={k: dict(f3dB_MHz=f3(top, cbpl, c)) for k, c in cfbs.items()}, margin_pF=lo - top)
    out['an1_with_bin_strays'] = {}
    for k, c in cfbs.items():
        core.EXTRA[0] = f'Cpad bin 0 {top * 1e-12:.6g}\nCbpl bpl 0 {cbpl * 1e-12:.6g}\n'
        out['an1_with_bin_strays'][k] = worst(c, model.PARAMS['AWG Cbin'][0])
    core.EXTRA[0] = ''
    core.CBIN[0] = model.PARAMS['AWG Cbin'][0]
    out['corner'] = dict(Rbin_Cbin_s=model.PARAMS['AWG Rbin'][0] * model.PARAMS['AWG Cbin'][0],
                         zero_Hz=1 / (2 * 3.141592653589793 * model.PARAMS['AWG Rbin'][0] * model.PARAMS['AWG Cbin'][0]),
                         matched_node_cap_pF=model.PARAMS['AWG Rbin'][0] * model.PARAMS['AWG Cbin'][0] / sum(model.PARAMS['AWG Rbpl'][0]) * 1e12)
    return out


def main(argv):
    out, work, want, it = os.path.abspath(os.path.join(HERE, '..', '..', 'results')), None, [], iter(argv)
    for a in it:
        if a == '--out': out = os.path.abspath(next(it))
        elif a == '--work': work = os.path.abspath(next(it))
        else: want.append(a)
    work = work or tempfile.mkdtemp(prefix='v1-study-')
    os.makedirs(out, exist_ok=True)
    want = want or ['scope', 'awg']
    # one process per scope case: v2's harness holds its parameters in module globals
    if 'scope' in want:
        cases = [c for c in model.CASES]
        import subprocess
        for c in cases:
            r = subprocess.run([sys.executable, '-I', os.path.abspath(__file__), '--one', c, '--out', out, '--work', work], capture_output=True, text=True)
            sys.stdout.write(r.stdout[-300:]); sys.stderr.write(r.stderr[-1500:])
            if r.returncode:
                return r.returncode
    if 'awg' in want:
        json.dump(awg_case(work), open(os.path.join(out, 'awg.json'), 'w'), indent=1, sort_keys=True)
    return 0


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--one':
        c = sys.argv[2]; a = sys.argv[3:]
        out = a[a.index('--out') + 1]; work = a[a.index('--work') + 1]
        res = scope_case(c, out, work)
        json.dump(res, open(os.path.join(out, f'scope_{c}.json'), 'w'), indent=1, sort_keys=True, default=float)
        print(c, 'done')
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
