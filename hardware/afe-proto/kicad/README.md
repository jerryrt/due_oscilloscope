# AFE shield, KiCad 10 project (round 1)

**Fixed version: AFE full range design 01 (FR-01)**, recorded in [DESIGN-01.md](DESIGN-01.md).

Generated, not hand-drawn. `design.py` is the one source: every part, its
value, LCSC code, footprint and the net on each pin. The generators write
the KiCad files from it (`../pcbtools`, the one tool package), and `python -m pcbtools.schematic_check` reads them back through KiCad.

| file | role |
|---|---|
| `design.py` | parts and connectivity. Values and designators are `../whatif/bom.txt`'s; connectivity is the simulated circuit's (`../docs/architecture.md`, `../sim/`) |
| `layout.py` | the placement: each part's position and rotation, chosen from its pinout and signal flow with the reason beside it, and the hand-drawn routes (`PREROUTE`, `PREVIA`) for what a grid router cannot do |
| `layout_view.py` | an SVG of the board or a window of it, for review: courtyards (red where two overlap), pads, ratsnest or tracks |
| `render/` | 3D renders and the schematic PDF |
| `3d/` | 3D models KiCad's library lacks, with source, hash and licence (`3d/SOURCES.md`) |

The tools are the package `../pcbtools` (README there); the build data of this board (titles, header and BNC
positions, model overrides, the names the checks read) is `../pcbtools/boards/v1.py`, which today loads `design.py`,
`floorplan.py` and `layout.py` from the frozen fixture `../tests/fixtures/v1-34b2e51/` and will load these files when the
reviewed v1 layout is carried onto main. Run them in the image (`docker/pcb/run.sh`), never on a bench host:

```sh
cd hardware/afe-proto
python3 -m pcbtools.schematic_check --board v1 --project kicad --pcb --arms     # ERC, netlist, BOM, pad nets, DRC, V03 headers; arms break each on purpose
python3 -m pcbtools.merge --board v1 --base BASE.kicad_pcb --out OUT.kicad_pcb AWG=awg.kicad_pcb ...   # merge block boards
kicad-cli pcb render --quality high --rotate '-50,0,-35' --perspective -o kicad/render/afe-iso.png kicad/afe-proto.kicad_pcb
```

Edit `design.py` or `pcbtools`, never the KiCad files. Once layout starts, the board
leaves the generator: from then on `pcbtools.build` must not be run over it (edit it with `pcbtools.editor`).

Known, listed in the checks with their reasons:
- One ERC exclusion: the LM27762's PGOOD is tied to GND as its datasheet asks when unused.
- The BNC footprint is the KH-BNC50-3511's, drawn from Kinghelm's drawing (`lib/afe.pretty`). It has no 3D model: EasyEDA's is licensed for JLCEDA/EasyEDA only. Its silkscreen crosses the board edge, the one DRC item allowed (J1-J3).
- The XIO0 socket footprint swaps odd and even pad numbers. KiCad's socket has pin 2 at -2.54 mm; the Due has it at +2.54. Its silkscreen pin-1 mark lands on pin 2.
- MH1 uses the ISO7380 courtyard (5.7 mm head). The plain M3 courtyard overlaps ADCH0's and XIO0's there. The M3 x 5 pan head is 5.6 mm *(check)*.

Own work, CC BY-SA 4.0.
