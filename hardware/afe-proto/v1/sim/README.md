# v1 scope and AWG study (gate 3: the extracted strays)

What it computes: the v1 board's scope channel (SC-3, SC-5/SM-3, SC-9, AN-1) and AWG stage (AN-1, AW-3 bandwidth, C304) with the strays
extracted from `kicad/afe-proto.kicad_pcb` put back in, at the top of each error bar (afe.md VT-19, LR-3, LR-4).

It is v2's study with v1's values, not a copy: `model.py` imports `v2/sim/scope` (`run.py`, `netlib.py`) and `v2/sim/awg`
(`netlist.py`) and patches them to the v1 circuit; `run_study.py` is the driver. Why a thin `v1/sim/` and not a parameter next to
v2's: v2's parameters are module globals of two harnesses (`netlib.P0`, `awg.params.D`), not a board config; a driver that overrides
them reuses 100 % of the harness, the netlists, the AC/loop-gain code and `simtools`, and edits none of it. `compare.py` proves the
patched netlists are v1's circuit (below). Nothing in `v2/`, `simtools/` or `pcbtools/` is edited.

## Run (from the repository root R; the image only, one container at a time)
    docker/pcb/run.sh -m 3G -c 2 -t 580 bash -c 'cd /work/hardware/afe-proto/v1/sim && python3 -I run_study.py --out /work/hardware/afe-proto/v1/results --work /tmp/v1w'
    docker/pcb/run.sh -m 3G -c 2 -t 300 bash -c 'cd /work/hardware/afe-proto && PCBTOOLS_V1_SOURCE=/work/hardware/afe-proto/kicad python3 -I v1/sim/compare.py --mutate'
    docker/pcb/run.sh -m 3G -c 2 -t 590 bash -c 'cd /work/hardware/afe-proto && python3 -m pytest -c tests/pytest.ini tests/test_v1_sim_study.py -q'
Parasitics (cap.py, board of record `kicad/afe-proto.kicad_pcb` (the first run was on the earlier merge `v1_merge5`: identical figures); `pcbtools/boards/v1.py` CAP_PAIRS / CAP_SELF; results/cap_converge.txt, cap_in_nets.txt):
    docker/pcb/run.sh -m 3G -c 2 -t 590 bash -c 'cd /work/hardware/afe-proto && PCBTOOLS_V1_SOURCE=/work/hardware/afe-proto/kicad python3 -m pcbtools.cap kicad/afe-proto.kicad_pcb --config v1 --converge'
    (IN nets: `PYTHONPATH=. ... python3 v1/sim/cap_in_nets.py kicad/afe-proto.kicad_pcb`: the 0.05 mm level does not fit 3M cells there)
Needs `models/tph2501/TPH2501.mdl` (vendor, local, gitignored, MC-6; `tools/fetch_models.py`); without it the test SKIPS with that reason.
Outputs: `results/scope_{baseline,A,B}.json`, `results/awg.json` (sha256: see Golden).

## Cases A and B (source: `v2/sim/scope/sensitivity_n_stray.json`, "cases")
- baseline: v2's assumptions: 3.5 pF at N (`Cn_par`), 4 pF BNC + trace (`Cwire`), no coupling.
- A: the extraction is ADDED to the assumption. B: the extraction REPLACES it. Both at the top of the error bar (extrapolated + uncertainty).
- v1's top-of-bar values (pF; model.STRAYS): N self with pour 0.737 + 0.091 = 0.83; IN self with pour: CH1_IN 1.78 + 0.79 = 2.57, CH2_IN 1.87 + 0.92 = 2.78 (after J201 moved to the owner's 17.78 mm scope pitch); the study uses the larger, 2.78, for both channels (coarse cells, 0.4/0.2/0.1 mm);
  N-N < 0.05 fF (used 0.05 fF); NP-NP 0.62 fF (no-pour; 0.10 fF with pour); IN-IN < 0.05 fF; /AWG_INV 0.569 + 0.042 = 0.61.
