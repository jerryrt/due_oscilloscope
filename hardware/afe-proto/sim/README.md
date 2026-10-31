# Simulation before assembly, one AFE stage at a time

**Status: procedure and test plan.** There are no runnable SPICE test
benches, runner scripts, model libraries or simulator workbooks in this
directory yet. The removed `hardware/afe-shield/sim/` commands are obsolete.
No simulation gate for the new assembly has passed.

Use KiCad 10.x for the AFE circuit and its ngspice-based simulator, with
batch ngspice runs added for repeatable sweeps and numeric checks. Record
the exact versions. The corrected
[carrier KiCad project](../../mega-proto-carrier/README.md) supplies board
geometry and existing connections; it is not a SPICE model of the AFE,
the Due's converters or the board's parasitics.

## Establish the sources

Create the working assembly as described in the [AFE README](../README.md).
Use shared AFE circuit sheets in test-bench schematics so the simulated
parts, feedback and RC networks match the assembly schematic. Put ideal
supplies, DAC stimuli, measurement loads and ADC surrogates in explicit
simulation-only test benches, excluded from the physical BOM and PCB.
Check that simulation-only sources cannot enter a PCB update.

Export the relevant analog test bench, rather than blindly exporting the
carrier's passive contact symbols and unmodeled headers. Account for every
boundary connection: supply, ground, input source and output load. Preserve
the full quad and unused-channel terminations in the integrated test. An
isolated block test is followed by a full-stage test at the same revision.

First validate [manufacturer models and adapters](../models/README.md).
Use **Inspect → Simulator** in KiCad's Schematic Editor to inspect circuits
and plots. Save analysis settings/workbooks with the test-bench revision.
A reusable batch runner and numeric checks are planned additions, not
commands available today. Consult the retained
[KiCad 10 schematic manual](../../../docs/reference/kicad-10/eeschema.pdf)
for the simulator and model assignment.

## Required stage tests

| Stage | Sequence before assembly | Numerical checks to retain |
|---|---|---|
| A1a reference | DC operating point; supply/bias range; startup ramps; buffer load steps | Reference voltage/error, shunt bias and supply current, startup time, overshoot and recovery |
| A1b midpoint | DC divider/buffer; startup; A2 RC and load changes; component tolerances | Midpoint error, headroom, loading, settling and reference disturbance |
| A1c drivers | Stock-Due DAC-range DC sweeps; AC about relevant bias points; both step polarities and amplitudes | Absolute DC error, gain/phase and peaking, input/output limits, overshoot and settling against defined band/deadline |
| A1d integrated Stage A | Whole quad, simultaneous loads, switched ADC surrogate; supply/temperature/passive corners; socket/wire/probe sensitivity; smaller time step | Acquisition-end dynamic and total errors, rail/reference movement, convergence and sensitivity; explicit model gaps |
| C1 output | DC span/offset per rail choice and load; filter AC; steps, startup and load changes; inverter ripple if selected | Output endpoints/headroom, gain, filter response, settling, drive/current and ripple; integrated A+C rerun |
| B1 input | Each range and offset; compensation on/off; PWM filtering; powered/unpowered clamp/fault cases | Transfer/headroom, flatness, offset ripple/settling, clamp currents and component stress; integrated A+C+B rerun |

Use realistic source impedance and declared loads. No-load success does
not close a loaded-output gate. SPICE fault tests supplement datasheet
ratings and later controlled tests; they do not establish transient or
ESD ratings. Simulate the chosen hardware configuration before assembling
it; the optional modified-Due AREF path is separate from default Stage A.

## Define acceptance before running

For each case, write the requirement/source, configuration, input span
or step, load, supply, temperature, component variations, error limit and
time window. Resolve missing numerical requirements in
[afe.md](../../../docs/afe.md) and [the plan](../../../docs/afe-plan.md)
before claiming completion. The historical driver comparison used a
1 dB/5 MHz screen and a 3 V / 4096 one-code band; these diagnostic choices
must not silently become new limits for the whole instrument.

Default hardware is stock Due with **JP101 open**. Use its actual ADVREF
for code-voltage interpretation and its roughly 0.55–2.75 V DAC window.
A 3.0 V reference elsewhere on the shield does not set that scale.

At 886 ksps the 1.129 us sample interval is not necessarily the available
acquisition time. Derive the latter from ADC clock, tracking/transfer
settings and channel sequence, and include previous-channel charge history.
Measure recovery immediately before sampling ends. Report dynamic recovery
relative to the pre-acquisition pin voltage separately from total error
relative to the ideal source, so DC error is not hidden.

The retained [SAM3X/SAM3A 11057C datasheet](../../../docs/datasheets/microchip/SAM3X-SAM3A-11057C.pdf),
section 45.7.2.1, gives `t_track_ns = 0.054 * R_source_ohm + 205` for its
specified case. The earlier screen used a 15-ADC-clock, 19.5 MHz example
(about 769.23 ns) and a fitted approximately 6 pF / 3.8 kohm sampling
surrogate. Those RC values were inferred using a half-LSB settling
assumption; they are not published internal component values. Recheck
applicability to the actual firmware. A constant input during charge
recovery is a different test from a full input step.

## Evidence and pass/fail rules

For each accepted run, retain under planned `../reports/`:

- Schematic/assembly revision, exported netlist, exact model hashes and
  simulator version/options, with a reproducible invocation or workbook.
- Case definitions, raw measurement provenance and representative plots
  with node names, units, input edges and measurement windows.
- A table of requirement, measured value, limit, margin and **PASS / FAIL /
  NOT MODELED** for every required case; distinguish unrun cases.
- Solver warnings, failed cases and remaining bench tests. Do not publish
  only passing traces or reuse a stale result after a failed run.

A stage closes when required model-supported tests meet their stated
limits and remaining model gaps have explicit hardware checks. Required
failures, missing acceptance limits or invalid/converging-only models
keep it open. Runner exit zero will mean execution completed; it cannot
by itself mean the electrical gate passed.

Use a sufficiently small maximum transient time step and rerun critical
measurements with a smaller one. Measure settling after the **last** band
excursion, with a sufficiently long stable observation window. Test
startup with a supply ramp; a transient initialized at the solved operating
point is not power-up evidence. Document any solver adjustments and check
they did not materially change the circuit being tested.

After SPICE passes, hand off the exact circuit/BOM and results to the
working carrier layout and [construction gate](../BUILD-VALIDATION.md).
Repeat affected tests after circuit or load changes. Noise, shared-ground
coupling, socket parasitics and actual ADC behaviour remain bench work
where the chosen models do not represent them. Historical findings in
[REVIEW.md](../REVIEW.md) guide the first rerun; they do not close a gate.
