#!/usr/bin/env python3
"""What-if opa354all, powercal side: the per-channel Vmid loop and the reference buffer with OPA354, and SC-2 centring
with OPA354's offset.  Netlists follow sim/powercal/run.py (vmid_pm_netlist, vmid_netlist_pc_z, an4_mc); the vendor
models are read in place by relative path.  Up to 3 ngspice processes.

    python3 -I vmid_ref.py
"""
import os, json, subprocess, math
from concurrent.futures import ThreadPoolExecutor
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = {'OPA365': '../../../models/opa365/OPA365_PSPICE.lib', 'OPA354': '../../../models/opa354/OPA354_PSPICE.lib'}
os.makedirs(os.path.join(HERE, 'raw'), exist_ok=True); os.makedirs(os.path.join(HERE, 'netlists'), exist_ok=True)
OUT = {}

# loops: the task's (sim/powercal's previous loop) and the current design (P8-i/P8-j)
LOOPS = {'task: 1R, 1k / 1.5 nF, 10 uF + 100 nF': dict(riso=1.0, rfb=1e3, cfb=1.5e-9, cd1=10e-6, esr1=0.005),
         'design: 0.2 ohm (5 x 1R), 4.7k / 2 x 1.5 nF, 2 x 10 uF + 100 nF': dict(riso=0.2, rfb=4.7e3, cfb=3.0e-9, cd1=20e-6, esr1=0.0025)}


def spice(name, text):
    p = os.path.join(HERE, 'netlists', name + '.cir')
    open(p, 'w').write(text)
    r = subprocess.run(['ngspice', '-b', p], capture_output=True, text=True, cwd=HERE)
    return r.stdout + r.stderr


def many(jobs):
    with ThreadPoolExecutor(max_workers=3) as ex:
        return list(ex.map(lambda j: spice(*j), jobs))


def pm_net(name, op, v, vdd=3.34):
    t = [f".include {MOD[op]}", f"Vdd vp 0 DC {vdd}", "Vdv dv 0 DC 1.65", f"Xb dv inm vp 0 bo {op}", f"Riso bo vm {v['riso']}",
         f"Rfb vm fb {v['rfb']}", f"Cfb bo fb {v['cfb']}", f"Cd1 vm c1 {v['cd1']}", f"Resr1 c1 0 {v['esr1']}", "Cd2 vm c2 100n", "Resr2 c2 0 0.03",
         "Vbr inm fb DC 0 AC 1", ".ac dec 40 100 200meg", ".control", "run", f"wrdata raw/{name}.txt v(fb) v(inm)", ".endc", ".end"]
    return "\n".join(t) + "\n"


def z_net(name, op, v, vdd=3.34):
    t = [f".include {MOD[op]}", f"Vdd vp 0 DC {vdd}", "Vdv dv 0 DC 1.65", f"Xb dv fb vp 0 bo {op}", f"Riso bo vm {v['riso']}",
         f"Rfb vm fb {v['rfb']}", f"Cfb bo fb {v['cfb']}", f"Cd1 vm c1 {v['cd1']}", f"Resr1 c1 0 {v['esr1']}", "Cd2 vm c2 100n", "Resr2 c2 0 0.03",
         "Iac 0 vm DC 0 AC 1", ".ac dec 40 1k 10meg", ".control", "run", f"wrdata raw/{name}.txt v(vm)", ".endc", ".end"]
    return "\n".join(t) + "\n"


def pm_of(name):
    b = np.loadtxt(os.path.join(HERE, f"raw/{name}.txt")); f = b[:, 0]; T = -(b[:, 1] + 1j * b[:, 2]) / (b[:, 4] + 1j * b[:, 5])
    m = np.abs(T); ph = np.degrees(np.angle(T)); idx = np.where(np.diff(np.sign(m - 1)) != 0)[0]
    return [float((180 + ph[i]) % 360) for i in idx], [float(f[i]) for i in idx]


