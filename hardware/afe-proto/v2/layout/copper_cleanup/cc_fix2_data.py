"""round 3 of the hand edits, applied after the detour pass (`cc_edits.py IN OUT cc_fix2_data`): the stair-steps the grid search leaves where two pads are offset in both axes. Same names and Due mm as cc_edits.py."""
OPS = [
    # R403 / R404 / R405: three pairs of pads offset by 1.65 mm in x and 1.7 mm in y. The LM_FB3M and LM_FBN runs between them were stairs of two 90 degree bends about 1 mm apart; each is one 45 degree
    # leg now, pad to pad (it enters each pad at 45 degrees, a named exception of the entry rule: an axial entry would need three bends, or cross the next pad's keep-out)
    ('/LM_FB3M', [(31.93, 9.0, 31.0, 9.0), (32.65, 8.18, 31.93, 8.18), (32.65, 7.3, 32.65, 8.18), (31.93, 8.18, 31.93, 9.0)], [([(32.65, 7.3), (31.0, 8.95)], 0.2)]),
    ('/LM_FBN', [(32.65, 9.88, 31.93, 9.88), (31.93, 9.88, 31.93, 10.7), (32.65, 9.0, 32.65, 9.88), (31.93, 10.7, 31.0, 10.7)], [([(32.65, 9.0), (31.0, 10.65)], 0.2)]),
    # VREF, C501.1 to U501.2: an L of two 90 degree bends (north 0.8, east 0.65, north 0.7) for an offset of 0.6 mm is a stair. A straight 0.1 mm track fits the pads' edge spans (0.011 mm of room, 0.44 degrees off
    # the vertical) but the board's minimum track width is 0.15 mm (DRC track_width); at 0.15 mm the spans do not overlap. So: south 0.6, one 45 degree leg (0.65 mm), south 0.64 into the pad (the last leg at x = 51.9625, a 0.001 mm inside the least the 0.2 mm track may be from the pad's centre to enter through its edge)
    ('/VREF', [(51.5, 14.8, 51.5, 14.0), (51.5, 14.0, 52.15, 14.0), (52.15, 14.0, 52.15, 13.3)], [([(51.5, 14.8), (51.5, 14.2), (51.9625, 13.7375), (51.9625, 13.1)], 0.2)]),
    # the stair-steps (two opposite 90 degree bends with a middle leg under 1.5 mm) the new `stair` check found:
    # VREF R514.1 to C501.1: south, east 0.85, south becomes south, one 45 degree leg, south
    ('/VREF', [(51.5, 18.2, 51.5, 19.075), (52.35, 18.2, 51.5, 18.2), (52.35, 18.2, 52.35, 15.0)], [([(51.5, 19.075), (51.5, 18.4), (52.35, 17.55), (52.35, 15.0)], 0.2)]),
    # VREF U501.2 to R305.1: east 0.7, north 1.02, east becomes east 0.6, one 45 degree leg, east
    ('/VREF', [(53.3, 13.2, 54.0, 13.2), (54.0, 13.2, 54.0, 14.22), (54.0, 14.22, 59.6, 14.22)], [([(53.3, 13.2), (53.9, 13.2), (54.92, 14.22), (59.6, 14.22)], 0.15)]),
    # SNS_B_N R511.1: east, north, west, north becomes one L (west 0.83 between the two pads of R511, then north on the vertical it joined)
    ('/SNS_B_N', [(58.42, 21.6, 59.25, 21.6), (59.25, 21.6, 59.25, 22.45)], [([(59.25, 22.45), (58.42, 22.45), (58.42, 21.6)], 0.2)]),
    # +3V3A_U C104.1 to U101.8: the hook up to y = 36.32 and back is one straight track along y = 35.7, into the pad's edge
    ('/+3V3A_U', [(80.075, 36.32, 80.695, 36.32), (79.08, 35.7, 80.075, 35.7), (80.695, 36.32, 80.695, 35.495), (80.075, 35.7, 80.075, 36.32)], [([(79.08, 35.7), (80.695, 35.7)], 0.3)]),
    # VNEG_G BR401.1 to R403.1: west along y = 6.45, north 0.85, west becomes west to x = 31.25 (0.6 mm clear of the +5V_F diagonal; the pad's edge span allows 0.25 off its centre) and north into the pad's bottom edge (one L)
    ('/VNEG_G', [(33.25, 6.45, 31.75, 6.45), (31.75, 6.45, 31.75, 7.3), (31.75, 7.3, 31.0, 7.3)], [([(33.25, 6.45), (31.25, 6.45), (31.25, 7.3)], 0.3)]),
]
NEW_VIAS = []
VIAS_DELETE = []
VIAS_MOVE_TO = []
VIAS_MOVE = []
