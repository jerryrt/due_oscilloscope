| # | net | from -> to | edge point (x, y) | layer / width | bridge | owner | note |
|---|---|---|---|---|---|---|---|
| 1 | +5V_DUE | EDGE -> POWER | (40.6, 4.6) | F 0.3 |  | POWER | J601.5 (40.64, 2.54) north to R404/R403 side (38.1, 6.0) and on to R408 |
| 2 | +3V3A to REFCAL | POWER -> REFCAL | (44.5, 12.6) | F 0.3 |  | POWER up to the edge, REFCAL after | one trunk east to U501.1 and its caps; the ADS side (U502.8, C502, R509/R511, the clamps D501/D502: net P33_R) through BR7 over a VREF leg |
| 3 | +3V3A to AWG | POWER -> AWG | (44.0, 5.0) | F 0.2, strip lane y 0.95 |  | POWER | lane east to the AWG riser (x 71.33), U301.8 and its 100 nF; own branch, never touches the quiet branch |
| 4 | +3V3A to SCOPE | POWER -> SCOPE | (44.0, 24.5) | F 0.2 | BR5 over the quiet VREF trunk, BR6 over the A1 column | POWER up to the edge, SCOPE after | own branch from the OUT+ star (LR-6): out of POWER's east edge, north through REFCAL's west side to BR5 (62.0, 35.7), then BR6 (66.04, 35.7) to the dual V+ segment and the clamp rails (P33_U); shares no copper with the AWG or REF branches |
| 5 | VNEG | POWER -> AWG | (44.0, 4.8) | F 0.2, strip lane y 0.55 |  | POWER | lane east, riser x 71.33, U301.4 and its 100 nF at the pin; TP VNEG |
| 6 | GND | all -> all | plane | B.Cu pour, one piece |  | integrator | every GND pad has its own via; no cut, no bottom signal copper anywhere |
| 7 | VREF branch A: precision readers | REFCAL -> EDGE | (50.8, 4.6) | F 0.2 |  | REFCAL | U501 pin 2 to J602.1 (A7 pad, 50.8, 2.54) and the ladder top R508.2; Kelvin from the pin, own copper (LR-8) |
| 8 | VREF branch B: ADS AIN0 | REFCAL -> REFCAL | inside the fence | F 0.2 |  | REFCAL | U501 pin to U502.4 and C503; own copper (LR-8) |
| 9 | VREF branch C: AWG offset | REFCAL -> AWG | (64.5, 1.35) | F 0.2, strip lane y 1.35 |  | REFCAL up to the edge, AWG after | U501 pin to the strip lane, east, riser x 71.33 to R307.1 (offset filter); own copper (LR-8) |
| 10 | VREF branch D1: scope CH1 leg + sense tie | REFCAL -> SCOPE | (64.8, 46.6) | F 0.2 |  | REFCAL up to the edge, SCOPE after | CH1 leg R104 and the sense tie R512 (in REFCAL): quiet trunk x 62.8 north, y 46.6 east |
| 11 | VREF branch D2: scope CH2 leg | REFCAL -> SCOPE | (64.5, 22.8) | F 0.2 | BR1 over A1, BR2 over A0 | REFCAL up to the edge, SCOPE after | spur off the quiet trunk (62.8, 22.8) to BR1, BR2, R204.2 (VREF_P); crosses the wall, separate from the CH1 leg row above (LR-8) |
| 12 | AREF | REFCAL -> EDGE | (48.4, 36.0) | F 0.2 |  | REFCAL | R510.2 north x 48.4, west y 49.4 to J606.8 (23.876, 50.8); unfitted part |
| 13 | SCL | REFCAL -> EDGE | (46.4, 36.0) | F 0.2 |  | REFCAL | U502.10 (net SCL1_A) through BR9 over a VREF leg, then north x 46.4, west y 47.5 to J606.10 (18.796, 50.8) |
| 14 | SDA | REFCAL -> EDGE | (47.4, 36.0) | F 0.2 |  | REFCAL | U502.9 (net SDA1_A) through BR8 over a VREF leg, then north x 47.4, west y 48.5 to J606.9 (21.336, 50.8) |
| 15 | TAP1..TAP5 | EDGE -> REFCAL | (53.3, 4.6) | F 0.2 |  | REFCAL | J602.2..J602.6 (x 53.34 .. 63.5) up to the ladder (y 6..8.2); TAP3/TAP4 on to J501 and the ADS |
| 16 | TAP3 / TAP4 to J501 and the ADS | REFCAL -> REFCAL | inside the fence | F 0.2 |  | REFCAL | inside the fence; nothing of another block crosses them |
| 17 | SNS_B | REFCAL -> REFCAL | inside the fence | F 0.2, sense guard and pair rule |  | REFCAL | R514 and R512 to J501.2; matched to its pair partner, away from the AWG output |
| 18 | A1 | SCOPE -> EDGE | (66.04, 33.5) | F 0.2 |  | SCOPE | D101/R107.2 down x 66.04 to J602.7 (66.04, 2.54); no via, top only (LR-4) |
| 19 | A0 | SCOPE -> EDGE | (68.58, 33.0) | F 0.2 |  | SCOPE | D201/R207.2 down x 68.58 to J602.8 (68.58, 2.54); no via, top only (LR-4) |
| 20 | DAC0 | EDGE -> AWG | (83.82, 4.4) | F 0.2 |  | AWG | J603.5 (83.82, 2.54) straight up to R305 and pin 5; short |
| 21 | AWG_BNC (sense node) | AWG -> REFCAL | (69.8, 19.0) | F 0.2 guard + pair rule | BR3 over A0, BR4 over A1 | AWG up to the edge, REFCAL after | from R304/R306 at the BNC to R501.1 across the wall (AWG_I is the island between the bridges) |
| 22 | AWG supply decoupling parts | AWG -> AWG | inside the fence |  |  | AWG | V+ and V- decoupling at pins 8 and 4; INV is a short top trace, Rg2 (R302) straddles the BIN stub as a bridge; no net leaves the pocket except those listed |
| 23 | SCOPE dual (U101) | SCOPE -> SCOPE | inside the fence |  |  | SCOPE (one agent for both channels) | U101 is shared; CH1 and CH2 are labelled on the silk beside its halves, CH2 laid out in CH1's pattern, mirrored |

