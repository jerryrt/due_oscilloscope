#!/usr/bin/env python3
"""AFE version 2 with the scope range of version 1 (owner, 2026-11-13): each input +-5 V nominal, usable to +-6 V.

A VALUES change on the same circuit, layout and part positions (no topology change, no new op-amp).  This script is the
closed-form half of the study: it derives the divider, shows why version 1's values are the answer in version 2's six
positions (a 0 ohm part where version 1 has one), and prints every DC figure against the requirement text.  The ngspice
half is run.py with --range 5v (sections dc ac bw noise d17 tran stab beh prot xtalk static mc guards cscan), results in
range5v/results/.  numpy only; exit 0 when every check passes.

    python3 -I hardware/afe-proto/v2/sim/scope/range5v.py [--json FILE]

Limits (docs/afe.md, as amended by docs/afe-v2.md):
  SC-2   +-6 V usable with the ADC pin inside 0..AREF with >= 80 mV per side at AREF 3.20 V; over AREF 3.20..3.30 V,
         component tolerance and a +-30 mV centring error
  SC-3   1 Mohm nominal within 1 % (D-V2-9: the 1 % parts' spread allowed on top), capacitance at most 30 pF
  SC-4   at most 4 mV per code at the input; +-5 V (10 V) occupies 70..75 % of full scale at nominal AREF 3.25 V
  SC-7   scope terms: R1 against R2||R3 drift (100 ppm/K opposed, 10 K), REF modulation into the centre, VOS drift
  SC-8   channel gain match (afe-v2.md 3.1: 3 %; afe.md D19: 5.5 %)
  PR-1   +-12 V at both inputs, powered or not: the currents through R1 and into the REF3030E
"""
import csv
import itertools
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BASIC = os.path.join(HERE, '..', '..', 'jlc-basic.csv')

AREF_LO, AREF_HI, AREF_NOM = 3.20, 3.30, 3.25
MARGIN, CENTRE_ERR = 0.080, 0.030
VOS_MAX = 0.5e-3                     # TPH2502 datasheet +-500 uV max (run.py)
CMRR_ERR = 3.0 * 10 ** (-65 / 20)    # run.py's CMRR term at 3.3 V *(check)*
USABLE = {'v2 old': (-2.0, 4.0), '5 V': (-6.0, 6.0)}
VR, VR_TOL = 3.0, 0.002
TOL = 0.01
TC = 100e-6
RIN = 1e6

# (R1a, R1b), (R2a, R2b), (R3a, R3b); the board's positions are CH1 R101/R102, R103/R104, R105/R106 (+100 for CH2)
VALUES = {
    'v2 old': dict(R1=(510e3, 30e3), R2=(1e6, 510e3), R3=(470e3, 200e3), C1=22e-12, Cn=12e-12, Rnp=470.0, Cpx=10e-12),
    '5 V': dict(R1=(470e3, 300e3), R2=(470e3, 330e3), R3=(330e3, 0.0), C1=12e-12, Cn=30e-12, Rnp=470.0, Cpx=10e-12),
}


def net(r1, r2, r3, vr=VR):
    rp = 1 / (1 / r1 + 1 / r2 + 1 / r3)
    return rp / r1, vr * rp / r3, r1 + 1 / (1 / r2 + 1 / r3), rp


def tot(v, k):
    return float(sum(v[k]))


def parse(s):
    for u, m in (('R', 1), ('k', 1e3), ('M', 1e6)):
        if u in s:
            a, b = s.split(u)
            return (float(a) if '.' in a else float((a or '0') + '.' + (b or '0'))) * m
    return float(s)


def basic_values():
    with open(BASIC) as f:
        return sorted({parse(r['value']) for r in csv.DictReader(f)
                       if r['kind'] == 'resistor' and r['basic'].strip().lower() == 'yes' and r['package'] == '0603'} - {0.0})


