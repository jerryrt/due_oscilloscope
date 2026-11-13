# AFE shield version 1, KiCad 10 project

**Fixed version: AFE full range design 01 (FR-01)**, recorded in [DESIGN-01.md](DESIGN-01.md).

This folder holds version 1's design data and its KiCad files. The tools
that build and check them live in [`../pcbtools`](../pcbtools/README.md)
and run in the pinned PCB image (`docker/pcb/run.sh`). The scripts that
used to live here (`build_sch.py`, `build_pcb.py`, `check.py`,
`lr_check.py`, `route.py` and the rest) were replaced by `pcbtools` and
deleted; the frozen copies under `../tests/fixtures/` are the reference
the replacements were proved against.

| file | role |
|---|---|
| `design.py` | parts and connectivity: every part, its value, LCSC code, footprint and the net on each pin. The one source |
| `layout.py` | the placement data: each part's position and rotation, with the reason beside it |
| `layout_view.py` | an SVG of the board or a window of it, for review |
| `afe-proto.kicad_sch`, `.kicad_pro`, `.kicad_pcb`, `lib/`, `*-lib-table` | the KiCad files, generated from the data by `pcbtools` |
| `render/` | renders and the schematic PDF |
| `3d/` | 3D models KiCad's library lacks, with source, hash and licence (`3d/SOURCES.md`) |

Board configuration (rules tables, fences, board setup) is
`../pcbtools/boards/v1.py`. Build, check and route with the commands in
the `pcbtools` README: `pcbtools.schematic` and `pcbtools.build` write
the files, `pcbtools.schematic_check` and `pcbtools.check --config v1`
check them, and routing uses the image's Freerouting flow
(`docker/pcb/freeroute.sh`).

Edit `design.py`, `layout.py` or `boards/v1.py`, never the generated
KiCad files.

Known, listed in the checks with their reasons:
- One ERC exclusion: the LM27762's PGOOD is tied to GND as its datasheet asks when unused.
- The BNC footprint is the KH-BNC50-3511's, drawn from Kinghelm's drawing (`lib/afe.pretty`). It has no 3D model: EasyEDA's is licensed for JLCEDA/EasyEDA only.
- The XIO0 socket footprint swaps odd and even pad numbers. KiCad's socket has pin 2 at -2.54 mm; the Due has it at +2.54. Its silkscreen pin-1 mark lands on pin 2.

Own work, CC BY-SA 4.0.
