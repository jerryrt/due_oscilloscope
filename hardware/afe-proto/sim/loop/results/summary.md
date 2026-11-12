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

## Three SM-5 readings (growth at a band of 8.6 codes; F = over 10 %)

codes: docs/afe.md arithmetic, floor fixed in codes. codes, DAC floor: the 0.64 mV floor is DAC0's own white noise and is amplified by the loop gain. normalised: the same floor, the band divided by the level spacing (input-referred). Loop gain = loop spacing / baseline spacing.

| run | ISI (codes) | loop gain | codes | codes, DAC floor | normalised |
|---|---|---|---|---|---|
| OPA365_Ca20_nom | +71.41 | 1.159 | +836.6 % F | +851.7 % F | +721.0 % F |
| OPA354_Ca20_nom | +26.96 | 1.277 | +319.8 % F | +346.1 % F | +249.5 % F |
| OPA365_idealawg | +48.72 | 1.174 | +572.8 % F | +589.3 % F | +487.2 % F |
| OPA354_idealawg | +1.85 | 1.293 | +27.8 % F | +55.7 % F | +20.4 % F |
| idealboth | +0.07 | 1.299 | +7.1 % | +35.6 % F | +4.4 % |
| OPA365_Ca20_range5 | +14.83 | 0.244 | +177.3 % F | +112.2 % F | +770.8 % F |
| OPA354_Ca20_range5 | +5.52 | 0.268 | +69.0 % F | +5.5 % | +293.1 % F |

## Follow-up 1: AWG with no Ca and no Cb

### AWG rows (stage alone, sim/awg's loads; first row validates this copy against sim/awg revision 5)

| case | BW hi-Z | BW 50 ohm | BW 1 m open (far end) | gain 8 MHz / DC, hi-Z | DAC Rout 1 k: gain, BW | AW-4 overshoot (limit 5 %) | settle 1 % | AW-6 (limit 100 uV) |
|---|---|---|---|---|---|---|---|---|
| final_Ca20Cb12_Cpar1.5 | 31.6 MHz | 17.8 MHz | 23.7 MHz | 0.951 | 1.112, 14.1 MHz | 0.75 % | 340 ns | 79.4 uV |
| nocap_Rab_cur_Cpar0.5 | 3.5 MHz | 3.5 MHz | 3.5 MHz | 0.387 | 1.112, 3.3 MHz | 0.01 % | 250 ns |  |
| nocap_Rab_cur_Cpar1.5 | 3.0 MHz | 3.0 MHz | 3.2 MHz | 0.342 | 1.112, 3.0 MHz | 0.00 % | 283 ns | 91.5 uV |
| nocap_Rab_cur_Cpar3.5 | 2.4 MHz | 2.4 MHz | 2.5 MHz | 0.276 | 1.112, 2.4 MHz | 0.00 % | 350 ns |  |
| nocap_Rab_1pct_Cpar0.5 | 3.3 MHz | 3.2 MHz | 3.3 MHz | 0.364 | 1.115, 3.2 MHz | 0.00 % | 266 ns |  |
| nocap_Rab_1pct_Cpar1.5 | 2.8 MHz | 2.8 MHz | 3.0 MHz | 0.321 | 1.115, 2.8 MHz | 0.00 % | 302 ns | 91.6 uV |
| nocap_Rab_1pct_Cpar3.5 | 2.2 MHz | 2.2 MHz | 2.2 MHz | 0.258 | 1.115, 2.2 MHz | 0.00 % | 373 ns |  |
| guard_bw_Cf100p | 2.5 MHz | 2.5 MHz | 2.5 MHz | 0.219 | 1.112, 2.5 MHz | 0.00 % | 315 ns |  |
| guard_ov_Ca33Cb22_Cpar0.5 | 35.5 MHz | 20.0 MHz | 25.1 MHz | 1.008 | 1.112, 11.2 MHz | 5.72 % | 313 ns |  |
| guard_nz_Rx40 | 13.3 MHz | 8.9 MHz | 11.2 MHz | 3.112 | 1.114, 12.6 MHz | 99.04 % | 1000 ns | 311.3 uV |

### Loop ISI with the no-cap AWG (+/-1.25 V)

