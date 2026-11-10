# Arduino Due hardware references

Use the **[V03 KiCad 10 project](v03/Arduino-DUE-V03.kicad_pro)** as the working
Due PCB reference for the owner's board. [V03 notes and checks](v03/README.md)
describe the conversion and its limits.

On 2026-11-01 the owner reported **DUE R3** silkscreen, an **AMS1117**
regulator, a separate inductor and a **six-pin IC2**, with no IC5 found.
That power-supply layout supports selecting V03: its source has a six-pin
LM2734Y at IC2 and a separate 10 uH L4. V02g instead uses an MPM3610 at
IC5. The V03 source specifies an NCP1117 at IC4; the reported AMS1117 is
a component substitution. R3 lettering alone does not identify the CAD
revision, and the observed supply layout does not verify every component
or connection. [Owner observation record](hardware-observations.json).

| Reference | Role |
|---|---|
| [v03/](v03/README.md) | Working reference for this board: KiCad project and PCB, original EAGLE sources, import script, checker and provenance |
| [v02g/](v02g/README.md) | Alternate archived revision, organized in the same way; retain for comparison |
| [models/](models/README.md) | 119 V03 model assignments: 18 assembly bodies, 91 standard package bodies and 10 simplified special parts; sources and exclusions recorded |

Both PCB conversions retain component values, embedded 2D footprints,
placements and nets. V03 assigns 119 component bodies; V02g has no 3D
assignments. Neither includes a converted native KiCad schematic; the original EAGLE schematics
are retained under each revision's `source/` directory.

Download ZIPs are intentionally omitted. Original extracted EAGLE files
remain under each revision's `source/`; source STEP geometry remains under
`models/assembly/`. Provenance records retain the original download names
and hashes. Neither opening the CAD nor regenerating it requires a ZIP or Git LFS.

These are reference conversions, not fabrication-qualified projects.
Use physical continuity checks before acting on the reference network.
In particular, BR1 schematic pins **1 / C / 2** correspond to PCB pads
**1 / 2 / 3**. The optional external-reference bridge is PCB **1-2** with
JR1 removed; the current AFE plan keeps the Due stock and JP101 open.

The [AFE plan](../../../docs/afe-plan.md) and the [AFE shield PCB](../../afe-proto/README.md) use V03
for Due mating and reference inspection.
