# tph2502.lib provenance

Clean-room model built only from FACTS.md (datasheet facts); no vendor SPICE model was consulted, opened or
in context while writing it or its tests.

- Input: `FACTS.md` in this folder, sha256 `0398cfad1abc944848f462cefd9764772f83c17b9010b7fecd131b3f38a611e9`.
- Brief: one amplifier of the dual as `.subckt TPH2502_OPEN INP INN VP VN OUT`; the board uses both halves as
  unity-gain followers and one as a gain stage of about 1.85 driving a 50 ohm back-termination into 50 ohm.
  Cover open-loop gain and GBW/phase, slew, offset, bias, input capacitance, common-mode limits, output swing,
  short-circuit current, output impedance, supply current and optional noise.
- Date: 2026-11-13. Test: `hardware/afe-proto/tests/open_models/test_tph2502_open.py`.

## What comes straight from FACTS.md

| model quantity | value | FACTS row |
|---|---|---|
| AVOL_DB | 110 dB | s4 table, AVOL typ (RL = 2 kohm). The curves read 138-143 dB (inconsistency 5); the table value was chosen |
| GBW | 128 MHz parameter (FACTS 120 MHz at G = +10) | s5; 128 is a calibration, see the modelling choices |
| VOS | 0 (parameter) | s3, +/-50 uV typ, +/-500 uV max; default 0 |
| IB | 0.3 pA net at VCM = VS/2 | s3, typ at 27 C |
| CDIFF, CCM | 2.7 pF, 1 pF | s8 (the 2 pF in the RI rows is inconsistency 10, not used) |
| RIN | 1e13 ohm | s8 |
| VCMLO, VCMHI | 0.1, 0.1 | s3 common-mode range printed as V- -0.1 to V+ -0.1 |
| RO | 21 ohm | s9 open-loop output impedance at 1 kHz |
| VSAT0 | 2 mV, both rails | s9 swing from rail typ at 100 kohm (the row does not split the rails) |
| ISRC, ISNK | 290 mA, 160 mA | s9 short-circuit typ (min 100 each) |
| IQ | 6.5 mA per amplifier | s2 table typ (the curve reads 7.2 mA at 25 C, 5 V: inconsistency 3; table chosen) |
| EN | 6.5 nV/rtHz when switched on | s7 at 1 MHz; white only, off by default (EN = 0) |

The model is white noise only; the 1/f rise in the s7 curve is not modelled.

## Modelling choices not in the datasheet

| choice | value | why needed | bench test that would pin it |
|---|---|---|---|
| GBW parameter | 128 MHz | the measured -3 dB of the G=+10 stage times 10 must land within 10 % of the FACTS 120 MHz together with G=+1 and G=+2; with GBW = 120 MHz the best joint fit left G=+10 at -14 %. Trade: the dominant-pole product is 7 % above the FACTS number; the Bode points stay inside +/-10 dB | G=+10 step or ac response on the bench |
| LO | 10 nH series in the output | raises closed-loop Zout above ~10 MHz; a larger L (100 nH reaches 24 ohm at 100 MHz) broke the G=+1 and G=+2 bandwidths, so it is kept small | closed-loop Zout vs frequency above 10 MHz |
| FZ, FP2 (one zero, one pole above the dominant pole at GBW/A0 = 400 Hz) | 60 MHz, 200 MHz | FACTS has no pole data. A single pole at GBW gives a 120 MHz follower; FACTS has G=+1 at 250 MHz, G=+2 at 90 MHz and the Bode crossing near 300 MHz. Fitted in ngspice on the G=1 (RF 25), G=2 and G=10 (RF 620) stages | open-loop gain and phase with a labelled phase axis, or the G=+2 step overshoot |
| Phase margin | follows from the two choices above; no numeric phase margin exists in FACTS | none in the datasheet | open-loop phase at the 0 dB crossing |
| SR parameter | 235 V/us internal | calibrated so the 20-80 % slope of a 4 V follower step at 5 V reads 200 V/us (FACTS s6 typ) | scope capture of 2 V and 4 V steps |
| RSAT | 11.5 ohm per rail | FACTS has no swing-vs-current curve (the p9 curve is absent). Headroom from a rail grows by RSAT per ampere of load. From the text "2.7 V swing at +/-100 mA on 5 V", read as peak-to-peak: (5 - 2.7) / 2 / 0.1 A. The reading is ambiguous. A more conservative alternative is RSAT = 21 (the open-loop output resistance) | **measure the swing at 17.5 mA on the bench**; at the default the headroom there is about 0.2 V per rail |
| Short-circuit slope RLIM | 1 kohm | the current limit needs a finite slope for the solver; the shorted current lands about 1-3 mA above the limit value | short-circuit current into 0 ohm |
| Common-mode clamp | each input clamped to V- - 0.1 .. V+ - 0.1, using the printed range | behaviour beyond the range is not in FACTS (the text claims rail-to-rail, inconsistency 11). Clamping both inputs makes the input stage go dead past the range, which is conservative. A follower held beyond V+ - 0.1 sits at about V+ - 0.1; a gain stage stops responding | input range sweep with a follower and a gain-of-2 stage |
| Bias sign and VCM | source draws IB - (VS/2)/RIN from each input, so the net is IB at VCM = VS/2 | FACTS gives no sign and no VCM for IB | picoammeter on a bare pin |
| Internal gain-node travel past the rails (VMARG) | 4 V | recovery speed after overload; FACTS has only tR = 50 ns | overload-recovery capture |
| Rounding of the min/max clamps | 1 mV (voltages), 0.1 uA (currents) | Newton convergence; ngspice settled on a false DC point with hard corners | none |
| gm of the input stage (1 mS) and the 1 kohm / 0.01 S helper values | internal | scale of the model, no effect on external figures | none |
| No temperature, supply-range, CMRR, PSRR, thermal-shutdown or crosstalk behaviour | not modelled | none in the board's checks that FACTS would let me pin | CMRR, PSRR curves |

