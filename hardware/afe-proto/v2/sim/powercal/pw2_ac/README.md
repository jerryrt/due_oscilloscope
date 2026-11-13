# PW-2 cap-distance ripple by AC (line-spectrum) analysis

TI's LM27762 transient model stalls on any series inductance in its capacitors (`../pw2_loopl_results.json`: 15 attempts,
'Timestep too small'). So the ideal transient (pure-C capacitors, no L) is run once, its ripple is decomposed into lines, and
each rail's real network (ESR(f), ESL, the loop L of every capacitor, in parallel across the bank) is applied line by line:
`V_m = I_m Z(f_m)` with the injected current `I_m = Y_tr(f_m) V_m`, `Y_tr` being the admittance the transient deck put on the node
(the lumped capacitance, the load resistor, the 1.2 ohm source on VIN).

Files: `pw2_ac.py` (module and CLI: `... pw2_ac.py transient` runs the ideal case, bare `... pw2_ac.py` writes the results),
`results/pw2_ac_results.json` (everything, including the `sources` table), `results/transient_ideal_window.npz` (the last 150 us of
the ideal transient: the AC step needs no ngspice), tests in `tests/pcbtools/test_pw2_ac.py`.

## What the transient showed, and why the method is not a Fourier series at f0

* The pump is **a PFM burst generator**: `cp` toggles at **2.13 MHz inside bursts** (centroid of its spectrum), bursts repeat at
  about 85 kHz, duty 0.59. `pw2.analyse`'s 1.25 MHz is the mean-crossing rate over bursts and idle. **The model's own pump
  frequency is already inside the datasheet's 1.7-2.3 MHz.**
* The ripple is the **burst-rate sawtooth, 99.6 % of its variance below 1 MHz** (VIN; OUT+ and OUT- 99.999 %). At each pump
  harmonic k f_pump the VIN ripple is 339, 29, 38, 11 uV (k = 1..4): the pump bands carry 0.4 % of the variance, so the harmonic
  series of the brief (1..10 harmonics of f0) describes almost none of the ripple. The decomposition is therefore over all lines
  m / 100 us (10 kHz apart), reported as: burst-rate band (< 0.5 f_pump), pump-harmonic bands (k f_pump +- 0.25 f_pump, k = 1..10)
  and the rest.
* The capacitor loop L acts on the **edge content** of the injected current (10-30 MHz), not on the 85 kHz sawtooth.

## Validation (step 5)

The AC machinery on the transient's own network (capacitance only) reproduces the transient: pk-pk 19.588 mV VIN (runner: 19.599),
0.1311 mV OUT+, 0.0437 mV OUT- (runner 0.1311, 0.0437), ratio **1.0000 +- 5e-5 on every node**. **This is nearly a tautology**
(I is derived from V through the same Y, so it checks the pipeline: windowing, ramp removal, line decomposition, inverse transform,
the interpolation) and says nothing about the physics. The linear sum of lines is 2.85x the pk-pk on VIN (an upper bound by
construction). A non-circular check is not available: the transient with ESR/ESL does not converge (harness docstring). The
known-answer tests (resonance, a line through a known network) carry the non-tautological checking.
The ideal case with the capacitors' own ESR and ESL (no loop L) reads VIN 19.4 (5 MHz limit) / 23.3 mV (30 MHz limit): the ESL
alone adds to it, which the transient cannot show.

## Band limit, and the weak link in the current

The injected current's content between 30 and 82 MHz is **not stable against the resampling grid** (its rms changes 24 / 44 / 38 mA
across grids of 2^13 / 2^14 / 2^15 points; 3-30 MHz is stable to 5 %). Lines above **30 MHz are dropped (`FMAX_HZ`)** *(check)*.
Its effect on the as-built VIN pk-pk (model frequency): 5 MHz 23.6, 10 MHz 32.4, 20 MHz 72.0, **30 MHz 125**, 40 MHz 198, 83 MHz 598 mV
(ideal: 19.4, 19.7, 21.0, 23.3, 26.3, 64.4). The figure is a strong function of how much high-frequency current the model's switch
edges carry, which no part of this has validated against the real part.

## Inductance sources (spec lead's condition)

