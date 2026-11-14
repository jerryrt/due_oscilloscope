# Task: five status LEDs on AFE-2

Add five LEDs to the COPPIA AFE-2 shield: one shows that the shield's
power is up, and four are set by Due GPIO pins, their meanings to be
decided later.

- The four status LEDs may change at any time, even during a capture,
  with no measurable effect on the scope or the AWG.
- Lowest cost: Basic parts, as few new part types as possible.
- Before you design anything, write one page on what these LEDs could
  do to the analog side, with numbers, and have it reviewed.
- Then do the whole flow yourself, through simulation, layout,
  manufacturing files, 3D renders and a bench test plan.

## Files you are given

| Folder | What |
|---|---|
| `afe-proto/v2/kicad/` | the schematic project, `afe-v2.kicad_pro` |
| `afe-proto/v2/layout/integrated/` | the board, `afe-v2-integrated.kicad_pcb` |
| `afe-proto/kicad/lib/` | the libraries and 3D models |
| `due/` | the Arduino Due 3D model, for the stacked render |
| `sim/` | `scope_v2.cir`, the scope channel's SPICE netlist; run it from that folder with `ngspice -b scope_v2.cir` |
| `models/` | SPICE models of the board's parts: TPH2502, LM27762, REF3030E, BAV99, ADS1115 |
| `datasheets/` | the datasheets of those parts and of the SAM3X8E |
| `docs/` | `due-header-table.md` (the Due's pins), `afe.md` and `afe-v2.md` (the shield's requirements and layout rules) |
| `jlc-basic.csv` | the board house's Basic parts |

Tools: KiCad 10 and ngspice.
