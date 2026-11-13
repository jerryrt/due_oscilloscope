import sys, importlib
sys.path.insert(0, '/work/hardware/afe-proto/whatif/blocks/refcal_router')
import plan
from pcbtools.editor import edit
src, out = sys.argv[1:3]
with edit(src, out) as e:
    for r, (x, y, rot) in plan.POSE.items():
        e.move(r, x, y, rot)
print('placed', len(plan.POSE))
