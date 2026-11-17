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
LANES = {'/VREF': [(47.0, 1.35), (70.9, 1.35), (70.9, 35.0)],
         '/+3V3A': [(44.0, 0.95), (71.3, 0.95), (71.3, 37.5)],
         '/VNEG': [(44.0, 0.55), (71.7, 0.55), (71.7, 14.5)]}
for net, pts in LANES.items():
    B.add([(net, 0, a, c, W, 'lane') for a, c in zip(pts, pts[1:])], [])
GX = 69.65
for y0, y1 in ((3.7, 14.7), (16.5, 35.5)):
    B.add([('/GND', 0, (GX, y0), (GX, y1), W, 'guard')], [])
B.add([], [('/GND', GX, y, 'guard') for y in (5.0, 9.0, 13.5, 17.5, 21.5, 25.5, 33.0)])
B.save(dst)
print('LANES', {n: len(p) - 1 for n, p in LANES.items()}, 'guard vias 7')
