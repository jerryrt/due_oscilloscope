# AFE version 2: the fabrication set for JLC

One command, in the pinned image, from the repository root:

```sh
docker/pcb/run.sh -m 2G -t 300 bash hardware/afe-proto/v2/layout/fab/build_fab.sh
```

It runs `pcbtools/fab.py` (kicad-cli 10.0.8) on `v2/layout/integrated/afe-v2-integrated.kicad_pcb`, writes `v2/layout/fab/out/COPPIA-AFE-2-REVA-fab.zip` (ignored by git),
writes `v2/layout/fab/manifest.json` (committed) and verifies the zip. `tests/pcbtools/test_fab.py` rebuilds the zip, checks the members, the outline
size from the configuration, the drill files against the holes counted from the board text, and compares the fresh build with the manifest: **rebuild and
commit the manifest whenever the board or `v2/bom/COPPIA-AFE-2-REVA-bom.csv` / `-cpl.csv` change.** The zip is not committed (about 170 kB; the manifest is enough
to prove a rebuild is the same file).

Options are those of `docs/jlcpcb.md` section 1: Gerber with Protel extensions, 4.6 format, extended X2 and netlist attributes, no drill marks, scale 1:1;
Excellon in mm, absolute origin, decimal zeros, PTH and NPTH in separate files, alternate mode for ovals. That page cites a KiCad 9 article; no KiCad 10 article
was found *(check)*. The plot time that kicad-cli writes into the headers is replaced by 2000-01-01, entries are sorted and carry a fixed date and mode, so
the zip is byte-identical between runs (tested). The names come from the board configuration (`NAME`, `MODEL`, `REV`), so a new revision letter renames every file; the zip is flat; JLC takes the BOM and CPL in a separate upload step, so leave those two out of the Gerber upload.

| member | size |
|---|---|
| `COPPIA-AFE-2-REVA-B_Cu.gbl` | 165683 |
| `COPPIA-AFE-2-REVA-B_Mask.gbs` | 3642 |
| `COPPIA-AFE-2-REVA-B_Silkscreen.gbo` | 4930 |
| `COPPIA-AFE-2-REVA-Edge_Cuts.gm1` | 735 |
| `COPPIA-AFE-2-REVA-F_Cu.gtl` | 330249 |
| `COPPIA-AFE-2-REVA-F_Mask.gts` | 13936 |
| `COPPIA-AFE-2-REVA-F_Paste.gtp` | 10402 |
| `COPPIA-AFE-2-REVA-F_Silkscreen.gto` | 401960 |
| `COPPIA-AFE-2-REVA-NPTH.drl` | 406 |
| `COPPIA-AFE-2-REVA-PTH.drl` | 2689 |
| `COPPIA-AFE-2-REVA-bom.csv` | 1917 |
| `COPPIA-AFE-2-REVA-cpl.csv` | 3195 |

Holes, counted independently from the board file: plated 144 (43 x 0.3 mm vias and pads, 95 x 1.0 mm, 6 x 2.2 mm), non-plated 2 (2.7 mm).

## Ordering options (fixed by the spec lead, cost first)

1.6 mm FR-4, 2 layers, 1 oz copper, green solder mask, white silk, lead-free HASL. JLC assembles 0.5 mm-pitch WSON and MSOP parts on HASL routinely, so
ENIG is not chosen up front; it is the one change to make if, and only if, JLC's DFM flags the WSON.

## Before ordering (the owner's list; none of it is checked by a test)

1. Upload the zip's Gerbers and drills to JLC's viewer and pass its DFM check; look at the paste layer, the 1.0 mm silk text and the mask openings of the WSON and MSOP footprints. Switch the finish to ENIG only if JLC's DFM flags the WSON.
2. CPL origin and rotation: the CPL is KiCad's position data with Y negated, not JLC's per-package corrected rotation. Check every polarised part (BAV99, SOT-23, TPH2502, ADS1115, LM27762, REF3030E) in the quote tool's placement preview *(check)*.
3. Stock on the chosen LCSC numbers, ADS1115 (C37593) and TPH2502 (C118223) first, on the day of the order; the BOM prices are read dates, not quotes *(check)*.
4. Copper to the routed edge is 0.45 mm in the project's rules against JLC's 0.2 mm minimum; JLC's published capability list should be compared with the project's DRC rules once more *(check)*.
5. Unpriced owner hardware: the M2.5 standoffs and screws, and the J501 CAL pin strip and its shunt have no price in the repository; the BNCs and the stacking headers are owner-fitted and outside the BOM and CPL.
6. The two documented MH602 courtyard overlaps in the DRC (owner caliper check pending, the screw is optional).
7. The three new capacitor and resistor numbers (C1647, C1671, C22808) have an international price read only; their domestic ladder was not read (jlc-smt.com did not answer on 2026-11-13) *(check)*.
8. The values of D-V2-17 rest on simulations: VT-10 (REF output impedance) and VT-23 (top of the range) are the first bench measurements.
