| # | net | from -> to | edge point (x, y) | layer / width | bridge | owner | note |
|---|---|---|---|---|---|---|---|
| 1 | +5V_DUE | EDGE -> POWER | (40.6, 4.6) | F 0.3 |  | POWER | J4.5 (40.64, 2.54) north to R27/R26 side (38.1, 6.0) and on to R70 |
| 2 | +3V3A to REFCAL | POWER -> REFCAL | (44.0, 12.6) | F 0.3 |  | POWER up to the edge, REFCAL after | one trunk east to U8.1 and the ADS (VDD, decoupling, pull-ups) |
| 3 | +3V3A to AWG | POWER -> AWG | (36.0, 22.0) | F 0.3 |  | POWER | north from the OUT+ star to U3.8 and its 100 nF (R93 side); own branch |
| 4 | VNEG | POWER -> AWG | (33.0, 22.0) | F 0.3 |  | POWER | north from the OUT- star to U3.4 and its 100 nF at the pin |
| 5 | +3V3A to SCOPE | POWER -> SCOPE | (44.0, 4.8) | F 0.2, strip lane y 0.95 |  | POWER up to the edge, SCOPE after | lane east under the pad rows, then riser x 71.1 north to the dual V+ and the clamps (SCOPE places a branch to D5/D6.2); no bridge |
| 6 | GND | all -> all | plane | B.Cu pour, one piece |  | integrator | every GND pad has its own via; no cut, no bottom signal copper anywhere |
| 7 | VREF branch A: precision readers | REFCAL -> EDGE | (50.8, 4.6) | F 0.2 |  | REFCAL | U8 pin 2 to J5.1 (A7 pad, 50.8, 2.54) and the ladder top R50.2; Kelvin from the pin, own copper (LR-8) |
| 8 | VREF branch B: ADS AIN0 | REFCAL -> REFCAL | inside the fence | F 0.2 |  | REFCAL | U8 pin to U9.4 and C26; own copper (LR-8) |
| 9 | VREF branch C: AWG offset | REFCAL -> AWG | (51.0, 22.0) | F 0.2 |  | REFCAL up to the edge, AWG after | U8 pin north x 51.0 to y 33, west to R93.1 (offset filter); own copper (LR-8) |
| 10 | VREF branch D1: scope CH1 leg + sense tie | REFCAL -> SCOPE | (62.8, 22.0) | F 0.2 |  | REFCAL up to the edge, SCOPE after | CH1 leg R14 and the sense tie R90 (in REFCAL): quiet trunk x 62.8 north, y 46.6 east |
| 11 | VREF branch D2: scope CH2 leg | REFCAL -> SCOPE | (64.5, 22.8) | F 0.2 | BR1 over A1, BR2 over A0 | REFCAL up to the edge, SCOPE after | spur off the quiet trunk (62.8, 22.8) to BR1, BR2, R16.2; separate from the CH1 leg (LR-8) |
| 12 | AREF | REFCAL -> EDGE | (52.6, 22.0) | F 0.2 |  | REFCAL | R81.2 north x 52.6, west y 49.4 to J9.8 (23.876, 50.8); unfitted part |
| 13 | SCL | REFCAL -> EDGE | (54.6, 22.0) | F 0.2 |  | REFCAL | U9.10 north x 54.6, west y 47.5 to J9.10 (18.796, 50.8) |
| 14 | SDA | REFCAL -> EDGE | (53.6, 22.0) | F 0.2 |  | REFCAL | U9.9 north x 53.6, west y 48.5 to J9.9 (21.336, 50.8) |
| 15 | TAP1..TAP5 | EDGE -> REFCAL | (53.3, 4.6) | F 0.2 |  | REFCAL | J5.2..J5.6 (x 53.34 .. 63.5) up to the ladder (y 6..8.2); TAP3/TAP4 on to J11 and the ADS |
| 16 | TAP3 / TAP4 to J11 and the ADS | REFCAL -> REFCAL | inside the fence | F 0.2 |  | REFCAL | short, inside the fence: J11 and U9 stand directly above the ladder; nothing crosses them |
| 17 | SNS_B | REFCAL -> REFCAL | inside the fence | F 0.2, sense guard and pair rule |  | REFCAL | R92 and R90 to J11.2; matched to its pair partner, away from the AWG output |
| 18 | A1 | SCOPE -> EDGE | (66.04, 28.5) | F 0.2 |  | SCOPE | D5/R55.2 down x 66.04 to J5.7 (66.04, 2.54); no via, top only (LR-4) |
| 19 | A0 | SCOPE -> EDGE | (68.58, 28.5) | F 0.2 |  | SCOPE | D6/R56.2 down x 68.58 to J5.8 (68.58, 2.54); no via, top only (LR-4) |
| 20 | DAC0 | EDGE -> AWG | (83.82, 1.9) | F 0.2, strip lane y 1.35 |  | AWG | J6.5 (83.82, 2.54) down to the lane, west to x 47.6, north through the header gap to R54.1 (AWG pocket) |
| 21 | AWG_BNC to J3 | AWG -> EDGE | (47.0, 24.5) | F 0.2, strip lane y 0.55 |  | AWG | R51/R88 (back termination, in AWG) to x 48.6, south through the header gap, east along the lane to x 100.5, north to J3 (102, 7.4) |
| 22 | AWG_BNC sense node | AWG -> REFCAL | (50.0, 24.5) | F 0.2 guard + pair rule |  | AWG up to the edge, REFCAL after | from R51/R88 east y 25 to x 50.0, south to R7.1; short, no wall crossing |
| 23 | AWG supply decoupling parts | AWG -> AWG | inside the fence |  |  | AWG | V+ and V- decoupling at pins 8 and 4; INV is a short top trace, Rg2 (R33) straddles the BIN stub as a bridge; no net leaves the pocket except those listed |
| 24 | SCOPE dual (U1) | SCOPE -> SCOPE | inside the fence |  |  | SCOPE (one agent for both channels) | U1 is shared; CH1 and CH2 are labelled on the silk beside its halves, CH2 laid out in CH1's pattern, mirrored |

| bridge | nets split | at (x, y) | crosses |
|---|---|---|---|
| BR1 (R98) | VREF / VREF_M | (66.04, 22.8) | the A1 line (x 66.04) |
| BR2 (R100) | VREF_M / VREF_X | (68.58, 24.5) | the A0 line (x 68.58) |

Notes:
- v1 moves the AWG to the west half: its VNEG, +3V3A and VREF come from POWER and REFCAL without crossing the A1/A0 wall, so the only wall crossings are the two VREF D2 bridges (BR1, BR2). The price is two long signal lanes under the pad rows (DAC0 in, AWG_BNC out to J3) and one more, +3V3A to SCOPE: three strip lanes, the same count as v2.
- The 8 x 0603 chain plan of the first fence page is withdrawn: it was for the AWG staying east. R33 (Rg2) in the AWG straddles the BIN stub, so INV needs no hop and no bridge.
- Keep-out (LR-5) = the courtyards of U7 and C31 inflated by 10 mm; REFCAL starts at x 49.5, 13 mm from C31.
- Strip lanes: pad edge of J4/J5/J6 is y 1.69 (1.7 mm pads), lane top 1.45, gap 0.24; outermost lane edge y 0.45, 0.45 mm to the outline (check on the board).
- Test points (one per block key node, on the existing path, no stub on A1/A0): TP A1 and A0 on the SCOPE column, AWG_OUT before R51/R88, +5V_DUE, +5V_F, +3V3A, VNEG, VREF, GND: 9, three new.