def sweep(name, v, n=200_000, seed=20261113):
    lo_in, hi_in = USABLE[name]
    full = 10.0 if name == '5 V' else 5.0       # the rated span the SC-4 occupancy is quoted for
    rng = np.random.default_rng(seed)
    parts = np.array(list(v['R1']) + list(v['R2']) + list(v['R3']))
    var = np.array([0 if p == 0 else 1 for p in parts])   # a 0 ohm part carries no tolerance that matters (<= 50 mohm *(check)*)
    R = parts[:, None] * (1 + var[:, None] * rng.uniform(-TOL, TOL, (6, n)))
    r1, r2, r3 = R[0] + R[1], R[2] + R[3], R[4] + R[5]
    vr = VR * (1 + rng.uniform(-VR_TOL, VR_TOL, n))
    vos = rng.uniform(-VOS_MAX, VOS_MAX, n) + rng.uniform(-CMRR_ERR, CMRR_ERR, n)
    a, voff, rin, rp = net(r1, r2, r3, vr)
    R2 = parts[:, None] * (1 + var[:, None] * rng.uniform(-TOL, TOL, (6, n)))       # a second, independent channel
    a2 = net(R2[0] + R2[1], R2[2] + R2[3], R2[4] + R2[5], vr)[0]
    lo_pin, hi_pin = voff + a * lo_in + vos, voff + a * hi_in + vos
    # the exact worst case: every combination at +-1 % (a 0 ohm part fixed) and the reference at +-0.2 %
    cs = np.array(list(itertools.product((-1, 1), repeat=7)), dtype=float)
    Rc = parts[None, :] * (1 + 0.01 * cs[:, :6] * var[None, :])
    ac, vc, rc, _ = net(Rc[:, 0] + Rc[:, 1], Rc[:, 2] + Rc[:, 3], Rc[:, 4] + Rc[:, 5], VR * (1 + 0.002 * cs[:, 6]))
    vos_w = VOS_MAX + CMRR_ERR
    nom = net(tot(v, 'R1'), tot(v, 'R2'), tot(v, 'R3'))
    out = dict(
        a_nom=nom[0], voff_nom=nom[1], rin_nom_k=nom[2] / 1e3, rp_nom_k=nom[3] / 1e3,
        a_range=[float(ac.min()), float(ac.max())], rin_k_range=[float(rc.min() / 1e3), float(rc.max() / 1e3)],
        span_pct_FS_nom_aref=[float(full * ac.min() / AREF_NOM * 100), float(full * ac.max() / AREF_NOM * 100)],
        span_pct_FS_nom=float(full * nom[0] / AREF_NOM * 100),
        mV_per_code_worst=float(AREF_HI / 4096 / ac.min() * 1e3),
        pin_usable_nom=[float(nom[1] + nom[0] * lo_in), float(nom[1] + nom[0] * hi_in)],
        # margins against 0 and AREF 3.20, worst over the 128 corners with VOS and the 30 mV centring error
        lo_margin_mV=float(((vc + ac * lo_in).min() - vos_w - CENTRE_ERR) * 1e3),
        hi_margin_mV=float((AREF_LO - (vc + ac * hi_in).max() - vos_w - CENTRE_ERR) * 1e3),
        lo_margin_mV_mc=float((lo_pin.min() - CENTRE_ERR) * 1e3), hi_margin_mV_mc=float((AREF_LO - hi_pin.max() - CENTRE_ERR) * 1e3),
        lo_margin_mV_nocentre=float(((vc + ac * lo_in).min() - vos_w) * 1e3),
        hi_margin_mV_nocentre=float((AREF_LO - (vc + ac * hi_in).max() - vos_w) * 1e3),
        centre_pin_V_range=[float(vc.min()), float(vc.max())],
        gain_match_pct_max_mc=float(np.abs(a / a2 - 1).max() * 100),
    )
    # worst gain mismatch between two channels from the corners: max a / min a - 1
    out['gain_match_pct_corners'] = float((ac.max() / ac.min() - 1) * 100)
    # PR-1, both inputs at +-12 V, DC: the amplifier's input diodes hold +IN near the rails; the current is through R1 only
    r1n = tot(v, 'R1')
    out['pr1'] = {
        '+12 V': dict(node_open_V=float(nom[1] + nom[0] * 12), i_R1_uA=float((12 - 3.6) / r1n * 1e6), ref_sink_uA=float((3.6 - VR) / tot(v, 'R3') * 1e6)),
        '-12 V': dict(node_open_V=float(nom[1] + nom[0] * -12), i_R1_uA=float((-12 + 0.3) / r1n * 1e6), ref_source_uA=float((VR + 0.3) / tot(v, 'R3') * 1e6)),
    }
    # REF3030E: source at the lowest usable input, sink with the node held at the rail + diode drop
    n_lo = voff + a * lo_in
    out['ref_source_uA_max_per_channel'] = float(((vr - n_lo) / r3).max() * 1e6)
    out['ref_sink_uA_clamped_per_channel'] = float(((3.3 * 1.01 + 0.7 - vr) / r3).max() * 1e6)
    # SC-7 scope terms at the input for a 10 K change since calibration
    d = TC * 10
    r1n, r2n, r3n = tot(v, 'R1'), tot(v, 'R2'), tot(v, 'R3')
    a0, _, _, rp0 = net(r1n, r2n, r3n)
    a1 = net(r1n * (1 - d), r2n * (1 + d), r3n * (1 + d))[0]
    out['sc7_scope_10K'] = dict(gain_drift_pct=float((a1 / a0 - 1) * 100),
                                ref_mod_input_mV=float(VR * 15e-6 * 10 * (rp0 / r3n) / a0 * 1e3),
                                vos_drift_input_mV=float(2e-6 * 10 / a0 * 1e3))
    out['gain_drift_20K_pct'] = float((net(r1n * (1 - 2 * d), r2n * (1 + 2 * d), r3n * (1 + 2 * d))[0] / a0 - 1) * 100)
    out['ref_to_pin'] = float(rp0 / r3n)
    # an input of 1 V in the AWG loopback: codes per volt at the pin, for the PAM table
    out['codes_per_V_input_3p25'] = float(a0 / AREF_NOM * 4096)
    return out


