"""The v2 AWG's constants: the rails the study is run at and the design, in one place. No code runs here.

RAILS and D are the values of design.md and ../powercal/design.md section 1; run.py applies the tolerances, not this file.
"""
KT4 = 4 * 1.380649e-23 * 300.15

# the LM27762 rails with 1 % Basic feedback resistors (R1 120k, R2 68k, R3 56k+8.2k, R4 100k), VFB +-1.5 %, 100 ppm/K opposed over 10 K, +2 mV regulation:
# ../powercal/design.md section 1 (power.py).  weak = least headroom, strong = most; their sum must stay at or below 5.5 V (5.4697 V at the strong corners)
RAILS = {'nom': (3.318, -2.003), 'weak': (3.2205, -1.9549), 'strong': (3.4172, -2.0525)}

# the design (values: design.md).  Tolerance is applied by the Monte Carlo, not here.
D = dict(Rf=3000.0, Rg1=float('inf'), Rg2=3000.0, Cf=10e-12, Rbin=2700.0, Rbpl=27e3, Rout=50.0, cpx=0.0, model='vendor',
         Rs=1000.0, Cs=18e-12, Cout=0.0, topo='Par', Rb=1.0, Rvr=130.0, Cvr=14e-6, vref=3.0, zref=0.05, Cref=1.1e-6, Cdec=0.1e-6,   # 100 nF at each supply pin; the 1 uF pair was dropped (AW-6 0.3 mV, D22)
         cpv=1.5e-12, cfb=2e-12, rp=0.2, rn=0.2,
         dac=1.6745, rails='nom', load='hiz', model_sha_check=True)
