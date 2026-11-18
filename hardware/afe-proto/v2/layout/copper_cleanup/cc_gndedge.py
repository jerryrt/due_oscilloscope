"""every SMD GND pad gets a via at its edge, and no track between: cc_gndedge.py IN OUT

The GND tracks of the board (the stubs from pad to via) and the vias at their ends are removed; for each SMD GND pad on the top copper, in designator order, a via is put where its annulus touches the pad's
box (centre 0.25 to 0.29 mm from it, so the annulus (0.3 mm radius) overlaps the box by 0.01 mm or more: the rule `gndpad` accepts a GND via within 0.05 mm of the box, and the fill step counts a via as attached to a pad when it is within its radius of the pad's box) and is clear of every other net's copper by the clearance model of the cleanup. Preference: straight out
of an edge of the pad, centred on it, and 0.29 mm from the box. A pad that has no such place is listed and keeps a legal stub and a via (cc_gndvias' search),
or, where the pour can keep it, none (that is the fill step's)."""
import sys, os, math
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path[:0] = [HERE]
import numpy as np
from cc_state import State, write, FRAME, KEY, key
from cc_reroute import Runner

st = Runner(sys.argv[1]); st.last = None
b = st.b
gnd = b.net_id('/GND')
for i in range(len(st.S)):
    if st.N[i] == gnd and st.L[i] == 0:
        st.alive[i] = False                                           # every GND track: the stubs and the 1.2 mm bars
st.via_dead = set(k for k in range(len(b.v_x)) if b.v_net[k] == gnd)       # and every GND via: each pad gets its own below, the fill step stitches what hangs
# a pad that the exposed pad of its own part holds by a straight track: the track, and no via (U401's pins 1 and 4 beside the exposed pad: 0.6 mm straight into it, within the pad's own height)
TIES = {'U401.1': ((30.55, 15.25), (31.15, 15.25), 0.15), 'U401.4': ((30.55, 13.75), (31.15, 13.75), 0.2)}
for spec, (p0, p1, w) in TIES.items():
    st.new.append((p0[0], p0[1], p1[0], p1[1], w, 0, gnd))
    print('tie   %s straight to the exposed pad, %.2f mm wide' % (spec, w))
# a pad no via fits at, whose stub is drawn by hand: R405.2 (best straight-out place has a copper gap of -0.02 mm against 0.15 required: the LM_FBN track passes along its west edge and R404.2 sits north-east), one L of two legs of 0.75 and 0.8 mm to a via
HAND = {'R405.2': ([(32.65, 10.7), (32.65, 11.5), (31.9, 11.5)], 0.2)}
for spec, (pl, w) in HAND.items():
    for k in range(len(pl) - 1):
        st.new.append((pl[k][0], pl[k][1], pl[k + 1][0], pl[k + 1][1], w, 0, gnd))
    st.vias = np.vstack([st.vias, [pl[-1][0], pl[-1][1], 0.6, gnd]])
    print('hand  %s stub %s and its via' % (spec, pl))
# the exposed pad of U401 has three plated holes of its own for four GND pads (pins 1 and 4 are tied to it, and it is two pads in the footprint): one via at the pad's north end, no track
EP_VIAS = [(31.5, 15.615)]
for (vx, vy) in EP_VIAS:
    st.vias = np.vstack([st.vias, [vx, vy, 0.6, gnd]])
    print('via   U401 exposed pad at (%.2f, %.2f), 0.29 mm from its end' % (vx, vy))
placed = [(pl[-1][0], pl[-1][1]) for pl, w in HAND.values()] + list(EP_VIAS)
rows = sorted([h for h in range(len(st.pa['rows'])) if b.p_net[h] == gnd and b.p_smd[h] and (b.p_layer_mask[h] & 1)], key=lambda h: (b.fp_ref[b.p_fp[h]], str(b.p_pin[h])))
left = []
for h in rows:
    ref, pin = b.fp_ref[b.p_fp[h]], b.p_pin[h]
    if '%s.%s' % (ref, pin) in TIES or '%s.%s' % (ref, pin) in HAND or (ref == 'U401' and str(pin) == '13'):
        continue                                                      # tied by a track to the exposed pad, or the exposed pad itself (its own plated holes are its vias)
    bx0, by0, bx1, by1 = b.p_bx0[h], b.p_by0[h], b.p_bx1[h], b.p_by1[h]
    cx, cy = float(b.p_x[h]), float(b.p_y[h])
    win = (cx - 3, cy - 3, cx + 3, cy + 3)
    obs = st.obstacles(gnd, 0, win, {int(h)}, [(cx, cy), (cx, cy)], 0.2)
    cands = []
    for dx in np.arange(-2.0, 2.0001, 0.05):
        for dy in np.arange(-2.0, 2.0001, 0.05):
            X, Y = cx + dx, cy + dy
            d = math.hypot(max(bx0 - X, X - bx1, 0), max(by0 - Y, Y - by1, 0))
            if not (0.25 <= d <= 0.29) or not (bx0 <= X <= bx1 or by0 <= Y <= by1):
                continue                                                  # straight out of an edge: a corner of a rounded pad is not copper
            if any(math.hypot(X - px, Y - py) < 0.9 for px, py in placed):
                continue                                              # two vias of ours keep their distance
            # straight out of an edge, centred on it: the offset along the edge is small
            off = min(abs(X - cx), abs(Y - cy))
            cands.append((off, abs(d - 0.29), round(X, 3), round(Y, 3)))
    cands.sort()
    done = False
    for off, dd, X, Y in cands:
        if st.valid([(0, [(X, Y), (X, Y)])], obs, 0.6)[0]:
            st.vias = np.vstack([st.vias, [X, Y, 0.6, gnd]])
            placed.append((X, Y))
            print('via   %s.%s at (%.2f, %.2f) offset %.2f from the pad axis' % (ref, pin, X, Y, off))
            done = True
            break
    if not done:
        left.append(h)
        print('NONE  %s.%s (%.2f, %.2f): no via fits at its edge' % (ref, pin, cx, cy))
