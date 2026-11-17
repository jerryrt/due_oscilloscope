"""stage0_lanes.py IN OUT: the exact pre-routed copper of the floorplan (owner-approved shape, spec lead's rulings):
 - the gate strip under the J602/J603 pad rows: VNEG y 0.55 (outer), +3V3A y 0.95, VREF y 1.35 (inner, pad side), 0.2 wide, straight, no via;
   0.24 mm from the pad edge (y 1.69): the +0.08 route margin is waived for these three tracks only, the DRC must read >= 0.2
 - the east bus on the wall: VREF x 70.9 (the A0 side), +3V3A 71.3, VNEG 71.7, nested turns north
 - the stitched GND guard between A0 and the bus (broken at the bridge R310's east pad), vias 0.6/0.3
The lanes are saved as ordinary tracks; LANENETS makes route_lib treat them as the root of each rail's tree."""
import sys
sys.path.insert(0, 'whatif/_scratch')
import route_lib as R
src, dst = sys.argv[1], sys.argv[2]
B = R.Board(src)
W = 0.2
import os
BUS = os.environ.get('BUS', 'A')     # A: the bus ends at y 22 (A0 crosses the wall north of it); B: the full bus, with a 4 mm break where A0 crosses (would be 2 supply bridges)
if BUS == 'A':
    LANES = {'/VREF': [[(47.0, 1.35), (70.9, 1.35), (70.9, 25.0)]], '/+3V3A': [[(44.0, 0.95), (71.3, 0.95), (71.3, 25.0)]], '/VNEG': [[(44.0, 0.55), (71.7, 0.55), (71.7, 14.5)]]}
    GUARD = ((3.7, 14.7), (16.5, 25.0))
else:
    LANES = {'/VREF': [[(47.0, 1.35), (70.9, 1.35), (70.9, 26.0)], [(70.9, 30.0), (70.9, 35.0)]],
             '/+3V3A': [[(44.0, 0.95), (71.3, 0.95), (71.3, 26.0)], [(71.3, 30.0), (71.3, 37.5)]],
             '/VNEG': [[(44.0, 0.55), (71.7, 0.55), (71.7, 14.5)]]}
    GUARD = ((3.7, 14.7), (16.5, 26.0), (30.0, 35.5))
for net, pls in LANES.items():
    for pts in pls: B.add([(net, 0, a, c, W, 'lane') for a, c in zip(pts, pts[1:])], [])
GX = 69.65
for y0, y1 in GUARD:
    B.add([('/GND', 0, (GX, y0), (GX, y1), W, 'guard')], [])
B.add([], [('/GND', GX, y, 'guard') for y in (5.0, 9.0, 13.5, 17.5, 21.5, 33.0 if BUS == 'B' else 23.5)])
B.save(dst)
import json
json.dump([[n, l, a[0], a[1], c[0], c[1], w] for n, l, a, c, w, t in B.tracks if n != '/GND'], open(dst.replace('.kicad_pcb', '.json'), 'w'))
print('LANES', BUS, {n: len(p) for n, p in LANES.items()}, 'guard vias 6')
