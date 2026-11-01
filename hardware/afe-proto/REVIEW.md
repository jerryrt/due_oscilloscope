# AFE prototype review and open gates

**Current decision: use the corrected carrier KiCad model and complete
each AFE stage in SPICE before assembly.** The deleted `afe-shield` files
were the old inaccurate shield/template. They are not the board baseline.
The current [carrier project](../mega-proto-carrier/README.md) represents
the photographed hardware; the new AFE assembly and simulation assets
under this directory are still to be created.

## Current project state

| Area | Evidence / next action |
|---|---|
| Carrier | P3.5, measured 103 × 55 mm outline, photo-traced copper and owner corrections; preserve the baseline and its pad IDs |
| Carrier checks | Recorded KiCad 10.0.6 results: 244 contacts match schematic/PCB, ERC zero errors/warnings; 11 copper-to-edge findings remain. These are carrier checks, not AFE circuit validation |
| Physical unknowns | Hidden copper, dimensions and continuity still need relevant physical checks; use the carrier's User.5 marks and trace audit |
| Working AFE CAD | Planned `afe-proto.kicad_pro/.kicad_sch/.kicad_pcb`, based on a carrier copy; no AFE circuit is installed in the baseline model |
| Annotation | Carrier R1–R3 and D1/D2 remain; Stage A uses U101/D101/R101–R116/C101–C107/JP101 |
| Models and runners | Absent; establish manufacturer libraries, adapters, test benches and reproducible measurements before A1 can close |
| Configuration | Stock Due, JP101 open, JR1/BR1 untouched. Use the [V03 KiCad reference](../reference/arduino-due/v03/Arduino-DUE-V03.kicad_pcb), selected from the owner's six-pin IC2/separate-inductor observations; reported AMS1117 differs from source IC4. Full physical continuity remains unverified |
| Assembly | Gated by the new simulation results, reviewed wiring/placement and unpowered checks; no new stage is released by old results |

## Historical Stage A findings to reproduce or explain

These numbers describe the removed circuit implementation, using KiCad
10.0.6 and ngspice 47 with nominal models at 3.3 V / 27 °C. The associated
scripts, model files, workbook and JSON report are not currently present.
The earlier design used MCP6024-E/SL (SOIC-14); the socketed recipe proposes
MCP6024-E/P (PDIP-14). Neither package's physical wiring is qualified by
these simulations. References in the current recipe use the 100-series.

| Earlier test | Historical result | Consequence for the new A1 gate |
|---|---|---|
| Reference / midpoint DC | 2.99839 V / 1.49959 V | Recheck bias, error, startup and actual loads |
| DAC0 DC sweep, 0.5–2.5 V | Maximum error about 0.418 mV | Rerun over the stock-Due window and stated error budget |
| Follower before driver resistor at 5.012 MHz | -5.86 dB | Does not establish the former driver-flatness target |
| Full path, 68 ohm / 470 pF | -8.90 dB at 5.012 MHz; sampled -3 dB crossing about 3.39 MHz | The passive RC's 4.98 MHz corner is not full-path bandwidth |
| 2 V steps, both polarities | About 1.218 us to stay within 0.732 mV of final plateau | Longer than the 1.129 us sample interval; absolute DC error and acquisition recovery are separate checks |
| Open-link loaded driver | About -5.915 dB before resistor at 5 MHz; about 1.232 us worst-polarity settling | Added loading did not resolve the driver shortfall |
| Selected supply/temperature/RC cases | About 1.199–1.264 us settling | Not combined worst-case qualification or a full-step timing pass |
| Fitted ADC surrogate | About ±0.0843 diagnostic code at 769.23 ns; ±3.714 codes at 210 ns | Strong dependence on the assumed acquisition window; not a validated transistor-level SAM3X model |
| Time-step check | About 0.0843 code magnitude at both 1 ns and 2 ns | Convergence evidence for that case only |
| Assumed 1 uH series wiring | No quiet final plateau in the observation window | Test wiring sensitivity; do not claim the carrier has 1 uH inductance |
| Closed-link AREF stress | About 0.828 mV p-p with 100 uA steps and a lumped 200 nF load | Separate modified-Due case; no permission to connect AREF |
| OPA4350 candidate | Integrated operating point failed or timed out | No comparative performance result or approved replacement |

The old 3 V / 4096 diagnostic code was about 0.732 mV. Default stock-Due
code scaling follows its actual ADVREF. The closed-link test omitted
ferrite impedance, board parasitics, ADC switching and power sequencing;
it was not a stability qualification. Nominal manufacturer models do not
establish worst-case error, noise, channel crosstalk or real-board settling.

## Work required to close A1

1. Build the new working schematic and [model setup](models/README.md),
   preserving the carrier as the physical reference. Audit all exact part,
   package, footprint and SPICE terminal mappings.
2. Define numerical passband, DC-error, step and acquisition limits with
   loads and operating conditions. Keep useful instrument bandwidth distinct
   from a driver test; record ADC settings and reference scale.
3. Complete reference, midpoint, driver and integrated tests in the order
   in [the plan](../../docs/afe-plan.md). Reproduce or explain the old
   shortfalls; change the circuit/network if needed and rerun. MCP6024 is
   a candidate, not a component selection already proven adequate.
4. Include supply/temperature/passive variation, realistic load and wiring
   sensitivity, startup and numerical convergence. Record missing model
   coverage with explicit later bench tests.
5. Save a complete pass/fail report at the exact schematic/model revision.
   Then review the working layout and use the
   [construction checklist](BUILD-VALIDATION.md) before assembly or power.

Current gates: **A1 not rerun; A2 not released; C1/C2 and B1/B2 pending;
custom PCB Phase P deferred.** Old ERC counts, old connector references
and old template DRC findings do not apply to the corrected carrier or
stand in for checks on the future assembly.
