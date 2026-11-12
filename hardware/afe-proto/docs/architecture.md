# AFE architecture, round 1 (Step 1 output, draft for G1)

Requirements are in `docs/afe.md`; this file says how they are met and
which choices the simulations (`docs/afe-plan.md`, step 2) must settle.
Budgets that need no datasheet are in `budget/afe_budget.py`
(`python3 -I hardware/afe-proto/budget/afe_budget.py`). Part numbers are
candidates until a simulation passes; stock and price are in `jlcpcb.md`.
The circuit as built is the KiCad project in `../kicad/` (design FR-01,
`design.py` and `DESIGN-01.md`), drawn from this file and the simulations.

## Facts the design is built on

- **The Due's AREF header pin is not the 3.3 V rail on a stock Due.** BR1
  is open and JR1 is fitted, so AREF goes nowhere (`hardware/reference/
  arduino-due/v03/README.md`). The AFE used to sense the Due's **3.3 V
  pin** (`POWER0.4`, the same net as ADVREF through JR1 and L3) through a
  high-impedance divider, at microamps (PW-1); **it no longer does**: the
  scope channels are centred from the REF3030E (`budget/v1_scope_ref.py`,
  `docs/afe.md` D19), so the shield draws nothing from the Due's 3.3 V pin
  and POWER0.4 is unconnected. The reference still routes to the AREF pin
  through the unfitted 0 ohm (PA-7). `afe.md` section 4.1 and PW-1 say AREF
  or the 3.3 V pin is the sense point; that text needs correcting.
