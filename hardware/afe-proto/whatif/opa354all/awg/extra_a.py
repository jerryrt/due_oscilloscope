#!/usr/bin/env python3
"""What-if opa354all, AWG extras (A): OPA354 model vs datasheet Fig 6-13, the AWG stage's loop-gain check with OPA354's
own input capacitance, AW-6 totals, and the DAC0 buffer's DC linearity across the input-stage transition.

    WI_OP=OPA354 python3 -I extra_a.py        (imports run.py of this folder as the buffered variant)
"""
import os, sys, json
ARGS = sys.argv[1:]
sys.argv = ['run.py', '--variant=buf']
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np
import run as R

R.NETDIR = os.path.join(HERE, 'netlists_extra_a'); R.RAWDIR = os.path.join(HERE, 'raw_extra_a')
OUT = {}


def fig613():
    """Datasheet Fig 6-13 (SBOS233H p11): G = +1, VS = 5 V, RL = 1 k to VS/2, VO 0.1 Vpp; CL 5.6 / 47 / 100 pF.
    Read by eye from a 110 dpi render: 5.6 pF flat (no visible peak), 47 pF peaks about +6 dB near 200 MHz,
    100 pF about +8 dB near 100 MHz *(check: graph reading)*."""
    res = {}
    for cl in (5.6e-12, 47e-12, 100e-12):
        for op in ('OPA354', 'OPA365'):
            t = (f".include {R.MODELS[op]}\nVp vcc 0 5\nVh h 0 2.5\nVi in 0 DC 2.5 AC 1\nX1 in out vcc 0 out {op}\n"
                 f"Rl out h 1k\nCl out 0 {cl}\n.ac dec 200 100k 2G\n")
            r = R.ng('f613', t, vecs='v(out)')
            f = r['frequency'].real; g = np.abs(r['v(out)'])
            res[f'{op}/{cl*1e12:g}pF'] = dict(peak_db=float(20 * np.log10(g.max() / g[0])), f_peak_MHz=float(f[g.argmax()] / 1e6))
    OUT['fig6_13'] = res
    return res


def stage_pm():
    """AN-1 of the AWG stage with OPA354, and the loop-gain self-check with the -IN replica set to OPA354's own Cin."""
    # OPA354 model input capacitance at +IN, the same method run.py uses for OPA365
    t = (f".include {R.MODELS['OPA354']}\nVp vcc 0 3.3\nVn vee 0 {R.VN}\nVi in 0 DC 0.5 AC 1\nRi in vp 100k\n"
         "X1 vp out vcc vee out OPA354\n.ac dec 100 1k 1G\n")
    r = R.ng('cin', t, vecs='v(out)')
    f = r['frequency'].real; g = np.abs(r['v(out)'])
    f3 = float(f[np.where(g < g[0] / np.sqrt(2))[0][0]])
    cin = 1 / (2 * np.pi * 100e3 * f3)
    res = dict(cin_pF=cin * 1e12)
    for lab, cn in (('Cin_n 5.4 pF (run.py, OPA365)', 5.4e-12), (f'Cin_n {cin*1e12:.2f} pF (OPA354 model)', cin), ('Cin_n 2 pF (OPA354 datasheet)', 2e-12)):
        p = R.P(Cin_n=cn)
        pm = R.phase_margin(p, tag='lgchk')
        rr = R.ng('clchk', R.build(p, ".ac dec 100 1k 2G\n", ac=('vos',)), vecs='v(out) v(vp)')
        ff = rr['frequency'].real; cl = np.abs(rr['v(out)'] / rr['v(vp)'])
        Tf, T = pm['f'], pm['T']
        d = dict(R.D); d.update(p)
        zf = 1 / (1 / d['Rf'] + 1j * 2 * np.pi * Tf * d['Cf'])
        zg = 1 / (1 / d['Rg'] + 1j * 2 * np.pi * Tf * (d['Cpar_n'] + cn))
        pred = np.abs(T / (1 + T) / (zg / (zf + zg)))
        sel = (Tf > 1e4) & (Tf < 3e7)
        err = float(np.max(np.abs(np.interp(Tf[sel], ff, cl) / pred[sel] - 1)))
        pms = {ld: R.phase_margin(R.P(Cin_n=cn, load=ld), tag='pm')['pm'] for ld in ('hiz', 'r50', 'cable_open', 'short')}
        res[lab] = dict(selfcheck_err=err, pm=pms, pm_min=min(pms.values()))
    OUT['stage_pm'] = res
    return res


