# AFE prototype on the reconstructed carrier

Use the corrected [Mega PrototypeShield V3 KiCad project](../mega-proto-carrier/mega-proto-carrier.kicad_pro)
as the physical baseline for this build. The deleted `hardware/afe-shield/`
project was the old, inaccurate shield/template. Its removal does not retire
the AFE work. The current carrier captures the actual 103 × 55 mm board;
it does not yet contain the proposed Stage A analog circuit.

**Current state:** this directory contains the AFE documentation. The new
AFE assembly schematic, PCB copy, SPICE libraries and simulation runners
have not been created. Earlier simulation numbers are historical findings,
not passes for the current carrier or a new assembly revision.

## Where things live

| Location | Role now |
|---|---|
| [mega-proto-carrier](../mega-proto-carrier/README.md) | Corrected carrier PCB, contact schematic, local libraries, pad map, photographs and copper evidence; preserve as the substrate baseline |
| [afe-proto](README.md) | AFE circuit/assembly plan and review; planned home of the working KiCad assembly and its SPICE checks |
| [Arduino Due reference](../reference/arduino-due/README.md) | Complete converted Due PCB for mating, clearance and signal-reference checks; verify the physical Due revision |
| [AFE plan](../../docs/afe-plan.md) | Stage order, simulation gates and implementation sequence |
| [Stage A recipe](../../docs/afe-prototype.md) | Candidate circuit, parts, connections and later bring-up procedure |
| [Simulation plan](sim/README.md) / [model plan](models/README.md) | Test benches, evidence and manufacturer-model requirements |
| [Review](REVIEW.md) / [construction checks](BUILD-VALIDATION.md) | Open findings and the conditions for assembly and power-up |

## Use the carrier in the working AFE project

1. Record the source carrier revision (currently P3.5) and Git commit.
   Inspect its pad map, existing copper and `User.5` review marks. Confirm
   the actual holes and critical connections by continuity measurement.
2. Create a separate working project here, named `afe-proto.kicad_pro`,
   from the carrier's matching PCB and schematic. Copy its required local
   footprint/symbol libraries and 3D assets; update project-relative library
   tables and model paths. Keep the carrier symbol/footprint UUID associations,
   coordinates, pad IDs, outline and existing tracks intact.
3. Keep inherited carrier contacts in the root sheet and add AFE sheets
   for Stage A, then C and B. The carrier contact schematic records existing
   connections; it is not an analog model. Audit inherited net labels against actual copper before
   joining the new circuit to the Due interface.
4. Reserve **100-series references for Stage A**: U101, D101, R101–R116,
   C101–C107 and JP101. Carrier R1–R3, D1/D2, SW1, headers, PG1 and TP1
   keep their existing references. Use 200-series for Stage C and 300-series
   for Stage B. Keep annotation stable as stages are added.
5. Reuse the same AFE circuit sheets in stage test benches, with explicit
   simulation-only supplies, sources and loads. Complete that stage's
   [SPICE gate](sim/README.md) before assembling it.
6. After the gate passes, place the stage on the working carrier copy.
   Review every schematic-to-PCB update; preserve fixed carrier geometry
   and copper. Record added insulated wires/jumpers and intentional cuts
   separately from existing F.Cu/B.Cu in an assembly drawing. Map each AFE
   component pin to an existing grid/header pad. PG1's schematic currently
   exposes only the 28 fanout contacts; extend the working contact symbol
   for any additional grid holes used, keeping the PCB's existing pad IDs.
   Represent socket/body placement on those holes without inventing extra
   drilled holes or treating TP1 land IDs as an IC pinout. DRC alone
   cannot validate hand wiring, insulation, crossings or underside clearance.

Do not run `mega-proto-carrier/build_model.py` over the working assembly:
it regenerates the carrier baseline and overwrites CAD edits. Run its
baseline checker on the carrier; add separate checks for the AFE assembly.
Existing model review marks and copper-to-edge findings remain visible
until individually resolved; the reconstructed board is not a fabrication
release.

The proposed working files above are **planned**, not files to open yet.
For now, open the linked carrier project to review the board and use the
[plan](../../docs/afe-plan.md) to prepare A1. The old `afe-shield/check.py`,
simulation commands and workbook no longer exist and are not current checks.

## Stage order

**A1 simulate → A2 assemble/measure → C1 simulate → C2 assemble/measure →
B1 simulate → B2 assemble/measure.** A later custom PCB is Phase P, using
these measured results. Within A1, finish the reference, midpoint, drivers
and integrated-load tests in sequence. Passing a SPICE run means its
numerical limits were met, not merely that ngspice exited successfully.

Default hardware is a stock Due, JP101 open and JR1/BR1 untouched. The
3.0 V reference and 1.5 V midpoint do not change its ADC/DAC full scale.
Any alternate AREF configuration needs its own model, revision-specific
Due checks and validation before it is used.