- Hardware SPI is **not** on any edge header, and the precision ADC no
  longer needs it: the ADS1115 is an I2C part on **SDA1/SCL1, PWMH0.9 and
  PWMH0.10** (D70/D71 on the Due; the SAM3X's TWI0 pins, not TWI1), the top edge, its traces along the west
  and top board edges so no digital line crosses an analog zone
  (`docs/afe.md` LR-9, D14, D15; `docs/due-header-table.md`). The Due has no
  pull-ups on those two nets (V03: each reaches U1 and PWMH0 only), so the
  shield carries them, **R69 and R82, 4.7k to +3.3 V_A** (`whatif/bom.md`,
  "Control-pin pull resistors"). D5-D8 are free again, as is every XIO0 pin;
  **SDA1 / SCL1 are the only Due pins the shield uses** and **no Due control pin
  is driven** (the ratio switch and its pin D9 are gone, D25;
  `docs/due-header-table.md` section 5).
- **The +/-1.25 V range is removed (`docs/afe.md` D18).** The range-select
  pins D16 (CH1) and D39 (CH2), the two range switches, their decouplers and
  their pull-downs are gone, and so is the ratio switch with its pin D9 and
  4.7k pull-down (D25: the ratio is measured with a hand-fitted jumper, see
  Calibration), so no Due control line is left. The ADC's chip
  select and its pull-up are gone with the SPI (`whatif/bom.md`,
  "Control-pin pull resistors"). Text below that describes RF, RG, the
  switch across RF or the 1.25 V range is history, marked as such.
- **Every resistor and capacitor is a JLC Basic part** (D15, V2-3): 1 %
  thick film at 100 ppm/K (20 ohm and up), with C0G for the small
  capacitors, values from `v2/jlc-basic.csv`. The 0.1 % precision parts of
  the earlier rounds are gone. SC-8, DF-3 and EN-1 are re-stated for 1 %
  and 100 ppm/K in `whatif/v1-basic/values.md` (section 3: SC-8 5.4 % and
  7.1 %, DF-3 before calibration 25 and 23 dB, EN-1 0.34 % and 0.62 %,
  against limits written for 0.1 % parts; `docs/afe.md` carries the
  current ones), and **the figures quoted below
  that were taken with 0.1 % parts are marked as superseded** where the new
  values move them. Those runs kept the old op-amp models
  (`values.md`); the TPH2502 runs are in `whatif/tph2502/`.

## Scope channel (x2, separate packages, SC-9) - 1 Mohm compensated, 2026-11-11

SM-5 is dropped and the input is 1 Mohm again (owner, 2026-11-11): the
first round's compensated divider with every change approved since.
Calibration is a BNC tee from the AWG into both inputs, so nothing is
switched onto N. Simulated values and margins are in `sim/scope/report.md`
(variant `hz`, the default) and `sim/diff/report.md`; numbers there, not
here, are the record *(superseded for the REF3030E-centred network: see
`whatif/v1-basic/values.md`, `whatif/tph2502/`, `budget/v1_scope_ref.py`; the
reports describe the Vmid-centred one)*. The ~22 kohm route (c) designs stay reproducible
as `--variant lowz` / `lowz2` and are not developed further.

```
BNC - IN --R1 770k--+--N--Rnp 680--+-- TPH2502 (+)     (U1, one dual for both channels)
        (470k + 300k)|   (C1 12 pF across R1;  Cnp 10 pF from the (+) node to GND;
                    |    C2 30 pF from N to GND)
                    +--R2 800k (470k + 330k) -- GND
                    +--R3 330k -- VREF (the REF3030E output, 3.0 V)
op-amp: unity follower, (-) tied to out (D18; the RF 1k / RG 270 pair, the
        range switch across RF and the +/-1.25 V range, gain 1 + 1k/270 = 4.70,
        are removed)
out -> Riso 22 -> ADC pin;  4.7 kohm bleed on the AFE 3.3 V rail
```
**The centre comes from the REF3030E (D19, `budget/v1_scope_ref.py`).** The
earlier network centred N on a buffered Vmid (a TLV9062 half per channel, with
a loop of 4 x 1R, 4.7k, 1 uF, 2 x 6 x 10 uF and 100 nF, and a 3.3 V sense
filter to the Due's 3.3 V pin); all of that is removed. N is a three-resistor
node: the input through R1, ground through R2 and VREF through R3, so the
divider ratio is a = Rp/R1 with Rp = R1 || R2 || R3 and the offset is
VREF x Rp/R3 (the script's own arithmetic). Nominal, by the script: a 0.2328,
offset 1.6295 V, input resistance 1003.6 kohm (993.7 to 1013.5 kohm over 1 %
parts), the 10 V span at 71.6 % of full scale at AREF 3.25 V, REF3030E load
9.09 uA per channel at N = 0 *(derived; whether the REF3030E may sink the 1.82 uA
that a clamped N returns is a datasheet *(check)*)*. These are arithmetic on
nominal values, not a simulation; the circuit has not been re-run in
`sim/scope` *(check)*.
Both channels share **one 3PEAK TPH2502-SR dual** (U1, C118223; D13, D16;
`v2/parts.md`), on +3.3 V_A only through the 1 ohm and 10 uF branch, in
place of the two OPA354, as a **unity follower per channel** (pin 2 = CH2
out, pin 6 = CH1 out). The AWG's two op-amps are the second TPH2502 (U3).
- **R1 = 470k + 300k (770k, R10 + R11 and R12 + R13), R2 = 470k + 330k (800k,
  R18 + R1 and R19 + R2), R3 = 330k (R14, R16)**, no trimmer, all **1 % Basic**
  (C23178, C23024, C23137; D15). The script chose them from the 79 Basic 0603
  values (`v2/jlc-basic.csv`) against the span, centring and input-resistance
  limits: a 5-part network per channel. The earlier 760k / 330k / 760k set and
  its 0.990 Mohm are *(superseded)*.
- **C1 is 12 pF across R1 (C1, C2; C38523), C2 is one 30 pF C0G from N to
  GND (C9, C11; C1658), and each channel's (+) node has a 10 pF Cnp (C60,
  C61; C1634).** The divider is flat when R1 x C1 = (R2 || R3) x (C2 + Cnp):
  9.24 us against 9.35 us here, 1 % apart (derived, with Cnp counted as
  loading N behind Rnp as `design.py` does; the parts are 5 % C0G) *(the
  re-trim is not run in `sim/scope`, *(check)*)*. The old network's C2 of
  39.5 pF, zero gain step at 38.96 pF, is *(superseded)*. Cnp is the AN-1
  capacitor of the TPH2502 input (`whatif/tph2502/`): a pole with Rnp at
  23 MHz (derived: 1/(2 pi x 680 x 10 pF)).
- **No Vmid on the scope.** The two TLV9062 halves (U6), their loops and the
  two banks of 6 x 10 uF, and the sense filter, are removed (D19). The
  scope-to-scope crosstalk of 0.37 LSB, the loop's 0.25 ohm peak near 2.5 kHz and
  the centring of 9.4 / 23.1 mV were figures of that circuit *(superseded: the
  centre is now VREF through R3; centring is the 1 % resistor spread and
  the reference's tolerance, which the script's Monte Carlo (1 % resistors,
  VREF +-0.2 %, +-30 mV centring term) puts at 170 mV of low-side margin and
  47 mV of high-side margin against the 80 mV required)*. Crosstalk through the shared
  VREF node is not simulated *(check, VT-10)*.
- **Simulated figures of the OPA354 / 0.1 % design, all *(superseded, and
  every +/-1.25 V figure is for a range D18 removed: the
  op-amp, the resistors and C2 changed; see `whatif/v1-basic/values.md`
  sections 2-3 for the 1 % values on the old op-amp model, and
  `whatif/tph2502/` for the TPH2502)*:** SM-3 105.6 / 14.1 MHz at the worst
  corner (+/-5 / +/-1.25 V); SC-6 138 / 158 uV; AN-1 54 degrees; SC-2
  115 mV and SC-11 119 mV per side (SC-11 gain 1.119-1.127); SC-8 2.3 % on
  +/-5 V (Ron in the gain) against 3 %; SC-10 settles in 205 ns. The 5 ns
  edge overshoots 27 % on +/-5 V (the OPA354's 5 dB peak near 90 MHz). For
  the 1 % values on the old op-amp model `values.md` reads SC-2 93.2 mV,
  SC-11 91.3 mV and gain 1.051-1.120 (below the old 1.10 floor), SC-8
  5.44 / 7.07 %.
- Rnp 680 holds the clamp current of a 5 ns 30 V edge through C1 to
  6.2 mA (71 mA without it) *(that run had no Cnp; 10 pF now sits at the
  node, not re-run here)*.
- **A BAV99 (C2500, Basic, D5 and D6) at each ADC pin, after Riso** (it was a
  BAT54S; every clamp is now the Basic BAV99, D25 / `whatif/v1-jumper/`; the figures
  below are the BAT54S's *(superseded: check the silicon BAV99's higher forward drop
  against PR-2, `whatif/v1-jumper/design.md` section 1, VT-22)*): pin 1 to ground,
  pin 3 on the ADC pin, pin 2 on the AFE +3.3 V_A (not the Due's 3.3 V,
  which would take 5.4 uA of a +12 V fault instead of 2 uA). Unpowered
  with +/-12 V on both inputs the pin stays at -0.13..0.26 V (-0.48 V
  without it, against PR-2's -0.2 V), the 4.7 kohm bleed keeps the rail at
  0.13 V and 2 uA reaches the Due. Its 10 pF behind Riso leaves SM-3 at
  105.6 / 14.1 MHz and SC-10's settling at 205 ns *(superseded: OPA354
  figures, see above)*; its leakage bound moves the pin 5 uV. The SAM3X gives -0.3 V on input pins and no
  injection-current rating *(check, VT-5)*.
- DF-3 with matched sources: before calibration 32.1 dB (DC) and 20.1 dB
  (10 kHz) on +/-5 V, the figures SM-6's hardware differential mode is
  held to *(also moved by the REF3030E-centred network, not re-run)*; after the tee calibration 47.5 / 50.9 dB at the signed worst
  corner against 44 dB (the tee calibrates divider and stage together;
  the residual is the Due ADC's INL, from `whatif/tee`). **0.1 % figures,
  *(superseded)*: with 1 % parts and 100 ppm/K `whatif/v1-basic/values.md`
  section 3 reads 25.4 / 23.2 dB before calibration (DC, +/-5 / +/-1.25 V)
  and 43.6 / 42.4 dB after it at dT 10 K (46.3 / 46.9 dB at dT 5 K), on the
  old op-amp model.**
- PW-1: **nothing is drawn from the Due's 3.3 V pin now** *(superseded: it was
  4.3 uA for the two R3 legs plus 5 uA for the Vmid divider)*; each R3 loads VREF
  instead, 9.09 uA per channel at N = 0 (derived above).

## AWG output (AW-1..AW-8)

**One TPH2502 half as the gain stage, DAC0 straight into a divider, the offset
from the REF3030E** (D24-D27; `whatif/v1-awg-ref/design.md`, the version 2 design
with values re-solved for version 1's window; the numbers there are the record,
not here). Removed against the earlier AWG block: the DAC0 buffer, the AWG Vmid
follower U5 (a TLV9062) and its 330k + 4.7k + 4.7k / 330k divider, the series
Schottkys D1 / D2 / D4, the supply filters (22 || 22 ohm), the Rb / Rf resistor
chains and the unfitted BAV99 output-clamp footprints; 36 fitted lines become 15
placements plus the BNC J3.

```
DAC0 --Rbin R54 51k--+-------------------------- (+) U3 half B (pin 5) --+
          Cbin C63 10p across R54   R94 51k + R22 75k (= 126k) to GND     |
                                                  U3 pin 7 = out --+-- R51 || R88 (2 x 100R 1206 = 50 ohm) -- BNC J3
                                                    Rf R35 3.3k with Cf C7 10 pF across it -- inverting node (pin 6)
VREF --R93 100R--+-- node AWG_X -- Rg2 R33 4.99k -- inverting node         (C64 + C65 = 2 x 10 uF, X to GND)
U3 half A (pins 1-3): + input to GND, follower (the spare); V+ pin 8 on the +3.3 V_A branch east of the A1 / A0 lines and V- pin 4 on the -2.05 V rail, 100 nF each (C21, C22)
```
Transfer (`whatif/v1-awg-ref/design.md`): Vout = Gs x kin x Vdac - K x Vref, with
Gs = 1 + Rf/(Rg2 + R93) = 1.6475, kin = 126k / (51k + 126k) = 0.7119 and
K = Rf/(Rg2 + R93) = 0.6475, so the DC gain is **1.1730** and the zero is at
Vdac = 1.67 V; above the offset filter's 114 Hz corner (100 ohm x 14 uF) the
capacitor shorts the 100 ohm and the gain is 1 + Rf/Rg2 = 1.1825, a shelf of
+0.81 %. The offset comes from the reference instead of a Vmid, through R93 and
two 10 uF at the node AWG_X (about 7 uF each at 3 V bias *(check)*), which keeps the
AWG's current out of the reference's kilohertz output impedance (SC-9: 1.12 ADC
codes against a limit of 2 on the graph read, 2.01 on the flat 110 ohm bound
*(check)*; one 10 uF reads 2.22). The AWG draws at most 0.60 mA from VREF, so the
reference's total load is 2.77 mA of 10 mA (the ladder, the scope centres and
the sense tie included, as that note counts them).
- **One half, the spare tied off** (V2-2): half B (pins 5-7, placed so that its pins
  face the DAC0 pin and its output the BNC) carries the stage (27.7 mA
  at a short, inside one half's 100 mA minimum short-circuit current); half A has
  its + input on GND and its output on its - input, a follower of ground, which
  costs no part and no net across the package. AN-1 reads 52.7 degrees with one
  half against 62.4 with two, and **minus 2.1 degrees without Cf**, so Cf C7 is
  essential; AW-3 reads 96.2 MHz and 12.5 MHz at the worst component corner; AW-6
  noise 216 uV against 300 (all from that note, simulated with its models *(check:
  nothing is measured on a board)*).
- **The divider and Cbin.** Rbin 51k with Rbpl 51k + 75k from DAC0 draws 15.8 uA at
  the DAC's top code, and an unpowered AFE draws 0.056 mA from the pin against
  VT-5's 3.8 mA bound (the old 680 ohm input: 4.1 mA). Cbin 10 pF across Rbin keeps
  the + input fast: a 12 pF stray at the node fails AW-3's 8 MHz.
- **Values.** Rf 3.3k, Rg2 4.99k, Rbin 51k, Rbpl 51k + 75k are the search's best
  under the three asks together (offset margin, gain margin, AW-1 position-aware
  92 %), which have no joint solution: offset margin +5.6 mV, AW-1 91.2 %, DC gain
  margin +0.011 against the 0.02 asked. **Three rows of that note's 115 fail and
  are open decisions** *(check: `whatif/v1-awg-ref/design.md` "Open decisions")*.
- Series 50 ohm after the stage (AW-4): **two 100 ohm 1 % 1206 in parallel** (C17901,
  R51 and R88), 50.0 ohm +-1 %; 20 mW each at the 28 mA short against a 250 mW
  rating. Short to ground (PW-3): 28.3 mA AC peak against 30 mA *(that note)*.
- **Everything simulated for the earlier AWG block is *(superseded: see
  `whatif/v1-awg-ref/design.md` for the new block, and `whatif/v1-basic/values.md`
  section 5 and `whatif/tph2502/results/` for the old one)*:** the buffered DAC0 with its
  680 ohm and Cbin, the 953 / 249 and then 1k / 270 || 270 / 22 / 22 gain
  chains (Rb = Rf = 1179 ohm, slope 1.176), the AWG's own Vmid (a TLV9062 follower with
  no output capacitor and its 3.5 us tap), the two Vmid conditions, the Schottky
  supply drops, the rail figures behind the 22 || 22 filters and the 5.492 V bare-rail
  figure, and the PAM-step and AW-6 figures of the OPA365 and 0.1 % parts.
  What stays from the supplies: the rails are the LM27762's (Power section), now
  straight on the op-amp pins with 100 nF each (the 22 || 22 ohm and the Schottkys
  are gone), the TPH2502's 7.0 V absolute maximum against the bare 5.492 V at the
  datasheet maxima *(check against the 7.5 V in the datasheet text, `v2/parts.md`)*.
- **Two 0R bridges (R95 / R96, C21189) carry the AWG's +3.3 V branch** over the A1
  and A0 lines, the ADC traces from the channels to the Due's pins (D24: a bridge, not
  a hop to the bottom layer, over an ADC trace); the branch east of them is
  +3V3A_E, with the AWG op-amp's V+ pin and C21. Two zero-ohm parts add 2 x 2 joints
  and a few milliohms *(check)*.
