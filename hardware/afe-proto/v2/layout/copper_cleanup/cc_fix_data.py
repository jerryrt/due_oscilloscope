"""round 2 of the hand edits, as data (the same names as cc_edits.py, applied by `cc_edits.py IN OUT cc_fix_data` after the GND vias and before the detour pass): the hooks, kinks, free ends,
bars and spur junctions the new copper checks (detour, dangling, tspur, wide) found on the first cleaned board. Coordinates are Due mm, as everywhere in this tool."""
OPS = [
    # AWG_VO, between R303 and C301: two hooks (3.0 mm and 2.9 mm of track for 1.1 and 1.6 mm of distance, because the pads are 0.05 and 0.1 mm off each other in x). One vertical at x = 85.9 now
    # runs R303.1 -> C301.1 -> the bus at y = 18.35; it enters both pads through their edges (0.05 mm off a pad centre is inside the span)
    ('/AWG_VO', [(85.85, 17.27, 86.98, 17.27), (86.98, 17.27, 86.98, 17.89), (86.98, 17.89, 86.36, 17.89), (86.36, 17.89, 85.9, 18.35),
                 (85.85, 16.31, 85.85, 17.27), (86.57, 16.31, 85.85, 16.31), (85.95, 15.69, 86.57, 15.69), (86.57, 15.69, 86.57, 16.31)],
     [([(85.9, 15.69), (85.9, 17.27)], 0.2), ([(85.9, 17.27), (85.9, 18.35)], 0.2)]),
    # CH2_IN: the V dip (a 0.44 mm 45 degree down and up between C201.1 and the junction) and the junction at the bend of the trunk go: C201.1's link starts at the height of the trunk, 0.26 mm
    # above the pad's centre (inside its edge span), runs straight east into the junction, and the trunk keeps its y = 24.13 between the header pads of J605
    ('/CH2_IN', [(88.3, 23.87, 90.223, 23.87), (90.223, 23.87, 90.662, 23.432), (90.662, 23.432, 91.36, 24.13)], [([(88.3, 24.13), (91.36, 24.13)], 0.2)]),
    # +5V_F: the diagonal ended 0.07 mm short of the vertical it meant to join: it ends on the vertical's vertex now, so the T has its trunk straight through
    ('/+5V_F', [(33.85, 5.95, 35.15, 7.25), (30.9, 5.95, 33.85, 5.95)], [([(30.9, 5.95), (33.75, 5.95), (35.1, 7.3)], 0.3)]),
    # +5V_F: the three tracks that met at the bend (29.5, 18.95) become a trunk with a bend and a 45 degree spur 0.7 mm from it (the spur's far end is re-drawn: a vertical of 0.65 mm, then the diagonal)
    ('/+5V_F', [(27.25, 21.2, 29.5, 18.95), (27.25, 21.2, 27.0, 21.45), (27.0, 21.45, 27.0, 22.8)], [([(27.0, 22.8), (27.0, 22.15), (30.2, 18.95)], 0.3)]),
    # +3V3A: one of two tracks laid on top of each other (the C405.1 link), and the R401.1 branch comes in along y = 19.85 so the three tracks no longer meet at the bend (34.4, 19.5)
    ('/+3V3A', [(34.4, 16.9, 33.35, 16.9), (37.45, 22.55, 34.4, 19.5), (37.45, 22.55, 37.9, 23.0), (37.9, 23.0, 41.0, 23.0), (34.4, 19.5, 34.4, 16.9),
                (34.4, 19.5, 33.612, 20.288), (33.612, 20.288, 33.173, 19.85), (33.173, 19.85, 31.3, 19.85)],
     [([(41.0, 23.0), (38.2, 23.0), (34.4, 19.2)], 0.2), ([(34.4, 19.2), (34.4, 16.9)], 0.2), ([(31.3, 19.85), (34.4, 19.85), (34.4, 19.2)], 0.2)]),
    # +3V3A: the 0.42 mm spur to C305.1 ends at the pad centre
    ('/+3V3A', [(79.0, 13.675, 79.0, 14.1)], [([(79.0, 13.675), (79.0, 14.5)], 0.2)]),
    # AWG_BIN: U301.5 -> R307.1 is one straight track and the vertical from below joins it in the middle (two tracks lay on each other there)
    ('/AWG_BIN', [(85.2, 13.675, 86.4, 13.675), (85.743, 13.675, 85.09, 13.675)], [([(85.09, 13.675), (86.7, 13.675)], 0.2)]),
    # SCL: R513.2 reaches the vertical 0.9 mm from the bend, by an L, so the three tracks no longer meet at the bend
    ('/SCL', [(45.1, 23.08, 45.1, 22.25), (45.92, 23.08, 45.1, 23.08), (46.4, 22.6, 45.92, 23.08)], [([(45.1, 22.25), (45.1, 23.5), (46.4, 23.5)], 0.2)]),
    # +3V3A_U: D201.2 reached the trunk by a '<' (up, 45 degrees left, 45 degrees right: a 0.44 mm dip for a 0.2 mm offset); straight up now
    ('/+3V3A_U', [(73.362, 35.062, 74.0, 35.7), (73.8, 33.3, 73.8, 34.624), (73.8, 34.624, 73.362, 35.062)], [([(73.8, 33.3), (73.8, 35.7)], 0.3)]),
    # AWG_BNC: R301.2 left its pad by an S (east, south, west, south) and came back; it leaves straight south
    ('/AWG_BNC', [(89.03, 8.89, 88.405, 8.89), (89.03, 8.27, 89.03, 8.89), (88.41, 8.27, 89.03, 8.27), (88.41, 7.6, 88.41, 8.27), (88.41, 7.6, 92.7, 7.6)],
     [([(88.405, 8.89), (88.405, 7.6), (92.7, 7.6)], 0.2)]),
]
NEW_VIAS = []
VIAS_DELETE = []
VIAS_MOVE_TO = []
VIAS_MOVE = []