| run | ISI (codes) | loop gain | codes | codes, DAC floor | normalised |
|---|---|---|---|---|---|
| nc_Rab_cur_Cpar0.5_idealscope | +13.25 | 1.297 | +160.4 % F | +188.6 % F | +122.6 % F |
| nc_Rab_cur_Cpar0.5_OPA354 | +14.30 | 1.290 | +172.5 % F | +200.2 % F | +132.7 % F |
| nc_Rab_cur_Cpar0.5_OPA365 | +60.79 | 1.171 | +713.1 % F | +729.4 % F | +608.1 % F |
| nc_Rab_cur_Cpar1.5_idealscope | +21.89 | 1.294 | +260.7 % F | +288.8 % F | +200.4 % F |
| nc_Rab_cur_Cpar1.5_OPA354 | +23.22 | 1.288 | +276.2 % F | +303.7 % F | +213.4 % F |
| nc_Rab_cur_Cpar1.5_OPA365 | +69.10 | 1.169 | +809.8 % F | +825.8 % F | +691.8 % F |
| nc_Rab_cur_Cpar3.5_idealscope | +45.87 | 1.287 | +539.6 % F | +567.0 % F | +418.1 % F |
| nc_Rab_cur_Cpar3.5_OPA354 | +47.58 | 1.281 | +559.5 % F | +586.2 % F | +435.8 % F |
| nc_Rab_cur_Cpar3.5_OPA365 | +91.00 | 1.163 | +1064.4 % F | +1079.8 % F | +914.8 % F |
| nc_Rab_1pct_Cpar0.5_idealscope | +17.10 | 1.297 | +205.1 % F | +233.4 % F | +157.1 % F |
| nc_Rab_1pct_Cpar0.5_OPA354 | +18.38 | 1.291 | +220.0 % F | +247.7 % F | +169.4 % F |
| nc_Rab_1pct_Cpar0.5_OPA365 | +64.67 | 1.172 | +758.2 % F | +774.4 % F | +646.4 % F |
| nc_Rab_1pct_Cpar1.5_idealscope | +27.92 | 1.294 | +330.9 % F | +358.9 % F | +254.6 % F |
| nc_Rab_1pct_Cpar1.5_OPA354 | +28.98 | 1.288 | +343.2 % F | +370.7 % F | +265.5 % F |
| nc_Rab_1pct_Cpar1.5_OPA365 | +74.48 | 1.169 | +872.2 % F | +888.3 % F | +745.4 % F |
| nc_Rab_1pct_Cpar3.5_idealscope | +55.76 | 1.285 | +654.6 % F | +681.8 % F | +508.4 % F |
| nc_Rab_1pct_Cpar3.5_OPA354 | +57.68 | 1.279 | +676.9 % F | +703.4 % F | +528.4 % F |
| nc_Rab_1pct_Cpar3.5_OPA365 | +100.20 | 1.160 | +1171.3 % F | +1186.5 % F | +1008.6 % F |

Host frequency-response correction of the scope shelf was tried and dropped: the owner holds SM-5 on the raw signal (2026-11-11).


# Scope-divider routes (R1 = R3 = 760k; AWG ideal so the scope's share is alone)

**Allowance (SM-5 normalised, raw signal).** The 0.64 mV floor is DAC0's and scales with the loop gain G like the levels, so k = sqrt((0.64 G)^2 + 0.2^2 + (0.1 x 1.1265)^2) / (0.64 G); at G = 1.293: k = 1.0378 (+3.78 %), leaving (10 % - 3.78 %) x 8.6 = **0.535 codes normalised = 0.69 codes at the pin** (at 11.4: 0.92 at the pin). This budget is shared by the AWG and the scope.

Guard on the reading: the baseline scaled by 1.3 (a pure gain) reads +0.000 codes normalised; the codes reading would read +0.06.

## C2 nulls

| op-amp | C2 sweep (pF): ISI at the pin | null C2 | slope (codes per pF) | C2 accuracy needed for the whole allowance |
|---|---|---|---|---|
| OPA354 | 37: 17.2, 37.5: 11.3, 38: 5.7, 38.5: 0.3, 39: 4.9, 39.5: 10.1, 40: 15.0, 40.5: 19.8, 41: 24.5 | 38.50 pF | -11.3 / +9.9 | +/-65 fF |
| OPA365 | 31: 25.5, 31.5: 19.4, 32: 13.5, 32.5: 7.7, 33: 2.2, 33.5: 3.1, 34: 8.3, 34.5: 13.3, 35: 18.2, 35.5: 22.9 | 33.06 pF | -11.4 / +7.7 | +/-72 fF |

null_fit self-check: synthetic V with its null at 34.30 pF and slope 12 reads 34.43 pF, slope 10.56.

## (c2) Tighter capacitors at the null (C1 and C2 at opposite ends of the tolerance)

| run | ISI at the pin (codes) | ISI normalised (baseline codes) | allowance at the pin | growth (normalised) | SM-5 | note |
|---|---|---|---|---|---|---|
| rc2_OPA354_null | +0.21 | +0.16 | 0.71 | +5.6 % | PASS | C2 at the null 38.50 pF |
| rc2_OPA354_t1_C1hi | +8.58 | +6.47 | 0.73 | +78.9 % | **FAIL** | +/-1 % |
| rc2_OPA354_t1_C1lo | +7.87 | +6.12 | 0.68 | +74.9 % | **FAIL** | +/-1 % |
| rc2_OPA354_t2_C1hi | +17.14 | +12.75 | 0.75 | +151.7 % | **FAIL** | +/-2 % |
| rc2_OPA354_t2_C1lo | +16.05 | +12.67 | 0.66 | +151.2 % | **FAIL** | +/-2 % |
| rc2_OPA354_t5_C1hi | +44.03 | +31.34 | 0.82 | +367.6 % | **FAIL** | +/-5 % |
| rc2_OPA354_t5_C1lo | +39.73 | +32.82 | 0.59 | +385.9 % | **FAIL** | +/-5 % |
| rc2_OPA354_c0gdrift_a | +0.71 | +0.54 | 0.71 | +10.0 % | PASS | C0G +/-30 ppm/K x 20 K, opposite on C1/C2, from an exact null |
| rc2_OPA354_c0gdrift_b | +0.05 | +0.03 | 0.71 | +4.1 % | PASS | C0G +/-30 ppm/K x 20 K, opposite on C1/C2, from an exact null |
| rc2_OPA365_null | +1.50 | +1.14 | 0.71 | +17.0 % | **FAIL** | C2 at the null 33.06 pF |
| rc2_OPA365_t1_C1hi | +9.32 | +7.03 | 0.73 | +85.3 % | **FAIL** | +/-1 % |
| rc2_OPA365_t1_C1lo | +6.08 | +4.71 | 0.69 | +58.6 % | **FAIL** | +/-1 % |
| rc2_OPA365_t2_C1hi | +17.28 | +12.85 | 0.75 | +152.9 % | **FAIL** | +/-2 % |
| rc2_OPA365_t2_C1lo | +13.76 | +10.82 | 0.67 | +129.7 % | **FAIL** | +/-2 % |
| rc2_OPA365_t5_C1hi | +41.93 | +29.94 | 0.82 | +351.3 % | **FAIL** | +/-5 % |
| rc2_OPA365_t5_C1lo | +36.18 | +29.67 | 0.60 | +349.3 % | **FAIL** | +/-5 % |
| rc2_OPA365_c0gdrift_a | +1.96 | +1.50 | 0.71 | +21.1 % | **FAIL** | C0G +/-30 ppm/K x 20 K, opposite on C1/C2, from an exact null |
| rc2_OPA365_c0gdrift_b | +1.03 | +0.79 | 0.71 | +12.9 % | **FAIL** | C0G +/-30 ppm/K x 20 K, opposite on C1/C2, from an exact null |