## Test tolerances

`TOL_TYP` = **+/-10 %** is a tolerance chosen here, not a FACTS accuracy. It applies to table rows that give a typ
value and no accuracy: the G=+1 (250 MHz), G=+2 (90 MHz) and GBW (120 MHz at G=+10) bandwidths and the 4 V slew
(200 V/us), and the 2 V slew (180 V/us). Ten percent is the width of the model's own fit; it is not widened to pass.
Rise times (7 ns at 2 Vpp, 2 ns at 200 mVpp) use +/-35 %, also chosen here, because they are typ-only and depend on the
drive edge.

| test | tolerance | source |
|---|---|---|
| DC follower accuracy | < 50 uV (VOS default 0) | chosen; FACTS VOS max is +/-500 uV |
| VOS parameter | 480-520 uV for VOS = 500 uV | chosen, tests the knob |
| open-loop gain | 109-111 dB | chosen around the table typ 110 dB |
| Bode points (100 Hz, 1 kHz, 1 MHz, 10 MHz, 100 MHz) | +/-10 dB | FACTS s5 reading accuracy |
| 0 dB crossing | 150-600 MHz | FACTS s5: near 300 MHz +/- a factor 2 |
| G=+1, G=+2, GBW, 4 V slew | +/-10 % | TOL_TYP, chosen |
| 2 V slew, Zout at 100 MHz, 200 mV rise | strict xfail, see below | |
| 2 Vpp rise | +/-35 % | chosen |
| swing from rail at 100 kohm | 1-3.5 mV | FACTS s9 typ 2 mV (max 30 mV); band chosen |
| 17.5 mA headroom | 5 mV around the model's own RSAT formula | tests the labelled choice, not a FACTS figure |
| short-circuit source / sink | +/-5 % of 290 / 160 mA | chosen; FACTS gives typ with min 100 mA |
| supply current | +/-0.3 mA of 6.5 mA | FACTS s2 curve reading accuracy |
| input capacitances | +/-2 % | chosen; the values are exact parameters |
| input bias | 0.2-0.4 pA around 0.3 pA | chosen |
| common-mode clamp | follower holds at 4.89-4.92 V past the range | tests the modelling choice |
| Zout open loop | +/-5 % of 21 ohm | chosen |
| Zout 1 kHz | < 0.01 ohm | FACTS s9 table |
| Zout 100 kHz, 1 MHz, 10 MHz | factor 1.5 | FACTS s9 curve accuracy |
| noise | +/-15 % of 6.5 nV/rtHz; off < 1 nV | chosen |

## FACTS figures the model does not match

Each is a strict xfail in the test, so a model change that fixes one makes the suite fail until the xfail is removed.

- Slew at a 2 V step: model 223 V/us (20-80 %) against 180 V/us (+24 %). The model slews at one value; the 2 V step is
  bandwidth-limited. Slew at VS = 3 V (160 V/us) is not modelled.
- Rise time for 200 mVpp: model 0.85 ns against 2 ns (-57 %). The 2 Vpp rise (7 ns) is met.
- Closed-loop Zout at 100 MHz: model 7.7 ohm against 25 ohm (needs 16.7-37.5 at the curve's factor 1.5). A 100 nH series
  inductance gets 24 ohm but costs the G=+1 and G=+2 bandwidths, so the trade went the other way.
- Open-loop gain at 10 Hz: curve 138 dB, model 110 dB (the AVOL table value was chosen deliberately).
- Met after the joint refit: G=+1 245 MHz (-2 %), G=+2 87 MHz (-3 %), G=+10 11.1 MHz so GBW 111 MHz (-8 %), 4 V slew 198 V/us.
- Not modelled or not tested: overload recovery, settling, HD2/HD3, differential gain and phase, crosstalk, CMRR, PSRR,
  temperature, the IQ-vs-supply curve and 1/f noise.
