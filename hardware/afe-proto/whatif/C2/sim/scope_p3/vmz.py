import sys; sys.path.insert(0,'.')
from run import *
for g in (False, True):
    p=pp(vmid_gen=g, aref=3.3)
    txt=header(p,"vmz")+rails(p)+"Iz 0 vm dc 0 ac 1\n.control\nop\nprint v(vm)\nac dec 40 1k 10meg\nwrdata ../work/vmz_z.dat v(vm)\n.endc\n.end\n"
    out=run_ng("vmz",txt); d=load("vmz","z"); f=d[:,0]; z=np.abs(d[:,1]+1j*d[:,2])
    print(g, re.search(r"v\(vm\) = \S+", out).group(0), f"Z1k {np.interp(1e3,f,z)*1e3:.1f} mohm, max {z.max():.3f} ohm at {f[z.argmax()]/1e3:.0f} kHz, 10MHz {np.interp(1e7,f,z)*1e3:.1f} mohm")