def aw6():
    res = {}
    for lab, kw in (('stage OPA354, buffer OPA354 (all-OPA354)', dict(opamp='OPA354', bufop='OPA354')),
                    ('stage OPA365, buffer OPA354', dict(opamp='OPA365', bufop='OPA354')),
                    ('stage OPA354, buffer OPA365', dict(opamp='OPA354', bufop='OPA365')),
                    ('stage OPA365, buffer OPA365 (stored design)', dict(opamp='OPA365', bufop='OPA365'))):
        p = R.P(**kw)
        tot = R.aw6_total(p, tag='nzv')
        n = R.noise_split(p, tag='nz'); n.pop('_f'); n.pop('_tot2')
        res[lab] = dict(total_uV=tot['total_uV'], circuit_uV=tot['circuit_uV'], supply_uV=tot['supply_uV'], ripple_uV=tot['ripple_uV'],
                        by_part_uV=n['by_part_uV'], dens_1MHz=n['density_nV_1MHz'], dens_10MHz=n['density_nV_10MHz'])
    OUT['aw6'] = res
    return res


def linearity():
    """DC sweep of DAC0 over 0.5-2.85 V: the buffer's error v(bo) - v(bin) and the output v(bnc), against a straight line
    fitted over the DAC window (0.578-2.771 V) and over the part AW-1 uses (+/-1 V at hi-Z, about 0.78-2.52 V)."""
    res = {}
    lsb_dac = (2.771 - 0.578) / 4096
    for bo in ('OPA354', 'OPA365'):
        for vp_, ds in ((3.235, 'DBAT54S_MAX'), (3.3, 'DBAT54S_TYP'), (3.342, 'DBAT54S_TYP')):
            for ld in ('hiz', 'r50'):
                p = R.P(opamp=bo, bufop=bo, vp=vp_, dsch=ds, load=ld, dac_pwl='0 1.6 1 1.6', vdac=1.6, vmid=1.65)
                r = R.ng('lin', R.build(p, ".dc Vdp 0.5 2.85 0.002\n"), vecs='v(bo) v(bin) v(bnc) v(bvcx) v(dsrc)')
                vd = r['v(dsrc)'].real; e = (r['v(bo)'] - r['v(bin)']).real; o = r['v(bnc)'].real
                vb = r['v(bin)'].real
                row = dict(bvcx=float(r['v(bvcx)'].real.mean()))
                for nm, lo, hi in (('window', 0.578, 2.771), ('aw1', 0.78, 2.52)):
                    m = (vd >= lo) & (vd <= hi)
                    c = np.polyfit(vb[m], r['v(bo)'].real[m], 1); res_b = r['v(bo)'].real[m] - np.polyval(c, vb[m])
                    co = np.polyfit(vd[m], o[m], 1); res_o = o[m] - np.polyval(co, vd[m])
                    row[nm] = dict(buf_err_mV=(float(e[m].min() * 1e3), float(e[m].max() * 1e3)),
                                   buf_inl_mV=float(np.abs(res_b).max() * 1e3), buf_inl_lsb=float(np.abs(res_b).max() / lsb_dac),
                                   out_inl_mV=float(np.abs(res_o).max() * 1e3), out_inl_lsb=float(np.abs(res_o).max() / (lsb_dac * abs(co[0]))),
                                   vin_at_max_buf_inl=float(vb[m][np.abs(res_b).argmax()]))
                # where the buffer's offset moves fastest (the transition): d(err)/d(vin) peak
                de = np.gradient(e, vb)
                mw = (vd >= 0.578) & (vd <= 2.771)
                row['transition_vin'] = float(vb[mw][np.abs(de[mw]).argmax()])
                row['offset_span_mV'] = float((e[mw].max() - e[mw].min()) * 1e3)
                res[f'{bo}/{vp_}/{ds}/{ld}'] = row
    OUT['linearity'] = res
    return res


if __name__ == '__main__':
    which = ARGS or ['fig613', 'stage_pm', 'aw6', 'linearity']
    for w in which:
        print(w, flush=True); globals()[w]()
    os.makedirs(R.RAWDIR, exist_ok=True)
    json.dump(OUT, open(os.path.join(HERE, 'extra_a_' + '_'.join(which) + '.json'), 'w'), indent=1, default=float)
    print(json.dumps(OUT, indent=1, default=float)[:20000])
