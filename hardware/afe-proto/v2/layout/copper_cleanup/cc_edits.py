"""the hand edits of the AFE-2 copper cleanup, as data: segments to remove and polylines to add per net, vias to move, delete or add. Applied on top of the automatic pass.
usage: python3 cc_edits.py IN OUT"""
import sys, os, math, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
import numpy as np
from cc_state import State, write, FRAME, geom, rules
from cc_reroute import Runner

# (net, [segments to remove (x0, y0, x1, y1)], [(polyline, width or [widths])])
OPS = [
    # LM_FBP: U401.2 goes west, north, and up the channel between R402.1 and R402.2 to the R402.1 / R401.2 branch
    ('/LM_FBP', [(29.9, 15.25, 29.9, 15.0), (29.9, 15.0, 30.1, 14.8), (30.1, 14.8, 30.3, 14.8), (29.9, 15.25, 29.42, 15.73), (29.42, 15.73, 29.42, 16.6), (29.42, 16.6, 28.6, 16.6)],
     [([(30.55, 14.75), (29.8, 14.75), (29.8, 15.5), (29.35, 15.95), (29.35, 17.35), (30.2, 18.2)], 0.2)]),
    # VNEG_G: U401.6 west 0.3, south down x = 30.25 to the C407 / C408 bus and west along it
    ('/VNEG_G', [(30.3, 12.6, 30.3, 11.5), (30.3, 11.5, 29.7, 10.9), (29.7, 10.9, 29.613, 10.428),
                  (33.498, 6.45, 33.25, 6.45), (34.325, 7.277, 33.498, 6.45), (34.325, 7.9, 34.325, 7.277)],
     [([(30.55, 12.75), (30.2, 12.75), (30.2, 10.95), (29.2, 10.95)], [0.2, 0.2, 0.3]),
      ([(33.25, 6.45), (33.6, 6.45), (34.325, 7.175), (34.325, 7.9)], 0.3)]),
    # LM_FBN: R405.1 north, then east to the bend by U401.7's branch
    # +3V3A: awg branch straight into the U401.11 / C405.1 vertical; the C406.1 branches straight in
    ('/+3V3A', [(36.2, 15.3, 34.5, 15.3), (34.5, 15.3, 33.65, 16.15), (33.65, 16.15, 33.573, 16.529),
                (44.5, 15.5, 44.0, 15.5), (44.0, 15.5, 43.85, 15.65), (43.85, 15.65, 36.271, 15.727),
                (41.9, 22.45, 36.4, 16.95), (36.4, 16.95, 35.5, 16.95), (35.5, 16.95, 35.35, 16.8), (35.35, 16.8, 35.427, 16.471)],
     [([(36.2, 15.3), (33.7, 15.3), (33.7, 16.5)], 0.2),
      ([(44.5, 15.5), (43.9, 16.1), (36.0, 16.1)], 0.3),
      ([(41.9, 22.45), (36.35, 16.9), (35.65, 16.9)], 0.3)]),
    # +5V_F: U401.3 straight west into C402.1; the loop round it goes
    ('/+5V_F', [(28.9, 14.54, 28.9, 15.17), (28.9, 15.17, 28.28, 15.17), (28.28, 15.17, 28.28, 14.25), (28.28, 14.25, 30.55, 14.25)],
     [([(30.55, 14.25), (29.0, 14.25)], 0.25)]),
    # GND: U401.1 and U401.4 reach the exposed pad (and its vias) straight, 0.15 wide so the track stays within the pad's edge
    ('/GND', [(54.88, 18.3, 54.3, 18.6), (54.88, 17.2, 54.88, 18.3), (30.95, 13.7, 31.5, 13.15), (30.8, 13.7, 30.95, 13.7), (31.2, 15.3, 31.2, 15.7), (31.5, 13.15, 31.5, 11.95)],
     [([(54.88, 17.2), (54.88, 18.85)], 0.2),
      ([(30.55, 15.25), (31.15, 15.25)], 0.15), ([(30.55, 13.75), (31.15, 13.75)], 0.2),
      ([(31.5, 15.0), (31.5, 16.2)], 0.2), ([(31.1, 12.9), (31.1, 12.15)], 0.2),
      ([(32.65, 10.7), (32.65, 11.5), (31.9, 11.5), (31.9, 12.15)], 0.2)]),
    # AWG_BNC_L: R507.1 to BR502.1 straight, at the height where both pads span
    ('/AWG_BNC_L', [(64.5, 19.5, 65.215, 19.5), (63.625, 20.0, 64.5, 20.0), (64.5, 20.0, 64.5, 19.5)], [([(63.8, 19.75), (65.0, 19.75)], 0.2)]),
    # VREF at U501.2 / C501.1: the six branches each take their own edge; the C501.1 to U501.2 link is one straight vertical
    ('/VREF', [(51.7, 14.3, 51.5, 14.8), (51.95, 13.5, 51.7, 14.3), (51.4, 14.8, 50.2, 14.8), (50.2, 14.8, 50.0, 14.8), (50.0, 14.8, 49.4, 15.4),
               (52.35, 14.8, 52.35, 18.2), (51.9, 14.8, 52.35, 14.8), (53.2, 13.5, 53.2, 14.58), (53.2, 14.58, 59.6, 14.58),
               (52.6, 13.2, 52.6, 12.41), (52.6, 12.41, 53.22, 12.41), (53.22, 12.41, 53.22, 13.03), (53.22, 13.03, 52.75, 13.5), (51.9, 13.2, 49.0, 13.2)],
     [([(51.5, 14.8), (51.5, 14.0), (52.15, 14.0), (52.15, 13.3)], 0.2), ([(51.5, 14.8), (49.8, 14.8)], 0.2), ([(52.35, 18.2), (52.35, 15.0), (51.5, 15.0)], 0.2),
      ([(53.05, 13.3), (53.05, 14.58)], 0.2), ([(53.05, 14.58), (59.6, 14.58)], 0.15), ([(49.0, 13.2), (52.05, 13.2)], 0.2)]),
    # the sensitive nets end ON the pads they connect (and restart), instead of running over them
    ('/CH2_NP', [(83.6, 25.43, 83.6, 28.14), (83.6, 28.14, 83.235, 28.505), (83.235, 28.505, 83.235, 29.74)],
     [([(83.6, 25.43), (83.6, 27.24)], 0.2), ([(83.235, 27.24), (83.235, 29.9)], 0.15)]),
    # A1: one vertical at x = 66.05 (the 0.01 mm jog goes), ending on D101.3 and restarting there instead of running over it; the track is 0.004 mm shorter, A1 may not get longer
    ('/A1', [(66.05, 41.2, 66.05, 38.95), (66.05, 38.95, 66.04, 38.94), (66.04, 38.94, 66.04, 2.54)],
     [([(66.05, 41.2), (66.05, 33.0)], 0.2), ([(66.05, 33.0), (66.05, 2.54)], 0.2)]),
]
NEW_VIAS = [(31.5, 16.2), (31.1, 12.15), (31.9, 12.15), (80.5, 33.25)]          # the last one ties the open end of the two 1.2 mm GND guard tracks beside U101 (the keep-out takes the pour they ended in)          # U401.1 and U401.4 each get a via of their own, on a stub from the exposed pad
VIAS_DELETE = [(29.85, 17.45), (31.5, 11.95), (32.25, 11.55)]
VIAS_MOVE_TO = [((54.3, 18.6), (54.88, 18.85))]          # the GND via of U502.3 goes to the end of a straight leg
VIAS_MOVE = []


