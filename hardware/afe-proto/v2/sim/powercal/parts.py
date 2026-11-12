#!/usr/bin/env python3
"""parts.csv of this block (rails, reference, ladder, sense, precision ADC).  Passives are looked up in ../../jlc-basic.csv and the run fails if one is not
Basic (V2-3); ICs are Extended per v2/parts.md and whatif/bom.md.  Unit prices are left blank (priced elsewhere).  python3 -I parts.py"""
import csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

ROWS = [  # refs, value, LCSC, role, qty
 ("U1", "LM27762 (WSON-12)", "C473398", "rails: +3.318 V_A and -2.003 V, shared by scope and AWG (V2-1)", 1),
 ("R_FB1", "120k 1 % 0603", "C25808", "LM27762 OUT+ feedback top (R1)", 1),
 ("R_FB2", "68k 1 % 0603", "C23231", "LM27762 OUT+ feedback bottom (R2, >= 50k)", 1),
 ("R_FB3a", "56k 1 % 0603", "C23206", "LM27762 OUT- feedback (R3, first of two in series: 64.2k)", 1),
 ("R_FB3b", "8.2k 1 % 0603", "C25981", "LM27762 OUT- feedback (R3, second of two)", 1),
 ("R_FB4", "100k 1 % 0603", "C25803", "LM27762 OUT- feedback bottom (R4, >= 50k)", 1),
 ("R_SENSE", "1R 1 % 0603", "C22936", "5 V feed sense resistor (test point either side)", 1),
 ("R_BLEED", "1.8k 1 % 0603", "C4177", "+3.3 V_A bleed (PR-3 and the AWG node forced to +5 V unpowered): 0.28 mA at 0.5 V; 1.8 mA at 3.3 V", 1),
 ("C_IN1,C_IN2", "10uF X5R 25 V 0805", "C15850", "LM27762 VIN bulk", 2),
 ("C_CP1,C_CP2", "10uF X5R 25 V 0805", "C15850", "LM27762 CPOUT", 2),
 ("C_OP1,C_OP2", "10uF X5R 25 V 0805", "C15850", "LM27762 OUT+", 2),
 ("C_ON1,C_ON2", "10uF X5R 25 V 0805", "C15850", "LM27762 OUT-", 2),
 ("C_FLY", "1uF X5R 50 V 0603", "C15849", "LM27762 flying capacitor C1", 1),
 ("U2", "REF3030E (SOT-23)", "C54120492", "3.000 V reference, +-0.1 %: ADS1115 anchor, ladder top, scope centre (D-V2-10)", 1),
 ("C_REFO", "1uF X5R 50 V 0603", "C15849", "REF3030E output (CL 0.1..22 uF)", 1),
 ("C_REFI", "100nF X7R 50 V 0603", "C14663", "REF3030E input (CIN >= 0.1 uF)", 1),
 ("U3", "ADS1115IDGSR (VSSOP-10)", "C37593", "16-bit four-input precision ADC, I2C (V2-8)", 1),
 ("C_ADS", "100nF X7R 50 V 0603", "C14663", "ADS1115 VDD (datasheet: 0.1 uF)", 1),
 ("R_L1..R_L6", "330R 1 % 0603", "C23138", "calibration ladder, six equal rungs (taps at 1/6 .. 6/6 of the reference)", 6),
 ("R_SRT", "15k 1 % 0603", "C22809", "AWG-sense divider top (Rt)", 1),
 ("R_SRB", "10k 1 % 0603", "C25804", "AWG-sense divider bottom (Rb): k = 0.4", 1),
 ("R_SRD", "1k 1 % 0603", "C21190", "sense divider's permanent default tie of the bottom node to the REF3030E (Rd)", 1),
 ("R_SRS", "3.9k 1 % 0603", "C23018", "series resistor from the tap to ADS1115 AIN2: the passive protection (VT-22); with Rt || Rb it is 9.9k, matched by R_SRM", 1),
 ("J_RAT", "1x3 male header, 2.54 mm, plated holes + pins", "", "calibration jumper header J_RAT, pin 1 = the 2/3 ladder tap | pin 2 = B | pin 3 = the 1/2 ladder tap (v1's form: TAP4 | B | TAP3): HAND-SOLDERED (not part of the assembled board), fitted by the owner; the only wrong placement is the shunt slipped across pins 1-2", 1),
 ("SH_RAT", "2.54 mm shunt (jumper cap)", "", "the calibration shunt, fitted across pins 2-3 (B and the 1/2 tap) for one calibration (one touch, with the tee cable) and removed with it; a hand tool, not assembled", 1),
 ("R_SRM", "10k 1 % 0603", "C25804", "series resistor from the divider bottom B to ADS1115 AIN3: matches AIN2's source impedance so Zcm loading cancels in the differential reading", 1),
]

def build(rows=ROWS):
    out = []
    for refs, value, lcsc, role, qty in rows:
        hand = refs in ("J_RAT", "SH_RAT")
        is_ic = value.startswith(("LM27762", "REF3030", "ADS1115"))
        row = lookup(lcsc)
        if hand:
            basic = "not a JLC part: hand-fitted (LCSC number *(check)*)"
        elif is_ic:
            basic = "Extended (v2/parts.md, whatif/bom.md)"
        else:
            if row is None or row["basic"] != "yes":
                raise SystemExit(f"{refs}: {lcsc} is not a Basic part in jlc-basic.csv (V2-3)")
            tok = value.split()[0]
            if row["value"].replace(" ", "").lower() != tok.replace(" ", "").lower():
                raise SystemExit(f"{refs}: {lcsc} is {row['value']} in jlc-basic.csv, not {tok}")
            basic = f"Basic (jlc-basic.csv, read {row['date_read']})"
        out.append((refs, value, lcsc, basic, role, qty, ""))
    return out

def main():
    rows = build()
    with open(os.path.join(HERE, "parts.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["refs", "value", "lcsc", "basic_status", "role", "qty", "unit_price"])
        w.writerows(rows)
    print(len(rows), "rows;", sum(r[5] for r in rows), "parts per board")
    # guard: an Extended passive (174k C861163) must be refused
    bad = list(ROWS); bad[1] = ("R_FB1", "174k 0.1 % 0603", "C861163", "x", 1)
    try:
        build(bad); broken = True
    except SystemExit:
        broken = False
    g = Guards("parts"); g.add("G-basic", "an Extended passive (C861163) in the list must be refused", broken, True); g.save(); print(g.rows)

if __name__ == "__main__":
    main()
