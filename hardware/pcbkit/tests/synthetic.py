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
