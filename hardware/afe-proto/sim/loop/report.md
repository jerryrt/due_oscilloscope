# SM-5 loop simulation: AWG -> cable -> scope -> Due ADC, PAM16 at 1.6 Msym/s

Status 2026-11-11: **FAIL at every corner.** The AFE adds 27 codes (OPA354 scope) to
71 codes (OPA365 scope) of inter-symbol interference against an allowance of about
0.32 codes (10 % of the 8.6-code band after the noise terms). The cause is the two
compensated dividers, not bandwidth: the AWG input attenuator (Ra/Rb with Ca/Cb,
tail about 250 ns) and the scope's 1 Mohm divider (C1/C2, shelf with an 8.6 us time
constant). Each would need its capacitor ratio held to about 0.02 pF.

Regenerate: `cd hardware/afe-proto/sim/loop && python3 -I run.py` (steps: sims,
sweeps, extras, summary, rerun TAG...). Uses up to 3 ngspice processes, no /tmp.
Model choices, the band definition, the guard and the positive control are in
`run.py`'s header and below; every figure is in `results/`.

Open questions for the requirement owner (not relaxed here):
1. Whether VT-15 / SM-5 reads the band after the host's SC-5 frequency-response
   calibration (CA-1), which can remove a known linear shelf.
2. Whether SM-5's band is counted in codes or normalised to the level spacing: the
   loop gain from DAC pin to ADC pin on +-1.25 V is 1.299, so in codes DAC0's own
   noise alone grows the band by about 35 %, against 3.7 % normalised.

The tables below are `results/summary.md` as generated.

## DAC fit (baseline network, numpy state space)

| S/H model, DAC Rout | DAC pole tau | slew | predicted rise 999/699/499/350/250/175 mV (ns) | note |
|---|---|---|---|---|
| derived|0 | 0.00 ns | 6.13 V/us | 136.7 / 102.4 / 81.9 / 68.5 / 60.7 / 55.8 | the S/H alone gives 50.1 ns, above the measured 42.4 ns floor: DAC pole set to 0 |
| stress|0 | 16.48 ns | 6.00 V/us | 136.7 / 100.0 / 77.5 / 62.5 / 53.9 / 48.4 |  |
| derived|300 | 0.00 ns | 6.21 V/us | 136.7 / 103.7 / 84.0 / 71.3 / 64.1 / 59.4 | the S/H alone gives 54.1 ns, above the measured 42.4 ns floor: DAC pole set to 0 |
| derived|1000 | 0.00 ns | 6.47 V/us | 136.7 / 107.2 / 89.8 / 78.7 / 72.4 / 68.5 | the S/H alone gives 64.4 ns, above the measured 42.4 ns floor: DAC pole set to 0 |

Measured (linux-x1, docs/ets-mode.md): 136.8 / 98.9 / 76.6 / 62.6 / 54.4 / 48.6 ns.

## Noise factor (docs/afe.md arithmetic)

- +/-1.25 V: sqrt(0.64^2 + 0.2^2 + (0.1 x 1.1265)^2) / 0.64 = 1.0624 (+6.24 %), leaving 0.324 codes of ISI at a band of 8.6 codes and 0.429 at 11.4
- +/-5 V: sqrt(0.64^2 + 0.2^2 + (0.1 x 0.233)^2) / 0.64 = 1.0483 (+4.83 %), leaving 0.444 codes of ISI at a band of 8.6 codes and 0.589 at 11.4

## Every loop run against its baseline

