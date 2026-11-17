"""Boards built in a test from KiCad's own library footprints with the pcbnew API: no project file, no fixture on disk.
Coordinates here are KiCad's (mm, y down); the tests state what the frame turns them into."""
import os

LIB = os.environ.get('KICAD_FOOTPRINT_DIR', '/usr/share/kicad/footprints')


def mm(pcb, v):
    return pcb.FromMM(v)


def pt(pcb, x, y):
    return pcb.VECTOR2I(pcb.FromMM(x), pcb.FromMM(y))


def build(pcb, path, with_zone=False):
    """two nets (GND, SIG), R1 at (60, 140) with pin 1 on SIG and pin 2 on GND, a 4 mm track on SIG, a via on GND, a board
    outline 40 x 30 from (50, 120), a silk text, and (optionally) a filled GND zone"""
    b = pcb.BOARD()
    nets = {}
    for n in ('GND', 'SIG'):
        ni = pcb.NETINFO_ITEM(b, n)
        b.Add(ni)
        nets[n] = ni
    fp = pcb.FootprintLoad(os.path.join(LIB, 'Resistor_SMD.pretty'), 'R_0603_1608Metric')
    fp.SetReference('R1')
    fp.SetPosition(pt(pcb, 60, 140))
    b.Add(fp)
    fp.FindPadByNumber('1').SetNet(nets['SIG'])
    fp.FindPadByNumber('2').SetNet(nets['GND'])
    t = pcb.PCB_TRACK(b)
    t.SetStart(pt(pcb, 62, 140))
    t.SetEnd(pt(pcb, 66, 140))
    t.SetWidth(mm(pcb, 0.2))
    t.SetLayer(pcb.F_Cu)
    t.SetNet(nets['SIG'])
    b.Add(t)
    v = pcb.PCB_VIA(b)
    v.SetPosition(pt(pcb, 70, 135))
    v.SetDrill(mm(pcb, 0.3))
    v.SetWidth(mm(pcb, 0.6))
    v.SetNet(nets['GND'])
    b.Add(v)
    e = pcb.PCB_SHAPE(b)
    e.SetShape(pcb.SHAPE_T_RECT)
    e.SetStart(pt(pcb, 50, 120))
    e.SetEnd(pt(pcb, 90, 150))
    e.SetLayer(pcb.Edge_Cuts)
    e.SetWidth(mm(pcb, 0.1))
    b.Add(e)
    tx = pcb.PCB_TEXT(b)
    tx.SetText('HELLO')
    tx.SetPosition(pt(pcb, 55, 125))
    tx.SetLayer(pcb.F_SilkS)
    tx.SetTextHeight(mm(pcb, 1.0))
    b.Add(tx)
    pcb.SaveBoard(str(path), b)
    return str(path)


def shape(pcb, b, kind, layer, w, *pts):
    s = pcb.PCB_SHAPE(b)
    s.SetShape(kind)
    s.SetLayer(layer)
    s.SetWidth(pcb.FromMM(w))
    if kind == pcb.SHAPE_T_POLY:
        s.SetPolyPoints([pt(pcb, *p) for p in pts])
    elif kind == pcb.SHAPE_T_ARC:
        s.SetArcGeometry(*[pt(pcb, *p) for p in pts])
    else:
        s.SetStart(pt(pcb, *pts[0]))
        s.SetEnd(pt(pcb, *pts[1]))
    b.Add(s)
    return s


def text(pcb, b, label, x, y, layer, h=1.0, thick=0.15, ang=0.0, just=None, hide=False):
    t = pcb.PCB_TEXT(b)
    t.SetText(label)
    t.SetPosition(pt(pcb, x, y))
    t.SetLayer(layer)
    t.SetTextHeight(pcb.FromMM(h))
    t.SetTextWidth(pcb.FromMM(h))
    t.SetTextThickness(pcb.FromMM(thick))
    t.SetTextAngleDegrees(ang)
    if just is not None:
        t.SetHorizJustify(just)
    if hide:
        t.SetVisible(False)
    b.Add(t)
    return t