## (c) Uncompensated divider, R scaled (0.1 pF across R1, 2 pF at N, strays *(check)*)

| op-amp | scale | R1 / R2 / R3 | Thevenin at N | input resistance | SM-3 bandwidth | ISI at the pin | ISI normalised | SM-3 | SM-5 |
|---|---|---|---|---|---|---|---|---|---|
| OPA354 | 1 | 760k / 335k / 760k | 178 k | 992.5 k | 0.33 MHz | +826.50 | +1111.19 | **FAIL** | **FAIL** |
| OPA354 | 0.3 | 228k / 100.5k / 228k | 53.4 k | 297.8 k | 1.10 MHz | +246.68 | +206.82 | **FAIL** | **FAIL** |
| OPA354 | 0.1 | 76k / 33.5k / 76k | 17.8 k | 99.25 k | 3.20 MHz | +16.33 | +12.55 | **FAIL** | **FAIL** |
| OPA354 | 0.05 | 38k / 16.75k / 38k | 8.9 k | 49.63 k | 5.85 MHz | +1.01 | +0.77 | **FAIL** | **FAIL** |
| OPA354 | 0.04 | 30.4k / 13.4k / 30.4k | 7.12 k | 39.7 k | 6.93 MHz | +0.46 | +0.35 | **FAIL** | PASS |
| OPA354 | 0.03 | 22.8k / 10.05k / 22.8k | 5.34 k | 29.78 k | 8.42 MHz | +0.29 | +0.22 | PASS | PASS |
| OPA354 | 0.02 | 15.2k / 6.7k / 15.2k | 3.56 k | 19.85 k | 10.56 MHz | +0.30 | +0.23 | PASS | PASS |
| OPA354 | 0.01 | 7.6k / 3.35k / 7.6k | 1.78 k | 9.925 k | 13.70 MHz | +0.55 | +0.43 | PASS | PASS |
| OPA354 | 0.007 | 5.32k / 2.345k / 5.32k | 1.25 k | 6.948 k | 14.78 MHz | +0.78 | +0.60 | PASS | **FAIL** |
| OPA354 | 0.005 | 3.8k / 1.675k / 3.8k | 0.89 k | 4.963 k | 15.42 MHz | +1.10 | +0.85 | PASS | **FAIL** |
| OPA354 | 0.003 | 2.28k / 1.005k / 2.28k | 0.534 k | 2.978 k | 15.91 MHz | +1.88 | +1.47 | PASS | **FAIL** |
| OPA354 | 0.001 | 0.76k / 0.335k / 0.76k | 0.178 k | 0.9925 k | 16.10 MHz | +5.59 | +4.50 | PASS | **FAIL** |
| OPA365 | 1 | 760k / 335k / 760k | 178 k | 992.5 k | 0.11 MHz | +1152.20 | +3502.57 | **FAIL** | **FAIL** |
| OPA365 | 0.3 | 228k / 100.5k / 228k | 53.4 k | 297.8 k | 0.37 MHz | +774.21 | +976.56 | **FAIL** | **FAIL** |
| OPA365 | 0.1 | 76k / 33.5k / 76k | 17.8 k | 99.25 k | 1.07 MHz | +247.04 | +207.17 | **FAIL** | **FAIL** |
| OPA365 | 0.05 | 38k / 16.75k / 38k | 8.9 k | 49.63 k | 2.03 MHz | +62.03 | +48.23 | **FAIL** | **FAIL** |
| OPA365 | 0.04 | 30.4k / 13.4k / 30.4k | 7.12 k | 39.7 k | 2.46 MHz | +34.09 | +26.32 | **FAIL** | **FAIL** |
| OPA365 | 0.03 | 22.8k / 10.05k / 22.8k | 5.34 k | 29.78 k | 3.09 MHz | +14.30 | +11.00 | **FAIL** | **FAIL** |
| OPA365 | 0.02 | 15.2k / 6.7k / 15.2k | 3.56 k | 19.85 k | 4.10 MHz | +3.59 | +2.76 | **FAIL** | **FAIL** |
| OPA365 | 0.01 | 7.6k / 3.35k / 7.6k | 1.78 k | 9.925 k | 5.87 MHz | +0.77 | +0.60 | **FAIL** | **FAIL** |
| OPA365 | 0.007 | 5.32k / 2.345k / 5.32k | 1.25 k | 6.948 k | 6.64 MHz | +0.85 | +0.65 | **FAIL** | **FAIL** |
| OPA365 | 0.005 | 3.8k / 1.675k / 3.8k | 0.89 k | 4.963 k | 7.23 MHz | +1.11 | +0.86 | PASS | **FAIL** |
| OPA365 | 0.003 | 2.28k / 1.005k / 2.28k | 0.534 k | 2.978 k | 7.84 MHz | +1.87 | +1.46 | PASS | **FAIL** |
| OPA365 | 0.001 | 0.76k / 0.335k / 0.76k | 0.178 k | 0.9925 k | 8.42 MHz | +5.58 | +4.50 | PASS | **FAIL** |