- AWG cases: the inverting-node stray `cfb` 2 pF (v2's assumption), +0.61 (A), 0.61 (B), and the budget points 10 / 30 / 60 pF.

## v1 parameter table (model.PARAMS; each value's place in kicad/design.py)
| quantity | value | design.py |
|---|---|---|
| R101 (IN-N) | 470k + 300k | SC[ch][0]: R102+R103, R202+R203 |
| R201 (N-GND) | 470k + 330k | SC[ch][1]: R105+R101, R205+R201 |
| R3 (N-VREF) | one 330k | R104, R204 |
| C101 / Cn / Cnp | 12p / 30p / 10p C0G | C101,C201 / C102,C202 / C105,C203 |
| Rnp, Riso | 680, 22 | R106,R206 / R107,R207 |
| clamp | BAV99, GND / pin / P33_U | D101, D201 |
| supply pin | 100n + 10u, R108 1R to P33_U | C103, C104, R108 |
| AWG Rf, Cf, Rg2 | 3.3k, 10p, 4.99k | R303, C301, R302 |
| AWG Rbin, Cbin, Rbpl | 51k, 10p, 51k + 75k | R305, C304, R308 + R301 |
| AWG offset filter, Rout | 100R + 20 uF nominal; 100 || 100 = 50 | R307, C305 + C306; R304 || R306 |
The op-amp is v2's: TPH2501 macro (vendor) and the datasheet-fitted BEH21 / BEH60 for the TPH2502 (`models-open/tph2502-beh`).

## Differences from v2's netlist, and the proof (results/spicecmp.txt)
`compare.py` reduces each harness netlist with `pcbtools.spicecmp` (rules in `spice_cfg.py`, each dropped element with its reason) and
compares it with v1's schematic: generated from the design data (`boards/v1.py` PARTS, `sch_cfg`), exported by kicad-cli. Result:
scope 28 / 28 elements, awg 14 / 14, SAME CIRCUIT; four mutants (R1 470k to 480k, Rnp wired to the other channel, C304 20 pF, C304 absent) all FAIL.
Modelled in the harness (text patches in model.py): R3 one part (v2: two); supply decoupling 100n + 10u (v2: 100n + 1u); R108 1 ohm
between the supply pin and the clamps' P33_U (v2: one node); AWG without v2's 1 ohm Rb at the amplifier output; C304 (v2: none);
the divider's lower arm as two parts. Listed, not modelled (each is a `drop` with its reason in spice_cfg.py): signal, rail and
reference sources; the REF3030E output capacitors (REFCAL block); the stray capacitances (they are the study's variables); ADC pin
capacitance; the loads. Two comparison conventions, not circuit differences: v1 has no `Block` field in its schematic, so the design
data's block stands in; v1 draws the TPH2502 with the LM358 symbol, so its pins are named from the 3PEAK datasheet table (as v2_checks.DATASHEET_PINS).
Not modelled and not compared: the dual's shared-die crosstalk (the macro is a single amplifier), 0R corridor bridges (shorts), TP / BNC.

## C304 (10 pF across Rbin), modelled, with and without (results/awg.json c304_*)
Rbin C304 = 51k x 10p = 0.51 us: a zero at 312 kHz. It compensates the divider's pole with the lower arm (126k) when the +IN node carries
4.05 pF (op-amp input + pad). It acts at 0.3-60 MHz, in the signal path and in the loop:
- DAC pin to BNC -3 dB (hi-Z, weak rails): with C304 / without, by +IN-node stray 0 / 2 / 4 / 8 pF: 109 / 91 / 62 / 3.2 MHz vs 6.7 / 1.7 / 1.0 / 0.5 MHz.
  Without it AW-3 (8 MHz) fails at every stray (6.7 MHz even at 0 pF); with it flat to 4 pF and peaking 1.25x at 3 MHz at zero stray (g 3 MHz / dc: 1.25, 1.05, 0.91, 0.71).
  **AW-3 threshold: 4.55 pF** of AWG_BIN stray (bisection 0-20 pF, tolerance 0.01 pF, bracket 4.551-4.561, 13 steps logged in
  results/awg.json `aw3_threshold.bisection_log`; monotonic assumed, checked at 0 / 5 / 10 / 20 pF: 104 / 6.9 / 0.74 / 0.19 MHz). Assumed
  with it: C304 10 pF; AWG_BPL stray 0.27 pF (extracted top of bar); inverting-node stray 2.61 pF (case A) and 0.61 pF (case B), the
  worst of A / B and both rail corners; vendor macro, hi-Z load; the op-amp's input capacitance is inside the macro.
  **Extracted /AWG_BIN, top of bar 1.14 pF** (with pour 1.055 pad-corrected + 0.086; 0.86 + 0.018 without; the window is pad-limited, so the
  pad-corrected figure is used): 3.4 pF under the threshold; -3 dB there 101 MHz (A), 91 MHz (B). AN-1 with it, BEH21 / BEH60 / vendor: A 62.4 / 53.4 / 61.6, B 59.4 / 51.5 / 60.7 deg.
- AN-1 loop (loop broken at the inverting pin; 5 loads, 2 rails, `cfb` 2 pF), BEH21 / BEH60: with C304 62.0 / 53.3 deg, crossover 75.5 / 67.6 MHz;
  without 69.9 / 58.1 deg, crossover 22.5 / 18.3 MHz. C304 grounds +IN at high frequency (the DAC is a low-impedance source), so the loop crosses higher and the margin is
  4.7-7.9 deg lower, still above 45. (results/cap_in_nets.txt, v1/sim/cap_awg_bin.py for AWG_BIN / AWG_BPL.) The earlier gate-3 AWG figures (no C304) are superseded by these.

## Results (all from this study's runs; rtol 1e-12 golden)
| | baseline | A | B | limit |
|---|---|---|---|---|
| SC-5 / SM-3 -3 dB at the pin | 23.76 MHz | 22.43 | 26.66 | >= 8 MHz, no filter |
| SC-3 input C at 1 MHz; R | 13.49 pF | 16.10 | 11.93; 1003.6 k | <= 30 pF |
| SC-9, 6 Vpp 10 MHz | 1e-4 LSB | 0.0181 | 0.0195 | <= 2 LSB |
| SC-9 sensitivities (fF per LSB at 10 MHz): N-N / pad-pad / IN-IN | 70 / 35 / 409 | 71 / 35 / 417 | 63 / 33 / 391 | |
| AN-1 scope PM BEH21 / BEH60 / vendor | 61.0 / 61.1 / 70.3 | same | same | >= 45 deg |
| AN-1 AWG PM, BEH60 (BEH21 / vendor in awg.json) | 53.3 (cfb 2 pF) | 53.9 (+0.61) | 52.0 (0.61) | >= 45 deg |
| AWG stray budget, BEH60 PM at 10 / 30 / 60 pF | 59.5 / 52.4 / 44.5 | | | 45 deg at about 60 pF |
SC-9 is 100x under the limit; the strays that could break it are 126 fF (N-N alone), 70 fF (pad-pad) against 0.05 and 0.62 fF extracted.

## Golden
`tests/golden_sim/v1-gate3/` (STAMP.json), taken in the image twice, `diff -r` byte-identical. sha256 (first 16): awg 7b852e21d525329e,
scope_A fe5fa663bafc03c7, scope_B c0afa2e55fece3f3, scope_baseline 30761d44b57cb57b.
`tests/test_v1_sim_study.py` (markers vendor, ngspice, slow): reproduces it at rtol 1e-12, and runs the spicecmp proof with its four
mutants. Broken on purpose: C101 12p to 13p in model.py fails both tests.

## Still *(check)*
Self capacitance is not validated against a field solver and most self figures do not converge monotonically (error bar = spread); N is window-limited
(pad 2.25 of 3 mm); IN figures use coarser cells; the TPH2502 is the TPH2501 macro or a datasheet fit (no dual crosstalk, no vendor dual model);
X5R 20 uF is nominal here (v2 derated to 14 uF; at 14 uF effective the PM is unchanged: BEH21 62.8, BEH60 53.9, awg.json cvr_14uF_effective); AWG_BIN window-limited (pad 0 of 3 mm; pad effect +0.19 / +0.22 pF at 0.2 mm), self figures do not converge monotonically; v1's schematic is regenerated from the
design data, not read from the stale `kicad/afe-proto.kicad_sch`.