def vmid():
    grid = [(ck, dr, es) for ck in (0.765, 1.0, 1.265) for dr in (0.25, 0.5, 1.0) for es in (0.002, 0.005, 0.02)]
    res = {}
    jobs, meta = [], []
    for op in ('OPA354', 'OPA365'):
        for lk, L in LOOPS.items():
            for i, (ck, dr, es) in enumerate(grid):
                v = dict(L, cfb=L['cfb'] * ck, cd1=L['cd1'] * dr, esr1=es * (L['esr1'] / 0.005))   # ESR per the loop's own scaling
                nm = f"vm_{op}_{'t' if lk.startswith('task') else 'd'}_{i}"
                jobs += [(nm + '_pm', pm_net(nm + '_pm', op, v)), (nm + '_z', z_net(nm + '_z', op, v))]
                meta.append((op, lk, i, ck, dr, es, nm))
    many(jobs)
    for op, lk, i, ck, dr, es, nm in meta:
        pms, fcs = pm_of(nm + '_pm')
        a = np.loadtxt(os.path.join(HERE, f"raw/{nm}_z.txt")); f = a[:, 0]; z = np.abs(a[:, 1] + 1j * a[:, 2]); b = (f >= 1e3) & (f <= 1e6)
        res.setdefault(f'{op} | {lk}', []).append(dict(cfb_k=ck, c_k=dr, esr=es, pm=min(pms) if pms else None, n_cross=len(pms),
                                                      fc=fcs, zmax=float(z[b].max()), fz=float(f[b][z[b].argmax()])))
    summ = {}
    for k, rows in res.items():
        nom = [r for r in rows if r['cfb_k'] == 1.0 and r['c_k'] == 1.0 and r['esr'] == 0.005][0]
        wp = min(rows, key=lambda r: r['pm']); wz = max(rows, key=lambda r: r['zmax'])
        summ[k] = dict(pm_nom=nom['pm'], fc_nom=nom['fc'], pm_worst=wp['pm'], pm_worst_at=(wp['cfb_k'], wp['c_k'], wp['esr']),
                       one_crossing=all(r['n_cross'] == 1 for r in rows), z_nom=nom['zmax'], fz_nom=nom['fz'], z_worst=wz['zmax'], fz_worst=wz['fz'],
                       z_worst_at=(wz['cfb_k'], wz['c_k'], wz['esr']))
    OUT['vmid'] = summ
    # break on purpose: no isolation and HF feedback 12 pF (powercal's guards) must fail 45 deg with OPA354 too
    g = {}
    for lab, kw in (('no isolation (1 mohm)', dict(riso=1e-3)), ('HF feedback 12 pF', dict(cfb=12e-12))):
        v = dict(LOOPS['design: 0.2 ohm (5 x 1R), 4.7k / 2 x 1.5 nF, 2 x 10 uF + 100 nF'], **kw)
        spice('g_' + lab[:4].replace(' ', ''), pm_net('g_' + lab[:4].replace(' ', ''), 'OPA354', v))
        g[lab] = min(pm_of('g_' + lab[:4].replace(' ', ''))[0] or [float('nan')])
    OUT['vmid_guards_OPA354'] = g
    return summ


def ref_buffer():
    """REF3030E (ideal 3.000 V) -> follower on +3.3 V_A -> ladder 1328 ohm at -tol (1326.7) to ground; output trace/pin C.
    DC: output error and the headroom at 3.235 / 3.288 / 3.342 V.  AC: loop break at -IN, C at the pin 5-30 pF."""
    res = {}
    rl = 1328.0 * 0.999
    jobs, meta = [], []
    for op in ('OPA354', 'OPA365'):
        for vp in (3.235, 3.288, 3.342):
            nm = f"ref_dc_{op}_{vp}"
            jobs.append((nm, f".include {MOD[op]}\nVp vp 0 {vp}\nVr r 0 3.0\nX1 r o vp 0 o {op}\nRl o 0 {rl}\n.op\n.control\nrun\nprint v(o) i(Vp)\n.endc\n.end\n"))
            meta.append(('dc', op, vp, None, nm))
            for c in (5e-12, 10e-12, 15e-12, 30e-12):
                nm2 = f"ref_pm_{op}_{vp}_{c*1e12:g}"
                jobs.append((nm2, f".include {MOD[op]}\nVp vp 0 {vp}\nVr r 0 3.0\nX1 r inm vp 0 o {op}\nRl o 0 {rl}\nCl o 0 {c}\n"
                                  f"Vbr inm o DC 0 AC 1\n.ac dec 40 1k 2G\n.control\nrun\nwrdata raw/{nm2}.txt v(o) v(inm)\n.endc\n.end\n"))
                meta.append(('pm', op, vp, c, nm2))
    logs = many(jobs)
    for (kind, op, vp, c, nm), lg in zip(meta, logs):
        if kind == 'dc':
            vo = [float(l.split('=')[1]) for l in lg.splitlines() if l.strip().startswith('v(o)')][0]
            res[f'{op} dc {vp}'] = dict(vout=vo, err_mV=(vo - 3.0) * 1e3, i_mA=vo / rl * 1e3, headroom_mV=(vp - 3.0) * 1e3)
        else:
            b = np.loadtxt(os.path.join(HERE, f"raw/{nm}.txt")); f = b[:, 0]
            T = -(b[:, 1] + 1j * b[:, 2]) / (b[:, 4] + 1j * b[:, 5])
            m = np.abs(T); ph = np.degrees(np.angle(T)); idx = np.where(np.diff(np.sign(m - 1)) != 0)[0]
            res[f'{op} pm {vp} {c*1e12:g}pF'] = min(float((180 + ph[i]) % 360) for i in idx) if len(idx) else None
    OUT['ref'] = res
    return res


