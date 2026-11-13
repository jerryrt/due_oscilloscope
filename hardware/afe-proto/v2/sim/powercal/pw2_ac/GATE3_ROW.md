# Gate-3 evidence row: LR-5 cap-distance deviation (PW-2 / PW-4), by AC analysis

**Ready to paste. No PW-4 pass is claimed.**

**What was computed.** TI's LM27762 transient model rejects any series inductance on its capacitors (15 attempts, 'Timestep too small'), so the
cap-distance effect was computed by AC (line-spectrum) analysis: the ideal transient (pure-C capacitors, the harness's own circuit, VIN 5.25 V)
was run once, its ripple over the last 100 us decomposed into lines, and each rail's network applied line by line: ESR(f) (Samsung esr.csv),
ESL 0.373 nH, the mounting loop L_i of every capacitor, in parallel across the bank. The model's pump is a PFM burst generator (2.13 MHz inside
bursts, ~85 kHz burst rate), and the ripple is 99.6 % burst-rate sawtooth: a Fourier series at one pump frequency does not describe it.
The AC step reproduces the transient's own ripple to 5e-5 (pk-pk 19.6 mV VIN, 0.131 mV OUT+, 0.044 mV OUT-), which is nearly a tautology
(it checks the pipeline, not the physics). `hardware/afe-proto/v2/sim/powercal/pw2_ac/`, results in `results/pw2_ac_results.json`.

**As-built distances (mm, pad to pin).** C409 1.77, C405 2.33, C406 7.64, C407 5.59, C408 8.42, C403 4.24, C404 7.59, C401 8.55, C402 5.95
(the earlier table, not re-measured). Pin-link widths 0.3 mm (C405/C406/C401/C402) and 0.2 mm (C403/C404/C407/C408).

**PW-2 nodes (OUT+ +3V3A, OUT- VNEG): the model cannot resolve the question.** As-built worst of 1.7-2.3 MHz: 0.138 mV and 0.049 mV pk-pk
(ideal 0.132 / 0.044; L x2 0.144 / 0.060; +100 nH on C407 control 0.072 on OUT-, the model does respond). The model injects 0.3 mA (burst
band) and 0.02 mA (pump band) into OUT+ and has no LDO loop (it under-reads the datasheet), so these rails are insensitive to L by
construction. The real chain's behaviour is VT-8's measurement.

**VIN in the PW-4 band (5 V rail's own ripple; PW-4's 0.3 mV rms is on the Due 3.3 V pin and AREF and is NOT judged here).** DC-1 MHz: ideal
5.74 mV rms / 18.85 mV pk-pk, as-built 5.70 / 18.04 (as-built 0.9 % / 4.3 % lower), L x0.5 and x2 5.72 / 5.65 rms: in band, ideal and as-built are
equal to within a few per cent; the loop L acts above 1 MHz. How ~20 mV of in-band 5 V ripple reaches the Due 3.3 V and AREF through the
Due's regulator is a property of the pump itself (the ideal layout included) and is VT-8's.

**Unvalidated 10-30 MHz VIN content.** It is the model's switch-edge current and depends on the band limit. VIN pk-pk, ideal / as-built, at
5, 10, 20, 30, 40, 83 MHz: 19.4/23.6, 19.7/32.4, 21.0/72.0, 23.3/125.0, 26.3/197.7, 64.4/598.2 mV (lines above 30 MHz are dropped in the
headline figures: the current there is not stable against the resampling grid). In 10-30 MHz alone: ideal 0.64 rms / 6.6 pk-pk, as-built 10.7 / 115.9 mV.
Nothing validates it against the real part; VT-8's 5 V measurement with a wideband probe is the check.

**L model and sources.** L_i = L'(w) d + L_via / n_vias. Microstrip L' = Z0 sqrt(er_eff)/c with Hammerstad-Jensen Z0 for a strip over the plane
1.6 mm below (board file thickness 1.6; er 4.5 and 35 um copper not in the file, check): 0.832 nH/mm at w 0.2 mm, 0.751 nH/mm at 0.3 mm
(earlier fit 0.87 nH/mm). Via: Johnson's 5.08 h [ln(4h/d)+1] nH, h 1.6 mm, d 0.3 mm (the board's v_drill) = 1.30 nH each (formula from memory,
check); GND vias within 1.5 mm of each capacitor's ground pad counted from the integrated board (1 each, 2 for C404 and C408; radius a choice, check);
no mutual inductance. Result 2.8-7.7 nH per capacitor (C405 3.05, C406 7.04, C407 5.95, C408 7.66, C403 4.83, C404 6.97, C401 7.72, C402 5.77).
Bracket: L x0.5 and x2 (VIN 30 MHz pk-pk 80 and 218 mV worst case; DC-1 MHz unchanged). The earlier 2.2 + 0.87 d fit is kept as a comparison
(22-32 % above the formula). ESL 0.373 nH is cited from the Samsung page's study, not re-derived (no |Z| data in the repository).

**Sensitivity.** Distance acts at the CP and VIN capacitors (C403, C404, C402, C401), not at the output capacitors: +2 nH on one capacitor
raises its rail by C403 35.3, C404 17.6, C402 16.3, C401 9.2 mV; C405 0.002, C407 0.0008, C408 0.0004, C406 0.0002 mV.

**What VT-8 measures.** The output rails through the real LDOs, the 5 V rail with a wideband probe (the 10-30 MHz content), and the Due 3.3 V pin
and AREF noise that PW-4 limits. Those decide the cap-distance deviation; this row does not.
