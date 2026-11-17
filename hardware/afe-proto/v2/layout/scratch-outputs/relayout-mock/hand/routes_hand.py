# hand routes on the bridge-free netlist (Due mm). A1 and A0 first: they are the walls everything else is drawn around.
W = 0.2
ROUTES = [
 # A1: J602.7 north along x 66.04, east along y 35.9 to R108.2, west stub to D101.3, north stub to TP101.1
 ('A1', 'F', [(66.04, 2.7), (66.04, 35.9), (76.7, 35.9)], W),
 ('A1', 'F', [(66.04, 35.9), (64.06, 35.9), (64.06, 38.6)], W),
 ('A1', 'F', [(69.5, 35.9), (69.5, 43.8)], W),
 # A0: J602.8 north along x 68.58 to y 27.3, east along y 27.3 to R208.2 (entered from the south at x 81.9), stubs to D201.3 and TP201.1
 ('A0', 'F', [(68.58, 2.7), (68.58, 27.3), (81.9, 27.3), (81.9, 28.1)], W),
 ('A0', 'F', [(70.56, 27.3), (70.56, 24.9)], W),
 ('A0', 'F', [(76.0, 27.3), (76.0, 29.2)], W),
]
VIAS = []
