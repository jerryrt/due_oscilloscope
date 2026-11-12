import json, sys
for v in sys.argv[1:]:
    J = json.load(open(f'out/{v}/results.json'))
    c = J['corners']; n = c['nominal']; pc = c['part-tolerance corners']; tt = c['corners + temperature (100 / 25 ppm/K x 40 K, assumed)']
    st = J['step']['fast/cable_open/Rs49.9/Cpar_corners']
    sw = J['swing']
    rows = {r['case'][:60]: r for r in J['rows']}
    nz = [r for r in J['rows'] if r['case'].startswith('added noise')][0]['worst']
    fl = J['bw']['flatness_10k_8M']
    s3 = J['step']['fast/cable_open/Rs49.9']['settle_1pct']; sd = J['step']['dac_edge/hiz']['settle_1pct']
    print(f"== {v}: Ra {J['design']['Ra']:.1f} Rb {J['design']['Rb']:.1f} Ca {J['design']['Ca']*1e12:.2f}p Cb {J['design']['Cb']*1e12:.1f}p rflt {J['design']['rflt']}")
    print(f"  slope {n['slope']:.4f} gain {n['gain']:.4f} offset_analytic {n['off_mV']:+.2f} mV (Rf/Rg req {n['Rf_over_Rg_required']:.4f} vs 1.2004); spice {J['dc_offset_nominal_V']*1e3:+.2f} mV; tols {c['tols']}")
    for lab, d in (('corners', pc), ('corners+T', tt)):
        print(f"  {lab}: " + ' | '.join(f"{s}: width {d[s]['use']*100:.1f} pos {d[s]['edge']*100:.1f} AW5 {d[s]['i']*1e6:.1f}uA gain {d[s]['gain'][0]:.4f}-{d[s]['gain'][1]:.4f} off {d[s]['off']*1e3:.1f}" for s in 'AB'))
    print(f"  swing r50 nominal err {sw['r50']['err_max']*1e3:.3f} mV least {sw['r50']['least']:.4f}; rail limit {sw.get('r50_rail_limit')}; corners err {c['swing_r50_corners']['err_max']*1e3:.3f} mV least {c['swing_r50_corners']['least']:.4f}")
    print(f"  overshoot {', '.join(f'{k} {x*100:.2f}%' for k,x in st.items())}; flat {fl}; settle fast {s3*1e9:.0f} ns dac {sd*1e9:.0f} ns")
    print(f"  noise {nz}; PW3 nominal {max(abs(x['i_short_mA']) for x in J['short'].values()):.2f} corners {c['pw3_corners_mA']:.2f}; pm {min(x['pm'] for k,x in J['pm'].items() if k.startswith('OPA365/') ):.1f}; bw hiz {J['bw']['OPA365']['f3db']/1e6:.1f} corners {J['bw']['corners']['f3db_min']/1e6:.1f} r50 {J['bw']['corners']['f3db_min_r50']/1e6:.1f}")
