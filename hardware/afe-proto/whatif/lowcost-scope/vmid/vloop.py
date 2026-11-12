"""Per-channel Vmid loop with an MCP6002 half (or another buffer): node impedance and loop phase margin.
Standalone; netlists and data in ./net, results printed.  Run: python3 -I vloop.py"""
import os, sys, subprocess, numpy as np, json, itertools
HERE = os.path.dirname(os.path.abspath(__file__))
NET = os.path.join(HERE, "net"); os.makedirs(NET, exist_ok=True)
MCP = "../../../../models-open/mcp6002/mcp6002_open.lib"
TLV = "../../../../models/tlv9062/tlv9062.lib"
open(os.path.join(NET, ".spiceinit"), "w").write("set ngbehavior=ps\n")   # the TI GWL model needs PSpice compatibility
def buf_line(kind, inp, inm, vdd, out, ro=300, fp2=6e6, gbw=1e6, a0db=112):
    if kind == "mcp":
        return f"X{out} {inp} {inm} {vdd} 0 {out} MCP6002_OPEN params: ro={ro} fp2={fp2} gbw={gbw} a0db={a0db}"
    if kind == "tlv":
        return f"X{out} {inp} {inm} {vdd} 0 {out} TLV9062"
    if kind == "lin365":   # powercal P8-k stand-in for the OPA365 loop: A0 90 dB, GBW 59.2 MHz, Rout 64.4
        A0 = 10 ** 4.5; g = 59.2e6
        return (f"Ex{out} {out}x 0 {inp} {inm} {A0}\nRx{out} {out}x {out}y 1k\nCx{out} {out}y 0 {A0/(2*np.pi*g*1e3)}\n"
                f"Ey{out} {out}z 0 {out}y 0 1\nRy{out} {out}z {out} 64.4")
    raise ValueError(kind)
def loop(kind, d, mode, name, **kw):
    """mode z: AC current into the node; mode t: loop broken between the feedback node and -IN (P8-j's method)."""
    inm = "inm" if mode == "t" else "fb"
    t = [f"* Vmid loop {kind} {d}", f".include {MCP}", f".include {TLV}", "Vdd vdd 0 3.3", "Vt tap 0 1.65",
         buf_line(kind, "tap", inm, "vdd", "bo", **kw),
         f"Riso bo vm {d['riso']}", f"Rfb vm fb {d['rfb']}", f"Cfb bo fb {d['cfb']}",
         f"Cd1 vm c1 {d['cnode']}", f"Re1 c1 0 {d['esr']}", "Cd2 vm c2 100n", "Re2 c2 0 30m"]
    if d.get("rd"):    # optional damping branch: R in series with C at the node
        t += [f"Cdd vm cdd {d['cd']}", f"Rdd cdd 0 {d['rd']}"]
    if mode == "z":
        t += ["Iac 0 vm dc 0 ac 1", ".control", "ac dec 40 1 10meg", f"wrdata {name}.dat v(vm)", ".endc", ".end"]
    else:
        t += ["Vbr inm fb dc 0 ac 1", ".control", "ac dec 40 1 100meg", f"wrdata {name}.dat v(fb) v(inm)", ".endc", ".end"]
    p = os.path.join(NET, name + ".cir"); open(p, "w").write("\n".join(t) + "\n")
    r = subprocess.run(["ngspice", "-b", name + ".cir"], cwd=NET, capture_output=True, text=True)
    a = np.loadtxt(os.path.join(NET, name + ".dat"))
    if mode == "z":
        return a[:, 0], a[:, 1] + 1j * a[:, 2]
    T = -(a[:, 1] + 1j * a[:, 2]) / (a[:, 4] + 1j * a[:, 5])
    return a[:, 0], T
def pm(f, T):
    m = np.abs(T); ph = np.degrees(np.angle(T)); idx = np.where(np.diff(np.sign(m - 1)) != 0)[0]
    return [(float(f[i]), float((180 + ph[i]) % 360)) for i in idx]
def evaluate(kind, d, tag="x", **kw):
    f, z = loop(kind, d, "z", f"z_{tag}", **kw); az = np.abs(z)
    ft, T = loop(kind, d, "t", f"t_{tag}", **kw); c = pm(ft, T)
    return dict(zmax=float(az.max()), fz=float(f[np.argmax(az)]), z10=float(np.interp(10, f, az)), z1k=float(np.interp(1e3, f, az)),
                crossings=c, pm_min=min(x[1] for x in c) if c else None, f=f, z=z)
if __name__ == "__main__":
    base = dict(riso=0.2, rfb=4.7e3, cfb=3e-9, cnode=20e-6, esr=2.5e-3)
    r = evaluate("lin365", base, "ref"); print("OPA365 stand-in, design loop:", {k: v for k, v in r.items() if k not in ('f', 'z')})
    for ro in (50, 300, 1000):
        r = evaluate("mcp", base, f"mcp{ro}", ro=ro); print(f"MCP ro {ro}, design loop:", {k: v for k, v in r.items() if k not in ('f', 'z')})
