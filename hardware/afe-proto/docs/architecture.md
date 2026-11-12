# AFE architecture, round 1 (Step 1 output, draft for G1)

Requirements are in `docs/afe.md`; this file says how they are met and
which choices the simulations (`docs/afe-plan.md`, step 2) must settle.
Budgets that need no datasheet are in `budget/afe_budget.py`
(`python3 -I hardware/afe-proto/budget/afe_budget.py`). Part numbers are
candidates until a simulation passes; stock and price are in `jlcpcb.md`.

## Facts the design is built on

- **The Due's AREF header pin is not the 3.3 V rail on a stock Due.** BR1
  is open and JR1 is fitted, so AREF goes nowhere (`hardware/reference/
  arduino-due/v03/README.md`). The AFE therefore senses the Due's **3.3 V
  pin** (`POWER0.4`, the same net as ADVREF through JR1 and L3) through a
  high-impedance divider, at microamps (PW-1). The reference still routes
  to the AREF pin through the unfitted 0 ohm (PA-7). `afe.md` section 4.1
  and PW-1 say AREF is the sense point; that text needs correcting.
- Hardware SPI is **not** on any edge header; the precision ADC and DAC use
  a bit-banged bus on D33-D37 (`docs/due-header-table.md`).
- Range-select and calibration-switch pins D38-D41 get external
  pull-downs, so low is the safe state (+/-5 V, calibration off).
- Precision resistors are 0.1 % at 25 ppm/K, the grade actually stocked
  (`docs/jlcpcb-parts.md`): SC-8 is 1 % (2026-11-11) and passes with it, and
  DF-3 after calibration is closed by one build-time trimmer per channel,
  not by tighter parts (CA-1 and DF-3 allow it, 2026-11-11).

## Scope channel (x2, separate packages, SC-9) - 1 Mohm compensated, 2026-11-11

SM-5 is dropped and the input is 1 Mohm again (owner, 2026-11-11): the
first round's compensated divider with every change approved since.
Calibration is a BNC tee from the AWG into both inputs, so nothing is
switched onto N. Simulated values and margins are in `sim/scope/report.md`
(variant `hz`, the default) and `sim/diff/report.md`; numbers there, not
here, are the record. The ~22 kohm route (c) designs stay reproducible
as `--variant lowz` / `lowz2` and are not developed further.

```
BNC - IN --R1 760k--+--N--Rnp 680-- OPA354 (+)
                    |   (C1 12 pF across R1; C2 39.5 pF from N to Vmid)
                    +--R2 330k-- Vmid (this channel's TLV9062 half)
                    +--R3 760k (= R1) -- shared 249R + 10 uF sense node -- Due 3.3 V pin
op-amp: RF 953 out->(-), RG 249 (-)->Vmid; range switch SHUNTS RF
        (closed = +/-5 V, G = 1 + Ron/RG; open = +/-1.25 V, G = 4.83)
out -> Riso 22 -> ADC pin;  4.7 kohm bleed on the AFE 3.3 V rail
```
- R1 = R3 = 330k + 330k + 100k (760k), R2 330k fixed (no trimmer), all
  0.1 %. R3 = R1 centres N on Vmid; alpha 0.2324, Thevenin 177 kohm,
  input 0.990 Mohm.
- **C2 = 20 || 12 || (12 s 20) = 39.5 pF**, Basic types only (the
  Extended 39 pF leaves): the DC-to-100 kHz gain step is zero at
  38.96 pF and moves 1.9 % per pF; 39.5 pF leaves -1.0 % (SC-5's host
  frequency calibration removes it; information now SM-5 is gone).
  20 + 12 + (20 s 20 s 20) = 38.7 pF gives +0.6 % with five parts.
- Vmid: one buffer per channel, both halves of one TLV9062 (powercal's
  loop, 0.25 ohm peak near 2.5 kHz): scope-to-scope crosstalk 0.37 LSB.