def search(vals, k=6):
    """Every v2-position build (R1, R2: one part or two in series, R3: one part or two in series) against SC-3 / SC-4 / SC-2,
    ranked by the worst margin over the corners.  Shows where the version 1 values sit; a 0 ohm in a pair is a one-part build."""
    rows = []
    cand = lambda x: [(y,) for y in vals if 0.4 * x < y < 1.6 * x] + [(p, q) for p in vals for q in vals if p >= q and 0.8 * x < p + q < 1.2 * x and 0.05 * x < q]
    # fixed ideal targets from SC-4 and the centre
    a_t = 0.725 * AREF_NOM / 10.0
    voff_t = AREF_NOM / 2 - 0.0
    r1_t = RIN * (1 - a_t)
    r3_t = VR * (a_t * r1_t) / voff_t
    r2_t = 1 / (1 / (r1_t * a_t / (1 - a_t)) - 1 / r3_t)
    c1, c2, c3 = cand(r1_t), cand(r2_t), cand(r3_t)
    c1 = sorted(c1, key=lambda c: abs(sum(c) / r1_t - 1))[:60]
    c2 = sorted(c2, key=lambda c: abs(sum(c) / r2_t - 1))[:60]
    c3 = sorted(c3, key=lambda c: abs(sum(c) / r3_t - 1))[:60]
    for x1, x2, x3 in itertools.product(c1, c2, c3):
        r1, r2, r3 = sum(x1), sum(x2), sum(x3)
        a, voff, rin, rp = net(r1, r2, r3)
        span = 10 * a / AREF_NOM
        if not (0.71 <= span <= 0.74) or abs(rin / RIN - 1) > 0.01:
            continue
        v = dict(R1=(x1 + (0.0,))[:2], R2=(x2 + (0.0,))[:2], R3=(x3 + (0.0,))[:2])
        parts = np.array(list(v['R1']) + list(v['R2']) + list(v['R3']))
        cs = np.array(list(itertools.product((-1, 1), repeat=7)), dtype=float)
        var = (parts != 0).astype(float)
        Rc = parts[None, :] * (1 + 0.01 * cs[:, :6] * var[None, :])
        ac, vc, _, _ = net(Rc[:, 0] + Rc[:, 1], Rc[:, 2] + Rc[:, 3], Rc[:, 4] + Rc[:, 5], VR * (1 + 0.002 * cs[:, 6]))
        if 10 * ac.min() / AREF_NOM < 0.70 or 10 * ac.max() / AREF_NOM > 0.75:      # SC-4's 70..75 % must hold at the 1 % corners too
            continue
        slack = min((vc + ac * -6.0).min() - 0.0 - CENTRE_ERR - VOS_MAX - CMRR_ERR - MARGIN,
                    AREF_LO - MARGIN - CENTRE_ERR - VOS_MAX - CMRR_ERR - (vc + ac * 6.0).max())
        nparts = sum(len(x) for x in (x1, x2, x3))
        rows.append((-slack * 100 + 0.5 * nparts, slack, v, nparts, a, rin))
    rows.sort(key=lambda r: r[0])
    return rows[:k]