## (c) Compensated divider at 1 M, 100 k and 10 k, C0G +/-5 % (C2 part rescaled so the nominal is the null)

| op-amp | input resistance | SM-3 bandwidth | ISI nominal | ISI C1 +5 % / C2 -5 % | ISI C1 -5 % / C2 +5 % | worst SM-5 |
|---|---|---|---|---|---|---|
| OPA354 | 992.5 k | 15.94 MHz | +0.21 | +44.03 | +39.73 | **FAIL** |
| OPA354 | 99.25 k | 13.53 MHz | +0.10 | +43.91 | +40.35 | **FAIL** |
| OPA354 | 9.925 k | 3.31 MHz | +14.32 | +41.70 | +51.58 | **FAIL** |
| OPA365 | 992.5 k | 8.69 MHz | +1.50 | +41.93 | +36.18 | **FAIL** |
| OPA365 | 99.25 k | 8.16 MHz | +0.14 | +43.62 | +39.99 | **FAIL** |
| OPA365 | 9.925 k | 3.08 MHz | +15.23 | +41.62 | +52.34 | **FAIL** |

## (b) Varactor trim (assumed abrupt junction, VJ 0.7 V, M 0.5, 400 ppm/K, Cblk 220 pF C0G, set at Vb 1.5 V where Cv = 20 pF) *(check)*

Cv(1.5 V) = 20 pF, Ceff = Cblk series Cv = 18.33 pF, CJO = 35.46 pF; the C2 part is the null minus Ceff.

| run | ISI at the pin (codes) | ISI normalised (baseline codes) | allowance at the pin | growth (normalised) | SM-5 | note |
|---|---|---|---|---|---|---|
| rideal_OPA354_lin | +0.21 | +0.16 | 0.71 | +5.6 % | PASS | linear trim of the same Ceff (reference: should equal the null) |
| rvar_OPA354_Rb1M | +96.56 | +74.17 | 0.70 | +866.2 % | **FAIL** | varactor, bias resistor 1 Mohm (signal dependence included) |
| rvar_OPA354_Rb10M | +13.70 | +10.42 | 0.72 | +124.9 % | **FAIL** | varactor, bias resistor 10 Mohm (signal dependence included) |
| rvar_OPA354_Rb100M | +6.20 | +4.71 | 0.72 | +58.4 % | **FAIL** | varactor, bias resistor 100 Mohm (signal dependence included) |
| rvarlin_OPA354_Rb100M | +1.05 | +0.80 | 0.71 | +13.0 % | **FAIL** | the same network, varactor replaced by a linear 20 pF: the bias network alone |
| rvar_OPA354_vartc_hot | +4.76 | +3.63 | 0.72 | +45.9 % | **FAIL** | + varactor tempco 400 ppm/K x 20 K *(check)* |
| rvar_OPA354_c0g_hot | +6.58 | +5.00 | 0.72 | +61.8 % | **FAIL** | + C0G drift of C1/C2, opposite |
| rvar_OPA354_vartc_cold | +7.65 | +5.80 | 0.72 | +71.0 % | **FAIL** | + varactor tempco 400 ppm/K x 20 K *(check)* |
| rvar_OPA354_c0g_cold | +5.82 | +4.42 | 0.72 | +55.1 % | **FAIL** | + C0G drift of C1/C2, opposite |
| rvar_OPA354_range5 | +1.28 | +4.62 | -0.99 | +105.1 % | **FAIL** | +/-5 V range (normalised against the +/-1.25 V baseline gain reading) |
| rideal_OPA354_range5 | +0.04 | +0.16 | -0.99 | +54.0 % | **FAIL** | +/-5 V range, ideal null, no varactor |
| rideal_OPA365_lin | +1.50 | +1.14 | 0.71 | +17.0 % | **FAIL** | linear trim of the same Ceff (reference: should equal the null) |
| rvar_OPA365_Rb1M | +98.10 | +75.19 | 0.71 | +878.0 % | **FAIL** | varactor, bias resistor 1 Mohm (signal dependence included) |
| rvar_OPA365_Rb10M | +15.07 | +11.44 | 0.72 | +136.6 % | **FAIL** | varactor, bias resistor 10 Mohm (signal dependence included) |
| rvar_OPA365_Rb100M | +7.54 | +5.71 | 0.72 | +70.1 % | **FAIL** | varactor, bias resistor 100 Mohm (signal dependence included) |
| rvarlin_OPA365_Rb100M | +2.34 | +1.79 | 0.71 | +24.5 % | **FAIL** | the same network, varactor replaced by a linear 20 pF: the bias network alone |
| rvar_OPA365_vartc_hot | +6.09 | +4.63 | 0.72 | +57.4 % | **FAIL** | + varactor tempco 400 ppm/K x 20 K *(check)* |
| rvar_OPA365_c0g_hot | +7.89 | +5.98 | 0.72 | +73.1 % | **FAIL** | + C0G drift of C1/C2, opposite |
| rvar_OPA365_vartc_cold | +9.00 | +6.81 | 0.73 | +82.8 % | **FAIL** | + varactor tempco 400 ppm/K x 20 K *(check)* |
| rvar_OPA365_c0g_cold | +7.19 | +5.45 | 0.72 | +67.0 % | **FAIL** | + C0G drift of C1/C2, opposite |
| rvar_OPA365_range5 | +1.56 | +5.62 | -0.98 | +116.6 % | **FAIL** | +/-5 V range (normalised against the +/-1.25 V baseline gain reading) |
| rideal_OPA365_range5 | +0.29 | +1.05 | -0.99 | +64.1 % | **FAIL** | +/-5 V range, ideal null, no varactor |

