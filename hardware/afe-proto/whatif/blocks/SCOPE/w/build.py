"""SCOPE block: place + route from orig.kicad_pcb into OUT. Due mm. Bounded, one process."""
import sys
from pcbtools.editor import edit
SRC, OUT = sys.argv[1], sys.argv[2]
YM = 68.58                               # mirror axis y=34.29 (U101 centre line)
mir = lambda y: round(YM - y, 3)
Xb, YB, YMD, YT = 81.2, 41.4, 43.1, 44.8
NW, NE = Xb-0.8, Xb+0.8                  # N pads of the west / east parts (courtyards must not touch)
XE, XW, XC = NE+0.82, NW-0.82, NW-0.78   # centres: east R, west R, west C
XNP = NE+1.64                            # R106.2 (NP) x
UX, UY = XNP-1.9, 34.29                  # U101 pin 5 under the NP pad
XV = 71.5                                # VREF bridge column
Y_A1, Y_T = 39.5, 35.3                   # A1 line, +3V3A trunk (CH1)
Y_A0 = mir(Y_A1)
P = {}
ch1 = {'R106': (XE, YB, 0), 'R103': (XE, YMD, 180), 'R105': (XE, YT, 0), 'R101': (XE+3.1, YT, 0),
       'C102': (XC, YB, 180), 'R104': (XW, YMD, 180), 'C101': (XC, YT, 0), 'R102': (90.6, YMD, 180),
       'C105': (XNP+1.76, 39.0, 0), 'R107': (UX-0.82, Y_A1, 180), 'D101': (68.8, Y_A1-0.94, 90), 'TP101': (74.0, Y_A1, 0),
       'R112': (XV, Y_A1, 90), 'R113': (XV, Y_T, 90), 'R108': (75.2, Y_T, 0), 'C104': (86.9, Y_T, 0), 'C103': (77.4, 38.0, 180)}
P.update(ch1)
for a_, b_ in (('R106','R206'),('R103','R203'),('R105','R205'),('R101','R201'),('C102','C202'),('R104','R204'),('C101','C201'),
             ('R102','R202'),('C105','C203')):
    x, y, r = ch1[a_]; P[b_] = (x, mir(y), r)
P.update({'R207': (UX-1.27-0.82, Y_A0, 180), 'D201': (74.1, Y_A0+0.94, 270), 'TP201': (77.0, Y_A0, 0), 'R111': (XV, Y_A0, 90),
          'U101': (UX, UY, 90)})
W = 0.2; WS = 0.25
tr = []        # (net, w, [pts])
vi = []        # (net, x, y)

