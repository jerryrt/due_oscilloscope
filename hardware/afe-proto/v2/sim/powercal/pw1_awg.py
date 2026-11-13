#!/usr/bin/env python3
"""PW-1 re-derived for the AWG at its +-1.6 V guaranteed range (owner ruling 2026-11-13), by hand, from datasheet figures and the loads of the design.

    python3 -I pw1_awg.py          # prints the budget, writes results/pw1_awg.json

Independent of power.py: it imports nothing from this folder, so a mistake there cannot reach it.  Every term names its source; 'typ' marks a
typical-only figure *(check)*.  PW-1: the AFE draws at most 100 mA from the Due's 5V pin in normal operation with any AWG load AW-4 allows, and the Due
(300 mA, D7) plus the AFE at most 450 mA, also in the indefinite-short fault (the short is exempt from the 100 mA, not from the 450 mA).

The 5V pin carries: the +LDO output current (1:1) + the inverting pump's output current x (1 + 10 % overhead allowance *(check)*) + the LM27762's own IQ.
The AWG output current is the stage's output current at the commanded end: 1.6 V over the 100 ohm of back-termination plus the 50 ohm load, plus or
minus the feedback network's share.
"""
import json, os, sys

# ---- sources ------------------------------------------------------------------------------------------------------------------------
IQ_AMP_MAX = 7.5e-3        # TPH2502 datasheet Rev. A, Electrical Characteristics, PDF p. 4: IQ per amplifier 6.5 mA typ, 7.5 mA max (models/tph2502/tph2502.pdf)
ADS_IQ_MAX = 300e-6        # ADS1115 SBAS444E 5.5: operating current 150 uA typ, 200 uA max at 25 C, 300 uA over temperature
REF_IQ_MAX = 37e-6         # REF3030E SBVS032K: quiescent current 27 uA typ, 37 uA max over temperature
LM_IQ_TYP = 0.39e-3        # LM27762 SNVSAF7C: IQ typical, no maximum given *(check)*
PUMP_OVERHEAD = 0.10       # allowance on the inverting pump's input current over its output current *(check: no efficiency table in the PDF text)*
VP_MAX = 3.4177            # the strong +rail corner (design.md section 1, 1 % feedback resistors)
VREF = 3.009               # REF3030E 3.000 V +0.3 % (initial 0.1 % + 0.2 % allowance)
# loads of the design (../awg/design.md, powercal/design.md): Rg2 + Rvr 3.1 kohm, Rf 3 kohm; ladder 6 x 330 ohm at -1 %; scope centres 2 x 5.4 uA; bleed 1.8 kohm;
# I2C pull-ups 2 x 4.7 kohm if fitted on the AFE; sense divider default tie 20 kohm total to the reference
RF, RG2, RVR = 3000.0, 3000.0, 100.0
ROUT, RLOAD = 49.5, 50.0   # the back-termination at its low corner (2 x 100 ohm 1 %), and a 50 ohm load
I_BLEED = VP_MAX / 1.8e3
I_I2C = 2 * VP_MAX / 4.7e3
I_LADDER = VREF / (6 * 330.0 * 0.99)
I_CENTRES = 2 * 5.4e-6
SCOPE_AMPS = 2            # The +-5 V change is values only: the scope still uses the one shared dual (U101, both halves) and the AWG its own dual (U301), so power.py's two scope halves stand.

def awg(vout, rl):
    K = RF / (RG2 + RVR); Gs0 = 1 + K
    vinv = (vout + K * VREF) / Gs0
    i_g2 = (VREF - vinv) / (RG2 + RVR)           # the offset path, from the reference (supplied from the +rail)
    i_load = 0.0 if rl is None else vout / (ROUT + rl)
    i_o = i_load - i_g2                          # op-amp output current, + sourcing from the +rail
    return i_g2, i_load, i_o

def budget(vout, rl, scope_amps=SCOPE_AMPS):
    i_g2, i_load, i_o = awg(vout, rl)
    sense = abs(VREF - (vout / 2 if rl else vout)) / 20e3
    ip = dict(awg_iq=2 * IQ_AMP_MAX, awg_offset_path=i_g2, awg_output_src=max(i_o, 0.0), scope_iq=scope_amps * IQ_AMP_MAX, ads=ADS_IQ_MAX,
              ref_iq=REF_IQ_MAX, ladder=I_LADDER, sense_tie=sense, centres=I_CENTRES, i2c=I_I2C, bleed=I_BLEED)
    ineg = dict(awg_iq=2 * IQ_AMP_MAX, awg_output_snk=max(-i_o, 0.0))
    Ip, In = sum(ip.values()), sum(ineg.values())
    return dict(vout=vout, rl=rl, i_load=i_load, i_o=i_o, Ip=Ip, In=In, Iin=Ip + In * (1 + PUMP_OVERHEAD) + LM_IQ_TYP, terms_p=ip, terms_n=ineg)