| case | baseline | loop band, worst level (codes) | baseline band | AFE-added ISI | growth at 8.6 | growth at 11.4 | SM-5 (10 %) |
|---|---|---|---|---|---|---|---|
| OPA354_Ca20_nom | base | 27.17 | 0.21 | +26.96 | +319.8 % | +242.8 % | **FAIL** |
| OPA354_Ca20_Cpar0.5 | base | 7.29 | 0.21 | +7.08 | +88.6 % | +68.3 % | **FAIL** |
| OPA354_Ca20_Cpar3.5 | base | 65.83 | 0.21 | +65.62 | +769.2 % | +581.8 % | **FAIL** |
| OPA354_Ca20_C1hi_C2lo | base | 52.14 | 0.21 | +51.93 | +610.1 % | +461.8 % | **FAIL** |
| OPA354_Ca20_C1lo_C2hi | base | 64.64 | 0.21 | +64.43 | +755.4 % | +571.4 % | **FAIL** |
| OPA354_Ca20_R2_330k | base | 24.24 | 0.21 | +24.03 | +285.6 % | +217.0 % | **FAIL** |
| OPA354_Ca20_R2_340k | base | 31.44 | 0.21 | +31.23 | +369.3 % | +280.1 % | **FAIL** |
| OPA354_Ca20_adcstress | base_stress | 26.95 | 0.02 | +26.93 | +319.4 % | +242.5 % | **FAIL** |
| OPA354_Ca20_rout300 | base_rout300 | 26.84 | 0.34 | +26.50 | +314.4 % | +238.7 % | **FAIL** |
| OPA354_Ca20_rout1000 | base_rout1000 | 26.06 | 0.83 | +25.23 | +299.6 % | +227.6 % | **FAIL** |
| OPA354_Ca20_slew5.9 | base_slew5.9 | 27.38 | 0.25 | +27.13 | +321.7 % | +244.2 % | **FAIL** |
| OPA354_Ca20_slew6.6 | base_slew6.6 | 26.79 | 0.16 | +26.64 | +316.0 % | +239.9 % | **FAIL** |
| OPA354_Ca20_rails_weak | base | 27.18 | 0.21 | +26.97 | +319.9 % | +242.8 % | **FAIL** |
| OPA354_Ca20_vmid_0.05ohm | base | 28.11 | 0.21 | +27.90 | +330.7 % | +251.0 % | **FAIL** |
| OPA354_Ca20_cable2m | base | 27.05 | 0.21 | +26.84 | +318.4 % | +241.7 % | **FAIL** |
| OPA354_Ca20_nocable | base | 27.23 | 0.21 | +27.02 | +320.4 % | +243.2 % | **FAIL** |
| OPA354_Ca20_T0 | base | 27.18 | 0.21 | +26.97 | +319.8 % | +242.8 % | **FAIL** |
| OPA354_Ca20_T50 | base | run failed: transient stopped at 0.0 us of 418.6: doAnalyses: TRAN:  Timestep too small; time = 5.0007e-12, timestep = 3.125e-22: trouble with node "xu.46" | Error: incompl | | | | | NOT RUN |
| OPA354_Ca20_T70 | base | run failed:                           nan                  nan
v.x1_a.v93#branch                               nan                  nan
visn_a#branch                        | | | | | NOT RUN |
| OPA354_Ca20_range5 | base | 5.73 | 0.21 | +5.52 | +69.0 % | +53.2 % | **FAIL** |
| OPA354_Ca20_idealscope | base | 25.62 | 0.21 | +25.41 | +301.7 % | +229.1 % | **FAIL** |
| OPA354_Ca24_nom | base | 44.04 | 0.21 | +43.83 | +515.9 % | +390.7 % | **FAIL** |
| OPA354_Ca24_Cpar0.5 | base | 64.05 | 0.21 | +63.84 | +748.6 % | +566.2 % | **FAIL** |
| OPA354_Ca24_Cpar3.5 | base | 5.39 | 0.21 | +5.18 | +66.5 % | +51.7 % | **FAIL** |
| OPA354_Ca24_C1hi_C2lo | base | 91.31 | 0.21 | +91.10 | +1065.5 % | +805.3 % | **FAIL** |
| OPA354_Ca24_C1lo_C2hi | base | 57.35 | 0.21 | +57.14 | +670.6 % | +507.4 % | **FAIL** |
| OPA354_Ca24_R2_330k | base | 48.42 | 0.21 | +48.21 | +566.8 % | +429.2 % | **FAIL** |
| OPA354_Ca24_R2_340k | base | 41.24 | 0.21 | +41.03 | +483.4 % | +366.2 % | **FAIL** |
| OPA354_Ca24_adcstress | base_stress | 44.30 | 0.02 | +44.28 | +521.1 % | +394.6 % | **FAIL** |
| OPA354_Ca24_rout300 | base_rout300 | 43.49 | 0.34 | +43.15 | +508.0 % | +384.8 % | **FAIL** |
| OPA354_Ca24_rout1000 | base_rout1000 | 42.19 | 0.83 | +41.36 | +487.2 % | +369.1 % | **FAIL** |
| OPA354_Ca24_slew5.9 | base_slew5.9 | 44.26 | 0.25 | +44.01 | +518.0 % | +392.3 % | **FAIL** |
| OPA354_Ca24_slew6.6 | base_slew6.6 | 43.63 | 0.16 | +43.48 | +511.8 % | +387.6 % | **FAIL** |
| OPA354_Ca24_rails_weak | base | 44.07 | 0.21 | +43.86 | +516.2 % | +391.0 % | **FAIL** |
| OPA354_Ca24_vmid_0.05ohm | base | 43.23 | 0.21 | +43.02 | +506.5 % | +383.6 % | **FAIL** |
| OPA354_Ca24_cable2m | base | 44.11 | 0.21 | +43.90 | +516.7 % | +391.3 % | **FAIL** |
| OPA354_Ca24_nocable | base | 44.04 | 0.21 | +43.83 | +515.9 % | +390.7 % | **FAIL** |
| OPA354_Ca24_T0 | base | 44.03 | 0.21 | +43.82 | +515.7 % | +390.6 % | **FAIL** |
| OPA354_Ca24_T50 | base | run failed: transient stopped at 0.0 us of 418.6: doAnalyses: TRAN:  Timestep too small; time = 5.0007e-12, timestep = 3.125e-22: trouble with node "xu.46" | Error: incompl | | | | | NOT RUN |
| OPA354_Ca24_T70 | base | run failed:                           nan                  nan
v.x1_a.v93#branch                               nan                  nan
visn_a#branch                        | | | | | NOT RUN |
| OPA354_Ca24_range5 | base | 9.23 | 0.21 | +9.01 | +109.7 % | +83.9 % | **FAIL** |
| OPA354_Ca24_idealscope | base | 46.00 | 0.21 | +45.79 | +538.7 % | +407.9 % | **FAIL** |
| OPA354_idealawg | base | 2.06 | 0.21 | +1.85 | +27.8 % | +22.5 % | **FAIL** |
| OPA354_reltol1e-4 | base | 27.17 | 0.21 | +26.96 | +319.8 % | +242.8 % | **FAIL** |
| OPA365_Ca20_nom | base | 71.62 | 0.21 | +71.41 | +836.6 % | +632.6 % | **FAIL** |
| OPA365_Ca20_Cpar0.5 | base | 53.61 | 0.21 | +53.39 | +627.1 % | +474.6 % | **FAIL** |
| OPA365_Ca20_Cpar3.5 | base | 106.66 | 0.21 | +106.45 | +1244.1 % | +940.0 % | **FAIL** |
| OPA365_Ca20_C1hi_C2lo | base | 39.24 | 0.21 | +39.03 | +460.1 % | +348.6 % | **FAIL** |
| OPA365_Ca20_C1lo_C2hi | base | 101.30 | 0.21 | +101.09 | +1181.7 % | +893.0 % | **FAIL** |
| OPA365_Ca20_R2_330k | base | 67.85 | 0.21 | +67.64 | +792.8 % | +599.6 % | **FAIL** |
| OPA365_Ca20_R2_340k | base | 75.29 | 0.21 | +75.08 | +879.3 % | +664.9 % | **FAIL** |
| OPA365_Ca20_adcstress | base_stress | 71.39 | 0.02 | +71.37 | +836.1 % | +632.3 % | **FAIL** |
| OPA365_Ca20_rout300 | base_rout300 | 70.81 | 0.34 | +70.48 | +825.8 % | +624.5 % | **FAIL** |
| OPA365_Ca20_rout1000 | base_rout1000 | 68.97 | 0.83 | +68.14 | +798.5 % | +603.9 % | **FAIL** |
| OPA365_Ca20_slew5.9 | base_slew5.9 | 71.89 | 0.25 | +71.64 | +839.3 % | +634.7 % | **FAIL** |
| OPA365_Ca20_slew6.6 | base_slew6.6 | 71.16 | 0.16 | +71.01 | +831.9 % | +629.1 % | **FAIL** |
| OPA365_Ca20_rails_weak | base | 71.62 | 0.21 | +71.41 | +836.6 % | +632.6 % | **FAIL** |
| OPA365_Ca20_vmid_0.05ohm | base | 72.49 | 0.21 | +72.28 | +846.7 % | +640.3 % | **FAIL** |
| OPA365_Ca20_cable2m | base | 71.52 | 0.21 | +71.31 | +835.4 % | +631.7 % | **FAIL** |
| OPA365_Ca20_nocable | base | 71.68 | 0.21 | +71.47 | +837.3 % | +633.2 % | **FAIL** |
| OPA365_Ca20_T0 | base | 71.59 | 0.21 | +71.38 | +836.2 % | +632.4 % | **FAIL** |
| OPA365_Ca20_T50 | base | run failed: transient stopped at 10.4 us of 418.6: doAnalyses: TRAN:  Timestep too small; time = 1.03533e-05, timestep = 3.125e-22: trouble with node "a_cp1" | Error: incom | | | | | NOT RUN |
| OPA365_Ca20_T70 | base | run failed: transient stopped at 10.8 us of 418.6: doAnalyses: TRAN:  Timestep too small; time = 1.08154e-05, timestep = 3.125e-22: trouble with x1_a:ji-instance j.x1_a.j11 | | | | | NOT RUN |
| OPA365_Ca20_range5 | base | 15.04 | 0.21 | +14.83 | +177.3 % | +134.9 % | **FAIL** |
| OPA365_Ca20_idealscope | base | 25.62 | 0.21 | +25.41 | +301.7 % | +229.1 % | **FAIL** |
| OPA365_Ca24_nom | base | 63.33 | 0.21 | +63.12 | +740.1 % | +559.9 % | **FAIL** |
| OPA365_Ca24_Cpar0.5 | base | 74.75 | 0.21 | +74.54 | +872.9 % | +660.1 % | **FAIL** |
| OPA365_Ca24_Cpar3.5 | base | 42.75 | 0.21 | +42.54 | +500.9 % | +379.4 % | **FAIL** |
| OPA365_Ca24_C1hi_C2lo | base | 39.12 | 0.21 | +38.91 | +458.7 % | +347.6 % | **FAIL** |
| OPA365_Ca24_C1lo_C2hi | base | 87.25 | 0.21 | +87.04 | +1018.4 % | +769.8 % | **FAIL** |
| OPA365_Ca24_R2_330k | base | 60.23 | 0.21 | +60.02 | +704.1 % | +532.7 % | **FAIL** |
| OPA365_Ca24_R2_340k | base | 66.35 | 0.21 | +66.14 | +775.3 % | +586.4 % | **FAIL** |
| OPA365_Ca24_adcstress | base_stress | 63.27 | 0.02 | +63.24 | +741.6 % | +561.0 % | **FAIL** |
| OPA365_Ca24_rout300 | base_rout300 | 62.64 | 0.34 | +62.30 | +730.7 % | +552.7 % | **FAIL** |
| OPA365_Ca24_rout1000 | base_rout1000 | 61.16 | 0.83 | +60.33 | +707.8 % | +535.5 % | **FAIL** |
| OPA365_Ca24_slew5.9 | base_slew5.9 | 63.33 | 0.25 | +63.08 | +739.8 % | +559.6 % | **FAIL** |
| OPA365_Ca24_slew6.6 | base_slew6.6 | 63.30 | 0.16 | +63.15 | +740.5 % | +560.2 % | **FAIL** |
| OPA365_Ca24_rails_weak | base | 63.33 | 0.21 | +63.12 | +740.1 % | +559.9 % | **FAIL** |
| OPA365_Ca24_vmid_0.05ohm | base | 64.12 | 0.21 | +63.91 | +749.4 % | +566.9 % | **FAIL** |
| OPA365_Ca24_cable2m | base | 63.30 | 0.21 | +63.09 | +739.9 % | +559.7 % | **FAIL** |
| OPA365_Ca24_nocable | base | 63.34 | 0.21 | +63.13 | +740.4 % | +560.0 % | **FAIL** |
| OPA365_Ca24_T0 | base | 63.30 | 0.21 | +63.09 | +739.9 % | +559.7 % | **FAIL** |
| OPA365_Ca24_T50 | base | run failed: transient stopped at 10.4 us of 418.6: doAnalyses: TRAN:  Timestep too small; time = 1.04032e-05, timestep = 3.125e-22: trouble with node "a_cp1" | Error: incom | | | | | NOT RUN |
| OPA365_Ca24_T70 | base | run failed: transient stopped at 9.8 us of 418.6: doAnalyses: TRAN:  Timestep too small; time = 9.75872e-06, timestep = 3.125e-22: trouble with x1_a:ji-instance j.x1_a.j11  | | | | | NOT RUN |
| OPA365_Ca24_range5 | base | 13.29 | 0.21 | +13.08 | +156.9 % | +119.6 % | **FAIL** |
| OPA365_Ca24_idealscope | base | 46.00 | 0.21 | +45.79 | +538.7 % | +407.9 % | **FAIL** |
| OPA365_idealawg | base | 48.93 | 0.21 | +48.72 | +572.8 % | +433.6 % | **FAIL** |
| OPA365_reltol1e-4 | base | 71.62 | 0.21 | +71.41 | +836.6 % | +632.6 % | **FAIL** |
| OPA354_Rab1pct_nom | base | 29.33 | 0.21 | +29.12 | +344.9 % | +261.7 % | **FAIL** |
| OPA354_Rab1pct_Cpar0.5 | base | 8.45 | 0.21 | +8.24 | +102.0 % | +78.5 % | **FAIL** |
| OPA354_Rab1pct_Cpar3.5 | base | 69.82 | 0.21 | +69.61 | +815.6 % | +616.8 % | **FAIL** |
| OPA354_Rab1pct_C1hi_C2lo | base | 52.85 | 0.21 | +52.64 | +618.3 % | +468.0 % | **FAIL** |
| OPA354_Rab1pct_C1lo_C2hi | base | 66.67 | 0.21 | +66.46 | +779.1 % | +589.3 % | **FAIL** |
| OPA354_Rab1pct_idealscope | base | 27.75 | 0.21 | +27.54 | +326.5 % | +247.8 % | **FAIL** |
| OPA365_Rab1pct_nom | base | 73.62 | 0.21 | +73.41 | +859.8 % | +650.2 % | **FAIL** |
| OPA365_Rab1pct_Cpar0.5 | base | 54.69 | 0.21 | +54.48 | +639.7 % | +484.1 % | **FAIL** |
| OPA365_Rab1pct_Cpar3.5 | base | 110.31 | 0.21 | +110.10 | +1286.4 % | +972.0 % | **FAIL** |
| OPA365_Rab1pct_C1hi_C2lo | base | 41.35 | 0.21 | +41.14 | +484.6 % | +367.1 % | **FAIL** |
| OPA365_Rab1pct_C1lo_C2hi | base | 103.18 | 0.21 | +102.97 | +1203.6 % | +909.5 % | **FAIL** |
| OPA365_Rab1pct_idealscope | base | 27.75 | 0.21 | +27.54 | +326.5 % | +247.8 % | **FAIL** |
| idealboth | base | 0.28 | 0.21 | +0.07 | +7.1 % | +6.9 % | PASS |
| idealboth_range5 | base | 0.06 | 0.21 | -0.15 | +3.1 % | +3.5 % | PASS |

