# v1 gate-3 table: deviations, added bridges and standing rules (kvm_01, running record)

Standing rules (owner's team, relayed by the spec session, in force from 2026-11-12):
- (a) a 0603 0R bridge of the existing type (0Rb, C21189) may be added inside a block when the crossed net is not an ADC line, a divider node or a VREF branch;
- (b) an LR-2 or LR-5 deviation of an already recorded kind is allowed, with its measured figure.

| # | what | rule | figure | ruling |
|---|---|---|---|---|
| 1 | SCOPE: IN pad to the N bus 10.22 mm in both channels (N cluster re-placed, chain east to the header limit) | LR-2 | 10.22 mm (asked 10-11); CH1_R1A node 6.1 mm, CH1_N / CH2_N 8.2 mm each with stubs | recorded deviation |
| 2 | SCOPE CH2: output run 17.8 mm not longer than the divider side 22.7 mm (CH1 24.1 vs 21.4) | LR-2 | A0 13.7 + CH2_OUT 4.0 | accepted as a second deviation; do not lengthen. Condition at gate 3: extract the N self-capacitance and IN stray of both channels with cap.py --converge and run the scope simulation at the top of the error bar (v2's case: 0.81 pF per N node) |
| 3 | R520 (new 0603 0R): splits the sense bottom node B into SNS_B / SNS_B_N so the Rd tie (R512) reaches VREF branch D without a crossing | contract: SNS_B row, VREF branch D | one part, carries only the ADS input current | owner team's ruling (option a), mirrors v2 BR508; the standing rule (a) is later and wider |
| 4 | R410 far pad on VNEG_O (U301.4, C303.1, TP405.1, R410.2): both pads were on VNEG, which KiCad cannot connect through a part | LR-6 / DRC unconnected | no new part | the other bridges' pattern; v1.py lists R410 in BRIDGES |
| 5 | POWER: +3V3A AWG edge point at y 5.2 not 5.0 (0.4 mm from VNEG); +3V3A SCOPE edge point at (44.0, 21.5), 3 mm short of 24.5; output caps C407-C410 5.6-8.3 mm from their pins | contract rows / cap priority | as listed | integrator extends the copper to the lane; for the caps, to be judged |
| 6 | A0 contract point (68.58, 33.0) is outside every SCOPE fence: A0 ends at (69.4, 33.0), 0.82 mm for the integrator (top copper, no via, LR-4) | contract | 0.82 mm | integrator bridges with top copper |

Open at the merge: IN corridor gaps 0.7 mm (CH1, CH2), two 0.5 mm tracks across SCOPE's fence A/B gap, the +3V3A-to-SCOPE branch (corridor box overlaps REFCAL's north-west; run in the 0.5 mm gap at x 44.0-44.5), BOM line for R520, regenerated contract table.
