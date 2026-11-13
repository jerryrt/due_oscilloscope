"""Add F.Fab arrows (a line with a small head) from the designator label of each named part to the part's centre, as a hand-rework aid
where silk labels are ambiguous (v1: C301 / C304 sit 0.33 mm apart in the AWG block). F.Fab is not printed; it is a fabrication-drawing layer.
usage (inside the image, from hardware/afe-proto): python3 tools/fab_arrows.py BOARD.kicad_pcb REF [REF ...]   (edits BOARD in place)"""
import math
import sys
import pcbnew

board_path, refs = sys.argv[1], sys.argv[2:]
b = pcbnew.LoadBoard(board_path)
mm = pcbnew.ToMM


def seg(a, c):
    s = pcbnew.PCB_SHAPE(b)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(pcbnew.VECTOR2I(*a))
    s.SetEnd(pcbnew.VECTOR2I(*c))
    s.SetLayer(pcbnew.F_Fab)
    s.SetWidth(pcbnew.FromMM(0.1))
    b.Add(s)
    s.thisown = False


for r in refs:
    f = b.FindFootprintByReference(r)
    t = f.Reference().GetPosition()
    p = f.GetPosition()
    d = math.hypot(p.x - t.x, p.y - t.y)
    if d < pcbnew.FromMM(0.2):
        continue
    ux, uy = (p.x - t.x) / d, (p.y - t.y) / d
    # start 0.6 mm from the label centre (outside the ink), end 0.5 mm short of the part centre
    a = (int(t.x + ux * pcbnew.FromMM(0.6)), int(t.y + uy * pcbnew.FromMM(0.6)))
    c = (int(p.x - ux * pcbnew.FromMM(0.5)), int(p.y - uy * pcbnew.FromMM(0.5)))
    seg(a, c)
    h = pcbnew.FromMM(0.4)
    for sgn in (1, -1):
        ang = math.atan2(-uy, -ux) + sgn * math.radians(28)
        seg(c, (int(c[0] + h * math.cos(ang)), int(c[1] + h * math.sin(ang))))
    print(r, 'arrow from label (%.2f, %.2f) to part (%.2f, %.2f)' % (mm(t.x) - 50, 150 - mm(t.y), mm(p.x) - 50, 150 - mm(p.y)))
b.Save(board_path)