| bridge | nets split | at (x, y) | crosses |
|---|---|---|---|
| BR1 (R515) | VREF / VREF_M | (66.04, 22.8) | the A1 line (x 66.04) |
| BR2 (R516) | VREF_M / VREF_P | (68.58, 24.5) | the A0 line (x 68.58) |
| BR3 (R310) | AWG_I / AWG_BNC | (68.58, 21.1) | the A0 line (x 68.58) |
| BR4 (R309) | AWG_S / AWG_I | (66.04, 19.5) | the A1 line (x 66.04) |
| BR5 (R109) | +3V3A / P33_S | (62.8, 35.7) | the quiet VREF trunk (x 62.8) |
| BR6 (R110) | P33_S / P33_U | (66.04, 35.7) | the A1 column (x 66.04) |

Notes:
- v2 arrangement (AWG east beside J301), as the spec lead ruled: LR-7 keeps the AWG current loop and the 50 ohm return in its own zone. Nine 0603 0R bridges (existing type), no hop, no 1206: six in the wall corridor and three inside REFCAL (the block agent found a planar cut there: the VREF tree with exits south, north and east splits the fence and the ADS straddles it, so +3V3A, SDA and SCL cross a VREF leg by a bridge each).
- The first v1 contract moved the AWG west and is withdrawn: it put the AWG output lane 95 mm past the TAP and A pads.
- Pad edges of J601/J602/J603 are y 1.69 (1.7 mm pads): inner lane top 1.45, gap 0.24; outer lane edge 0.45 mm to the outline. Check on the v1 board.
- Keep-out (LR-5) = the courtyards of U401 and C402 inflated by 10 mm. Sensitive copper in REFCAL stays east of x 48.6 between y 9 and y 19.
- +3V3A to SCOPE is its own branch from the star (LR-6) with two bridges (BR5, BR6), as row 4 of v2; the riser variant is rejected because it shares the strip lane of the AWG.
- Test points: one per block key node, on the existing path, no stub on A1/A0: A1, A0, AWG_OUT before R304/R306, +5V_DUE, +5V_F, +3V3A, VNEG, VREF, GND = 9, three new.
