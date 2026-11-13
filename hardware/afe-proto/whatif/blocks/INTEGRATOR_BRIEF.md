# Integrator brief: the inter-block corridors of AFE v1 (read BRIEF.md first for tools and limits; they apply unchanged)

You are the integrator for the copper BETWEEN fences. Board: whatif/blocks/integrator/v1.kicad_pcb (merge 1: base + SCOPE + POWER + AWG + a bottom GND pour; REFCAL is NOT in it:
its interior is unrouted and its parts are at the baseline positions). Work in your own copies under whatif/blocks/integrator/. Do not move any part and do not touch
copper inside any fence (pcbtools.fence FENCES in kicad/floorplan.py): only add tracks/vias/bridges OUTSIDE the fences, in the corridors, to the contract edge points. Set
PCBTOOLS_V1_SOURCE=/work/hardware/afe-proto/kicad inside the container (live design with R520 and the VNEG_O net split).

## What to route (every contract row in whatif/blocks/ref/floorplan_table.md whose from/to is not 'inside', plus corridors in kicad/floorplan.py CORRIDORS)
- The edge points of the three merged blocks are in the merged board (their copper ends there; list them with boardio). REFCAL's edge points are the contract points; where REFCAL's real
  point differs, use REFCAL_partial's: VREF A (50.8, 4.6); VREF C (52.07, 4.6) (the contract (64.5, 1.35) lies outside the fence, so C goes from (52.07, 4.6) to the strip lane); VREF D (64.5, 22.8);
  AREF (48.4, 36.0), SDA (47.4, 36.0), SCL (46.4, 36.0); +3V3A north feed (56.0, 36.0); +3V3A west (44.5, 12.6); TAP1..5 at y 4.6 (x 63.5, 60.96, 58.42, 55.88, 53.34); AWG_S (64.5, 19.5).
  Leave REFCAL's end of each corridor net at its edge point, unconnected inside REFCAL (the REFCAL pass comes later). The A1/A0 wall column x 66.04 / 68.58 stays clear except at the bridges.
- Strip lanes under the ADC/PWM header pad rows: +3V3A (y 0.55, 0.2 wide) from POWER's (44.0, 5.2) to the AWG riser x 71.33; VNEG (y 0.95) from POWER's (44.0, 4.8); VREF C (y 1.35); the riser north to U301/R307
  (the AWG block's own edge points; look where its copper ends). 0.2 mm wide, 0.2 gap; pad edge 1.69, lane top 1.45.
- The wall (x 64.8..69.4): the 0603 bridges R515/R516 (VREF to the CH2 R3 leg), R309/R310 (AWG_BNC sense tap), R109/R110 (the scope's own +3V3A) are already placed at their floorplan points; draw the nets to them across the
  A1 (x 66.04) and A0 (x 68.58) columns without crossing them (a bridge is the crossing). A0's contract point (68.58, 33.0) lies outside every SCOPE fence: A0 ends at (69.4, 33.0), join it with TOP copper, no via (LR-4).
- The +3V3A branch from POWER (44.0, 21.5; the contract wants (44.0, 24.5)) to the scope bridge R109 (62.8, 35.7) outside the fences: it must run in the 0.5 mm gap at x 44.0-44.5 and then north outside the REFCAL fence
  (REFCAL fence is 44.5..64.5 x 4.6..36.0) and east at y about 37-38, crossing the I2C/AREF bundle (SCL x 46.4, SDA x 47.4, AREF x 48.4 going north to the J606 header, y 47.5-49.4 west) NOT by a bottom hop (LR-1 forbids bottom copper): cross each of SCL, SDA and AREF with a 0603 bridge of the existing type (0Rb) or route around them. You may add 0603 0R bridges (standing rule: not over an ADC line, a divider node or a VREF branch); tell me each one added.
- SCOPE's IN gaps: CH1_IN and CH2_IN tracks end at x 97.8 and 98.5 (y 44.45 and 24.13): a 0.7 mm gap across the header corridor each; the two 0.5 mm gaps between SCOPE's fence A and fence B (P33_U at x 72.6, VREF_Q at x 71.5, y 33.0 to 33.5); the SCOPE-to-AWG sides; all with top copper.
- P33_S from SCOPE (64.8, 35.7) to R110.1, 0.78 mm to R109.2 left in the corridor.

## Rules
0.2 mm top tracks (0.3 for supply where the row says), clearance 0.2, no bottom signal copper, no new via except where a row calls for one; keep 0.5 mm top-GND keep-back from the AWG_INV node; A0/A1 top only, no via. After each batch: `python3 -m pcbtools.check <board> --config v1 --no-drc`
(LR-6 / LR-8 can only be judged fully when REFCAL lands, but the AWG, SCOPE and POWER-side rows must not get worse), fence check clean per block against whatif/blocks/base.kicad_pcb, and a kicad-cli DRC with the project/library tables beside the board (no shorting_items, clearance or hole_clearance). Report under 40 lines:
the corridors routed (net, from, to, layer, width), bridges added (ref, nets, place), what you could not route with numbers, the rows and DRC kinds before and after, *(check)*.
