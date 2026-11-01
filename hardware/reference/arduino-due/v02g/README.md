# Arduino Due V02g in KiCad

Open **[DUE_V02g.kicad_pcb](DUE_V02g.kicad_pcb)** directly in the
KiCad 10 PCB Editor to inspect the complete Due board, its headers,
components, copper and mounting holes. This is an alternate archived
revision. Use the [V03 PCB](../v03/Arduino-DUE-V03.kicad_pcb) as the working
reference for the owner's board; [selection evidence](../hardware-observations.json).

For the other retained board revision, open the separate
**[V03 KiCad PCB](../v03/Arduino-DUE-V03.kicad_pcb)**.
[V03 conversion notes and checks](../v03/README.md) document its source,
layer corrections and limitations. V03 now assigns 119 component bodies;
this alternate V02g reference has no 3D model assignments.

Arduino's [Due documentation](https://docs.arduino.cc/hardware/due/) links
to [this official CAD archive](https://docs.arduino.cc/static/f051671bbed80ddf7352991d62cb0d5c/A000056-cad-files.zip).
Downloaded on 2026-10-30, it contained **DUE_V02g** in EAGLE format.
The original extracted EAGLE files and license metadata are retained;
the ZIP itself was removed at the owner's request.
The KiCad board here is a local conversion using KiCad **10.0.6**;
it is not an Arduino-published native KiCad design.

| File | Purpose |
|---|---|
| `DUE_V02g.kicad_pcb` | Converted full Due PCB, with embedded footprints |
| `DUE_V02g.kicad_dru` | Importer-generated clearance rules; not a complete verified KiCad project setup |
| `source/DUE_V02g.brd` | Original EAGLE PCB |
| `source/DUE_V02g.sch` | Original EAGLE schematic; no native KiCad schematic conversion is included |
| `source/License.textClipping` | Publisher's original license metadata |
| `sources.json` | Source URL, date, sizes and SHA-256 hashes |
| `import-board.py` | Reproduce the conversion with KiCad 10.x |
| `check-board.py` | Verify source component positions, pad nets, native reload and SVG export |
| `import-report.json` | Original importer report, before the drawing-layer corrections below |
| `validation.json` | Component-position, pad-net and reload verification results |

Recreate the native board from the repository root:

```sh
python3 hardware/reference/arduino-due/v02g/import-board.py
```

Set `KICAD_CLI` if the required executable is not on PATH or at the default
macOS application location. Reimporting overwrites the converted PCB.

Verify using Python with KiCad 10's `pcbnew` module (bundled on this Mac):

```sh
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 hardware/reference/arduino-due/v02g/check-board.py
```

## Conversion checks and limitations

All 141 source components are present at their original coordinates,
within 0.000002 mm serialization tolerance. All 605 source pad-to-net
assignments match. Six additional footprints represent the source's
six standalone holes. KiCad appends `0` to 15 references without a
numeric suffix, such as `POWER` becoming `POWER0`; the mapping is retained
in `validation.json`. Native-board reload and top-layer SVG export passed.

The importer reports no warnings or errors, but initially writes 140
plain-board graphics onto an `UNDEFINED` layer. The reproduction script
identifies their original layers by position and preserves them as:

- `User.1`: 139 graphics from EAGLE layer 114, `test-probe`.
- `User.2`: one line from EAGLE layer 42, `bRestrict`. This is a reference
  drawing only; it does **not** enforce a copper keepout in KiCad.

This is a reference conversion for inspecting the existing Due and
comparing shield geometry. The checks do not qualify the conversion for
fabrication or establish that a particular physical board revision matches.
Publisher copyright, trademark and license terms remain applicable.

The separate `Arduino-DUE-V03` source is extracted under
[`v03/source/`](../v03/source/), with its conversion under [`v03/`](../v03/README.md).
The revisions have different power-supply layouts and are not interchangeable.
The AFE assembly plan is in
[`hardware/afe-proto`](../../../afe-proto/README.md), based on the corrected
[Mega proto carrier](../../../mega-proto-carrier/README.md).