with edit(SRC, OUT) as e:
    for r, (x, y, rot) in P.items():
        e.move(r, x, y, rot)
    # bridges: pin1 south of pin2 (VREF_Q/S/P side south)
    for r in ('R112', 'R113', 'R111'):
        if e.pad_xy(r, 1)[1] > e.pad_xy(r, 2)[1]:
            x, y, _ = P[r]; e.move(r, x, y, 270)
    pad = e.pad_xy
    def T(net, w, *pts): tr.append((net, w, list(pts)))
    def GV(net, ref, pin, dx, dy):
        x, y = pad(ref, pin); T(net, W, (x, y), (x+dx, y+dy)); vi.append((net, x+dx, y+dy))
    # ---- CH1 divider bus and chain
    T('CH1_N', W, (Xb, YB), (Xb, YT))
    for ref, pn, dy in (('R106',1,YB),('R103',2,YMD),('R105',1,YT),('C102',1,YB),('R104',1,YMD),('C101',2,YT)):
        x, y = pad(ref, pn); T('CH1_N', W, (x, y), (Xb, y))
    T('CH1_R1A', W, pad('R103',1), pad('R102',2))
    T('CH1_R2A', W, pad('R105',2), pad('R101',1))
    GV('GND', 'R101', 2, 1.1, 0); GV('GND', 'C102', 2, -1.2, 0)
    # IN: BNC -> R102.1 ; C101.1 around the north
    T('CH1_IN', W, (102.0, 44.45), (98.5, 44.45)); T('CH1_IN', W, (97.8, 44.45), (91.42, 44.45))
    T('CH1_IN', W, pad('R102',1), (91.42, 46.6)); x, y = pad('C101',1)
    T('CH1_IN', W, (x, y), (x, 46.6), (91.42, 46.6))
    # NP: R106.2 down to U101.5, C105
    T('CH1_NP', W, pad('R106',2), pad('U101',5)); x, y = pad('C105',1); T('CH1_NP', W, (XNP, y), (x, y))
    GV('GND', 'C105', 2, 1.1, 0)
    # OUT -> R107 ; A1 line
    T('CH1_OUT', W, pad('U101',6), pad('U101',7)); T('CH1_OUT', W, (UX, 36.76), pad('R107',1))
    T('A1', W, pad('R107',2), (66.04, Y_A1), (66.04, 33.5))
    x, y = pad('D101',3); T('A1', W, (x, y), (x, Y_A1))
    # D101 : GND via, P33_U tap
    GV('GND', 'D101', 1, -0.9, 0)
    x, y = pad('D101', 2); T('P33_U', WS, (x, y), (x, Y_T))
    # trunk
    x, y = pad('R110', 2); T('P33_U', WS, (x, y), (x, Y_T), (pad('R108',1)[0], Y_T))
    # P33_S edge
    T('P33_S', W, (64.8, 35.7), pad('R110',1))
    # SC_VCC
    T('SC_VCC', WS, pad('R108',2), (pad('R108',2)[0], 36.76), pad('U101',8))
    x, y = pad('C103',1); T('SC_VCC', WS, (x, y), (x, 36.76))
    T('SC_VCC', WS, pad('R108',2), pad('C104',1))
    GV('GND', 'C103', 2, -1.2, 0); GV('GND', 'C104', 2, 1.3, 0)
    # VREF chain
    x1, y1 = pad('R111', 2); T('VREF_Q', W, (x1, y1), (x1, 33.0)); T('VREF_Q', W, (x1, 33.5), pad('R113', 1))
    T('VREF_S', W, pad('R113', 2), pad('R112', 1))
    x, y = pad('R112', 2); x2, y2 = pad('R104', 2); T('VREF_R', W, (x, y), (x, YMD), (x2, y2))
    # ---- CH2 mirrored chain
    T('CH2_N', W, (Xb, mir(YB)), (Xb, mir(YT)))
    for ref, pn in (('R206',1),('R203',2),('R205',1),('C202',1),('R204',1),('C201',2)):
        x, y = pad(ref, pn); T('CH2_N', W, (x, y), (Xb, y))
    T('CH2_R1A', W, pad('R203',1), pad('R202',2)); T('CH2_R2A', W, pad('R205',2), pad('R201',1))
    GV('GND', 'R201', 2, 1.1, 0); GV('GND', 'C202', 2, -1.2, 0)
    T('CH2_IN', W, (102.0, 24.13), (98.5, 24.13)); T('CH2_IN', W, (97.8, 24.13), (91.42, 24.13))
    T('CH2_IN', W, pad('R202',1), (91.42, mir(46.6))); x, y = pad('C201',1)
    T('CH2_IN', W, (x, y), (x, mir(46.6)), (91.42, mir(46.6)))
    # NP (pin 3) and C203
    x3, y3 = pad('U101', 3); xr, yr = pad('R206', 2); xc, yc = pad('C203', 1)
    T('CH2_NP', W, (xr, yr), (xr, yc), (xc, yc)); T('CH2_NP', W, (xr, yc), (x3, yc), (x3, y3))
    GV('GND', 'C203', 2, 1.1, 0); GV('GND', 'U101', 4, 1.3, 0)
    T('CH2_OUT', W, pad('U101',1), pad('U101',2)); T('CH2_OUT', W, (UX-1.27, 31.82), pad('R207',1))
    T('A0', W, pad('R207',2), (69.6, Y_A0), (69.6, 33.0), (69.4, 33.0))
    x, y = pad('D201', 3); T('A0', W, (x, y), (x, Y_A0)); T('A0', W, pad('TP201',1), (76.6, Y_A0))
    GV('GND', 'D201', 1, 1.1, 0)
    x, y = pad('D201', 2); T('P33_U', WS, (x, y), (x, 32.4), (72.6, 32.4), (72.6, 33.0)); T('P33_U', WS, (72.6, 33.5), (72.6, Y_T))
    # VREF_P
    xv, yv = pad('R111', 1); xr4, yr4 = pad('R204', 2)
    T('VREF_P', W, (69.4, 24.5), (xv, 24.5), (xv, yv)); T('VREF_P', W, (xv, yr4), (xr4, yr4))
    for net, w, pts in tr:
        for a, b in zip(pts, pts[1:]):
            if abs(a[0]-b[0]) > 1e-9 or abs(a[1]-b[1]) > 1e-9:
                e.add_tracks(net, 'F', a[0], a[1], b[0], b[1], w)
    for net, x, y in vi:
        e.add_vias(net, x, y)
print('built', len(tr), 'polylines', len(vi), 'vias')