## (e) Internal loopback: DAC0 to node N through the PA-3 switch (3.7 ohm), 270 mV swing, against a 270 mV baseline

| run | ISI at the pin (codes) | ISI normalised (baseline codes) | allowance at the pin | growth (normalised) | SM-5 | note |
|---|---|---|---|---|---|---|
| rloop_OPA354_rout0 | +0.10 | +0.02 | 4.04 | +0.5 % | PASS | DAC Rout 0 |
| rloop_OPA354_rout300 | +0.07 | +0.01 | 4.03 | +0.4 % | PASS | DAC Rout 300 ohm |
| rloop_OPA354_rout1000 | +16.98 | +3.55 | 4.00 | +41.5 % | **FAIL** | DAC Rout 1 kohm |
| rloop_OPA354_C1hi5 | +0.10 | +0.02 | 4.04 | +0.5 % | PASS | C1 +5 % / C2 -5 % |
| rloop_OPA365_rout0 | +0.15 | +0.03 | 4.04 | +0.6 % | PASS | DAC Rout 0 |
| rloop_OPA365_rout300 | +0.11 | +0.02 | 4.03 | +0.5 % | PASS | DAC Rout 300 ohm |
| rloop_OPA365_rout1000 | +17.79 | +3.72 | 4.00 | +43.5 % | **FAIL** | DAC Rout 1 kohm |
| rloop_OPA365_C1hi5 | +0.15 | +0.03 | 4.04 | +0.6 % | PASS | C1 +5 % / C2 -5 % |

# AWG n1 (Ra 16.45k, Rb 18.8k, 1 %, 0.3 pF per node, 11 ohm supply filter)

| case | BW hi-Z | BW 50 ohm | BW 1 m open (far end) | DAC Rout 1 k: gain, BW | AW-4 overshoot (5 %) | settle 1 % | AW-6 (100 uV) |
|---|---|---|---|---|---|---|---|
| n1_Ca20Cb12_Cpar1.5 | 31.6 MHz | 17.8 MHz | 23.7 MHz | 1.108, 13.3 MHz | 0.04 % | 458 ns | 79.4 uV |
| n1_nocap_Cpar0.5 | 2.8 MHz | 2.8 MHz | 3.0 MHz | 1.108, 2.8 MHz | 0.00 % | 298 ns |  |
| n1_Ca20Cb12_Cpar0.5x | 33.5 MHz | 18.8 MHz | 25.1 MHz | 1.108, 15.0 MHz | 3.08 % | 88 ns |  |
| n1_nocap_Cpar1.5 | 2.4 MHz | 2.4 MHz | 2.5 MHz | 1.108, 2.4 MHz | 0.00 % | 353 ns | 91.0 uV |
| n1_Ca20Cb12_Cpar1.5x | 31.6 MHz | 17.8 MHz | 23.7 MHz | 1.108, 13.3 MHz | 0.04 % | 458 ns |  |
| n1_nocap_Cpar3.5 | 1.8 MHz | 1.8 MHz | 1.8 MHz | 1.108, 1.8 MHz | 0.00 % | 461 ns |  |
| n1_Ca20Cb12_Cpar3.5x | 28.2 MHz | 15.0 MHz | 22.4 MHz | 1.108, 10.0 MHz | 0.12 % | 686 ns |  |
| ref_13k7_15k8_Ca20Cb12 | 31.6 MHz | 17.8 MHz | 23.7 MHz | 1.112, 14.1 MHz | 0.75 % | 340 ns | 79.4 uV |

Loop, +/-1.25 V, scope at its C2 null with R1 = R3 = 760k (or the uncompensated 30 k divider), normalised SM-5:

