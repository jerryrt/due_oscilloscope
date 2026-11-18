"""give each listed SMD GND pad a via of its own, joined by a track that enters the pad perpendicular: cc_gndvias.py IN OUT REF.PIN ... [--tight]"""
import sys, os, math
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path[:0] = [HERE]
import numpy as np
import cc_state
from cc_state import State, write, FRAME, KEY, key
if '--tight' in sys.argv:
    sys.argv.remove('--tight')
    State.req = lambda self, na, nb, g: 0.15       # the DRC floor, for the GND via stubs only
from cc_reroute import Runner

st = Runner(sys.argv[1]); st.last = None
b = st.b
gnd = b.net_id('/GND')
newv = []
for spec in sys.argv[3:]:
    ref, pin = spec.split('.')
    h = next(h for h in range(len(st.pa['rows'])) if b.fp_ref[b.p_fp[h]] == ref and b.p_pin[h] == pin and (b.p_layer_mask[h] & 1) and b.p_shape[h] != 0 or False)
    ps = st.pad_spec(h)
    A = ps['pos']
    # candidate via positions on a 0.1 grid, nearest first
    Cs = [(A[0] + dx, A[1] + dy) for dx in np.arange(-2.6, 2.61, 0.1) for dy in np.arange(-2.6, 2.61, 0.1) if 0.5 <= math.hypot(dx, dy) <= 2.6]
    Cs.sort(key=lambda p: math.hypot(p[0] - A[0], p[1] - A[1]))
    win = (A[0] - 4, A[1] - 4, A[0] + 4, A[1] + 4)
    obs = st.obstacles(gnd, 0, win, ps['skip'], [A, A], 0.2)
    done = False
    for V in Cs:
        V = (round(V[0], 3), round(V[1], 3))
        if not st.valid([(0, [V, V])], obs, 0.6)[0]:
            continue
        sb = dict(pos=V, dirs=list(range(8)), minleg=0.62, skip=set())
        res = st.route_pair(gnd, 0, 0.2, dict(ps), sb, [A, V], 3, K=1)
        if res:
            pp, ws = res[0]
            for k in range(len(pp) - 1):
                st.new.append((round(pp[k][0], 4), round(pp[k][1], 4), round(pp[k + 1][0], 4), round(pp[k + 1][1], 4), ws[k], 0, gnd))
            st.vias = np.vstack([st.vias, [V[0], V[1], 0.6, gnd]])
            print('via for', spec, 'at', V, 'path', np.round(pp, 2).tolist())
            done = True
            break
    if not done:
        print('NO VIA for', spec)
write(sys.argv[1], sys.argv[2], st)
