# AFE shield

The KiCad 9 project for the analog front end on the Arduino Due.
`docs/afe.md` is the requirement, `docs/afe-plan.md` the phases and
what proves each.

| file | what |
|---|---|
| `afe-shield.kicad_pro`, `afe-shield.kicad_sch` | the project and its root sheet: KiCad's `Arduino_Mega` template, whose headers are the Due's, with one sheet symbol per stage |
| `reference.kicad_sch` | Stage A: the LM4040 reference, its buffer, the mid-rail, the AREF jumper |
| `pin-driver.kicad_sch` | Stage A: the followers from DAC0 and DAC1 into A0 and A1, VREF1V5 onto A2, the unused pins held |
| `afe-shield.kicad_pcb` | the template's board outline, headers and holes; the PCB phase draws on it |
| `models/afe-models.lib` | simulation models, placeholders until the vendor models are in, and marked so |
| `sim/stage_a.cir`, `sim/run.sh` | the phase A1 checks: `sim/run.sh` exports the netlist from the schematic and runs ngspice on it |

Open the project in KiCad to edit; the sheets are ordinary KiCad
files. `sim/run.sh` needs `kicad-cli` and `ngspice` on `PATH`.