# ---- SC-2 centring (P8-c's an4_mc), with the Vmid buffer offset as a parameter
SC_RF, SC_RG = 953.0, 249.0
RSF = 249.0


def an4(vos, r1, r2, r3, rs3_shared, N=200000, delta=5e-3, rdiv=330e3, tol_div=0.001, seed=7):
    """r1/r2/r3 the divider; rs3_shared True: one 249 ohm sense filter for both channels (P8-c's old network), False: one per
    channel (the current design: R3 + Rs3 = R1, so the sense resistor is inside R3's leg).  vos: Vmid buffer max |VOS|."""
    rng = np.random.default_rng(seed)
    u = lambda tol: rng.uniform(-tol, tol, N)
    e = []
    for v33 in (3.10, 3.20, 3.25, 3.30):
        rt = rdiv * (1 + u(tol_div)); rb = rdiv * (1 + u(tol_div))
        vmid = v33 * rb / (rt + rb) + u(vos) + u(10e-12 * rdiv / 2 if vos < 1e-3 else 50e-12 * rdiv / 2)
        R1 = r1 * (1 + u(0.001)); R2 = r2 * (1 + u(0.001)); R3 = r3 * (1 + u(0.001)); g = 1 + SC_RF * (1 + u(0.001)) / (SC_RG * (1 + u(0.001)))
        if rs3_shared:
            i_s = (v33 - 1.65) / r3 + rng.uniform(0, v33 / r3, N); vs = v33 - i_s * RSF
        else:
            vs = v33           # own 249 in series inside R3 (R3 here is the whole leg, 16.67k + 249); the 10 uF holds the node at DC
        n0 = (vmid / R2 + vs / R3) / (1 / R1 + 1 / R2 + 1 / R3)
        aref = v33 - delta
        for pin in (n0, g * n0 - (g - 1) * vmid):
            e.append(np.abs(pin - aref / 2))
    return float(np.max(e))


def centring():
    res = {}
    old = (760e3, 330e3, 760e3, True)
    # current per-channel divider (architecture.md): R1 = six 100k || + 249 = 16.916k; R2 = 8 x 953 || 330k = 7.452k; R3 leg 16.667k + 249
    r1 = 1 / (6 / 100e3) + 249.0; r2 = 1 / (1 / (8 * 953.0) + 1 / 330e3); r3 = 1 / (6 / 100e3) + 249.0
    new = (r1, r2, r3, False)
    for lab, net in (('old 760k/330k/760k (P8-c)', old), (f'current {r1/1e3:.2f}k/{r2/1e3:.3f}k/{r3/1e3:.2f}k', new)):
        for vl, vos in (('OPA365 0.2 mV (25 C max)', 0.2e-3), ('OPA354 8 mV (25 C max)', 8e-3), ('OPA354 10 mV (-40..125 C max)', 10e-3)):
            res[f'{lab} | {vl}'] = an4(vos, *net) * 1e3
    # analytic sensitivity of the pin to the Vmid offset, current divider
    k = (1 / (1 / r1 + 1 / r3)) / ((1 / (1 / r1 + 1 / r3)) + r2)
    res['d pin / d Vmid, current divider: +/-5 V (G 1) / +/-1.25 V (G 4.83)'] = (k, 1 - (1 + SC_RF / SC_RG) * (1 - k))
    OUT['centring_mV'] = res
    # break on purpose: the check must fail when the offset is large enough (100 mV) and pass at OPA365's
    OUT['centring_guard'] = dict(broken_100mV=an4(0.1, *new) * 1e3, restored_0p2mV=an4(0.2e-3, *new) * 1e3)
    return res


if __name__ == '__main__':
    centring(); print(json.dumps(OUT['centring_mV'], indent=1), OUT['centring_guard'], flush=True)
    vmid(); print(json.dumps(OUT['vmid'], indent=1), OUT['vmid_guards_OPA354'], flush=True)
    ref_buffer(); print(json.dumps(OUT['ref'], indent=1), flush=True)
    json.dump(OUT, open(os.path.join(HERE, 'vmid_ref.json'), 'w'), indent=1, default=float)
