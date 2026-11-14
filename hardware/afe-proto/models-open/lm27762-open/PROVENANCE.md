# LM27762_OPEN provenance

License: CC-BY-SA 4.0 (see LICENSE).

## Inputs

- `FACTS.md` in this folder, sha256 `7bded36acf8cb4991da9928b0c4b1176e97a51b76550f956a7a842dcccfb70f0`
  (written from the datasheet by a separate spec writer).
- The brief: build `lm27762.lib` with `.subckt LM27762_OPEN VIN GND OUTP FBP OUTN FBN CPOUT C1P C1N ENP ENN PGOOD`
  (pin mapping in the lib header), the board VIN about 5 V, OUT+ about +3.3 V and OUT- about -2.05 V by external
  dividers, datasheet-recommended external caps; two variants in one file (`LM27762_OPEN_AVG` averaged,
  `LM27762_OPEN` switching pump); tests per the clean-room rules.
- `IMPL_RULES.md` (clean-room implementer rules).
- Date: 2026-11-13.
- No vendor SPICE model was in context at any point, and none was opened.

## What each element comes from

Positive LDO from VIN with FB+ reference (param `VFBP`, 1.182/1.2/1.218), dropout line (Fig 5-3, 0.47 ohm),
500 mA limit; inverting pump to CP (-VIN unloaded) with the Fig 5-4 output resistance and 2 MHz switching (param
`FSW`, 1.7/2.0/2.3); negative LDO from CP with FB- reference (param `VFBN`) and dropout line (Fig 5-3, 0.32 ohm);
UVLO 2.6 V up / 2.4 V down; enables; PGOOD at 95 % of target and the Table 6-1 logic; shutdown discharge 50 kohm;
IQ 390 uA and ISD 0.5 uA; line regulation 1.9 / 1.5 mV/V; load regulation 11 / 34 uV/mA; PSRR shape of Fig 7-3/7-4.

## Use and limits

The switching variant reproduces the pump's input-current pulses and the CP ripple, and is valid for input-side and CP studies. It is not valid for output ripple: it underestimates the ripple on OUT+ and OUT- by about 17x (0.03-0.06 mV against 0.95 mV p-p at 100 mA, VIN 3.7 V). Output-ripple studies should inject the pump current through the board network (the line-spectrum method), or wait for a calibrated path. The misses against FACTS figures are held as strict xfail tests in the test file.

## Modelling choices not in the datasheet

| choice | value | why it is needed | bench test that would pin it |
|---|---|---|---|
| Pass device form | triode FET, I = tanh(K*error)*Vds/Rds-on, implicit current limit | a current-source form with a Vds limit could not be solved by ngspice at .op; this one is smooth and has the dropout line as its exact limit | load-regulation and dropout curves at several VIN |
| Pass gate gains `KGP`, `KGN` | 20 and 4.8 (1/V) | set the load regulation to FACTS 11 / 34 uV/mA at 1.8 V, VIN 5 V; gain scales with Vds, so headroom costs regulation | load regulation vs VIN-VOUT |
| Dropout knee | soft (a consequence of the gains above) | output sags earlier than the Fig 5-3 line near dropout; conservative | output vs VIN just above dropout |
| Neg LDO current limit `ILIMN` | 0.5 A | FACTS gives only the pump's 500 mA input limit | short-circuit test of OUT- |
| Soft current limit exponent | 40 | smooth limit; reads 7.6 % above 500 mA at a hard short | short-circuit I vs VIN |
| Error-path pole | 30 MHz (1 kohm, 5.3 pF) | keeps the loop with the 2.2 uF output cap well damped | load-step response |
| IQ split | 100 uA (OUT+) + 90 uA (neg side, from VIN) + 200 uA (neg LDO, drawn from CP) = 390 uA | FACTS gives the total only | IQ with one enable on at a time |
| Enable threshold `VEN` | 0.8 V, 10 Mohm input | between VIL max 0.4 and VIH min 1.2; no input current given | EN threshold and input current |
| Soft-start time constant `TSS` | 50 us (reference RC) | Fig 5-10 is a scope capture without numbers | start-up time of both rails |
| CP discharge in shutdown `RCPD` | 10 kohm | the block diagram shows a discharge source, no value | CP decay in shutdown |
| PGOOD on-resistance `RPG` | 100 ohm; threshold taken on the FB pins at 0.95 x the reference parameter | not given | PGOOD low level and delay |
| Line-regulation trims `KLP` 2.5 mV/V, `KLN` -1.2 mV/V | reference shift per V of VIN, negative for the neg rail | the pass device's headroom effect adds to the FACTS figure; trimmed so the total over VIN 2.7-5 V at 50 mA is 1.9 / 1.5 mV/V | line regulation at other loads |
| PSRR paths | two-pole high-pass (60 kHz pos, 40 kHz neg), gain 0.07 / 0.03, one 300 kHz low-pass | shape Fig 7-4 / 7-3 above 10 kHz; no data above 100 kHz | PSRR to 1 MHz |
| CP droop law `lm27762_dcp` | 0.28 V*tanh(I/0.5 mA) + 2.11 ohm above a 120 mA knee | monotone fit of the Fig 5-4 R*I points; the dip at 30-60 mA is not followed because it would be a negative resistance; zero at zero load and the shape under 1 mA are not in the figure | CP voltage vs load, 0.1-100 mA |
| Pump droop vs VIN | none (Fig 5-4 is at 5.5 V only) | no data | CP droop vs VIN |
| Pump temperature | 25 C curve only | the 85 C curve is lower at 10-30 mA | repeat Fig 5-4 hot |
| Switch on-resistance `RSWON` | 0.3 ohm each, four switches | tuned so the switching variant gives 2.5 ohm at 100-250 mA with C1 = 1 uF, 2 MHz | R at 300 mA, other C1 |
| Pulse-skip law | comparator on VIN+V(CP) against the droop law at the measured load, band `PFMVH` = 40 mV, constant frequency above `IPWM` = 100 mA, load averaged over `TIAV` = 100 us | the datasheet gives no law for burst spacing; this is the parameter that sets it | burst repetition rate vs load |
| Clock | sine zero crossings at +-0.1 V, 30 mV smoothing, no dead time beyond that | break-before-make without breakpoints | CP ripple at 2 MHz |
| Input current limit | only in the averaged variant (soft, 10 ohm above 0.5 A); the switching variant has none | a peak limit would distort the average the figures describe | start-up inrush |
| Leakage resistors | 1 Gohm on C1P/C1N | no floating nodes while the pump is skipping | none |

## Not matched (see the report with the tests)

OUT- load regulation at -3.3 V (Fig 5-7), headroom collapse (Fig 5-5), PSRR at low frequency and a few points,
ripple magnitude on OUT+/OUT- (Fig 5-1/5-2), unloaded pulse rate ("sub-2 kHz"), the 85 C curve, the Fig 5-9
efficiency (not checked), start-up timing, noise, thermal shutdown (not modelled), efficiency.