| run | ISI at the pin | ISI normalised | allowance at the pin | growth | SM-5 |
|---|---|---|---|---|---|
| n1L_nocap_Cpar0.5_ideal | +25.91 | +20.20 | 0.68 | +238.7 % | **FAIL** |
| n1L_nocap_Cpar0.5_OPA354 | +26.55 | +20.61 | 0.69 | +243.4 % | **FAIL** |
| n1L_nocap_Cpar0.5_OPA365 | +27.64 | +21.41 | 0.69 | +252.7 % | **FAIL** |
| n1L_nocap_Cpar0.5_OPA354_unc30k | +27.96 | +21.76 | 0.68 | +256.8 % | **FAIL** |
| n1L_Ca20Cb12_Cpar0.5_ideal | +5.21 | +4.05 | 0.68 | +51.0 % | **FAIL** |
| n1L_Ca20Cb12_Cpar0.5_OPA354 | +5.17 | +4.00 | 0.69 | +50.4 % | **FAIL** |
| n1L_Ca20Cb12_Cpar0.5_OPA365 | +5.31 | +4.10 | 0.69 | +51.5 % | **FAIL** |
| n1L_Ca20Cb12_Cpar0.5_OPA354_unc30k | +5.39 | +4.19 | 0.68 | +52.5 % | **FAIL** |
| n1L_nocap_Cpar1.5_ideal | +45.62 | +35.74 | 0.67 | +419.5 % | **FAIL** |
| n1L_nocap_Cpar1.5_OPA354 | +45.98 | +35.85 | 0.68 | +420.7 % | **FAIL** |
| n1L_nocap_Cpar1.5_OPA365 | +47.41 | +36.90 | 0.68 | +432.9 % | **FAIL** |
| n1L_nocap_Cpar1.5_OPA354_unc30k | +47.72 | +37.32 | 0.68 | +437.8 % | **FAIL** |
| n1L_Ca20Cb12_Cpar1.5_ideal | +38.83 | +30.75 | 0.66 | +361.6 % | **FAIL** |
| n1L_Ca20Cb12_Cpar1.5_OPA354 | +38.66 | +30.47 | 0.66 | +358.3 % | **FAIL** |
| n1L_Ca20Cb12_Cpar1.5_OPA365 | +37.81 | +29.73 | 0.67 | +349.7 % | **FAIL** |
| n1L_Ca20Cb12_Cpar1.5_OPA354_unc30k | +39.05 | +30.86 | 0.66 | +362.8 % | **FAIL** |
| n1L_nocap_Cpar3.5_ideal | +96.25 | +76.62 | 0.65 | +894.9 % | **FAIL** |
| n1L_nocap_Cpar3.5_OPA354 | +97.57 | +77.32 | 0.66 | +903.0 % | **FAIL** |
| n1L_nocap_Cpar3.5_OPA365 | +97.98 | +77.49 | 0.66 | +905.0 % | **FAIL** |
| n1L_nocap_Cpar3.5_OPA354_unc30k | +98.92 | +78.62 | 0.65 | +918.1 % | **FAIL** |
| n1L_Ca20Cb12_Cpar3.5_ideal | +104.03 | +85.20 | 0.61 | +995.0 % | **FAIL** |
| n1L_Ca20Cb12_Cpar3.5_OPA354 | +104.13 | +84.89 | 0.61 | +991.2 % | **FAIL** |
| n1L_Ca20Cb12_Cpar3.5_OPA365 | +103.21 | +83.96 | 0.62 | +980.4 % | **FAIL** |
| n1L_Ca20Cb12_Cpar3.5_OPA354_unc30k | +104.53 | +85.44 | 0.61 | +997.7 % | **FAIL** |
| n1L_ref13k7_Cpar1.5_ideal | +25.35 | +19.76 | 0.68 | +233.6 % | **FAIL** |

n1 attenuator, Ca swept (Cb 12 pF, V+ 1.5 pF, scope ideal), ISI at the pin: 18 pF: 81.1, 19 pF: 59.8, 20 pF: 38.8, 21 pF: 18.3, 22 pF: 1.6, 23 pF: 21.4, 24 pF: 40.9, 25 pF: 60.0, 26 pF: 78.6; null 21.96 pF, slope -19.5 / +19.5 codes per pF.


# Inverting AWG (Rin 4 x 4.7k + 680 = 19.48k, Rf (5 x 4.7k) || 330k = 21.94k, G 1.126; Vref' (174k || 174k) + 1k + 680 over 100k, 100 nF)

Phase margin by Middlebrook injection at the op-amp output (first |T| = 1 crossing). The method reads the non-inverting revision-5 stage at 80.9 deg (hi-Z) where sim/awg's loop-break reads about 72: use it to rank, not to the degree *(check)*.

