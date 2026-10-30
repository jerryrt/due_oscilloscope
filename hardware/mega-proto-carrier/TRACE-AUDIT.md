# P3.5: stripped-board trace audit

Sources: front [IMG_2135](photo/IMG_2135.jpeg), control [2136](photo/IMG_2136.jpeg), corner [2137](photo/IMG_2137.jpeg), digital [2138](photo/IMG_2138.jpeg); mirrored back corner [2139](photo/IMG_2139.jpeg), control [2140](photo/IMG_2140.jpeg), digital [2141](photo/IMG_2141.jpeg). The four earlier photos remain evidence. Originals are unchanged; hashes are recorded in `model-evidence.json`.

## Wiring revisions

| Region | P3.1 representation | Replaces / resolves |
|---|---|---|
| Corner lower left | J9.2 → SPI50-F → V50 → SPI50-B → D50 | Open O01 |
| Corner upper middle | J9.3 → SPI51-F → V51 → SPI51-B → D51 | Open O02 |
| Corner lower middle | J9.4 → SPI52-F → D52 | Open O03 |
| D13 / STAT | STAT-B starts at inner J1.3, with no B.Cu departure from J10.3; STAT-F reaches R3.2 | STAT-B-RETURN, O04/O05 and UB-03 |
| Reset pads | RESET-F reaches SW1.2; RESET-TOP-BAR joins SW1.1/2 | Hidden switch copper now visible |
| Switch lower pair | GND-BOTTOM-BAR joins SW1.3/4; SW-GND-B reaches J4.4 | Incorrect RESET-B connection deleted |
| Corner reset | J9.6 → CORNER-SW-B → SW1.1 | Open O06 |
| 103 resistor | R1.1 → PULLUP-LEFT → J9.1; R1.2 → PULLUP-RIGHT → SW1.1 | O07/O08; R1-left / R2-right front link now establishes +5V |
| PWR resistor | R2.2 → PWR-RES-RIGHT → J4.3 / +5V | O09 |
| LED common | LED-COMMON + LED-COMMON-RIGHT → SW1.3 / GND | O10 / UF-01 |
| Corner ground | J9.5 → CORNER-GND-F → VCORNER → CORNER-GND-B → VLED | UB-02; front/back rounded features paired |
| Corner to upper header | J9.5 → CORNER-HEADER-B → J10.2 / GND | Endpoint confirmed by owner; final bends under plastic estimated |
| R1/R2 supply link | R1-R2-SUPPLY joins R1.1 to R2.2 on F.Cu | IMG_2136 resolves corner +5V |
| Bottom digital 5V pair | 5V-BOTTOM moved to B.Cu; 5V-PERIMETER joins J13.3 to J8.39 | IMG_2138 has no front bar; IMG_2140/2141 show back bar/feed |
| Power grounds | POWER-GND-BAR joins main power-header ground pads 4/5 | Newly exposed front bar |

The 28 SMD fanouts, 46 paired-header spokes, 32 digital fanouts, digital end crossbars, 5V-EDGE, GND-PERIMETER and LED series connections remain represented. Their endpoints and geometry were updated with the placement correction. There are 115 supplemental route sections and no remaining unclassified fragments. All route endpoints are now identified; hidden bend geometry remains estimated.

J9 numbering is spatial: 1/3/5 top row, 2/4/6 bottom row. It does not assume a standard ISP pinout. J9.1 is now +5V: IMG_2136 shows a front diagonal from R1 left to R2 right, which joins the power-header +5V feed. This assignment follows visible copper rather than an assumed ISP pinout.

J7.31 entry-angle review (P3.4): SPI50-B runs diagonally from V50, then enters pad mid-height horizontally. This is the middle-right edge in the flipped B.Cu view and the left edge in canonical top view. The owner supplied this geometry correction; the D50 connection is unchanged.

Ground-perimeter review (P3.5): GND-PERIMETER moves from y=48.2 to 47.2 mm, away from the socket row. It leaves J13.4 vertically, uses a short chamfer into the horizontal lane and reaches J7.35 on a 45-degree approach. Native pad-to-track edge distance increases from 0.286 to 1.286 mm; all other route geometry and nets are unchanged. See `ground-route-clearance.json`.

## Placement revision

P2.1 conflated the along-row 2.54 mm pitch with the separation of the parallel single-row headers. P3 uses an estimated 4.064 mm paired-row gap. J3 lies between D22/D23 and D24/D25, correcting the prior alignment statement. Digital 5V remains level with J12. Grid registration moves to (3.8, 8.3) mm; passive pads, switch pads, empty SMD field, holes and SPI transitions were re-registered.

Manual projective landmarks are reproducible in `photo_registration.py` / `photo-registration.json`. Native coordinates are rounded estimates; the 103 × 55 mm owner-measured outline is retained. These images do not provide calibrated manufacturing dimensions.

## Remaining checks

Q02 records the owner-confirmed J9.5 → J10.2 / GND endpoint. This is an endpoint identification, not a supplied resistance reading. Q05 marks the now photo-resolved R1/R2 supply link for meter confirmation. The owner confirmed a physical crack near J9 on 2026-10-30; Q09 marks nearby SPI/reset routes for continuity checks. Copper breaks remain unverified. The confirmation is recorded in `owner-observations.json`. LED polarity, transition features, physical fit and all proposed connections await measurement. SW1/J9 were removed only on the routing-photo specimen; reverse main-header pins remain there. The default KiCad assembly represents the normal boards with SW1/J9 and main headers fitted. The confirmed crack applies to the photo specimen; other boards have not been assessed for that damage.

`wiring-evidence.json` is the route inventory. `continuity.csv` and the User.5 Q01-Q12 overlay are the current review aids. Earlier worksheets and alignment assertions are archived under `evidence/` for comparison, not current instructions.
