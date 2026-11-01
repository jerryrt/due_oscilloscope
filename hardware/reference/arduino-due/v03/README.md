# Arduino Due V03 in KiCad

Open **[Arduino-DUE-V03.kicad_pro](Arduino-DUE-V03.kicad_pro)** in the
**KiCad 10 Project Manager**, then double-click `Arduino-DUE-V03.kicad_pcb`
in the project tree. You can also open the
[PCB](Arduino-DUE-V03.kicad_pcb) directly in the PCB Editor.
This is the working Due reference for the
owner's board. The alternate [V02g board](../v02g/DUE_V02g.kicad_pcb)
is retained for comparison.

The owner reported DUE R3 silkscreen, an AMS1117 regulator, a separate
inductor and a six-pin IC2 on 2026-11-01. That matches V03's power-supply
topology rather than V02g's IC5 module. The source specifies NCP1117 at
IC4; AMS1117 is a reported substitution, and IC2's exact marking is
unreported. [Observation record](../hardware-observations.json).

The source is `Arduino-DUE-V03` from the retained
[Arduino reference-design archive](../../../../docs/datasheets/arduino/arduino-Due-Reference-design.zip).
Duplicate loose ZIP downloads were removed after verifying they match
this canonical archive. Original publisher notices remain in those
source files. This is a local conversion, not an Arduino-published native
KiCad design.

| File | Purpose |
|---|---|
| `Arduino-DUE-V03.kicad_pro` | Project entry point and shared settings; initialized from KiCad 10.0.6's default template |
| `Arduino-DUE-V03.kicad_pcb` | Full converted PCB with embedded 2D footprints |
| `Arduino-DUE-V03.kicad_dru` | Importer-generated rules, not a fully verified project setup |
| `source/Arduino-DUE-V03.brd` | Unmodified EAGLE PCB |
| `source/Arduino-DUE-V03.sch` | Unmodified EAGLE schematic; no native KiCad schematic conversion |
| `sources.json` | Archive provenance, file hashes and layer-recovery notes |
| `import-report.json` | KiCad import statistics and diagnostics |
| `validation.json` | Source correspondence, reload and SVG-export checks |
| `import-board.py` / `check-board.py` | Recreate the board / verify it |

The PCB was originally imported in standalone mode, which did not create
a project file. The added `.kicad_pro` uses the same basename as the PCB
so KiCad opens them together. It starts with KiCad defaults; fabrication
rules and source net-class constraints have not been qualified. The
importer-generated `.kicad_dru` remains alongside it. Reimporting the board
preserves the project file and its settings.

The `.kicad_prl` file is local editor/view state and is ignored by Git.
There is still no native `.kicad_sch`; the original EAGLE schematic is
retained under `source/`. Creating a project file does not convert it.

KiCad **10.0.6** imports all **129 source components**, plus six footprints
for standalone mounting holes. All **591 source pad-to-net assignments**
match, and all component positions match within 0.000002 mm. Sixteen
references without numeric suffixes gain a trailing `0`; `validation.json`
records the mapping. Native load/save/reload and top-layer SVG export pass.
The import report contains no warnings or errors.

The importer puts seven unique straight-line restriction geometries on
an invalid `UNDEFINED` layer, merging front/back duplicates. The script
recovers all ten source lines as reference drawings: five front lines on
`User.1`, five back lines on `User.2`. **These lines do not enforce copper
keepouts.** Imported circular rule areas are separate. This board is for
reference and inspection; it has not been qualified for fabrication.
The owner's power-layout observations support using it as the reference;
full-board geometry and electrical continuity remain to be checked physically.

## 3D view

**119 component models are assigned.** The owner-supplied STEP assembly provides 18:
the MCU, both USB connectors, barrel jack, main headers, debug/SPI/ICSP/JTAG
headers, two large capacitors and reset switch. Another 91 assignments use
standard KiCad package bodies, and 10 use documented simplified bodies for
the fuses, power inductor, small crystal, ESD protectors and erase switch.
Reopen the PCB from disk
and choose **View -> 3D Viewer** (Option+3 on macOS).

![V03 with component bodies](preview/3d-top.png)

The owner reported on 2026-11-01 that the initial 18-model preview passed a first visual
inspection and matches the physical board well. This is an overall visual
check, with no dimensional measurements or electrical checks reported.
The expanded population shown above has not yet been inspected by the owner.
[Observation record](../hardware-observations.json).

The source board is 101.6 x 53.34 mm and its six mounting-hole centers
match V03's EAGLE source within 0.000006 mm. Bodies retain the source's
small placement offsets, including the MCU's 0.020 mm center offset.
These are CAD correspondence checks, not physical measurements. Connector
heights, detailed pin fit and component substitutions are not qualified.

The supplied assembly's PCB slab is excluded so the native PCB and copper
remain visible. Its oversized LED bodies and generic capacitor bodies are
also excluded; standard package and simplified bodies now fill the small
components. Four bare fiducials and six source NM items (including BR1)
remain without bodies. Generic
plastic/metal colors improve visibility; they do not identify actual
materials or capacitor values. New package models align polarity and pin-1
to the source pad layout; installed markings and body heights remain
unqualified. In particular the tantalum B-case bodies and erase-switch
height are approximations. The
[model preparation/alignment record](../models/README.md) lists all assets
and exclusions. [Attachment evidence](models-3d.json) confirms every
non-model line of the PCB file is unchanged.

`attach-models.py` restores these assignments without rewriting the native
geometry. `import-board.py` also reapplies them when `models/alignment.json`
is present. The checker verifies all assigned file paths and hashes.

From the repository root, recreate the conversion (overwrites this V03
PCB and its import/provenance records):

```sh
python3 hardware/reference/arduino-due/v03/import-board.py
```

Then verify with KiCad's bundled Python on this Mac:

```sh
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 hardware/reference/arduino-due/v03/check-board.py
```

On another system use Python with KiCad 10's `pcbnew` module available.
Set `KICAD_CLI` if the executable is not on PATH or at the default macOS
location. The checker writes `validation.json` and uses temporary files
for its reload and SVG checks.