## Sampling phase (single phase, worst level, codes; centre of the fold's window = 0.50)

| case | 0.20 | 0.25 | 0.30 | 0.35 | 0.40 | 0.45 | 0.50 | 0.55 | 0.60 | 0.65 | 0.70 | 0.75 | 0.80 | 0.85 | 0.90 | 0.95 | window 0.3-0.7 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base | 49.54 | 12.65 | 3.23 | 0.82 | 0.21 | 0.05 | 0.01 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 6.14 | 274.00 | 3.23 |
| OPA354_Ca20_nom | 103.76 | 52.87 | 37.17 | 30.88 | 27.16 | 24.28 | 21.81 | 19.62 | 17.66 | 15.90 | 14.32 | 12.91 | 11.64 | 10.50 | 34.52 | 355.73 | 37.24 |
| OPA354_Ca24_nom | 41.32 | 46.36 | 49.79 | 47.96 | 44.04 | 39.95 | 36.12 | 32.62 | 29.46 | 26.59 | 24.00 | 21.66 | 19.55 | 17.64 | 33.90 | 362.69 | 49.85 |
| OPA365_Ca20_nom | 156.34 | 100.49 | 81.84 | 74.75 | 70.96 | 68.17 | 65.81 | 63.70 | 61.79 | 60.06 | 58.50 | 57.08 | 55.80 | 54.63 | 80.85 | 367.04 | 83.25 |
| OPA365_Ca24_nom | 83.36 | 71.24 | 68.85 | 66.02 | 63.33 | 60.86 | 58.62 | 56.59 | 54.74 | 53.06 | 51.54 | 50.14 | 48.87 | 47.71 | 81.16 | 375.37 | 68.85 |
| OPA354_Rab1pct_nom | 105.80 | 54.96 | 39.33 | 33.05 | 29.32 | 26.41 | 23.89 | 21.64 | 19.61 | 17.78 | 16.12 | 14.63 | 13.27 | 12.05 | 35.80 | 355.96 | 39.39 |
| OPA365_Rab1pct_nom | 158.23 | 102.42 | 83.81 | 76.76 | 72.95 | 70.14 | 67.73 | 65.57 | 63.60 | 61.81 | 60.18 | 58.68 | 57.32 | 56.08 | 81.89 | 366.77 | 85.23 |

