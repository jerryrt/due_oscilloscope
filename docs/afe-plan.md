# Building the AFE on the corrected carrier

**Status: carrier reconstruction available; AFE circuit and SPICE work next.**
The old, inaccurate `hardware/afe-shield/` KiCad project has been removed.
The physical baseline is now
[`hardware/mega-proto-carrier/mega-proto-carrier.kicad_pro`](../hardware/mega-proto-carrier/mega-proto-carrier.kicad_pro),
which records the photographed 103 × 55 mm board. It contains carrier
contacts and existing copper, not the proposed analog front end.

Develop the AFE assembly under [hardware/afe-proto](../hardware/afe-proto/README.md)
using a working copy of that baseline. **Complete each circuit stage in
SPICE before assembling that stage.** The requirements remain in
[afe.md](afe.md); failed simulations lead to circuit changes and reruns,
not silently relaxed limits. Hardware measurements follow simulation and
remain necessary for construction effects, noise and actual ADC behaviour.

## Project setup before A1

| Step | Work | Completion evidence |
|---|---|---|
| Carrier baseline | Record carrier revision/commit; inspect pad map, traces, fanouts and `User.5` unknowns; compare relevant connections with the physical board | Baseline reports retained; unresolved continuity/geometry questions listed with their assembly impact |
| Working assembly | Create `afe-proto.kicad_pro`, matching schematic and PCB under `hardware/afe-proto/`, copying required carrier libraries and assets | Native files reopen; carrier geometry, pad IDs, existing copper and schematic associations preserved; relative paths resolve |
| AFE circuit sheets | Add Stage A sheets and explicit Due interface; use U101/D101/R101–R116/C101–C107/JP101 without renumbering carrier parts | ERC and critical-net review; exact parts, package/footprint and model pin mapping checked |
| Simulation setup | Obtain and validate manufacturer models under `afe-proto/models/`; create stage test benches under `afe-proto/sim/` | Model provenance and hashes, simple model smoke tests, exported netlist and exact KiCad/ngspice versions recorded |
| Acceptance table | Give each test an input, load, numerical limit, deadline and source requirement | Limits and unresolved requirements written before interpreting plots; default is stock Due, JP101 open |

These working CAD files and simulation assets are planned; currently only
the documentation is present in `afe-proto/`. Do not restore the old shield
geometry or start again from the generic Arduino Mega template. The
[working-project instructions](../hardware/afe-proto/README.md) explain how
to preserve the accurate carrier while adding the AFE.

## Stage order and gates

| Phase | Circuit / implementation | Required evidence before moving on | Evidence location |
|---|---|---|---|
| **A1** | Reference, midpoint and DAC-to-ADC drivers in KiCad | Reference and midpoint DC/startup/load tests; driver DC/AC/step tests; explicit ADC acquisition load and timing; relevant supply, temperature, tolerance and wiring cases meet written limits | Planned `hardware/afe-proto/sim/` test benches and `reports/` accepted results; [review](../hardware/afe-proto/REVIEW.md) |
| **A2** | Stage A assembled on the existing carrier from the reviewed working layout | A1 passed; placement/wiring and unpowered checks complete; current-limited bring-up, DC, dynamic and loopback measurements recorded | Working assembly revision, photographs, measurement notes and `records/` captures |
| **C1** | DAC reconstruction filter, output summer, output load; optional inverter evaluated separately | DC span/centering/headroom per rail choice; AC response; transient/settling, startup, load and supply sensitivity; integrated rerun with Stage A | Stage C test benches and accepted reports |
| **C2** | Simulated Stage C added to the carrier | C1 passed; repeat construction checks and compare loopback/output measurements; inverter off/on only for configurations already simulated | Assembly revision and `records/` |
| **B1** | Attenuation, compensation, protection, ranges and PWM offset | DC transfer and headroom per range; AC compensation; offset range/ripple/settling; clamp currents and powered/unpowered fault cases; integrated A+C+B rerun | Stage B test benches and accepted reports; any required PWM firmware tracked separately |
| **B2** | Simulated Stage B added to the carrier | B1 passed; inspect and bring up at controlled low voltage, then planned range/protection and loopback measurements | Assembly revision and `records/` |
| **P**, later | Custom PCB derived from the validated circuit | Simulations rerun with declared PCB/load assumptions, measured prototype, Due fit, selected manufacturing rules, reviewed ERC/DRC and fabrication outputs; repeat bring-up and measurements | Separate future PCB project and release evidence |

A goes first because the reference and ADC drive underpin the measurement.
C precedes B because the loopback bench needs the output stage before an
external-input attenuator. The current work uses the carrier KiCad PCB to
plan assembly; it is not a request to fabricate another carrier.

## A1: complete these simulation steps first

