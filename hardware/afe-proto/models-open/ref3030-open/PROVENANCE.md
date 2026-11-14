# ref3030.lib provenance

Licence: CC BY-SA 4.0 (LICENSE). Clean-room model: built only from FACTS.md (datasheet facts); no vendor SPICE model was consulted, and none was in the implementer's context.

## Inputs
- FACTS.md, sha256 `ee28bc73ddf7dd8381761c038aed2039ff1d319cd5a5b8ba35b381ff01254d21` (REF3030E, datasheet SBVS032K).
- The brief: a `.subckt REF3030E_OPEN IN OUT GND` with output voltage and initial accuracy (parameter), line and load regulation (typ default, max as parameter), dropout, short-circuit limit, quiescent current from IN, output impedance vs frequency per Fig 6-14 with a scale parameter, optional noise (off by default); the board's use is a 1.9 kHz current disturbance at OUT.
- Date: 2026-11-13.

## Parameters and their FACTS rows
| parameter | value | FACTS row |
|---|---|---|
| VNOM | 3.0 V | s2 Output voltage, typ |
| ACC | 0 % (limits +/-0.1) | s2 Initial accuracy |
| LINE | 16 uV/V (max 240) | s2 Line regulation, VOUT+300 mV <= VIN <= 5.75 V; referred to VIN = 3.3 V |
| LSRC | 3 ppm/mA (max 15) | s3 Load regulation, source, VIN = VOUT+500 mV |
| LSNK | 3 ppm/mA (max 150) | s3 Load regulation, sink |
| VDO | 20 mV (max 200) | s3 Dropout voltage |
| ISC | 35 mA | s3 Short-circuit current |
| IQ | 27 uA | s3 Quiescent current, 25 degC (Fig 6-9 reads 27.6 uA on the 5 V part) |
| Zout network | L1 30.291 mH \|\| (46.655 Ohm + 9.2855 mH) \|\| 2.8561 uF | s7 Fig 6-14, "5 V, open" points, least-squares fitted to the +/-5 Ohm reading tolerance |
| noise | 51 uVrms 10 Hz - 10 kHz | s2 Output voltage noise; shape from s7 Fig 6-13 |

## Behaviour
- OUT = soft-min(3.000 V x (1+ACC) + LINE x (VIN - 3.3 V), VIN - VDO), floored at 0, minus I_out x R_load-reg (R = ppm/mA x 3 V, separate source and sink values), minus a 100 kOhm current-limit term above ISC (sourcing) or ISNK (sinking), behind the Zout network.
- IN supplies IQ plus the sourced current. The sunk current returns through GND.
- 1 A of AC current at OUT with no external capacitor reads |Z| of the network directly; at 1.9 kHz the model gives about 40 Ohm, the curve interpolates to 39.6 Ohm.
- The network is the 5 V-part, open-output curve. FACTS: Fig 6-14 was taken on 1.25 V and 5 V parts, not on a 3.0 V part, and CIN/COUT are not stated. The 5 V curve is the higher of the two at 1.9 kHz (about 40 Ohm against about 33 Ohm for 1.25 V), so it is the conservative default for a disturbance check. The `ZS` parameter multiplies every impedance of the network (L and R by ZS, C by 1/ZS) so a 3.0 V part can be placed between the curves (roughly ZS 0.75-1.0, not established: *(check)*). An external COUT on OUT adds in parallel to the network and is not included in the fit.
- Not modelled: temperature, long-term stability, hysteresis, turn-on, reverse current with VIN < VOUT, load transients.

## Modelling choices not in the datasheet
| choice | value | why needed | bench test that would pin it |
|---|---|---|---|
| Zout network topology and element values | as above | FACTS gives points only. Fit rms error is under one reading tolerance except at 3 kHz (model 21 Ohm against 12 Ohm), which passes only through the +/-0.1 decade x tolerance | Network analyser or injection sweep at OUT of the REF3030E with the board's COUT, 10 Hz-100 kHz |
| Zout default = 5 V open curve | ZS = 1 | conservative for the 1.9 kHz check | same, on the 3.0 V part |
| Zout independent of load | none | FACTS shows the peak moves with load (1 kOhm: 2 kHz and 4 kHz) but only for 5 V and 1.25 V parts; not modelled | same, with a load |
| 1 uOhm series in the L1 branch, 1 mOhm ESR on the C branch | tiny | keep ngspice's branches well-posed | none |
| DC load regulation as a separate current-dependent drop | R = ppm/mA x VNOM | the Zout curve reads 0-3 Ohm below 10 Hz at +/-3 Ohm; FACTS load regulation says 9 mOhm. DC follows the table; the network's L branch carries DC with 1 uOhm | precision load step at 10 mA |
| Sinking limit ISNK | 35 mA (same as ISC) | FACTS gives no sink limit (Gaps) and the output must not sink without bound | force OUT above VOUT, read the current |
| Dropout independent of load | 20 mV constant | FACTS has no load condition for the 20 mV row and Fig 6-11 is a 5 V part | dropout vs load on the 3.0 V part |
| Line regulation referred to VIN = VOUT + 0.3 V, linear | 16 uV/V | the spec condition | none |
| Current-limit softness | 100 kOhm slope above ISC, 0.5 uA knee | convergence; the output is 30 uA above 35 mA at a hard short | foldback behaviour, VIN dependence of ISC (FACTS Gaps) |
| Soft-min knee 0.1 mV | | convergence; shifts VOUT by under 0.01 uV at regulation | none |
| Noise shape: white 3 uV/rtHz through H = lag(127.49 Hz zero, 34.076 Hz pole) x 2nd-order low-pass (1117.9 Hz, Q 0.9476) - 0.5318 x (1-pole 2559.6 Hz)^2 | | least-squares fit to the 16 Fig 6-13 points (a 5 V part); not rescaled to the REF3030E, so the 10 Hz-10 kHz band reads 53.2 uVrms against FACTS 51 (+4 %). Transient noise only (and its density is read off the AC magnitude); NOISE=0 by default | spectrum analyser on the 3.0 V part |
| 1/f noise (0.1-10 Hz, 24 uVpp) | not modelled; the white part alone gives about 3 uVrms there, which is of the order | ngspice's 1/f generator is not usable here | long record on the 3.0 V part |
| Noise sample step NT | 2 us | the white source's density is set against it; bandwidth 250 kHz | none |

## FACTS figures not matched
- Fig 6-14, 5 V open: within +/-5 Ohm / +/-0.1 decade at all 12 points, but 3 kHz (12 Ohm) reads 21 Ohm at the model's 3 kHz (match only at about 2.4 kHz), 10 Hz reads 1.9 (3), 30 Hz 5.7 (8), 10 kHz 5.6 (4), 100 kHz 0.6 (2), 1 MHz 0.1 (1). The "spike near 2 Hz" artefact is not modelled. The 1 kOhm-load, 1.25 V and 100 kOhm curves are not reproduced (ZS only scales).
- Fig 6-13 density (reading accuracy +/-40 nV/rtHz): 14 of 16 points are within it and tested. Two are not, and are strict xfails in the test: 60 Hz reads 994 against 1050 and 5 kHz reads 302 against 250. The in-band rms is 53.2 uV against FACTS 51 (tested at +/-20 %).
- 0.1-10 Hz noise 24 uVpp: not modelled.
- Fig 6-9 IQ vs temperature, Fig 6-11 dropout vs load and temperature, Figs 6-4 to 6-8, thermal, transients (6-17 to 6-20), PSRR (Fig 6-16): not modelled (no temperature or PSRR path in this model).