| case | AN-1 PM hi-Z / 50 ohm / 1 m open (>= 45 deg) | BW hi-Z (peaking) | BW 50 ohm | AW-4 overshoot | settle 1 % | AW-6 |
|---|---|---|---|---|---|---|
| val_noninv_final | 80.9 / 108.5 / 93.7 | | | | | |
| inv_Cf0_C0.5 | 5.4 / 38.6 / -13.8 | 11.22 MHz (20.9 dB) | 7.94 MHz | 82.5 % | 1000 ns |  |
| inv_Cf0_C1.5 | -2.9 / 24.9 / -23.2 | 10.00 MHz (26.5 dB) | 7.08 MHz | 19.0 % | 1000 ns | 705 uV |
| inv_Cf0_C3.5 | -14.5 / 4.7 / -34.8 | 8.41 MHz (13.0 dB) | 5.96 MHz | 10.5 % | 1000 ns |  |
| inv_Cf4p_C1.5 | 83.8 / 166.6 / 89.8 | 2.11 MHz (0.0 dB) | 2.24 MHz | 0.0 % | 395 ns |  |
| inv_Cf6p_C1.5 | 85.1 / 162.8 / 98.9 | 1.33 MHz (0.0 dB) | 1.33 MHz | 0.0 % | 602 ns |  |
| inv_Cf10p_C1.5 | 84.0 / 157.2 / 107.5 | 0.75 MHz (0.0 dB) | 0.75 MHz | 0.3 % | 836 ns |  |
| guard_pm_Cn20p | -48.9 / -74.0 / -58.9 | | | | | |
| guard_aw5_Rin3x4k7 | 2.3 / 27.8 / -18.7 | 11.89 MHz (26.8 dB) | 8.91 MHz | 254.9 % | 1000 ns |  |
| guard_aw8_Rf+30pct | -10.7 / 2.4 / -29.9 | 8.41 MHz (15.4 dB) | 7.08 MHz | 0.0 % | 1000 ns |  |

inv_Cf0_C1.5: gain -1.1261, offset at 1.65 V +1.1 mV; DAC for +/-1 V 0.762..2.538 V (window 0.578-2.771 V, 81.0 % of it); AW-1 into 50 ohm, weak rails: -0.5005..0.5005 V, error 0.009 mV; AW-5 97.4 uA; PW-3 24.21 mA; AW-8 worst |out| 2.011 V (DAC0 0 / -0.1 / +0.2 / 3.3 V / floating, Vmid 1.55-1.685, both rail corners)

guard_aw5_Rin3x4k7: gain -1.0482, offset at 1.65 V +61.6 mV; DAC for +/-1 V 0.696..2.604 V (window 0.578-2.771 V, 87.0 % of it); AW-1 into 50 ohm, weak rails: -0.5001..0.5003 V, error 0.009 mV; AW-5 134.5 uA; PW-3 23.75 mA; AW-8 worst |out| 1.934 V (DAC0 0 / -0.1 / +0.2 / 3.3 V / floating, Vmid 1.55-1.685, both rail corners)

guard_aw8_Rf+30pct: gain -1.3632, offset at 1.65 V -182.7 mV; DAC for +/-1 V 0.916..2.384 V (window 0.578-2.771 V, 66.9 % of it); AW-1 into 50 ohm, weak rails: -0.5001..0.5001 V, error 0.007 mV; AW-5 95.4 uA; PW-3 25.62 mA; AW-8 worst |out| 2.247 V (DAC0 0 / -0.1 / +0.2 / 3.3 V / floating, Vmid 1.55-1.685, both rail corners)

| loop run | ISI at the pin | ISI normalised | allowance at the pin | SM-5 |
|---|---|---|---|---|
| invL_Cf0_C0.5_ideal | +1682.0 | +1233.5 | 0.77 | **FAIL** |
| invL_Cf0_C0.5_OPA354 | +1579.3 | +1172.6 | 0.75 | **FAIL** |
| invL_Cf0_C1.5_ideal | +2752.5 | +1962.2 | 0.82 | **FAIL** |
| invL_Cf0_C1.5_OPA354 | +2651.9 | +1726.3 | 0.97 | **FAIL** |
| invL_Cf0_C3.5_ideal | +5286.2 | +5641.5 | 0.24 | **FAIL** |
| invL_Cf0_C3.5_OPA354 | +4099.0 | +5813.7 | -0.13 | **FAIL** |
| invL_Cf4p_C1.5_ideal | +59.5 | +47.5 | 0.64 | **FAIL** |
| invL_Cf6p_C1.5_ideal | +175.2 | +146.3 | 0.58 | **FAIL** |
| guard_invL_slowCf100p | +1066.4 | +4713.6 | -1.51 | **FAIL** |

# Buffered DAC0 + low-impedance attenuator (OPA365 follower; Ra 953, Rb 953 + 249||249 + 22, Rf = Rb, Rg 953, no Rx, no Ca/Cb)

| case | AN-1 AWG stage hi-Z / 50 ohm / 1 m open | AN-1 buffer hi-Z / 50 ohm | BW hi-Z (peak) | BW 50 ohm | AW-4 overshoot | settle 1 % | AW-6 |
|---|---|---|---|---|---|---|---|
| buf_C0.5 | 92.4 / 130.9 / 125.0 | 76.7 / 76.7 | 14.1 MHz (0.00 dB) | 10.0 MHz | 0.63 % | 86 ns |  |
| buf_C1.5 | 91.2 / 130.7 / 120.1 | 76.9 / 76.9 | 15.0 MHz (0.00 dB) | 10.0 MHz | 1.06 % | 98 ns | 82.6 uV |
| buf_C3.5 | 88.9 / 130.2 / 112.5 | 77.2 / 77.2 | 15.8 MHz (0.00 dB) | 10.6 MHz | 2.01 % | 105 ns |  |
| guard_buf_slow_Ra4k7x4 | 91.9 / 131.9 / 118.1 | 69.6 / 69.6 | 2.1 MHz (0.00 dB) | 2.0 MHz | 0.00 % | 411 ns |  |
| guard_buf_noCf | 54.8 / 97.4 / 66.9 | 76.9 / 76.9 | 31.6 MHz (1.17 dB) | 18.8 MHz | 10.01 % | 150 ns | 119.6 uV |
| info_buf_pm_Cbo1n | 91.8 / 131.5 / 120.3 | 79.2 / 79.2 | 0.3 MHz (0.00 dB) | 0.3 MHz | 1.95 % | 1000 ns |  |