| Step | Test | What must be resolved |
|---|---|---|
| A1a reference | Shunt bias, filter, reference buffer: operating point, supply ramps, load steps and supply limits | Bias-current/headroom margins, startup and recovery, stable reference with its declared load |
| A1b midpoint | Divider, buffer and A2 RC: DC error, startup, load and tolerance cases | Midpoint error allocation, loading and settling; no dependence on a floating unused amplifier |
| A1c drivers | Both DAC-to-ADC paths: DC sweep, small-signal AC, rising/falling steps | Gain deviation/band, absolute DC error, settling band/deadline and input/output headroom at the stock-Due DAC window |
| A1d integration | Whole quad, local supply/decoupling, switched ADC-load surrogate and channel histories; socket/wire/load sensitivity and time-step convergence | Actual acquisition window from ADC settings, combined loading and recovery; distinguish model coverage from later bench tests |

The former MCP6024/68 ohm/470 pF simulations had unresolved bandwidth and
full-step settling findings. Recreate the candidate and reproduce or
explain those findings before selecting the final driver/network. The
[Stage A recipe](afe-prototype.md) is the candidate connection schedule,
not permission to bypass the simulation gate. Component changes must be
reflected in the circuit, BOM, models, layout and recipe together.

At 886 ksps, 1.129 us is a sample interval, **not automatically the ADC
acquisition time**. Record ADC clock, channel sequence and tracking settings.
The historic 3 V / 4096 diagnostic code is 0.732 mV; a stock Due uses its
actual ADVREF instead. State the scale and error allocation in every report.
The intended 200–300 kHz instrument passband and a driver-bandwidth test
are different requirements. Define allowed gain deviation and the settling
stimulus/deadline explicitly before calling A1 passed.

## SPICE completion and assembly handoff

Follow the [simulation procedure](../hardware/afe-proto/sim/README.md).
A completed stage has a reproducible source schematic, model hashes,
exported test netlist, stimuli/loads, numerical measurements, limits and
a case-by-case pass/fail table. Record unsupported effects as model gaps
with bench tests; failed required cases keep the stage open. A converged
operating point or an exit code of zero does not close the gate.

Then place the passed circuit on the working carrier copy. Keep existing
copper distinct from added wiring, use grid/header pad IDs, and check
SMD fanouts before assigning holes. Maintain carrier locks and review
schematic-to-PCB changes individually. Model estimated wiring parasitics
as sensitivity cases, not as extraction from the PCB. Repeat affected
simulations if placement changes a critical load or connection.

Use [construction validation](../hardware/afe-proto/BUILD-VALIDATION.md)
and the recipe for later assembly and power-up. Record the exact assembly,
Due identity/revision, firmware/timing, reference configuration, instruments
and probes with measurements. Feed failures back into the same stage's
schematic and simulation. SPICE cannot close the measured noise, crosstalk,
physical-fit or actual sampling-accuracy gates.

## Tools and references

Use **KiCad 10.x** with matching symbol/footprint libraries and ngspice.
Earlier results used KiCad 10.0.6 and ngspice 47; record the actual versions
for new runs. The old AFE runner/check scripts and workbook are absent.
Do not advertise them as current commands. The carrier's `check_model.py`
validates its baseline, not the new analog circuit or its SPICE performance.

| Reference | Purpose |
|---|---|
| [Corrected carrier](../hardware/mega-proto-carrier/README.md) | Existing geometry, copper, pad IDs, photographs and open physical checks |
| [Due V03 PCB](../hardware/reference/arduino-due/v03/Arduino-DUE-V03.kicad_pcb) | Working reference for mating/clearance and board nets; selected from the owner's reported power layout. [Reference index](../hardware/reference/arduino-due/README.md) records the AMS1117 substitution and remaining physical checks; V02g is archived separately |
| [Reference index](reference/README.md) | Offline datasheets, KiCad manuals, official source URLs and provenance |
| [Model plan](../hardware/afe-proto/models/README.md) | Vendor models, package mapping and smoke tests to establish before A1 |
| [Workflow](afe-workflow.md) | General design, simulation and hardware quality gates |

## Open decisions and records

| Item | Current rule / remaining work |
|---|---|
| AREF | Stock Due; JP101 open and JR1/BR1 untouched. Driving AREF is a separate future configuration requiring revision-specific checks and reference-load validation |
| Stage A driver/network | MCP6024 is a candidate with historical shortfalls; resolve in A1, before assembly |
| Stage B ranges | Select the ranges before B1 acceptance tests are finalized |
| Stage C inverter | Simulate each rail configuration before choosing and building it |
| Requirements | Numerical passband/error/settling allocations must be explicit; retain original targets and record any deliberate revision in `afe.md` |

Keep one tracker item per phase if using the tracker. Keep accepted
simulation reports under planned `hardware/afe-proto/reports/`; raw rerun
outputs stay separate. Measurements belong in `records/` with their
assembly revision. This document defines the work; it does not claim
that a simulation, assembly or release gate has already passed.