## Each stage alone, compensation swept (the other stage ideal)

| run | band, worst level (codes) | AFE-added ISI (against base) | boundary (ns) |
|---|---|---|---|
| sw_awg_Ca16 | 99.69 | +99.48 | 82 |
| sw_awg_Ca18 | 62.44 | +62.23 | 81 |
| sw_awg_Ca20 | 25.62 | +25.41 | 79 |
| sw_awg_Ca22 | 10.73 | +10.52 | 79 |
| sw_awg_Ca24 | 46.00 | +45.79 | 78 |
| sw_awg_Ca26 | 80.16 | +79.95 | 78 |
| sw_awg_Ca28 | 113.13 | +112.92 | 77 |
| sw_awg_Ca30 | 144.90 | +144.69 | 77 |
| sw_awg1pct_Ca16 | 106.24 | +106.03 | 82 |
| sw_awg1pct_Ca18 | 66.64 | +66.43 | 81 |
| sw_awg1pct_Ca20 | 27.75 | +27.54 | 79 |
| sw_awg1pct_Ca22 | 10.33 | +10.12 | 79 |
| sw_awg1pct_Ca24 | 47.14 | +46.93 | 78 |
| sw_awg1pct_Ca26 | 82.64 | +82.43 | 78 |
| sw_awg1pct_Ca28 | 116.79 | +116.58 | 77 |
| sw_awg1pct_Ca30 | 149.59 | +149.38 | 77 |
| sw_awg_Ca20_Cpar0.5 | 5.97 | +5.76 | 79 |
| sw_awg_Ca24_Cpar0.5 | 66.09 | +65.88 | 78 |
| sw_awg_Ca20_Cpar3.5 | 64.31 | +64.10 | 80 |
| sw_awg_Ca24_Cpar3.5 | 6.89 | +6.68 | 79 |
| sw_scope_OPA354_C2_31 | 110.61 | +110.40 | 83 |
| sw_scope_OPA354_C2_33 | 76.23 | +76.02 | 83 |
| sw_scope_OPA354_C2_35 | 46.22 | +46.01 | 83 |
| sw_scope_OPA354_C2_37 | 20.46 | +20.25 | 83 |
| sw_scope_OPA354_C2_39 | 2.06 | +1.85 | 83 |
| sw_scope_OPA354_C2_41 | 21.64 | +21.43 | 83 |
| sw_scope_OPA354_C2_43 | 38.78 | +38.57 | 83 |
| sw_scope_OPA365_C2_31 | 28.78 | +28.57 | 94 |
| sw_scope_OPA365_C2_33 | 5.46 | +5.25 | 94 |
| sw_scope_OPA365_C2_35 | 15.31 | +15.10 | 94 |
| sw_scope_OPA365_C2_37 | 33.23 | +33.02 | 94 |
| sw_scope_OPA365_C2_39 | 48.93 | +48.72 | 94 |
| sw_scope_OPA365_C2_41 | 62.72 | +62.50 | 94 |
| sw_scope_OPA365_C2_43 | 74.82 | +74.61 | 94 |

## Guard, positive control, switched S/H

- guard_pass: band 0.28 codes, AFE-added +0.07, growth at 8.6 +7.1 % -> PASS
- guard_slowawg: band 255.41 codes, AFE-added +255.20, growth at 8.6 +2973.6 % -> FAIL
- guard_slowawg_real: band 450.77 codes, AFE-added +450.56, growth at 8.6 +5245.3 % -> FAIL
- sw_cont: band 71.62 codes, AFE-added +71.41, growth at 8.6 +836.6 % -> FAIL
- metric positive control (baseline waveform + a known fraction of the previous symbol): inject 0: 0.21 codes (expected 0.21), inject 0.002: 2.75 codes (expected 2.75), inject 0.01: 12.89 codes (expected 12.89)
- switched S/H against the continuous one, same instants (317 samples): max 0.010 codes, rms 0.002
