"""A board built in a test from KiCad's own library footprints with the pcbnew API (no project file): R1, a track, a via, a rectangle outline, a silk text, optionally a GND zone."""
import os, sys
sys.path.append('/usr/lib/python3/dist-packages')
LIB = os.environ.get('KICAD_FOOTPRINT_DIR', '/usr/share/kicad/footprints')


def build(path, dx=0.0, track_dx=0.0, drill=0.3, zone_dx=0.0, sig_net_on_pin2=False, text_dx=0.0, model=None, zone=False):
    import pcbnew as pcb
    pt = lambda x, y: pcb.VECTOR2I(pcb.FromMM(x), pcb.FromMM(y))
    b = pcb.BOARD()
    nets = {}
    for n in ('GND', 'SIG'):
        ni = pcb.NETINFO_ITEM(b, n); b.Add(ni); nets[n] = ni
    fp = pcb.FootprintLoad(os.path.join(LIB, 'Resistor_SMD.pretty'), 'R_0603_1608Metric')
    fp.SetReference('R1'); fp.SetPosition(pt(60 + dx, 140)); b.Add(fp)
    fp.FindPadByNumber('1').SetNet(nets['GND' if sig_net_on_pin2 else 'SIG']); fp.FindPadByNumber('2').SetNet(nets['SIG' if sig_net_on_pin2 else 'GND'])
    if model:
        m = pcb.FP_3DMODEL(); m.m_Filename = model; fp.Add3DModel(m)
    t = pcb.PCB_TRACK(b); t.SetStart(pt(62 + track_dx, 140)); t.SetEnd(pt(66 + track_dx, 140)); t.SetWidth(pcb.FromMM(0.2)); t.SetLayer(pcb.F_Cu); t.SetNet(nets['SIG']); b.Add(t)
    v = pcb.PCB_VIA(b); v.SetPosition(pt(70, 135)); v.SetDrill(pcb.FromMM(drill)); v.SetWidth(pcb.FromMM(0.6)); v.SetNet(nets['GND']); b.Add(v)
    e = pcb.PCB_SHAPE(b); e.SetShape(pcb.SHAPE_T_RECT); e.SetStart(pt(50, 120)); e.SetEnd(pt(90, 150)); e.SetLayer(pcb.Edge_Cuts); e.SetWidth(pcb.FromMM(0.1)); b.Add(e)
    tx = pcb.PCB_TEXT(b); tx.SetText('HELLO'); tx.SetPosition(pt(55 + text_dx, 125)); tx.SetLayer(pcb.F_SilkS); tx.SetTextHeight(pcb.FromMM(1.0)); b.Add(tx)
    if zone:
        z = pcb.ZONE(b); z.SetLayer(pcb.F_Cu); z.SetNet(nets['GND'])
        o = z.Outline(); o.NewOutline()
        for x, y in ((52, 122), (58 + zone_dx, 122), (58, 130), (52, 130)):
            o.Append(pcb.FromMM(x), pcb.FromMM(y))
        b.Add(z)
    pcb.SaveBoard(str(path), b)
    return str(path)