- SM-3 105.6 / 14.1 MHz at the worst corner (+/-5 / +/-1.25 V); SC-6
  138 / 158 uV; AN-1 54 degrees; SC-2 115 mV and SC-11 119 mV per side
  (SC-11 gain 1.119-1.127); SC-8 2.3 % on +/-5 V (Ron in the gain)
  against 3 %; SC-10 settles in 205 ns. The 5 ns edge overshoots 27 %
  on +/-5 V (the OPA354's 5 dB peak near 90 MHz).
- Rnp 680 holds the clamp current of a 5 ns 30 V edge through C1 to
  6.2 mA (71 mA without it).
- **A BAT54S (C7420333) at each ADC pin, after Riso**: pin 1 to ground,
  pin 3 on the ADC pin, pin 2 on the AFE +3.3 V_A (not the Due's 3.3 V,
  which would take 5.4 uA of a +12 V fault instead of 2 uA). Unpowered
  with +/-12 V on both inputs the pin stays at -0.13..0.26 V (-0.48 V
  without it, against PR-2's -0.2 V), the 4.7 kohm bleed keeps the rail at
  0.13 V and 2 uA reaches the Due. Its 10 pF behind Riso leaves SM-3 at
  105.6 / 14.1 MHz and SC-10's settling at 205 ns; its leakage bound
  moves the pin 5 uV. The SAM3X gives -0.3 V on input pins and no
  injection-current rating *(check, VT-5)*.
- DF-3 with matched sources: before calibration 32.1 dB (DC) and 20.1 dB
  (10 kHz) on +/-5 V, the figures SM-6's hardware differential mode is
  held to; after the tee calibration 47.5 / 50.9 dB at the signed worst
  corner against 44 dB (the tee calibrates divider and stage together;
  the residual is the Due ADC's INL, from `whatif/tee`).
- PW-1: the Due's 3.3 V pin supplies 4.3 uA for the two R3 legs plus
  5 uA for the Vmid divider.

## AWG output (AW-1..AW-8)

**Buffered DAC0, a low-impedance attenuator, and the AWG's own fast Vmid**
(owner, 2026-11-11; `sim/awg/report.md`, the design; `sim/loop` step `buf`
shows SM-5). DAC0 drives an OPA365 follower, which drives an attenuator
low enough in impedance to need no compensation capacitors, and the gain
stage's Rg returns to a Vmid of the AWG's own:

```
DAC0 --680--+-- OPA365 follower --+--Ra 953--+-- V+ --(OPA365, rails +3.3 / -2.07 V)-- out --49.9 ohm 0.1 %-- BNC
   330k to GND   (+3.3 V_A via its      |    Rb = 953 + 249||249 + 22 to GND
                  own BAT54S, 100 nF)   |    Rf = 953 + 249||249 + 22 with Cf 12 pF, out to V-; Rg 953, V- to AWG Vmid
BNC --100k + 100k--+--100k-- AWG Vmid or 3.0 V (switched; sim/powercal's)     the ADS124S08 sense divider, 0.1 %, k = 1/3
                   +-- ADS124S08 input
AWG Vmid: 330k / 330k from +3.3 V_A, 12 pF at the tap -> OPA365 follower (own BAT54S, 100 nF), NO output capacitor
out = (Rb/Ra) x (Vbuf - Vmid) = 1.153 x (Vbuf - Vmid);  Vbuf = Vdac x 330k / 330.68k
```
Rf/Rg = Rb/Ra puts the zero at Vmid by construction; the slope DAC0 to
output is 1.1513, so +/-1 V uses 81-82 % of the DAC window by width and
**88.8 % position-aware against AW-1's 92 %, the binding as-built check**
(the Vmid follows +3.3 V_A, not AREF; the pre-calibration offset, up to
90 mV, is information, calibrated by the ADS124S08 reading the output).
Every part is a type already in the BOM (953 and 249 0.1 %, 22 and
680 1 % *(check: C23345's code reads 5 %)*, 330k 0.1 %, 12 pF C0G),
and 13.7k, 15.8k and 20 pF leave it. AW-3 15.1 MHz into high-Z and
10.0 MHz into 50 ohm; AW-6 89.9 uV with supply noise and ripple (the
LM27762 ripple 11.2 uV of it, calibrated as sim/powercal P4-b and agreeing
with its 10.93 uV to 3 %, on two C15850 10 uF per rail modelled from
Samsung's data: ESR, ESL, DC bias and tolerance); AN-1
69.6 deg (the gain stage). OPA354 and OPA356 fail AW-6 in the AWG
position, so **OPA365** throughout. PAM step at 1.6 Msym/s (information;
AW-3 sets no settling limit): the AFE adds 0.00 codes at the symbol centre
on a one-level step and 3.8-4.7 codes on a full-scale 1.5 V step (DAC0
impedance 0-1 kohm), against 17.5-42.8 codes from DAC0 alone into the
ADC's input.
- **The DAC0 buffer.** 680 ohm in series at its input and 330k from its
  input to ground: DAC0 sources 8.5 uA at the window ends (AW-5), and an
  undriven DAC0 commands -1.15 x Vmid, -1.52 to -1.72 V (AW-8 2.1 V). The
  330k returns to ground, not Vmid, so that an unpowered Vmid buffer
  dragged negative through Rg cannot pull the undriven DAC0 pin below
  -0.2 V (it reached -0.49 V that way, PR-2).
- **No injection branch** (2026-11-11: the PA-3 injection is replaced by
  a BNC-tee calibration). The buffer drives the attenuator and its pin
  trace only: **59.8 deg** of phase margin with a 5-10 pF trace, 55.2 deg
  at 15 pF (target 50), and 45 deg holds to 30 pF at the buffer pin (loop
  break, worst over DAC level and rail). sim/loop's Middlebrook injection
  could not see a capacitive load at all (it read 77 deg at 1 nF).
- **The precision ADC's sense divider** (k = 1/3: 100k + 100k from the BNC
  to the tap, 100k from the tap to the far end, 0.1 %, the far end
  switched between Vmid and 3.0 V; the ADS124S08 and its input protection
  are the Calibration section's) loads the BNC with 300 kohm, 0.017 % of
  amplitude into 50 ohm. The tap moves by 1/3 of the BNC swing. It sees
  +0.54..+1.62 V (far end at Vmid) or +1.43..+2.50 V (at 3.0 V) at AW-8's
  excursions, and -0.58..+2.76 V or +0.33..+3.67 V with the output forced
  to +/-5 V powered (PR-4); unpowered -2.13..+3.67 V or -1.67..+1.67 V.
  The divider limits none of these (`sim/awg/report.md` also gives the
  k = 2/3 arrangement for comparison).
- **The AWG's own Vmid, and its two conditions.** The scope's Vmid tap
  (2 x 330k, 10 uF, tau 1.65 s) starts in seconds, while DAC0 sits near
  3.3 V at reset: the output then runs to 2.6 V (AW-8 2.1 V), with this
  stage and with the unbuffered one. A separate Vmid for the AWG is
  allowed because the ADS124S08 calibrates the AWG's offset.
  **Condition 1: no capacitor on the AWG Vmid buffer's output.** A 10 uF
  there leaves the OPA365 follower **9.8 deg** of phase margin (77.6 deg
  bare), and it cannot be charged in time (65 mA into 10 uF is 250 us).
  **Condition 2: the Vmid tap's time constant under about 3.5 us**, so
  Vmid keeps up with rails that rise in 10 us; 330k / 330k with 12 pF is
  2 us for the part alone and about 3.0 us with the op-amp's ~6 pF input
  (OPA365 macromodel, `sim/loop` vmchk), so board strays at the tap must
  stay under about 3 pF *(check at layout)*. With
  both, AW-8 holds at **1.745 V** over 48 start-up runs and **1.720 V** at
  power-up (soft-start 20 us and 2 ms, DAC0 on its reset trace); a 100 nF
  tap fails both (2.60 V). The divider draws 5 uA from +3.3 V_A.
- **The rails.** The output sits on the LM27762's +3.3 V and about
  -2.07 V (the Power section owns the divider), behind 22 || 22 ohm and a
  Schottky in each op-amp supply pin. At the LM27762's datasheet maxima
  the bare rails are 5.445 V across, 0.055 V under the OPA365's 5.5 V;
  with the Schottkys the op-amp pins reach 4.783 V in every start-up order.
  AW-1 into 50 ohm reaches -0.5 V at the datasheet's weak rail corner
  (-2.039 V; the row's edge is -1.87 V). **Into 50 ohm AW-1 is judged at
  the LM27762's 34 uV/mA load regulation, 0.31 mV against one code**: the
  AWG Vmid follows +3.3 V_A, so the rail's sag under the 20 mA load is a
  linearity term, and on the model's 0.2 ohm rails it reads 0.76 mV. The
  datasheet figure is a typical for the - LDO; **VT-8 measures the + rail's
  load regulation into 50 ohm**.
- **The Schottky is BAT54S C7420333** (hongjiacheng; a series pair in
  SOT-23, pin 3 common), modelled from its datasheet in
  `models-open/bat54s-c7420333/` (own, CC BY-SA 4.0): typical 278 / 349 mV
  at 1 / 10 mA, maximum 320 / 400 / 500 mV at 1 / 10 / 30 mA, 2 uA
  leakage at 25 V. The swing rows take the maximum drop, everything else
  the typical; one die per supply pin, and one each for the DAC0 and
  Vmid buffers.
- Series 50 ohm after the stage (AW-4): **one** 49.9 ohm 0.1 % 1206
  (Yageo RT1206BRB0749R9L, C869759, 10 ppm/K; `jlcpcb-parts.md`). Short to
  ground (PW-3): 26.1 mA at the DAC window ends against 30 mA.

### AWG output protection (PR-4, `sim/awg/report.md`)

- **Stated PR-4 level: +/-1.8 V for 10 s, powered or unpowered.** It is the
  forced voltage at which the op-amp's current through the resistor reaches its
  65 mA typical short-circuit rating, with the output at the worst value a DAC
  code can command (derived: 65 mA x 49.85 ohm - 1.34 V = 1.90 V); 57.1 mA
  simulated at +/-1.8 V. The rating is a typical, not a maximum *(check)*.
- Up to +/-5 V the op-amp, the resistor (0.29 W in the simulation, against
  a 1206's 0.25 W *(check the part's rating)*) and the clamp may be damaged
  and nothing else: unpowered, the supply-pin Schottkys and the 4.7 k bleed
  keep the AFE rails at 2 mV and the current into them at 0.23 uA (PR-3),
  the undriven DAC0 pin stays at 0 V (PR-2), and the op-amp pins see
  4.12 V powered. Powered, the Due and AFE total 425 mA, judged against
  PW-1's 450 mA (2026-11-11).
- The six clamp diodes (3 per direction, to ground, on the **op-amp side** of
  the resistor) are not needed for any limit; on the load side they would
  carry 0.4 A at +/-5 V. The footprint may be left unpopulated.
- **Back-feed into the DAC0 buffer (AN-3, VT-5).** The AFE is powered from
  the Due's 5V pin with the LM27762 enabled from its input, so "AFE
  unpowered while DAC0 drives" exists only in a start-up window or a fault.
  With the dead buffer as its ESD diodes DAC0 sources 10 uA; a dead CMOS
  part on a lifted supply pin can draw more, and the **680 ohm input
  resistor bounds it at 3.8 mA** (DAC0 at 3.3 V into a supply short; 2.3 mA
  as 440 ohm). A larger resistor costs AW-3 (1k: 8.3 MHz into 50 ohm with
  6 pF at the input), so 680 ohm stays and **VT-5 measures the current**
  with DAC0 at 3.3 V into the unpowered AFE, against the 3.8 mA bound.
  The SAM3X datasheet gives no DAC0 current limit *(check)*.

## Power (PW-1..PW-7)

5 V feed from the Due's 5V pin, **take only, never drive** (it is the Due's
buck output and the file does not isolate it from USB VBUS), through the
1 ohm sense resistor with a test point either side (D7) and the bulk
capacitance, into the LM27762 (+3.3 V_A, -2.0712 V). **No ferrite bead**
(R2, approved 2026-11-11): the sense resistor and the bulk are the feed's
filter, and each scope op-amp branch has a 1 ohm ahead of its 10 uF; the
sense resistor's DC drop still reads the current between its test points.
Nothing is drawn from the Due's 3.3 V pin except the microamp Vmid sense
(PW-1, PW-4). Figures below are `sim/powercal` (datasheet maxima at once).

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
- **One bleed on +3.3 V_A: 4.7 kohm 1 % 0603** (C23162), 0.71 mA. The
  scope's PR-3 bleed and the AWG back-feed bleed are this one part. With
  the Due unpowered and +/-12 V on both scope inputs at once (PR-3) it
  holds +3.3 V_A at 0.106 V (limit 0.5 V); 1.8 uA reaches the Due's 3.3 V
  pin through the R3s and the sense filter and nothing its 5V pin (limit
  100 uA); the ADC pins sit at -0.149 to +0.156 V (PR-2: -0.2 to 3.45 V,
  51 mV of margin on the Due-pin clamp model) (`sim/powercal` P7).
- **Current (P3):** 48.3 mA normal, 61.3 mA with the AWG shorted (OPA354
  scope; 45.7 / 58.7 mA with OPA365), against PW-1's 100 mA. It carries
  one TLV9062 for both scope channels' Vmid (2 x 0.8 mA max), the AWG's
  own Vmid OPA365 and its DAC0 buffer (5 mA maximum each), the 2.26 mA
  ladder (now on the REF3030E), and the ADS124S08 (0.44 mA max) with one
  TMUX1119; the reference-buffer OPA365, the DAC8551, the MCP3564 and the
  four injection switches are gone.
- **Fault totals** (PR-4): +/-5 V forced on the AWG output, powered, the
  Due and AFE draw at most 411.8 mA as simulated (OPA354 scope; increment
  73.5 mA), 403.3 mA at the op-amp's 65 mA rating, against PW-1's 450 mA;
  the 400 mA target is for normal operation.
- **Rails.** +3.3 V_A: 174k / 100k 0.1 %, 3.288 V (3.235-3.342 V).
  **Negative rail -2.0712 V: R3 = 330k || 100k, R4 = 330k || 330k || 330k**
  (0.1 %, approved; the 768k left the BOM), -2.039 to -2.103 V, 45 kohm at
  FB-, whose input current the datasheet does not give *(check)*. Bare
  rails at the datasheet maxima 5.445 V, 55 mV under the OPA365's 5.5 V;
  start-up reaches 5.487 V on the bare rails and 4.796 V at the AWG op-amp
  pins behind the
  Schottkys (P1-a), with 300 mV of overshoot tolerated per rail (P1-b; the
  datasheet gives no overshoot, VT-8 *(check)*).
- **PW-6:** at a 4.4 V 5V pin the +3.3 V LDO keeps 0.97 V and the charge
  pump 2.14 V of headroom (P6-a; PW-6's minimum is now 4.50 V).
- **Ripple (no bead):** 4.6 uV rms of supply residue at the scope pin
  (P4-a, 20 uV allocation), 10.9 uV at the AWG output (P4-b, against a 20 uV
  internal share of AW-6, accepted 2026-11-11; 10.8 / 16.8 uV on the old
  10 / 20 mohm assumptions, 18.9 uV with one 10 uF per rail), its largest
  line 11.7 uV pk at 2 MHz = -98.7 dBc of +/-1 V,
  0.10 mV at the amplifier pins (PW-2, 20 mV), 0.43 uV at the Due's 5V pin
  at 2 MHz (PW-4). The pulse-skipping case of PW-4 still needs about 27 dB
  of the Due regulator's rejection, which nothing in the repository gives
  (P5-b, open).
- **PW-7 start-up:** the Vmid divider is 2 x 330k 0.1 % with 10 uF at its
  tap (M-7, M-10, approved): 13.7 s to 0.5 LSB.
- **Vmid: one TLV9062 (C398355) for both scope channels, one half each,
  on the one divider tap (owner, 2026-11-11)**; the AWG's Rg has its own
  OPA365 follower. Each half's loop (whatif/lowcost-scope/vmid): 4 x 1R in
  parallel for isolation (0.25 ohm), DC feedback from the node through
  4.7k, HF feedback through 1 uF, 6 x 10 uF + 100 nF at the node.
  `sim/powercal`, with the behavioural stand-in fitted to TI's model
  (0.59 %; TI's model does not converge beside the OPA354's in ngspice):
  impedance peak 0.251 ohm at 2 kHz, worst 0.260 ohm over the X7R's
  tolerance, Samsung's 1.65 V derating and ESR (target 0.3, P8-i; TI's
  model 0.252 ohm); phase margin 68 deg, worst 64 deg (P8-j); a
  full-scale step on its own node 1.20 mV, settled in 9 us. SC-9 between
  the channels 0.53 LSB (the shared sense node at DC); through the package
  100 dB of channel separation at DC (P8-l; no AC figure read *(check)*).
  Centring with the TLV9062's 2 mV offset 9.4 mV against 30 (P8-c). The
  stiffened OPA365 loop it replaces read 0.228 ohm and 82 deg.
  Phase margin is measured with the loop broken at the inverting input,
  so the capacitive load stays inside the loop; an OPA365 straight into
  10 uF + 100 nF reads 3 deg the same way (sim/awg's flag), the previous
  1R / 1k / 1.5 nF loop 96 deg.
- **The AWG has its own Vmid** (sim/awg variant buf): 330k / 330k 0.1 %
  off +3.3 V_A with 12 pF at the tap and an OPA365 follower with no output
  capacitor (77 deg), 5 uA. Its divider carries +3.3 V_A ripple to the
  AWG output: 10.9 uV rms in `sim/powercal` P4-b (20 uV share of AW-6).
  sim/awg's 2 MHz source, 5 mV behind 0.2 ohm, would show only about
  0.9 mV on the datasheet's 2.2 uF; until it is calibrated to 5 mV there,
  the powercal figure stands.

## Calibration (Phase 3)

- 3.0 V reference (REF3030-class; datasheet only, no usable model, so
  behavioural with its drift/noise numbers), **straight to the ladder with
  no buffer (owner, 2026-11-11)**. Its output node is also the ladder's top
  tap and the ADS124S08's REFP0 (REFN0 at AGND). **Load: two 100 nF at REFP0** (Yageo CC0603KRX7R9BB104,
  C14663, JLC Basic, 37.5 M in JLC stock on 2026-11-11 though LCSC showed
  0; approved 2026-11-11): one alone is 0.09 uF at its -10 % tolerance,
  below the REF30E's 0.1 uF minimum (C4-d), and two give 0.18 uF. A 100 nF
  across the reference pins is the ADS124S08's own
  guidance (a 100 nF across the external reference pins; unbuffered
  reference input about 250 kohm, 6 uA/V max), judged against the REF30E's
  stated stable range (0.1-22 uF with 10-500 mohm ESR). Its ESR is
  assumed at 30 mohm *(check)*: Yageo's data could not be fetched and its
  MLCC datasheets give no ESR. 100 nF + 10 uF through 1R || 1R || 1R also
  sits inside that range and stays in the BOM unfitted; the 10 uF directly
  (about 4 mohm) and through one 1R (1 ohm) do not. The REF30 (non-E) states no
  range, and the BOM's C38423 is that grade (bom.md F-10). Ringing is not
  simulated (encrypted model) *(check, VT)*.
- Precision ADC (2026-11-11): **ADS124S08IPBSR** (C2870171, TQFP-32),
  AVDD and DVDD from +3.3 V_A (AVDD 330 nF minimum, DVDD 100 nF), PGA
  bypassed, single-ended against AINCOM = AGND, low-latency filter at
  20 SPS (1.2 uVrms, 8.0 uVpp, from the gain-1 table *(check)*). Inputs: the
  six ladder taps (the top tap is REFP0's own node), the AWG-sense
  tap and the sense divider's bottom node; the rest spare. INL 10 ppm FSR
  max; its gain error is taken out against the top tap; input current
  1 nA/V typical (no maximum) needs no loading correction. 0.31 mA typical,
  0.44 mA max (P3).
- **BNC-tee calibration (PA-3, 2026-11-11), replacing the injection.** The
  AWG drives both scope inputs through a tee; the ADS124S08 reads the AWG
  on the BNC side through a 0.1 % 10 ppm/K divider, **100k to the tap and
  100k to a far end (k = 1/2, 2026-11-11)** that one TMUX1119 (PA-4's ratio switch, SEL
  pulled down: S1 the AWG's Vmid by default, S2 the buffered 3.0 V ladder
  top) moves, so the ratio is measured at every calibration. The ADC reads
  the bottom node itself, so the switch's Ron and leakage are outside the
  ratio (C3-u). **The switch's pins are clamped**: one BAT54S (C7420333,
  a die to ground and a die to +3.3 V_A) on the bottom node D and one on
  S1, with **100k** (C394537) from the AWG's Vmid node to S1; S2 (the ladder top) needs
  none. The T-switches, the 249 ohm injection branch, their
  decouplers and the D40/D41 pull-downs are gone; the injection rows
  (C3-a..f and the SC-9 injection rows) are retired.
- **The tee's fit share is 0.1 % on both ranges (owner, 2026-11-11).**
  With the ADC's INL referred to the AWG (whatif/tee's re-run), k = 1/3
  levered the ratio error by (1-k)/k = 2 and +/-5 V read 0.109 % at the
  bound; at k = 1/2 it is 0.051 % on +/-1.25 V (256 points) and 0.074 %
  (0.091 % at the bound) on +/-5 V (1024 points) (C3-t, quoted).
- **Input protection at k = 1/2 (C1-p, C1-q, C1-r; taps computed from
  sim/awg's AWG levels):** powered, AW-8 takes the tap to -0.048 V
  (-0.238 V at AW-8's +/-2.1 V bound), inside the ADS124S08's -0.3 V
  absolute limit and outside its -0.05 V operating range, where no reading
  is taken; the clamp current is at most 4.8 uA through 100k || 100k against
  10 mA. Unpowered, PR-4 +/-1.8 V takes the tap to -1.24..+1.80 V through
  at most 36 uA (80 uA at +/-5 V), which the ADS124S08's datasheet allows
  by current limiting (owner ruling on PR-4, 2026-11-11). The TMUX1119's
  does not, so its pins are clamped: within 0.20 V of a rail against 0.5 V
  (ngspice, the clamp at its datasheet-maximum Vf, +3.3 V_A held at 0 V or
  floating), 0.60 V without. The clamps sit on D and S1, never on the tap.
  With 100k to S1 the clamps lift the dead +3.3 V_A to 0.12 V at +1.8 V
  (0.31 V at +5 V; the 4.7k gave 0.80 V) against PR-3's 0.5 V (C1-r). D's
  leakage reaches it through Ron + 100k on S1, so at the datasheet bound
  it can move D by 0.4 V; D is read, so it is a reading, not an error.
  D is read by the ADC and S1 reaches the ratio only
  through D, so their leakage (2 uA max per die, the datasheet's only
  figure, at 25 V) is read rather than injected and leaves the ratio
  unchanged (C3-w). On the tap the same leakage would be 100 mV. At +/-5 V
  (shield damage allowed) the powered tap reaches +4.0 V through 34 uA.
- **Ladder (PA-9, D11, 2026-11-11): eight 249 ohm 0.1 % 10 ppm/K
  resistors** (C2692731, a type already in the design), three in parallel
  at the bottom and five in series, 1328 ohm: six taps on A2-A7 at
  0.188 / 0.750 / 1.312 / 1.875 / 2.438 / 3.000 V, the top tap being the
  REF3030E output itself (PA-8). Worst tap source 327 ohm (tap 3) against
  SC-10's 5 kohm. **The REF3030E carries it (C1-c):** 2.28 mA with REFP0,
  inside its 0-10 mA load-regulation range, 235 mV of headroom at the
  lowest +3.3 V_A against its 0.2 V, load regulation at most 103 uV
  (specified at 0.5 V of headroom *(check)*), self-heating 2.6 ppm. That is
  ratiometric for the ADS124S08 and a static PA-6 term for the Due's gain
  fit (C4-b: +/-3.74 mV, +/-0.73 mV with a meter).
- **Sequencing rule (B): the Due does not read the ladder while the
  ADS124S08 converts.** A Due sample on the top tap now lands on the
  reference node: 18 pC into the 2 x 100 nF is 0.12 LSB before the
  REF3030E recovers it, and its output impedance at MHz is not modelled
  (C1-d). Calibration already reads them one after the other (C4-c).
- With six taps and the ADS124S08 reading every tap at each calibration
  the fit adds 0.10 LSB (C2-a, limit 0.5), 0.10 LSB with one dropped
  (C2-b), and the Due's pin leakage (0.5 uA max) across the worst tap
  brings it to 0.17 LSB (C2-c). The taps are re-read at every calibration
  (C2-d, 0.10 LSB); with 10 ppm/K parts a reading reused after 10 K would
  still pass (0.13 LSB), so the rule is margin here.
- **The top tap is the reference node itself**, so no offset sits between
  it and REFP0.
  Element rating not read *(check)*. No switch between tap and pin.

## Layout and assembly facts (JLCPCB, `jlcpcb.md`)

Two layers, one side populated, Economic PCBA, 0603 minimum, extended-part
count kept small (a loading fee per distinct extended part), BNCs and
headers hand-soldered (not in the BOM/CPL).