def build_rich(pcb, path):
    """what the label and silk tools read: footprints with fab bodies and silk (R1 turned 90 degrees at (60, 140), R2 at (80, 140) with
    its reference hidden and left-justified, X1 at (70, 130) with no fab graphics at all), board silk of every shape on F.SilkS plus
    one each on B.SilkS and F.Fab that must not be read, and texts: HELLO (turned 90, left-justified, 0.2 stroke), GHOST (asked to hide: a board-level text cannot be hidden in KiCad 10), and
    one on B.SilkS that must not be read"""
    b = pcb.BOARD()
    for n in ('GND', 'SIG'):
        b.Add(pcb.NETINFO_ITEM(b, n))
    for ref, x, y, rot in (('R1', 60, 140, 90.0), ('R2', 80, 140, 0.0)):
        fp = pcb.FootprintLoad(os.path.join(LIB, 'Resistor_SMD.pretty'), 'R_0603_1608Metric')
        fp.SetReference(ref)
        fp.SetPosition(pt(pcb, x, y))
        if rot:
            fp.SetOrientationDegrees(rot)
        b.Add(fp)
    r2 = b.FindFootprintByReference('R2')
    ft = pcb.PCB_TEXT(r2)                                   # a text on F.Fab well outside R2's body: part of the F.Fab box
    ft.SetText('FABTXT')
    ft.SetPosition(pt(pcb, 80, 145))
    ft.SetLayer(pcb.F_Fab)
    ft.SetTextHeight(pcb.FromMM(1.0))
    r2.Add(ft)
    r2.Reference().SetVisible(False)
    r2.Reference().SetHorizJustify(pcb.GR_TEXT_H_ALIGN_LEFT)
    x1 = pcb.FOOTPRINT(b)
    x1.SetReference('X1')
    x1.SetPosition(pt(pcb, 70, 130))
    pad = pcb.PAD(x1)
    pad.SetNumber('1')
    pad.SetSize(pcb.VECTOR2I(pcb.FromMM(1.0), pcb.FromMM(1.0)))
    pad.SetShape(pcb.PAD_SHAPE_RECTANGLE)
    pad.SetAttribute(pcb.PAD_ATTRIB_SMD)
    pad.SetLayerSet(pad.SMDMask())
    pad.SetPosition(pt(pcb, 70, 130))
    x1.Add(pad)
    b.Add(x1)
    S, SL = pcb, pcb.F_SilkS
    shape(pcb, b, S.SHAPE_T_SEGMENT, SL, 0.2, (52, 122), (58, 122))
    shape(pcb, b, S.SHAPE_T_RECT, SL, 0.15, (60, 122), (66, 126))
    shape(pcb, b, S.SHAPE_T_POLY, SL, 0.1, (70, 122), (74, 122), (72, 126))
    shape(pcb, b, S.SHAPE_T_ARC, SL, 0.12, (80, 126), (82, 124), (84, 126))
    shape(pcb, b, S.SHAPE_T_CIRCLE, SL, 0.15, (86, 125), (88, 125))
    shape(pcb, b, S.SHAPE_T_SEGMENT, pcb.B_SilkS, 0.2, (52, 128), (58, 128))
    shape(pcb, b, S.SHAPE_T_SEGMENT, pcb.F_Fab, 0.1, (52, 130), (58, 130))
    text(pcb, b, 'HELLO', 55, 135, SL, h=1.0, thick=0.2, ang=90.0, just=pcb.GR_TEXT_H_ALIGN_LEFT)
    text(pcb, b, 'GHOST', 55, 145, SL, hide=True)      # KiCad 10 keeps no hide flag on a board-level text: it stays visible
    text(pcb, b, 'BACK', 55, 147, pcb.B_SilkS)
    e = pcb.PCB_SHAPE(b)
    e.SetShape(pcb.SHAPE_T_RECT)
    e.SetStart(pt(pcb, 50, 120))
    e.SetEnd(pt(pcb, 90, 150))
    e.SetLayer(pcb.Edge_Cuts)
    b.Add(e)
    pcb.SaveBoard(str(path), b)
    return str(path)
