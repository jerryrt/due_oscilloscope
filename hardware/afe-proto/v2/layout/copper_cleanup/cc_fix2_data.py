"""round 3 of the hand edits, applied after the detour pass (`cc_edits.py IN OUT cc_fix2_data`): the stair-steps the grid search leaves where two pads are offset in both axes. Same names and Due mm as cc_edits.py."""
OPS = [
    # R403 / R404 / R405: three pairs of pads offset by 1.65 mm in x and 1.7 mm in y. The LM_FB3M and LM_FBN runs between them were stairs of two 90 degree bends about 1 mm apart; each is one 45 degree
    # leg now, pad to pad (it enters each pad at 45 degrees, a named exception of the entry rule: an axial entry would need three bends, or cross the next pad's keep-out)
    ('/LM_FB3M', [(31.93, 9.0, 31.0, 9.0), (32.65, 8.18, 31.93, 8.18), (32.65, 7.3, 32.65, 8.18), (31.93, 8.18, 31.93, 9.0)], [([(32.65, 7.3), (31.0, 8.95)], 0.2)]),
    ('/LM_FBN', [(32.65, 9.88, 31.93, 9.88), (31.93, 9.88, 31.93, 10.7), (32.65, 9.0, 32.65, 9.88), (31.93, 10.7, 31.0, 10.7)], [([(32.65, 9.0), (31.0, 10.65)], 0.2)]),
]
NEW_VIAS = []
VIAS_DELETE = []
VIAS_MOVE_TO = []
VIAS_MOVE = []
