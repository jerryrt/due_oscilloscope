# Checks marked in KiCad

Enable **User.5** in the PCB Editor. The **Carrier review questions R2** group contains
the circles, enlarged detail views and Q01-Q12 question cards. This layer adds no copper.

Use the point letters beside the circles when replying, for example:
`Q04: A and B are continuous; R3 right land connects to D13.`

All coordinates use the top view, with the small corner header at the upper left.
The enlarged views are drawing-only copies; they are not extra physical board parts.

| ID | What to check | Marked points |
|---|---|---|
| Q01 | PHOTO RESOLVED: J9 1=+5V, 2=D50, 3=D51, 4=D52, 5=GND, 6=RESET. Pad 1 reaches +5V through the R1-left / R2-right copper link. Confirm by meter. | A: J9.2 / SPI50-F; B: J9.3 / SPI51-F; C: J9.4 / SPI52-F; D: J9.6 / CORNER-SW-B; E: J9.1 / +5V via R1-R2-SUPPLY |
| Q02 | OWNER CONFIRMED: J9.5 reaches J10.2 / GND. The trace bypasses AREF. Bends under plastic are estimated; no resistance value was supplied. | A: J9.5 / CORNER-HEADER-B; B: J10.2 / GND (owner confirmed) |
| Q03 | PHOTO RESOLVED: A/B join corner GND to LED GND along the back edge. Confirm continuity and via details. | A: VCORNER / CORNER-GND-B; B: VLED / CORNER-GND-B |
| Q04 | PHOTO RESOLVED: back D13 trace starts at inner J1.3, not outer J10.3, then reaches R3 right. The J1/J10 pair is linked on the front. Confirm by meter. | A: STAT-B upper dogleg; B: STAT-B lower dogleg; C: VSTAT |
| Q05 | PHOTO RESOLVED: R1 left joins R2 right by a front diagonal, establishing +5V at R1 left and J9.1. R1 right remains RESET. Confirm the copper link by meter. | A: R1.1 left land; B: R1.2 right land; C: SW1.1 / PULLUP-RIGHT |
| Q06 | PHOTO RESOLVED: R2 right reaches power-header +5V via the exposed lower dogleg. Confirm R2.2 to J4.3. | A: R2.2 right land; B: PWR-RES-RIGHT dogleg |
| Q07 | PHOTO RESOLVED: left LED rail joins SW1.3/4 and power-header GND. Lower switch pads are NOT reset. Confirm by meter. | A: VLED / common-rail spur; B: LED-COMMON-RIGHT bend; C: SW1.3 / ground bar |
| Q08 | PHOTO RESOLVED: old UB-03 belongs to D13/STAT, now copper. Confirm the rounded VSTAT feature and its connection to R3.2. | A: VSTAT rounded feature; B: STAT-B former UB-03 segment |
| Q09 | Crack confirmed on the stripped photo specimen. Check its marked SPI/reset routes. Other boards are not assessed for this damage. | A: SPI51 surface-line crossing; B: SPI52 surface-line crossing; C: SPI50 surface-line crossing; D: RESET surface-line vicinity |
| Q10 | For D1/PWR and D2/STAT identify anode and cathode. Left/right are physical coordinates, not measured polarity. | A: D1 PWR LED; B: D2 STAT LED |
| Q11 | Confirm A/V50 reaches D50 and B/V51 reaches D51. Confirm the middle long path reaches D52. | A: V50 / apparent D50 transition; B: V51 / apparent D51 transition |
| Q12 | Check hole positions, grid/header registration, 4.064 mm paired-row gap, pad/drill sizes and board thickness. Fit is photo-derived. | A: H1 position / diameter; B: H2 position / diameter; C: PG1.R01C01 registration |

Enter measurements in [review-checks.csv](review-checks.csv), or report the Q IDs in chat.
There are no inferred passes in the checklist. A question can be answered independently.
For resistance/continuity checks, remove the board from the Due and disconnect power.
