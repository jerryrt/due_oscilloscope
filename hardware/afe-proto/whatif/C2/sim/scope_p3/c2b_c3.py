import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from c2b_common import *
DES = dict(Csw=6e-12, C2=27.5e-12)
R = {"sens": {}, "vmid": {}}
for csw in ():
    R["sens"][str(csw)] = comp_row(pp(Csw=csw*1e-12, C2=27.5e-12))
    print("sens", csw, {rg: {k: round(v, 3) if "bw" not in k else round(v/1e6, 3) for k, v in x.items()} for rg, x in R["sens"][str(csw)].items()}, flush=True)
lsb = LSB(3.2)
def xt_ac(p, vfs):
    txt = header(p, "xac") + rails(p) + f"Va sa 0 dc 0 ac {vfs}\nRsa sa ain 50\n" + core(p, pre="a") + "\nVb sb 0 dc 0\nRsb sb bin 50\n" + core(p, pre="b") + f"""
.control
ac dec 20 1k 10meg
wrdata {wr('xac','x')} v(bpin)
.endc
.end
"""
    run_ng("xac", txt); d = load("xac", "x"); f = d[:, 0]; v = np.abs(d[:, 1] + 1j*d[:, 2])
    return dict(peak_lsb=float(v.max()/lsb), f_peak=float(f[v.argmax()]), at_10k_lsb=float(np.interp(1e4, f, v)/lsb), at_1M_lsb=float(np.interp(1e6, f, v)/lsb))
def xt_tran(p, vfs, tr=5e-9):
    txt = header(p, "xtr") + rails(p) + f"Va sa 0 dc 0 pulse(0 {vfs} 200n {tr} {tr} 20u 40u)\nRsa sa ain 50\n" + core(p, pre="a") + "\nVb sb 0 dc 0\nRsb sb bin 50\n" + core(p, pre="b") + f"""
.control
tran 1n 20u 0 2n
wrdata {wr('xtr','x')} v(bpin)
.endc
.end
"""
    run_ng("xtr", txt); d = load("xtr", "x"); t = d[:, 0]; v = d[:, 1]
    base = v[t < 190e-9].mean(); dev = np.abs(v - base); bad = np.where(dev > 0.5*lsb)[0]
    return dict(peak_lsb=float(dev.max()/lsb), t_peak_us=float((t[dev.argmax()]-200e-9)*1e6), recover_0p5LSB_us=float((t[bad[-1]]-200e-9)*1e6) if len(bad) else 0.0,
                final_lsb=float((v[t > 19e-6].mean()-base)/lsb))
for vg in (True,):
    key = "powercal" if vg else "50mohm"; out = {}
    for rng, vfs in (("5", 6.0), ("1.25", 1.25)):
        p = pp(rng=rng, vmid_gen=vg, **DES)
        for lab, adc in ():
            hi = kick_run(p, +vfs, 0.0, adc, aref=3.2); lo = kick_run(p, -vfs, 0.0, adc, aref=3.2); full = kick_run(p, +vfs, -vfs, adc, aref=3.2)
            out[f"{rng}_{lab}_kick"] = dict(crosstalk_lsb=abs(hi["errB_lsb"]-lo["errB_lsb"]), full_err=max(abs(full["errA_lsb"]), abs(full["errB_lsb"])), settle_ns=full["settleB_ns"])
        out[f"{rng}_ac"] = xt_ac(p, vfs)
        out[f"{rng}_tran_up"] = xt_tran(p, vfs); out[f"{rng}_tran_dn"] = xt_tran(p, -vfs)
        for tr in (42e-9, 5e-9):
            out[f"{rng}_edge_{tr*1e9:.0f}ns"] = step_response(p, "e2c", 2.0 if rng == "5" else 0.5, tr, tstop=2.5e-6)
    R["vmid"][key] = out
    print(key, json.dumps(out, default=float), flush=True)
save("c2b_c_fast", R)
