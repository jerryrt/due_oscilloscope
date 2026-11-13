import sys
sys.path.insert(0, '/work/hardware/afe-proto/whatif/blocks/refcal_router')
import plan
from pcbtools.editor import edit
src, out = sys.argv[1:3]
with edit(src, out) as e:
    for r, (x, y, rot) in plan.POSE.items():
        e.move(r, x, y, rot)
    for net, w, pts in plan.HAND:
        for a, b in zip(pts, pts[1:]):
            e.add_tracks(net, 'F', a[0], a[1], b[0], b[1], w)
    for ref, pin, dx, dy in plan.GND:
        e.stub_via('GND', ref, pin, dx, dy, w=0.2)
print('built')