- **No clamp on the output.** The six-diode clamp footprints (D9-D11) are not
  carried; PR-4's level is the op-amp's own short-circuit rating (TPH2502: infinite
  duration, 100 mA minimum, `v2/parts.md` section 1.3), with the 100R pair taking the
  fault current (0.143 W each at +-5 V for 10 s against 0.25 W, *(check the part's
  derating)*) *(the older 65 mA OPA365 derivation and the 57.1 mA simulation are
  superseded; this level is re-derived in the new note and not re-read here
  *(check)*)*.
- **Back-feed into the divider (AN-3, VT-5).** The AFE is powered from the Due's
  5V pin with the LM27762 enabled from its input, so "AFE unpowered while DAC0
  drives" exists only in a start-up window or a fault. With the AFE unpowered and DAC0
  at 3.3 V the divider and the op-amp's ESD diodes draw 0.056 mA from the pin (derived
  in the note, with the diodes at Vf 0.5 V *(check)*), so the 3.8 mA of the old 680 ohm
  bound is no longer the figure; **VT-5 measures it**. The SAM3X datasheet gives no
  DAC0 current limit *(check)*.
- The AWG-sense divider and its clamps (the BNC node, R7, R8) belong to the
  Calibration section.

## Power (PW-1..PW-7)

5 V feed from the Due's 5V pin, **take only, never drive** (it is the Due's
buck output and the file does not isolate it from USB VBUS), through the
1 ohm sense resistor with a test point either side (D7) and the bulk
capacitance, into the LM27762 (+3.3 V_A, about -2.05 V). **No ferrite bead**
(R2, approved 2026-11-11): the sense resistor and the bulk are the feed's
filter, and the scope dual's branch has a 1 ohm ahead of its 10 uF; the
sense resistor's DC drop still reads the current between its test points.
**The AWG's 22 || 22 ohm filters and series Schottkys are gone** (D24-D27): the
op-amp pins take the rails directly, each with 100 nF (C21, C22), so the
start-up and bare-rail figures below that include them are *(superseded: see
`whatif/v1-awg-ref/design.md`)*.
Nothing is drawn from the Due's 3.3 V pin (the microamp Vmid sense went with
the scope Vmid; PW-1, PW-4). Figures below are `sim/powercal` (datasheet maxima
at once); those that describe the removed scope Vmid network are marked.