def main():
    rows = []
    for name, v, rl in (("hi-Z, +1.6 V", 1.6, None), ("hi-Z, -1.6 V", -1.6, None), ("50 ohm, +1.6 V (op-amp output 16 mA)", 1.6, RLOAD),
                        ("50 ohm, -1.6 V (op-amp output 16 mA)", -1.6, RLOAD), ("50 ohm, 0 V", 0.0, RLOAD)):
        b = budget(v, rl); b["name"] = name; rows.append(b)
    worst = max(r["Iin"] for r in rows)
    awg_alone = 1.6 / (ROUT + RLOAD)                       # the 16 mA load by itself, on one rail
    inc_p = awg_alone * 1e3; inc_n = awg_alone * 1e3 * (1 + PUMP_OVERHEAD)
    # fault totals, the indefinite short at the ends of the window (AC top 2.1971 V hard corner 49.5 ohm; bottom stage output about -1.73 V, power.py/awg/run.py)
    shorts = {}
    for name, vout in (("short, DAC at the window top (2.197 V AC top end)", 2.1971), ("short, DAC at the window bottom (-1.73 V, weak-rail clip)", -1.73),
                       ("short, DAC at the 3.3 V reset level (stage output about 3.0 V, accepted transient D-V2-12)", 3.0)):
        b = budget(vout, 0.0); shorts[name] = b["Iin"]
    worst_fault = max(shorts.values())
    # headroom: how many more op-amp halves (7.5 mA each, from OUT+ or OUT-) the 100 mA allows over the worst normal state
    head_halves_p = (0.100 - worst) / IQ_AMP_MAX
    out = dict(rows=[{k: (v if not isinstance(v, dict) else {a: round(c * 1e3, 3) for a, c in v.items()}) for k, v in r.items()} for r in rows],
               worst_normal_mA=worst * 1e3, margin_100_mA=100 - worst * 1e3, awg_load_alone_mA=awg_alone * 1e3,
               awg_load_on_5V_pin_mA=(inc_p + inc_n) / 2, shorts_mA={k: v * 1e3 for k, v in shorts.items()}, worst_fault_mA=worst_fault * 1e3,
               total_with_due_mA=300 + worst_fault * 1e3, margin_450_mA=450 - (300 + worst_fault * 1e3), extra_opamp_halves_within_100mA=head_halves_p)
    print("PW-1 with the AWG at +-1.6 V (strong +rail 3.4177 V, IQ at the datasheet maximum)")
    for r in rows:
        print(f"  {r['name']:42s} OUT+ {r['Ip']*1e3:6.2f} mA  OUT- {r['In']*1e3:6.2f} mA  5V pin {r['Iin']*1e3:6.2f} mA  (op-amp output {r['i_o']*1e3:+.2f} mA)")
    print(f"worst normal state {worst*1e3:.1f} mA against 100 mA: {100-worst*1e3:+.1f} mA; the 16 mA AWG load alone adds {inc_p:.1f} mA (OUT+ at +1.6 V) or {inc_n:.1f} mA (OUT- x 1.10 at -1.6 V) to the 5V pin")
    for k, v in shorts.items():
        print(f"  fault {k}: {v*1e3:.1f} mA AFE, {300+v*1e3:.1f} mA with the Due (limit 450)")
    print(f"extra op-amp halves the 100 mA would still carry: {head_halves_p:.1f} (7.5 mA each, taken from OUT+)")
    # guard: the same check with the limit lowered to 40 mA must fail, the real one pass
    assert worst * 1e3 > 40 and worst * 1e3 <= 100, "guard"
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"), exist_ok=True)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "pw1_awg.json"), "w") as f:
        json.dump(out, f, indent=1)
    return 0 if worst * 1e3 <= 100 and 300 + worst_fault * 1e3 <= 450 else 1

if __name__ == "__main__":
    sys.exit(main())