| quantity | value | source | status |
|---|---|---|---|
| ESL | 0.373 nH | PROVENANCE.md (median 3-10 MHz of (X + 1/wC)/w from the page's |Z| and ESR curves) | cited, **not re-derived**: the repo holds esr.csv and dcbias.csv only; no |Z| curve |
| board | 1.6 mm, 2 layers | fixture `.kicad_pcb` `(general (thickness 1.6))`, no stackup block: top copper to the plane = 1.6 mm | board file |
| er, copper | 4.5, 35 um | not in the file | (check); copper not used |
| microstrip L' | **w 0.2: 0.832 nH/mm; w 0.3: 0.751 nH/mm** | Hammerstad-Jensen Z0, er_eff (Z0 = 144.5 / 129.9 ohm, er_eff 2.98 / 3.01); L' = Z0 sqrt(er_eff)/c | formula; the agent's 0.87 nH/mm is within 5-16 % |
| via | **1.299 nH** each | Johnson L = 5.08 h [ln(4h/d)+1] nH (inches), h 1.6 mm, d 0.3 mm = the fixture's v_drill (all 41 vias) | from memory (check) |
| GND vias per cap | 1 each, **2 for C404 and C408** | GND vias within 1.5 mm of the GND pad, `v2-integrated-990d4b03.npz` | board data; the radius is a choice (check); no mutual L |
| L_i = L'(w_i) d_i + L_via / n_i | C405 3.05, C406 7.04, C407 5.95, C408 7.66, C403 4.83, C404 6.97, C401 7.72, C402 5.77 (C409 2.77, not a bank) nH | widths: C405/406/401/402 0.3 mm, C403/404/407/408 0.2 mm | d from the earlier table, not re-measured (check) |
| agent fit | 2.2 + 0.87 d: 4.2 ... 9.6 nH | earlier agent | fit, kept as case `agent_fit`; 22-32 % above the formula |

## Results (peak-to-peak, mV; limit 20 mV; bandwidth 30 MHz; as-built = formula L)

| case | f_pump | OUT+ (+3V3A) | OUT- (VNEG) | VIN | CPOUT (not PW-2) |
|---|---|---|---|---|---|
| transient (no ESR, ESL, L) | 2.13 (model) | 0.131 | 0.044 | 19.6 | 23.3 |
| ideal (ESR + ESL only) | model | 0.132 | 0.044 | 23.3 | |
| as-built | model 2.13 | 0.137 | 0.049 | 125.0 | |
| as-built | 1.7 | 0.136 | 0.048 | 104.7 | |
| as-built | 2.0 | 0.137 | 0.049 | 119.0 | |
| as-built | 2.3 | 0.138 | 0.049 | 133.1 | |
| **as-built, worse of 1.7-2.3** | | **0.138** | **0.049** | **133.1** | 195 |
| L x 0.5, worse | | 0.135 | 0.047 | 80.1 | 103 |
| L x 2, worse | | 0.144 | 0.060 | 217.9 | 385 |
| agent fit, worse | | 0.140 | 0.051 | 159.7 | 239 |
| control: +100 nH on C407, worse | | 0.138 | **0.072** (+47 %) | 133.1 | |

Linear / RSS sums (as-built, model f, VIN): 708 / 35 mV against the phasor (exact, waveform pk-pk) 125 mV. The linear sum bounds,
the RSS under-reads, because the lines are phase-locked to the burst edges. Only the phasor sum is used for the verdict. Higher
pump frequency raises the as-built ripple (the loop's inductive impedance grows with f; the capacitor's falls only as 1/f).
Frequency scaling: lines above 0.5 f_pump are evaluated at s x f with the same I_m (the charge per cycle falls as 1/f0 and the pulse is as short, so the
current as a function of phase is the same); the burst rate is not scaled *(check)*.

**Verdict.** OUT+ and OUT-: **with margin** by two orders (0.14 and 0.05 mV against 20), but see limits: that is the model's LDO,
and the model under-reads. **VIN: fail** (133 mV as-built, 80 mV even at half the inductance, over the limit at every band limit
above 5 MHz; the ideal case is already 23 mV at 30 MHz and the transient's own 19.6 mV leaves no margin). The VIN figure is the ripple at the
converter's pin side of the loop inductance and its size rests on the model's 10-30 MHz edge current *(check)*.

## Sensitivity (+2 nH on one capacitor, others as-built; rise in rail pk-pk, mV, model f; and x2 / +100 nH)

C403 35.3 (71 / 231), C404 17.6 (46 / 113), C402 16.3 (37 / 97), C401 9.2 (26 / 60), C405 0.0019 (0.003 / 0.021), C407 0.0008,
C408 0.0004, C406 0.0002. On VIN the capacitor with the **shorter** loop matters more (C402, 5.8 nH, carries more of the edge
current than C401, 7.7 nH). CPOUT's two capacitors rank first but are not a PW-2 node. OUT+/OUT- are insensitive: the model injects
only 0.3 mA (burst band) and 0.02 mA (pump band) into OUT+ against 28 and 49 mA into VIN.

## Limits

* The model has no LDO loop and under-reads the datasheet (VT-8): its OUT+/OUT- ripple is the pump filtered by a 1 mohm ideal
  source, so the OUT+/OUT- figures here are not the rails' ripple through a real LDO's rising high-frequency output impedance.
* The L extraction is a formula (microstrip + via) for stated geometry, not a field solve: no mutual inductance between the
  capacitors' loops or between a capacitor's vias, the pin end of the loop, pad and via-in-pad parasitics, or the pour. x0.5 and
  x2 bracket it; the verdict on VIN holds across the bracket.
* The injected current is the model's, taken as a constant current source: the converter's source impedance is ignored, and the
  band above 30 MHz is excluded (above).
* The load network's own filtering and the 1.2 ohm source on VIN are the deck's (parsed from it), not the board's.
* `er`, copper thickness, the via-return radius, C409's width and the d table are (check).

## Runs

Ideal transient through x1's runner (`tstop 1.3 ms, tmax 0.25 us`, mem 2G, under `capped.sh -m 3G`): 140.7 s, peak RSS 15 MB, converged,
OK. The line analysis: under 2 s, numpy only. `get_pw2()` imports `simtools.pw2` and, if the checkout has not caught up with
origin/pcbtools, a scratch copy of origin's `simtools` under `pcbtools/.scratch/orig` (symlinks to the TI model in the main checkout).
