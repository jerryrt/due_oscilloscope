import sys, math
sys.path.insert(0, 'whatif/_scratch')
import route_lib as R
src, dst = sys.argv[1], sys.argv[2]
B = R.Board(src)
for n in ['/A1', '/A0', '/AWG_INV', '/CH1_N', '/CH1_NP', '/CH1_R1A', '/CH1_R2A', '/CH2_R1A', '/CH2_N', '/CH2_NP', '/CH2_R2A']:
    segs, vs, fails = B.route(n, width=0.2)
    B.add(segs, vs)
    print(n, 'len %.1f' % sum(math.hypot(s[3][0]-s[2][0], s[3][1]-s[2][1]) for s in segs), 'fails', fails, flush=True)
B.save(dst)
