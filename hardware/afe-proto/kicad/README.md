# AFE shield, KiCad 10 project (round 1)

**Fixed version: AFE full range design 01 (FR-01)**, recorded in [DESIGN-01.md](DESIGN-01.md).

Generated, not hand-drawn. `design.py` is the one source: every part, its
value, LCSC code, footprint and the net on each pin. The generators write
the KiCad files from it, and `check.py` reads them back through KiCad.

| file | role |
|---|---|
| `design.py` | parts and connectivity. Values and designators are `../whatif/bom.txt`'s; connectivity is the simulated circuit's (`../docs/architecture.md`, `../sim/`) |
| `build_sch.py` | writes `afe-proto.kicad_sch`, the project file, `sym-lib-table` and `lib/afe.kicad_sym` (TMUX1119, ADS124S08, OPA354) |
| `build_pcb.py` | writes `afe-proto.kicad_pcb`: outline, every footprint at its `layout.py` position, every pad on its schematic net, `lib/afe.pretty` (the XIO0 socket). **Not routed** |
| `layout.py` | the placement: each part's position and rotation, chosen from its pinout and signal flow with the reason beside it, and the hand-drawn routes (`PREROUTE`, `PREVIA`) for what a grid router cannot do |
| `route.py` | routes a placed board: the hand routes first, a via to the GND plane from every SMD ground pad, then a grid router with rip-up and reroute; pours GND on both layers. Refuses a board that already carries copper |
| `layout_view.py` | an SVG of the board or a window of it, for review: courtyards (red where two overlap), pads, ratsnest or tracks |
| `check.py` | ERC, schematic netlist against `design.py`, BOM against `bom.txt`, board pads against the schematic, DRC with schematic parity, header positions against V03; each check broken on purpose first |
| `render/` | 3D renders and the schematic PDF |
| `3d/` | 3D models KiCad's library lacks, with source, hash and licence (`3d/SOURCES.md`) |

```sh
cd hardware/afe-proto/kicad
python3 -I build_sch.py && kicad-cli sch upgrade afe-proto.kicad_sch
/usr/bin/python3.14 -I build_pcb.py      # pcbnew is built against the system Python 3.14
python3 -I route.py                      # optional: routes the placed board (minutes); check.py's P2 allows unrouted
python3 -I check.py --pcb --frozen       # ends in ALL PASS; --frozen rebuilds from source and compares bytes
kicad-cli pcb render --quality high --rotate '-50,0,-35' --perspective -o render/afe-iso.png afe-proto.kicad_pcb
```

Edit `design.py` or the generators, never the KiCad files. Once layout
starts in the KiCad GUI, the board leaves the generator: from then on
`build_pcb.py` must not be re-run over it.

Known, listed in the checks with their reasons:
- One ERC exclusion: the LM27762's PGOOD is tied to GND as its datasheet asks when unused.
- The BNC footprint is the KH-BNC50-3511's, drawn from Kinghelm's drawing (`lib/afe.pretty`). It has no 3D model: EasyEDA's is licensed for JLCEDA/EasyEDA only. Its silkscreen crosses the board edge, the one DRC item allowed (J1-J3).
- The XIO0 socket footprint swaps odd and even pad numbers. KiCad's socket has pin 2 at -2.54 mm; the Due has it at +2.54. Its silkscreen pin-1 mark lands on pin 2.
- MH1 uses the ISO7380 courtyard (5.7 mm head). The plain M3 courtyard overlaps ADCH0's and XIO0's there. The M3 x 5 pan head is 5.6 mm *(check)*.

Own work, CC BY-SA 4.0.