def match(S, a, tol=1e-3):
    for i in range(len(S.S)):
        if S.alive[i] and ((np.abs(S.S[i] - a).max() < tol) or (np.abs(S.S[i] - np.array([a[2], a[3], a[0], a[1]])).max() < tol)):
            return i
    return None


def main():
    inp, out = sys.argv[1:3]
    st = Runner(inp)
    st.last = None
    nets = {n: i for i, n in enumerate(st.b.nets)}
    missing = []
    for net, kill, adds in OPS:
        for a in kill:
            i = match(st, a)
            if i is None:
                missing.append((net, a))
            else:
                st.alive[i] = False
        for pl, w in adds:
            ws = w if isinstance(w, list) else [w] * (len(pl) - 1)
            for k in range(len(pl) - 1):
                st.new.append((round(pl[k][0], 4), round(pl[k][1], 4), round(pl[k + 1][0], 4), round(pl[k + 1][1], 4), ws[k], 0, nets[net]))
    if missing:
        raise SystemExit('edits that remove a segment that is not on the board (the data and the automatic pass disagree): %s' % missing)
    st.via_dead = set()
    for (vx, vy) in VIAS_DELETE:
        k = int(np.argmin(np.hypot(st.b.v_x - vx, st.b.v_y - vy)))
        assert abs(st.b.v_x[k] - vx) < 1e-3 and abs(st.b.v_y[k] - vy) < 1e-3, (vx, vy)
        st.via_dead.add(k)
    gnd = nets['/GND']
    for (vx, vy) in NEW_VIAS:
        st.vias = np.vstack([st.vias, [vx, vy, 0.6, gnd]])
    for (fx, fy), (tx, ty) in VIAS_MOVE_TO:
        k = int(np.argmin(np.hypot(st.b.v_x - fx, st.b.v_y - fy)))
        assert abs(st.b.v_x[k] - fx) < 1e-3 and abs(st.b.v_y[k] - fy) < 1e-3, (fx, fy)
        st.vias[k, 0], st.vias[k, 1] = tx, ty
    st.vias_moved = {}
    for (vx, vy), near in VIAS_MOVE:
        k = int(np.argmin(np.hypot(st.b.v_x - vx, st.b.v_y - vy)))
        # new tracks first: the obstacles must include them
        st.alive_save = None
        best = None
        obs = st.obstacles(int(st.b.v_net[k]), 0, (near[0] - 4, near[1] - 4, near[0] + 4, near[1] + 4), set(), [near, near], 0.2, {k})
        for r_ in np.arange(0.5, 2.9, 0.05):
            for a_ in range(0, 360, 5):
                P = (round(near[0] + r_ * math.cos(math.radians(a_)), 3), round(near[1] + r_ * math.sin(math.radians(a_)), 3))
                if st.valid([(0, [P, P])], obs, 0.6)[0]:
                    best = P
                    break
            if best:
                break
        print('via', (vx, vy), '->', best)
        st.vias[k, 0], st.vias[k, 1] = best
    fnd = st.findings()
    import collections
    print('findings', dict(collections.Counter(f[0] for f in fnd)))
    write(inp, out, st)


if __name__ == '__main__':
    main()
