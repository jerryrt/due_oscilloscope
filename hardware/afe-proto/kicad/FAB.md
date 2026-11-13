# AFE version 1 (COPPIA AFE-1 REV A): the fabrication set for JLC

One command, in the pinned image, from the repository root:

```sh
docker/pcb/run.sh -m 2G -t 300 bash hardware/afe-proto/kicad/fab/build_fab.sh
```

It runs `pcbtools/fab.py --design v1` (kicad-cli 10.0.8, the engine version 2 uses) on `kicad/afe-proto.kicad_pcb`, writes `kicad/fab/out/COPPIA-AFE-1-REVA-fab.zip` (ignored by git),
writes `kicad/fab/manifest.json` (committed) and verifies the zip. `tests/pcbtools/test_fab_v1.py` rebuilds the zip, checks the members, the outline size from the configuration
(100 x 62.34 mm), the drill files against the holes counted from the board text, the BOM and CPL against the board's JLC-assembled footprints, bom.md against the order file,
and compares the fresh build with the manifest: **rebuild and commit the manifest whenever the board or `bom/v1/COPPIA-AFE-1-REVA-bom.csv` / `-cpl.csv` change** (those two
files and `bom/v1/order-5-100.md` come from `python3 -I v2/bom/bom.py --order`). The zip is not committed (about 114 kB; the manifest is enough to prove a rebuild is the same file).

Options are those of `docs/jlcpcb.md` section 1: Gerber with Protel extensions, 4.6 format, extended X2 and netlist attributes, no drill marks, scale 1:1; Excellon in mm,
absolute origin, decimal zeros, PTH and NPTH in separate files, alternate mode for ovals. That page cites a KiCad 9 article; no KiCad 10 article was found *(check)*.
The plot time that kicad-cli writes into the headers is replaced by 2000-01-01, entries are sorted and carry a fixed date and mode, so the zip is byte-identical between
runs (tested). The names come from the board configuration (`NAME`, `MODEL`, `REV` in `pcbtools/boards/v1.py`), so a new revision letter renames every file; the zip is flat; JLC
takes the BOM and CPL in a separate upload step, so leave those two out of the Gerber upload.

| member | size |
|---|---|
| `COPPIA-AFE-1-REVA-B_Cu.gbl` | 172196 |
| `COPPIA-AFE-1-REVA-B_Mask.gbs` | 3635 |
| `COPPIA-AFE-1-REVA-B_Silkscreen.gbo` | 4918 |
| `COPPIA-AFE-1-REVA-Edge_Cuts.gm1` | 723 |
| `COPPIA-AFE-1-REVA-F_Cu.gtl` | 49926 |
| `COPPIA-AFE-1-REVA-F_Mask.gts` | 15001 |
| `COPPIA-AFE-1-REVA-F_Paste.gtp` | 11412 |
| `COPPIA-AFE-1-REVA-F_Silkscreen.gto` | 412435 |
| `COPPIA-AFE-1-REVA-NPTH.drl` | 406 |
| `COPPIA-AFE-1-REVA-PTH.drl` | 2926 |
| `COPPIA-AFE-1-REVA-bom.csv` | 1916 |
| `COPPIA-AFE-1-REVA-cpl.csv` | 3498 |

Holes, counted independently from the board file: plated 160 (59 x 0.3 mm vias and pads, 95 x 1.0 mm, 6 x 2.2 mm), non-plated 2 (2.7 mm). The top layer carries no copper pour; the bottom
is the one ground plane.

U401 (the LM27762, WSON-12) has no 3D model in KiCad 10; the board points it at the project's own VRML stand-in, `lib/afe.3dshapes/WSON-12-1EP_3x2mm_P0.5mm_standin.wrl` (`MODEL_BY_REF` in `pcbtools/boards/v1.py`, applied by `v2/layout/set_models.py --design v1`). It is for the renders only: a KiCad STEP export leaves U401 out, and nothing in the fabrication set uses it.

## Ordering options (fixed by the spec lead, cost first)

1.6 mm FR-4, 2 layers, 1 oz copper, green solder mask, white silk, lead-free HASL. JLC assembles 0.5 mm-pitch WSON and MSOP parts on HASL routinely, so ENIG is not chosen up front; it
is the one change to make if, and only if, JLC's DFM flags the WSON. The silk carries `JLCJLCJLCJLC` on the bottom, where JLC prints its order number.

## Before ordering (the owner's list; none of it is checked by a test)

1. Upload the zip's Gerbers and drills to JLC's viewer and pass its DFM check; look at the paste layer, the 1.0 mm silk text, the Due's pin names in the two bands and the mask openings of the WSON and MSOP footprints. Switch the finish to ENIG only if JLC's DFM flags the WSON.
2. CPL origin and rotation: the CPL is KiCad's position data with Y negated, not JLC's per-package corrected rotation. Check every polarised part (BAV99, SOT-23, TPH2502, ADS1115, LM27762, REF3030E) in the quote tool's placement preview *(check)*.
3. Stock on the chosen LCSC numbers, ADS1115 (C37593) and TPH2502 (C118223) first, on the day of the order; the BOM prices are read dates, not quotes *(check)*. The 0 ohm bridge C21189 was priced from a domestic ladder read 2026-11-13.
4. Copper to the routed edge is 0.45 mm in the project's rules against JLC's 0.2 mm minimum; JLC's published capability list should be compared with the project's DRC rules once more *(check)*. The bands (4.5 mm on each long edge) carry no top copper and are filled on the bottom.
5. Unpriced owner hardware: the M2.5 standoffs and screws, and the J501 CAL pin strip and its shunt have no price in the repository; the BNCs and the stacking headers are owner-fitted and outside the BOM and CPL.
6. The two documented MH602 courtyard overlaps in the DRC (owner caliper check pending, the screw is optional), and the five recorded silk overlaps and the C301 / C304 label exception (`kicad/gate3/notes.md`).
7. Write the serial of each board in the S/N box before calibrating it: the per-board calibration is keyed to it.
