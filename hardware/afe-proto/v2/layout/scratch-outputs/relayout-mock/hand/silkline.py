import sys
sys.path.insert(0, '/work/hardware/afe-proto')
from pcbtools import silkread
sh = silkread.read_silk(open(sys.argv[1]).read())
x0, y0, x1, y1 = map(float, sys.argv[2:6])
for s in sh:
    print(s) if False else None
n = 0
for s in sh:
    t = repr(s)
    # shapes are lines/rects; print those whose coordinates fall in the window
    import re
    nums = [float(v) for v in re.findall(r'-?\d+\.?\d*', t)]
    xs = nums[0::2]; ys = nums[1::2]
    if xs and ys and min(xs) < x1 and max(xs) > x0 and min(ys) < y1 and max(ys) > y0:
        print(t[:200]); n += 1
print(n, 'shapes in window')
