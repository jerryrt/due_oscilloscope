# AFE full range design 01 (FR-01)

The complete round-1 AFE shield, fixed on 2026-11-11 at the owner's request.
It covers both scope channels with both ranges (±5 V and ±1.25 V), the
AWG output, the calibration block and the power. The schematic is
validated, and every part is placed on the board. **The board is not
routed.** It sits on main after db85f57, the commit range that holds the
simulations it is drawn from.

## What it is

| item | value |
|---|---|
| Parts | 180 symbols: 159 JLC placements of 23 types, 3 BNCs and 7 headers fitted by the owner, 4 footprints left unfitted (D9-D11, R81), 6 test points, 1 standoff hole |
| Nets | 81 |
| Board | 100 x 53.34 mm (Due x 17-117), 2 layers, BNCs overhanging the right edge |
| Values and part codes | `../whatif/bom.txt`, plus D7 and D8 (below) |
| Connectivity | the simulated circuit (`../docs/architecture.md`, `../sim/`), reviewed independently against the simulation netlists and the datasheet pin tables: no wrong connection found |

## Validation (`python3 -I check.py --pcb --frozen`: ALL PASS)

- ERC: 0 errors, 0 warnings, 1 documented exclusion.
- KiCad's netlist equals `design.py`, net for net and pin for pin, and part values, footprints and LCSC codes match.
- `bom.txt`: every designator and LCSC code matches.
- Board: every pad matches the schematic; DRC is clean with the schematic consistency check; the Due header pads sit exactly on V03; nothing lies off the board; 360 connections are unrouted.
- Rebuilt from source, the schematic and board come out byte for byte the same as the committed files.
- Each check was broken on purpose (9 arms) and failed as it should.

## Known items carried by this version

- **D7 and D8**, the ratio-switch clamps (architecture.md C1-q, C1-r), are fitted but are not in `bom.txt`: +2 placements, no new type, about $0.03 per board.
- **ERC exclusion:** LM27762 PGOOD is tied to GND as its datasheet asks when unused.
- **BNC footprint is a stand-in** (Amphenol B6252HB). The KH-BNC50-3511 drawing is unread *(check before ordering)*.
- **XIO0 footprint** exchanges odd and even pad numbers to match the Due. Its silkscreen pin-1 mark sits on pin 2.
- **MH1** uses the ISO7380 courtyard; the M3 x 5 pan head size is *(check)*.
- **U9's 3D model** is LQFP-32 5 x 5 mm, a stand-in for the TQFP (3d/SOURCES.md).
- **Assumed or placeholder values from bom.txt:** the range and ratio-switch pull-downs, the CS pull-up, and the IC decoupling marked "assumed".
- **Documents still behind this design:** architecture.md (k = 1/3 text, "buffered" ladder top) and due-header-table.md (taps A2..A9, D41, D37).

## File hashes (sha256)

| file | sha256 |
|---|---|
| `afe-proto.kicad_sch` | `e9f55cecfd6a95d33e9a784393325e5d062f80ce279c5fa345344c91be1528f1` |
| `afe-proto.kicad_pcb` | `a0b951e72bd8534013cc36d07d166f2e696904e008a3696dca474309ec489c91` |
| `afe-proto.kicad_pro` | `f95c8d75c67a7315ef2449e635f1ac4f6e7ac48eb6c35b85a436093578cfc966` |
| `lib/afe.kicad_sym` | `491c60cd01047d8914b014f75f0dded6a08c69a2bdc566b7df1adc952c35d789` |
| `lib/afe.pretty/PinSocket_2x18_P2.54mm_Vertical_DueXIO.kicad_mod` | `c7c72f9b90370767bbe5e74ff0969737589096505494bfb5888c4a6a262de182` |
| `3d/LQFP-32_5x5mm_P0.5mm.step` | `9f2be83a713ff62d2355f91718245c4e93f9a75ac14a804dc68810514dd9a3a3` |
| `design.py` | `3baa82e18526ab41ad5bb9306d33a6645a5bf63f70cfff644f53f42ad5752522` |
| `build_sch.py` | `b0e220ab9e93eb3d052275436a40cef9050de94d9c8ce928a7d1ef289f84ce6d` |
| `build_pcb.py` | `0234b35409e5f9d4eb1470a1327e085c21da3f5e46818eac3aa5a3e34f1d0684` |
