# v1 REFCAL planar obstruction (Option P), as found by the REFCAL block agent, 2026-11-12 (hand derivation, not a machine proof)

Inputs for a planarity pre-check: fence REFCAL (44.5, 4.6, 64.5, 36.0); parts = design.PARTS with block 'cal' (hundreds 5) in
kicad/design.py (live) or tests/fixtures/v1-34b2e51/kicad/design.py (frozen, without R520); edge points = the rows in
whatif/blocks/ref/floorplan_table.md (VREF branches A/C/D, TAP1..5, SCL/SDA/AREF north exits at x 46.4/47.4/48.4 y 36.0, +3V3A west (44.5,12.6)
and north (56.0,36.0), AWG_S east (64.5,19.5)); pad geometry from tests/fixtures/v1-34b2e51/kicad/afe-proto.kicad_pcb
(whatif/blocks/base_34b2e51.kicad_pcb is the same board). Option P placement: U501 rotated 90 (VREF pin 2 at 51.45, 14.86), U502 rotated 90,
R517/R518/R519 straddling branch D in the order SCL, SDA, R510 (AREF), +3V3A west to east.

## The crossing (frozen design, no R520)
Region Ry = east of branch C, south of branch D. VREF legs leave U501's pin 2 south in the order A, C, B, D.
- B is a spoke from the pin to U502.4; TAP3 a spoke from the south edge to U502.5; the SNS pair a spoke from AWG_S (east edge) to U502.6/7.
- Faces: F1 between B and TAP3 touches only the south-edge points TAP5 and TAP4; F2 between TAP3 and SNS; F3 beside D in the north-east.
- J501 needs TAP4 (only reachable in F1), TAP3 (the TAP3 spoke) and SNS_B (net with R502.2, R514.1, J501.2; reached from R502, R514 and R512).
- R512.2 must sit on branch-D copper, which borders only the D faces (F3 and the D side), so SNS_B (via R512.1) has to live in F3 while TAP4 can only be in F1.
No face holds both. Rotating U502 does not help: the cyclic order of U502's pins 4,5,6..10 equals the boundary order fixed by the contract nets.
Cut set: J501 {TAP4, SNS_B, TAP3} + the R512 tie {SNS_B, VREF-D} + U502 {VREF-B, TAP3, SNS}. Crossing nets: SNS_B (J501.2 - R512) against the B line
(VREF branch B) and against the TAP4/TAP3 lines, near J501 at about (55-57, 10-13).

## The fix (ruled by the spec session, option a; mirrors v2's BR508)
One 0603 0R, R520, in series on the sense bottom node: pin 1 = SNS_B (J501.2, R502.2, R514.1), pin 2 = SNS_B_N (R512.1). The bridge straddles the B line. In the
agent's rerun R520 sits at (54.5, 14.45) with R502 and R514 beside it, SNS_B in the pocket south of B, SNS_B_N and R512.1 north of it; the face
obstruction is gone. The agent also notes a device straddling a track resolves a crossing as well as a bridge does.
Where: whatif/blocks/add_r520.py (the board change), kicad/{design,layout,floorplan}.py (data), commit a14611b on origin/pcbtools,
whatif/blocks/REFCAL/REFCAL_partial.kicad_pcb (the routed rerun, not finished).
Earlier attempts (three failed passes, planar cut): /tmp/claude-1000/-home-jerry-EE-Projects-due-oscilloscope/03688616-436c-475d-a0e7-d8a9b1032ed0/scratchpad/blocks/REFCAL{,2,3}/.