- **Bulk: 2 x 10 uF X5R 0805 25 V, C15850** (the only Basic 10 uF), and
  **two 10 uF on each LM27762 output** (+3.3 V_A and the negative rail,
  at OUT+ / OUT- ahead of the AWG's 22 || 22 ohm filters; the second one
  on each approved 2026-11-11). Every 10 uF is modelled from Samsung's
  characterisation of the part (`models/cl21a106kaynnne`): ESR 4.0 mohm
  at 2 MHz, 12-15 mohm at 4-10 MHz, ESL 0.37 nH, self-resonance 2.1 MHz;
  capacitance -50 / -30 / -14 / -9 % at 5 / 3.3 / 2.07 / 1.65 V of DC
  bias, with -10 % tolerance on top. The ESR's change with bias is not
  given *(check)*. The LM27762's datasheet asks for at least 2.2 uF of
  ceramic on each LDO output for stability (Sec 7.2.2.4.4) and states no
  maximum, no ESR window and nothing about large ceramic outputs; it
  recommends low-ESR ceramics (<= 15 mohm typical). OUT+ and OUT- now
  carry about 15-20 uF effective at about 4 mohm: above the minimum, with
  no datasheet bound to test against, and the behavioural model has no
  LDO loop, so their stability is *(check, VT-8)*. Start-up with the added
  capacitance is unchanged in P1 / P2. **The charge-pump output (CPOUT,
  4.7 uF recommended, 10 uF at higher current, at least 2 uF effective)
  is a separate pin and is not modelled separately in `sim/powercal`**
  (the behavioural part lumps pump and negative LDO); a C15850 there sits
  at about -5 V and keeps about 4.5 uF after derating and tolerance.