def verdicts(new, old=None):
    """[(name, ok, detail)] for one set of sweep() figures against the requirement text."""
    sp = new['span_pct_FS_nom_aref']
    v = [
        ('SC-3 Rin nominal 1 Mohm +-1 %', abs(new['rin_nom_k'] / 1e3 - 1) <= 0.01,
         f'{new["rin_nom_k"]:.1f} k nominal; 1 % parts {new["rin_k_range"][0]:.1f}..{new["rin_k_range"][1]:.1f} k'),
        ('SC-4 mV/code <= 4 (AREF 3.30, smallest a)', new['mV_per_code_worst'] <= 4.0, f'{new["mV_per_code_worst"]:.3f} mV'),
        ('SC-4 +-5 V span 70..75 % FS (AREF 3.25, 1 % parts, corners)', sp[0] >= 70.0 and sp[1] <= 75.0,
         f'{sp[0]:.2f}..{sp[1]:.2f} % (nominal {new["span_pct_FS_nom"]:.2f})'),
        ('SC-2 low margin (pin >= 80 mV, with VOS and +-30 mV centring)', new['lo_margin_mV'] >= 80,
         f'{new["lo_margin_mV"]:.1f} mV (slack {new["lo_margin_mV"] - 80:.1f}); MC {new["lo_margin_mV_mc"]:.1f}'),
        ('SC-2 high margin (pin <= AREF 3.20 - 80 mV)', new['hi_margin_mV'] >= 80,
         f'{new["hi_margin_mV"]:.1f} mV (slack {new["hi_margin_mV"] - 80:.1f}); MC {new["hi_margin_mV_mc"]:.1f}'),
        ('SC-8 channel gain match <= 3 % (afe-v2.md 3.1; 200,000 draws, the project\'s method)', new['gain_match_pct_max_mc'] <= 3.0,
         f'{new["gain_match_pct_max_mc"]:.2f} % (information: 128 corners {new["gain_match_pct_corners"]:.2f} %; afe.md D19 5.5 %)'),
    ]
    return v


def main(argv):
    out = {}
    res = {name: sweep(name, VALUES[name]) for name in ('v2 old', '5 V')}
    out['figures'] = res
    new, old = res['5 V'], res['v2 old']
    print('value sets (R1 = R1a + R1b, R2 = R2a + R2b, R3 = R3a + R3b):')
    for k, v in VALUES.items():
        print(f'  {k:7s} R1 {tot(v, "R1")/1e3:g}k  R2 {tot(v, "R2")/1e3:g}k  R3 {tot(v, "R3")/1e3:g}k  C1 {v["C1"]*1e12:g}p Cn {v["Cn"]*1e12:g}p Rnp {v["Rnp"]:g}')
    for name in ('v2 old', '5 V'):
        f = res[name]
        print(f'{name}: a {f["a_nom"]:.4f}, centre {f["voff_nom"]:.4f} V, Rin {f["rin_nom_k"]:.1f}k, Rp {f["rp_nom_k"]:.1f}k, Rp/R3 {f["ref_to_pin"]:.4f}, '
              f'span {f["span_pct_FS_nom"]:.2f} % FS @3.25 V, {f["codes_per_V_input_3p25"]:.1f} codes/V, {f["mV_per_code_worst"]:.3f} mV/code worst')
    print('checks (5 V):')
    fails = []
    for name, ok, detail in verdicts(new, old):
        print(f'  [{"PASS" if ok else "FAIL"}] {name}: {detail}')
        if not ok:
            fails.append(name)
    print(f'  (info) SC-7 scope terms, 10 K: {new["sc7_scope_10K"]}  (v2 old: {old["sc7_scope_10K"]})')
    print(f'  (info) PR-1 DC: {new["pr1"]}')
    print(f'  (info) REF3030E per channel: source {new["ref_source_uA_max_per_channel"]:.2f} uA, sink {new["ref_sink_uA_clamped_per_channel"]:.2f} uA (rating +-10 mA); '
          f'REF reaches the pin by Rp/R3 = {new["ref_to_pin"]:.3f} (v2 old {old["ref_to_pin"]:.3f}, x{new["ref_to_pin"] / old["ref_to_pin"]:.2f})')
    print('search over the six positions (Basic 0603; slack = worst margin over 128 corners less 80 mV, VOS and 30 mV centring included; SC-4 span 70..75 % at the corners):')
    rows = search(basic_values())
    out['search'] = [dict(score=r[0], slack_mV=r[1] * 1e3, R1=r[2]['R1'], R2=r[2]['R2'], R3=r[2]['R3'], parts=r[3], a=r[4], rin_k=r[5] / 1e3) for r in rows]
    for r in rows:
        print(f'  slack {r[1]*1e3:6.1f} mV  parts {r[3]}  R1 {r[2]["R1"]} R2 {r[2]["R2"]} R3 {r[2]["R3"]}  a {r[4]:.4f} Rin {r[5]/1e3:.1f}k')
    if '--json' in argv:
        with open(argv[argv.index('--json') + 1], 'w') as f:
            json.dump(out, f, indent=1)
    print('ALL PASS' if not fails else 'FAIL: ' + ', '.join(fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