buf_C1.5: gain 1.1506, offset at 1.65 V +0.9 mV; DAC for +/-1 V 0.781..2.519 V (79.3 % of the window); 50 ohm, weak rails -0.5000..0.5003 V (error 0.010 mV); AW-5 (buffer input) 3.39 uA; PW-3 20.87 mA; AW-8 worst |out| 1.668 V; buffer output at DAC0 0 / -0.1 / 0.2 / 3.3 V: 0.007 / 0.007 / 0.203 / 2.759 V; +3.3 V_A current added (buffer, DAC0 0.578 / 1.65 / 2.771 V): 4.49 / 5.00 / 5.38 mA

| loop run (+/-1.25 V) | ISI at the pin | ISI normalised | allowance at the pin | SM-5 |
|---|---|---|---|---|
| bufL_C0.5_ideal | +0.05 | +0.04 | 0.70 | PASS |
| bufL_C1.5_ideal | +0.05 | +0.04 | 0.70 | PASS |
| bufL_C3.5_ideal | +0.06 | +0.04 | 0.70 | PASS |
| bufL_C1.5_ideal_rout1k | -0.74 | -0.57 | 0.69 | PASS |
| guard_bufL_slow_Ra4k7x4 | +67.59 | +52.89 | 0.67 | **FAIL** |
| rloopbuf_OPA365_rout1000 | +0.06 | +0.01 | 4.04 | PASS |
| rloopbuf_OPA354_rout1000 | -0.01 | -0.00 | 4.04 | PASS |

# Combined: buffered AWG into sim/scope P_LOWZ (netlib sha 7139d6227d2ab2de), +/-1.25 V, Vmid ideal against powercal's per-channel generator

Generator stand-in |Z|: 11.1 mohm at 1 kHz and 1.158 ohm at 38 kHz against the macromodel's 11.4 mohm and 1.162 ohm; within 2.3 % over 1 kHz-10 MHz.

| run | ISI at the pin | ISI normalised | allowance at the pin | SM-5 |
|---|---|---|---|---|
| cmb_OPA354_vmideal_C0.5 | +10.54 | +8.15 | 0.69 | **FAIL** |
| cmb_OPA354_vmideal_C1.5 | +10.49 | +8.11 | 0.69 | **FAIL** |
| cmb_OPA354_vmideal_C3.5 | +10.37 | +8.02 | 0.69 | **FAIL** |
| cmb_OPA354_vmreal_C0.5 | +10.29 | +7.96 | 0.69 | **FAIL** |
| cmb_OPA354_vmreal_C1.5 | +10.23 | +7.91 | 0.69 | **FAIL** |
| cmb_OPA354_vmreal_C3.5 | +10.11 | +7.82 | 0.69 | **FAIL** |
| cmb_OPA354_vmideal_noCsoff | +0.44 | +0.34 | 0.69 | PASS |
| cmb_OPA354_vmreal_noCsoff | +0.70 | +0.54 | 0.69 | **FAIL** |
| cmb_OPA365_vmideal_C0.5 | +39.97 | +31.10 | 0.68 | **FAIL** |
| cmb_OPA365_vmideal_C1.5 | +39.89 | +31.04 | 0.68 | **FAIL** |
| cmb_OPA365_vmideal_C3.5 | +39.72 | +30.91 | 0.68 | **FAIL** |
| cmb_OPA365_vmreal_C0.5 | +39.59 | +30.81 | 0.68 | **FAIL** |
| cmb_OPA365_vmreal_C1.5 | +39.51 | +30.75 | 0.68 | **FAIL** |
| cmb_OPA365_vmreal_C3.5 | +39.35 | +30.62 | 0.68 | **FAIL** |
| cmb_OPA365_vmideal_noCsoff | +8.45 | +6.54 | 0.69 | **FAIL** |
| cmb_OPA365_vmreal_noCsoff | +8.19 | +6.34 | 0.69 | **FAIL** |
| guard_cmb_OPA365_vmreal_noC10u_noCsoff | +10.62 | +8.22 | 0.69 | **FAIL** |

# AWG Vmid follower stand-in (330k/330k tap, 12 pF, bare OPA365 follower)

Macromodel |Zout|: 2.17 mohm at 100 Hz, 2.44 mohm at 1 kHz, 1.143 ohm at 1 MHz, 11.38 ohm at 10 MHz. P8-k unchanged: |Zout| within 6.0 %, tap step (100 mV on the divider top, 50 mV at the tap) within 14.8 % of the step: not used. In use: A0 90.0 dB, GBW 59.2 MHz, Rout 68 ohm, input capacitance 6 pF: |Zout| within 2.3 % from 100 Hz to 10 MHz, step within 0.02 %.
