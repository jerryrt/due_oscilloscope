"""P3 manual photo landmarks and projective registration (stdlib only).

Pixels below use the indicated resized, oriented image coordinate systems.
These are visual picks, not dimensional measurements. The owner's 103x55
outline and nominal 2.54 mm hole pitch are the registration constraints.
"""
import json
import math
from pathlib import Path


def solve(a, b):
    a = [list(row) + [value] for row, value in zip(a, b)]
    for c in range(len(b)):
        pivot = max(range(c, len(b)), key=lambda r: abs(a[r][c]))
        a[c], a[pivot] = a[pivot], a[c]
        divisor = a[c][c]
        a[c] = [v / divisor for v in a[c]]
        for r in range(len(b)):
            if r != c:
                factor = a[r][c]
                a[r] = [v - factor * w for v, w in zip(a[r], a[c])]
    return [row[-1] for row in a]


def fit(pairs):
    a, b = [], []
    for (u, v), (x, y) in pairs:
        a.extend(([u, v, 1, 0, 0, 0, -x*u, -x*v],
                  [0, 0, 0, u, v, 1, -y*u, -y*v]))
        b.extend((x, y))
    return solve([[sum(row[i]*row[j] for row in a) for j in range(8)]
                  for i in range(8)],
                 [sum(row[i]*v for row, v in zip(a, b)) for i in range(8)])


def project(h, p):
    u, v = p
    d = h[6]*u + h[7]*v + 1
    return [(h[0]*u + h[1]*v + h[2])/d,
            (h[3]*u + h[4]*v + h[5])/d]


OUTLINE_PICKS = [((334, 507), (0, 0)), ((1580, 470), (103, 0)),
                 ((1606, 1152), (103, 55)), ((344, 1183), (0, 55))]
FULL_PICKS = {
    'PG1': (381, 608), 'J1': (580, 568), 'J10': (578, 520),
    'J2': (844, 559), 'J11': (842, 510),
    'J3': (1119, 551), 'J12': (1116, 500),
    'J4': (704, 1157), 'J13': (703, 1106),
    'J5': (921, 1150), 'J14': (919, 1100),
    'J6': (1202, 1143), 'J15': (1200, 1093),
    'J7': (1427, 496), 'J8': (1496, 494), 'J9': (357, 527),
    'H1': (520, 550), 'H2': (1467, 1099),
    'TP1': (395, 766), 'TP1_bottom': (397, 882),
    'V50': (1390, 1007), 'V51': (1403, 929),
}
full_h = fit(OUTLINE_PICKS)
FULL_MM = {key: project(full_h, point) for key, point in FULL_PICKS.items()}
# Rounded registration; fit error includes the owner's rounded outline size,
# lens distortion and manual picking. Preserve nominal grid/header pitches.
GRID_X, GRID_Y = 3.8, 8.3


def grid(r, c):
    return GRID_X + (c-1)*2.54, GRID_Y + (r-1)*2.54


# IMG_2136 rotated 270; lossless crop +800+992 2400x1400, displayed at
# 2048x1195. Several grid rows constrain both scale and perspective.
CONTROL_PAIRS = [((100, 37), grid(11, 1)), ((634, 28), grid(11, 6)),
                 ((106, 358), grid(14, 1)), ((639, 350), grid(14, 6)),
                 ((108, 465), grid(15, 1)), ((641, 455), grid(15, 6)),
                 ((1068, 447), grid(15, 10))]
CONTROL_PICKS = {
    'SW1.1': (704, 648), 'SW1.2': (977, 645),
    'SW1.3': (706, 840), 'SW1.4': (980, 832),
    'R1.1': (365, 608), 'R1.2': (451, 607),
    'R2.1': (365, 737), 'R2.2': (453, 736),
    'R3.1': (381, 877), 'R3.2': (460, 876),
    'D1.1': (132, 675), 'D1.2': (197, 675),
    'D2.1': (135, 884), 'D2.2': (199, 884),
    'VSTAT': (573, 874), 'VLED': (60, 771),
    'J4.1': (1185, 868), 'J13.1': (1185, 685),
}
control_h = fit(CONTROL_PAIRS)
CONTROL_MM = {key: project(control_h, point) for key, point in CONTROL_PICKS.items()}


def report():
    return dict(photo='IMG_2135.jpeg rotated 270; 1824x1368 display coordinates',
                outline_picks=OUTLINE_PICKS, full_image_mm=FULL_MM,
                control_photo='IMG_2136.jpeg rotated 270; crop +800+992 2400x1400; 2048x1195 display',
                control_grid_landmarks=CONTROL_PAIRS, control_mm=CONTROL_MM,
                control_fit_rms_mm=math.sqrt(sum(sum((a-b)**2 for a,b in zip(project(control_h,p),q))
                                               for p,q in CONTROL_PAIRS)/len(CONTROL_PAIRS)),
                interpretation='Photo registration only; values rounded in the CAD model. Physical fit pending.')


if __name__ == '__main__':
    data = report()
    Path(__file__).with_name('photo-registration.json').write_text(json.dumps(data, indent=2)+'\n')
    print(json.dumps(data, indent=2))
