# AFE v1: block fences and the nets that cross them

Picture: `v1-fences.png` (Due coordinates, x right, y up; the fences are rectangles). This is the plan for the re-place; nothing is moved yet.

## Fences

| block | fence (x0, y0, x1, y1) | holds |
|---|---|---|
| DIGITAL EDGE | 17, 49.2, 100, 53.3 | the Due headers J9/J7/J8; SDA/SCL run along its edge (LR-9) |
| POWER | 20, 3, 44, 22 | LM27762 and caps, R5/R6/R83/R29 etc, rail test points |
| REF | 44, 11, 50, 22 | U8, C24/C26/C27/C32, R81 (AREF 0 ohm), the VREF test point |
| CAL-LADDER | 50, 3, 64, 11 | R43, R46..R50 over the J5 pins A2..A7 |
| CAL-SENSE | 44, 11.5, 63, 28 | J11, U9 (ADS1115), R7/R8/R90-R92, D7/D8, C25, R69/R82 |
| AWG | 70, 3, 92, 20 | U3, Rbin/Rbpl divider, Rf/Cf, Rg2, the VREF filter, R51/R88, J3 |
| CH2 | 70, 20, 97, 29 | CH2 input chain, J2 |
| CH1 + shared U1 | 70, 29, 97, 49 | CH1 input chain, J1, the shared TPH2502 dual and its supply (the dual is one package for both channels, so CH2's follower sits in this fence) |

The A1 line (x 64.0) and the A0 line (x 67.3) run top-side from the J5 pins to their clamps and are the wall between the west blocks and the east blocks. The west half above y 28 stays empty except for the sense block's spares and the I2C edge route.

## Nets that cross a fence

| net | from -> to | crossing | layer | crossing part | owner |
|---|---|---|---|---|---|
| +3V3A | POWER -> REF, CAL-SENSE | inside the west half | top | none | router |
| +3V3A_E | POWER -> AWG, CH1 dual | the A1/A0 wall at y 25 | top | two 0603 0 ohm in a chain, pad pair per line | hand |
| VNEG_E | POWER -> AWG | the wall at y 23 | top | two 0603 in a chain | hand |
| VREF_X | REF -> AWG (and CH2 R3) | the wall at y 27 | top | two 0603 in a chain | hand |
| VREF | REF -> CH1 R3 | north lane y 48.5, no wall | top | none | hand |
| AWG_BNC / AWG_S | AWG -> CAL-SENSE | the wall at y 21, west-bound | top | two 0603 in a chain | hand |
| A1, A0 | J5 pins -> clamps | they are the wall | top only, no via | none | hand |
| TAP1..TAP5 | CAL-LADDER -> J5 pins | drops of 3-6 mm | top | none | router |
| TAP3, TAP4 | CAL-LADDER -> CAL-SENSE | north, 2-8 mm, then J11 and U9 | top | none | hand |
| SDA1, SCL1 | CAL-SENSE -> J9 | north, then west along the top edge | top | none | hand |
| DAC0 | J6 pin 5 -> AWG | 3 mm | top | none | hand |
| CH1_IN, CH2_IN | J1, J2 -> own chains | inside the fence | top | none | router |

No net crosses the wall on the bottom layer and there are no bottom hops: the ground plane is whole under the REF, ladder, AWG, scope front ends and ADC. The four west-to-east crossings are four rows at y 21, 23, 25 and 27 on the open stretch of the walls above the AWG, one row each. The wall lines are spread to 3.3 mm (x 64.0 and 67.3) so a chain of two 0603 per net spans them: one bridge per line, the middle pad pair between the lines at 1.7 mm, the line sitting 0.25 mm from each pad. That is eight 0603 0 ohm parts and no 1206. If the owner prefers four 1206 over eight 0603 the lane count is two per bridge and each is then a recorded LR-1 deviation.

## What this changes from the branch

- The sense block moves from y 31-46 (the north-west) back to the west of the ladder in the CAL-SENSE fence, close to the TAP lines, so TAP3/TAP4 are 2-8 mm instead of 20 mm and no lane crosses them: the three supply lanes run above the fence at y 23-27.
- U8 and its caps move west (REF fence, x 44-50) to clear the LR-5 keep-out and to give each VREF reader its own trace from the pin (LR-8).
- Test points: one per block key node. Today there are TP1-TP6; the target list is A1, A0, AWG_OUT (before R51/R88), +5V_F, +3V3A, VNEG, VREF, GND (plus +5V_DUE) = 9; three new.