# second look at the pads with no place: the clearance model of the DRC floor (0.15 mm to other nets); the via still overlaps the pad's box, so it is joined by copper
st.req = lambda na, nb, g: 0.15
still = []
for h in left:
    ref, pin = b.fp_ref[b.p_fp[h]], b.p_pin[h]
    bx0, by0, bx1, by1 = b.p_bx0[h], b.p_by0[h], b.p_bx1[h], b.p_by1[h]
    cx, cy = float(b.p_x[h]), float(b.p_y[h])
    obs = st.obstacles(gnd, 0, (cx - 3, cy - 3, cx + 3, cy + 3), {int(h)}, [(cx, cy), (cx, cy)], 0.2)
    cands = []
    for dx in np.arange(-2.0, 2.0001, 0.05):
        for dy in np.arange(-2.0, 2.0001, 0.05):
            X, Y = cx + dx, cy + dy
            d = math.hypot(max(bx0 - X, X - bx1, 0), max(by0 - Y, Y - by1, 0))
            if 0.25 <= d <= 0.29 and (bx0 <= X <= bx1 or by0 <= Y <= by1) and not any(math.hypot(X - px, Y - py) < 0.9 for px, py in placed):
                cands.append((d, min(abs(X - cx), abs(Y - cy)), round(X, 3), round(Y, 3)))
    cands.sort()
    for d, off, X, Y in cands:
        if st.valid([(0, [(X, Y), (X, Y)])], obs, 0.6)[0]:
            st.vias = np.vstack([st.vias, [X, Y, 0.6, gnd]]); placed.append((X, Y))
            print('via   %s.%s at (%.2f, %.2f), %.2f mm from the box (0.15 mm clearance)' % (ref, pin, X, Y, d))
            break
    else:
        still.append(h)
left = still
# a pad with no place at its edge keeps a via of its own on a legal stub (the search of cc_gndvias, 0.15 mm clearance to other nets, as there), until the fill can keep it in the pour
st.req = lambda na, nb, g: 0.15
for h in left:
    ref, pin = b.fp_ref[b.p_fp[h]], b.p_pin[h]
    ps = st.pad_spec(h)
    A = ps['pos']
    Cs = [(A[0] + dx, A[1] + dy) for dx in np.arange(-2.6, 2.61, 0.1) for dy in np.arange(-2.6, 2.61, 0.1) if 0.5 <= math.hypot(dx, dy) <= 2.6]
    Cs.sort(key=lambda p: math.hypot(p[0] - A[0], p[1] - A[1]))
    obs = st.obstacles(gnd, 0, (A[0] - 4, A[1] - 4, A[0] + 4, A[1] + 4), ps['skip'], [A, A], 0.2)
    for V in Cs:
        V = (round(V[0], 3), round(V[1], 3))
        if not st.valid([(0, [V, V])], obs, 0.6)[0]:
            continue
        res = st.route_pair(gnd, 0, 0.2, dict(ps), dict(pos=V, dirs=list(range(8)), minleg=0.62, skip=set()), [A, V], 3, K=1)
        if res:
            pp, ws = res[0]
            for k in range(len(pp) - 1):
                st.new.append((round(pp[k][0], 4), round(pp[k][1], 4), round(pp[k + 1][0], 4), round(pp[k + 1][1], 4), ws[k], 0, gnd))
            st.vias = np.vstack([st.vias, [V[0], V[1], 0.6, gnd]])
            print('stub  %s.%s via at %s path %s' % (ref, pin, V, np.round(pp, 2).tolist()))
            break
    else:
        print('NO VIA for %s.%s' % (ref, pin))
write(sys.argv[1], sys.argv[2], st)
print('pads without an edge via:', ', '.join('%s.%s' % (b.fp_ref[b.p_fp[h]], b.p_pin[h]) for h in left) or 'none')
