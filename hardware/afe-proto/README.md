# AFE assembly

The working KiCad project for the AFE, made from the corrected
[Mega ProtoShield V3 carrier](../mega-proto-carrier/README.md). The
requirements are in [docs/afe.md](../../docs/afe.md) and the plan that builds
them is [docs/afe-plan.md](../../docs/afe-plan.md).

| Location | Role |
|---|---|
| [mega-proto-carrier](../mega-proto-carrier/README.md) | The photographed board: geometry, existing copper, pad IDs. Never edited to hold the AFE |
| This directory | The working copy of the carrier's schematic and PCB with the AFE added, plus its models, simulation benches and reports, created as the plan's steps need them |
| [Due V03 PCB](../reference/arduino-due/v03/Arduino-DUE-V03.kicad_pcb) | The Due reference for mating, clearance and signal nets |

Rules for the working copy:

- Keep the carrier's footprint and symbol associations, coordinates, pad IDs,
  outline and existing tracks intact; record added wires and cuts separately
  from existing copper.
- Do not run `mega-proto-carrier/build_model.py` over the working assembly: it
  regenerates the baseline and overwrites CAD edits.
- Use KiCad 10.x only.