- **One bleed on +3.3 V_A: 2.2 kohm 1 % 0603 (R65, C4190), was 4.7 kohm**, which
  `whatif/v1-jumper/design.md` section 8 shows fails PR-3 on kvm_02's worst case (+5 V on
  the AWG BNC, unpowered: 0.746 V on the rail against 0.5 V; 0.496 V with the ladder in
  place); 2.2k reads 0.382 V (118 mV margin) there and 0.269 V with the ladder.
  **PW-1 cost: 3.4177 V / (2.2k x 0.99) = 1.57 mA permanent, +0.84 mA over the 4.7k**
  (that note; 1.6 % of the 100 mA budget at the 5 V pin). The scope's PR-3 bleed and
  the AWG back-feed bleed are this one part. The 0.71 mA and the figures below were the
  4.7k's *(superseded for the value; the +/-12 V scope case is 27 uA into the rail and
  0.060 V with 2.2k, in that note)*. With
  the Due unpowered and +/-12 V on both scope inputs at once (PR-3) it
  holds +3.3 V_A at 0.106 V (limit 0.5 V); 1.8 uA reached the Due's 3.3 V
  pin through the R3s and the sense filter and nothing its 5V pin (limit
  100 uA); the ADC pins sit at -0.149 to +0.156 V (PR-2: -0.2 to 3.45 V,
  51 mV of margin on the Due-pin clamp model) (`sim/powercal` P7)
  *(superseded: the R3s now go to VREF, not to the Due's 3.3 V pin, and the
  sense filter is gone; the path of a +/-12 V fault into the unpowered
  REF3030E's output is not simulated *(check, PR-3)*)*.
- **Current (P3):** 48.3 mA normal, 61.3 mA with the AWG shorted (OPA354
  scope; 45.7 / 58.7 mA with OPA365), against PW-1's 100 mA *(superseded:
  the amplifiers changed. The figure now is two TPH2502 duals (scope on
  +3.3 V only, AWG on both rails, one half unused), no TLV9062 at all (the scope
  Vmid pair and the AWG's Vmid follower are removed), the 2.08 mA ladder (270 ohm
  x 8, `values.md` section 7, on the REF3030E), the ADS1115, the AWG's 0.60 mA
  offset current from VREF and the 1.57 mA bleed; there is no TMUX1119 any more. `v2/parts.md` section 1.5 derives 93 mA for three TPH2502 duals
  with the scope on +3.3 V only and 83 mA for an OPA2365 scope beside a
  TPH2502 AWG; this board's mix is not summed there and has not been
  re-run in `sim/powercal` *(check against PW-1's 100 mA)*)*. The reference-buffer
  OPA365, the DAC8551, the MCP3564, the ADS124S08 and the four injection
  switches are gone.
- **Fault totals** (PR-4): +/-5 V forced on the AWG output, powered, the
  Due and AFE draw at most 411.8 mA as simulated (OPA354 scope; increment
  73.5 mA), 403.3 mA at the op-amp's 65 mA rating, against PW-1's 450 mA;
  the 400 mA target is for normal operation *(superseded: OPA354 scope and
  OPA365 AWG; the TPH2502's short current is 100 mA minimum, sink and
  source, `v2/parts.md` section 1.3, so the increment is re-derived
  there)*.
- **Rails.** +3.3 V_A: **R1 = 75k + 100k = 175k, R2 = 100k**, 1 % Basic
  (C23242, C25803), **3.300 V nominal, 3.2095-3.3926 V** at the LM27762's
  limits with the 1 % feedback resistors (`values.md` section 4; 3.288 V and
  3.235-3.342 V with 174k / 100k at 0.1 %). **Negative rail:
  R3 = 75k (one part), R4 = 330k || 330k || 330k**, **-2.052 V nominal,
  -2.005 to -2.099 V** (was -2.0712 V from 330k || 100k, -2.039 to
  -2.103 V), 45 kohm at FB- on R4's side, whose input current the datasheet
  does not give *(check)*. Bare rails at the datasheet maxima 5.492 V,
  8 mV under the OPA365's 5.5 V (the old op-amp; the TPH2502's absolute
  maximum is 7.0 V) and "thin" in `values.md`'s word; the start-up reaches
  4.841 V at the AWG op-amp pins behind the Schottkys (P1-a), 5.487 V on
  the bare rails with the old dividers *(not re-run for the bare-rail
  figure)*, with 300 mV of overshoot tolerated per rail (P1-b; the
  datasheet gives no overshoot, VT-8 *(check)*). The REF3030E's headroom
  at the lowest +3.3 V_A is 210 mV against its 200 mV dropout maximum
  (`values.md` section 7, 235 mV with 0.1 % parts): 10 mV over.
- **PW-6:** at a 4.4 V 5V pin the +3.3 V LDO keeps 0.97 V and the charge
  pump 2.14 V of headroom (P6-a; PW-6's minimum is now 4.50 V).
- **Ripple (no bead)** *(the AWG-output figure below went through the removed AWG Vmid divider and the 22 || 22 filters: superseded)*: 4.6 uV rms of supply residue at the scope pin
  (P4-a, 20 uV allocation), 10.9 uV at the AWG output (P4-b, against a 20 uV
  internal share of AW-6, accepted 2026-11-11; 10.8 / 16.8 uV on the old
  10 / 20 mohm assumptions, 18.9 uV with one 10 uF per rail), its largest
  line 11.7 uV pk at 2 MHz = -98.7 dBc of +/-1 V,
  0.10 mV at the amplifier pins (PW-2, 20 mV), 0.43 uV at the Due's 5V pin
  at 2 MHz (PW-4). The pulse-skipping case of PW-4 still needs about 27 dB
  of the Due regulator's rejection, which nothing in the repository gives
  (P5-b, open).
- **PW-7 start-up:** the scope's Vmid divider (2 x 330k, 10 uF at its tap:
  13.7 s to 0.5 LSB) is removed *(superseded: the scope centre is now VREF, the
  REF3030E's output, which settles in 2 ms to 0.1 % with the datasheet's
  CL = 1 uF, SBVS032K 6.5)*. Start-up of VREF with C26 and C27, the scope's R3 loads
  and the AWG offset filter (R93, 100 ohm into 2 x 10 uF, 1.4 ms time constant
  in the note's reading) is not simulated *(check)*.
- **The scope Vmid is gone (D19).** Its TLV9062 halves, the loop (4 x 1R
  isolation, 4.7k DC feedback, 1 uF HF feedback, 6 x 10 uF + 100 nF at the node),
  the impedance peak of 0.251 ohm, the 68 degrees of phase margin and the other
  `sim/powercal` P8 figures belong to that circuit and are history *(superseded: see
  `whatif/v1-basic/values.md`, `whatif/tph2502/`, `budget/v1_scope_ref.py`)*.
- **The AWG's Vmid is gone too (D24-D27).** The 330k + 4.7k + 4.7k / 330k divider
  and the TLV9062 follower U5 are removed: the AWG's offset is the REF3030E through
  the filter R93 + 2 x 10 uF (AWG section), so the +3.3 V_A ripple no longer
  reaches the AWG output through a Vmid divider *(superseded: the 10.9 uV of
  `sim/powercal` P4-b was that path; the new term is the reference's noise
  through the filter, 12.1 uV in `whatif/v1-awg-ref/design.md`, AW-6 total 216.0 uV
  against 300; the supply-ripple term at the op-amp pins, now on 100 nF alone, is
  not re-run *(check)*)*. The board has no Vmid at all.

## Calibration (Phase 3)

- 3.0 V reference (REF3030E, C54120492; datasheet only, no usable model, so
  behavioural with its drift/noise numbers), **straight to the ladder with
  no buffer (owner, 2026-11-11)**. Its output node, VREF, is the ladder's top
  tap, the ADS1115's AIN0 (a check; the ratio is built from the pair
  below), **the two scope R3 resistors (R14, R16: the scope centre), the AWG's
  offset filter (R93) and the sense circuit's Rd (R90)** and the Due's A7; the 0R to the AREF pin (R81, PA-7) is unfitted. **Load at the
  output: 100 nF (C26) and 1 uF (C27); 100 nF and 1 uF at VIN.** The REF30E asks
  for 0.1-22 uF at 10-500 mohm ESR (C4-d); 1.1 uF nominal meets the capacitance
  with 0.99 uF at -10 % *(check: X5R DC-bias loss at 3 V, and a ceramic's ESR
  against the 10 mohm floor)*. Not simulated: the reference model is
  encrypted. The REF30
  (non-E) states no range; the BOM's REF3030EAIDBZR is the E grade, which
  does. Ringing is not simulated *(check, VT)*.
- Precision ADC (D15, `v2/parts.md` section 2, 2026-11-12): **ADS1115IDGSR**
  (C37593, VSSOP-10 drawn on the 3 x 3 mm, 0.5 mm pitch TSSOP-10
  footprint), 16-bit, I2C at 0x48 (ADDR to GND) on SDA1/SCL1 (the SAM3X's TWI0
  pins) with R69 and R82 (4.7k to +3.3 V_A), VDD from +3.3 V_A with 100 nF (C25),
  ALERT/RDY unused. Inputs: **AIN0 VREF (a check), AIN1 TAP3, AIN2 the sense tap
  T0 (through Rs 3.9k), AIN3 the bottom end B (through Rm 13k)**; the pair AIN2-AIN3
  is read differentially (the ADS1115's differential pairs are AIN0-1, AIN0-3,
  AIN1-3 and AIN2-3 only) and AIN3 alone single-ended. It reads **one** of the
  six ladder taps (TAP3), not every one (the ADS124S08 read them all), and the other
  five are the Due's. Its figures from `v2/parts.md` section 2: LSB 125 uV at
  the +/-4.096 V range, INL 1 LSB max at 8 SPS and +/-2.048 V, inputs
  GND to VDD, absolute maximum GND - 0.3 V to VDD + 0.3 V with 10 mA on any
  pin; INL at +/-4.096 V and the input-to-input gain match are not given
  *(check)*. Its current and the INL-referred fit share of the old
  ADS124S08 numbers below are *(superseded: not re-run for the ADS1115)*.
- **The ratio measurement by jumper (PA-3 / PA-4, D25), replacing the TMUX1119
  ratio switch** (`whatif/v1-jumper/design.md`, kvm_02's structure S3; the procedure
  is `whatif/calibration-steps.md`, which at the time of writing still describes the
  switch and needs the jumper steps *(check)*). The AWG drives both scope inputs through
  the BNC tee, as before, and the sense circuit hangs on the AWG BNC node: **R7 22k
  (C31850) to the tap T0, R8 15k (C22809) from T0 to the bottom end B (k = R8 /
  (R7 + R8) = 0.405), and Rd R90 1k from B to VREF** (the default tie, wire off). T0
  and B each reach the ADS1115 through a series resistor (Rs 3.9k, Rm 13k = Rt || Rb +
  Rs, so the two source impedances match) and a **BAV99 clamp (D8 on AIN2, D7 on
  AIN3)**: a voltage forced on the AWG's BNC (PR-4) would otherwise take AIN2 below
  ground and, per SBAS444E 7.3.1, an overdriven input disturbs the others. **The user
  fits a shunt across pins 2-3 of J11, `TAP4 | B | TAP3` (a hand-fitted 1x3 header),
  together with the tee**: that joins B to TAP3, which AIN1 reads. The host takes the pair
  AIN2-AIN3 (T0 - B) in both states and detects the wire from AIN1 against AIN3 (the
  smallest gap 383 mV against 62 mV needed); the reference's scale is rebuilt on B
  with the wire off (REF = B - Rd (T - B)/Rb), so the ratio is measured at every
  calibration. With the wire off T0 reads 1.147 .. 2.312 V and B 2.88 .. 2.96 V; with
  it on (B-TAP3) T0 0.465 .. 1.595 V and B 1.72 .. 1.76 V; the neighbouring position
  TAP4 stays in range (B-TAP4: T0 0.703 .. 1.835 V), so a wrong placement is
  detected, not a hazard (`whatif/v1-jumper/design.md` section 1: simulated, window
  +-1.35 V, 1 % parts *(check: not measured)*). **Ratio, 99.9th percentile: 0.088 % /
  1.84 mV if the common-mode impedance tracks, 0.307 % / 2.60 mV if it is independent,
  against an allotment of 0.05 % / 3 mV: the gain term FAILS in both readings, and the
  whole SC-7 stack passes on tracking (sum 0.428 %, RSS 0.234 %)** *(that note,
  sections 0 and 4; the decision is the spec lead's, VT)*. The 5 uA the old switch
  pushed through the divider and the switch's Ron are gone with it. The T-switches,
  the 249 ohm injection branch, the TMUX1119 and the single-ended sense of the earlier
  designs are retired.
- **The tee's fit share was 0.1 % on both ranges (owner, 2026-11-11)** with the
  ADC's INL referred to the AWG (whatif/tee's re-run: 0.074 %, 0.091 % at the bound,
  on +/-5 V, 1024 points, at k = 1/2; that range pair is reduced to one, D18)
  *(superseded: those were the ADS124S08's 10 ppm INL and a single-ended divider
  at k = 1/2; the ADS1115's 1 LSB at 16 bits is about 15 ppm of its range, the
  divider is now the differential S3 pair at k = 0.405, and the stack is
  `whatif/v1-jumper/design.md` section 4)*.
- **Input protection (PR-3 / PR-4, C1-p, C1-q, C1-r) is *(superseded)*:** the
  old figures (the single-ended tap at -0.048 V, 36 uA at +/-1.8 V, the TMUX1119's D
  clamped within 0.20 V of a rail) were for the 100k + 100k divider with the switch.
  Now both ADS1115 inputs sit behind Rs / Rm and a BAV99: unpowered, +5 V on the BNC
  puts the rail at 0.411 V and 87 uA (the optimistic assumptions) and, on kvm_02's worst
  case, **0.382 V and 173 uA with R65 = 2.2k** (0.746 V with the old 4.7k:
  a fail; Power section), the rail-voltage reading of PR-3 being the one applied
  *(check: simulated, and the strict 100 uA-into-the-rail reading is met by no bleed)*.
  The -0.3 V row: the silicon BAV99 holds the tap pin 0.13 to 0.28 V past GND - 0.3 V
  at 9 to 117 uA, 85x to 1000x inside the 10 mA row; SBAS444E 7.3.1 prefers Schottky
  diodes, and **VT-22 decides** *(check: no BAV99 datasheet read)*.
- **Ladder (PA-9, D11, D15): eight 270 ohm 1 % resistors** (C22966, Basic),
  three in parallel at the bottom (R43-R45) and five in series (R46-R50),
  1440 ohm: 2.08 mA nominal, 2.12 mA with every element -1 %; six taps on
  A2-A7 at 0.1875 / 0.750 / 1.3125 / 1.875 / 2.4375 / 3.000 V, the top tap
  being the REF3030E output itself (PA-8). Worst tap source 354 ohm (tap 3)
  against SC-10's 5 kohm; 358 ohm with every element +1 %
  (`values.md` section 7). **The REF3030E carries it (C1-c):** 2.12 mA
  inside its 0-10 mA load-regulation range, **210 mV of headroom at the
  lowest +3.3 V_A against its 200 mV dropout maximum**, thin and set by the
  1 % feedback resistors (235 mV with 0.1 % parts), self-heating 0.18 K =
  2.7 ppm. That is ratiometric for the ADS1115 and a static PA-6 term for
  the Due's gain fit (C4-b: +/-3.74 mV, +/-0.73 mV with a meter, *(0.1 %
  ladder; superseded)*). Run on 1 %, `values.md` section 7: fit error
  0.098 / 0.101 LSB with the taps re-read (C2-a/b), 0.181 LSB with the Due's
  pin leakage across the worst tap (C2-c), and **0.826 LSB, a fail, with a
  stale reading (C2-d) unless the taps are re-read at every calibration**,
  which PA-9 already requires *(check: those fits assumed the ADC reads
  every tap; the ADS1115 reads TAP3 only)*.
- **Sequencing rule (B): the Due does not read the ladder while the
  ADS1115 converts.** A Due sample on the top tap lands on the reference
  node: 18 pC into the old 2 x 100 nF was 0.12 LSB before the REF3030E
  recovered it, and its output impedance at MHz is not modelled (C1-d).
  Into the 100 nF + 1 uF now fitted it is a tenth of the old two-100 nF
  figure (derived: 18 pC / 1.1 uF = 16 uV, 0.02 LSB of 0.73 mV; the scope R3
  legs add a few microamps of load, not a charge step) *(check)*. Calibration already
  reads them one after the other (C4-c).
- **The top tap is the reference node itself**, so no offset sits between
  it and VREF. Element rating not read *(check)*. No switch between tap
  and pin.

## Layout and assembly facts (JLCPCB, `jlcpcb.md`)

Two layers, one side populated, Economic PCBA, 0603 minimum, extended-part
count kept small (a loading fee per distinct extended part), BNCs and
headers hand-soldered (not in the BOM/CPL).
