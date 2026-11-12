"""blocktools.py: the small pcbnew helpers a block agent uses to place and route inside its own fence.

Run your script with  /usr/bin/python3.14 -I  (pcbnew only imports there; -I drops the current directory, so start the script with
sys.path.insert(0, '/home/jerry/EE.Projects/due_oscilloscope/hardware/afe-proto/kicad') ).  Everything is in Due coordinates (mm, x right,
y up); the board transform is board_x = 50 + x, board_y = 150 - y.

    import blocktools as bt
    b = bt.load('mine.kicad_pcb')
    bt.move(b, 'R303', 80.0, 6.9, 180)                  # centre and rotation (degrees)
    bt.track(b, 'AWG_OUT', 'F', [(80.65, 9.53), (80.65, 8.1)], 0.25)
    bt.via(b, 'GND', 81.0, 7.0)                         # 0.6 / 0.3 mm
    x, y = bt.pad(b, 'U301', '7')                       # a pad's centre
    bt.silk_ref(b, 'R303', 0.0, 1.4)                    # designator on F.SilkS at 1.0 mm, offset from the part centre
    bt.silk_word(b, 'AWG', 82.0, 18.0)                  # block word, 1.0 mm
    bt.save(b, 'mine.kicad_pcb')
    print(bt.drc('mine.kicad_pcb'))                     # {'type': count} of violations (kicad-cli, all severities)

Tracks and vias outside your fence are rejected by fence_check.py (a track crossing the fence edge counts as outside).
GND is the bottom plane: give every GND pad its own via; the integrator fills the pour.  Never draw a bottom signal track.
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew as pcb  # noqa: E402

OX, OY = 50.0, 150.0
_keep = []          # pcbnew SWIG crashes if a board or a removed item is garbage-collected: keep them alive


def P(x, y):
    return pcb.VECTOR2I(pcb.FromMM(OX + x), pcb.FromMM(OY - y))


def load(path):
    b = pcb.LoadBoard(path)
    _keep.append(b)
    return b


def save(b, path):
    pcb.SaveBoard(path, b)


def fp(b, ref):
    f = b.FindFootprintByReference(ref)
    if f is None:
        raise KeyError(ref)
    return f


def move(b, ref, x, y, rot=None):
    f = fp(b, ref)
    f.SetPosition(P(x, y))
    if rot is not None:
        f.SetOrientationDegrees(rot)


def pad(b, ref, num):
    p = fp(b, ref).FindPadByNumber(str(num))
    return (pcb.ToMM(p.GetPosition().x) - OX, OY - pcb.ToMM(p.GetPosition().y))


def _net(b, name):
    n = b.FindNet('/' + name) or b.FindNet(name)
    if n is None:
        raise KeyError(name)
    return n


def track(b, net, layer, pts, width=0.25):
    lay = pcb.F_Cu if layer == 'F' else pcb.B_Cu
    n = _net(b, net)
    for a, c in zip(pts, pts[1:]):
        t = pcb.PCB_TRACK(b)
        t.SetStart(P(*a)); t.SetEnd(P(*c)); t.SetWidth(pcb.FromMM(width)); t.SetLayer(lay); t.SetNet(n)
        b.Add(t)
        _keep.append(t)


def via(b, net, x, y, dia=0.6, drill=0.3):
    v = pcb.PCB_VIA(b)
    v.SetPosition(P(x, y)); v.SetWidth(pcb.FromMM(dia)); v.SetDrill(pcb.FromMM(drill)); v.SetNet(_net(b, net))
    v.SetViaType(pcb.VIATYPE_THROUGH)
    b.Add(v)
    _keep.append(v)


def silk_ref(b, ref, dx, dy, size=1.0):
    """the designator on F.SilkS, size mm tall, at (part centre + (dx, dy))"""
    f = fp(b, ref)
    r = f.Reference()
    r.SetLayer(pcb.F_SilkS)
    r.SetVisible(True)
    r.SetTextSize(pcb.VECTOR2I(pcb.FromMM(size), pcb.FromMM(size)))
    r.SetTextThickness(pcb.FromMM(0.15))
    c = f.GetPosition()
    r.SetPosition(pcb.VECTOR2I(c.x + pcb.FromMM(dx), c.y - pcb.FromMM(dy)))
    r.SetTextAngleDegrees(0)


def silk_word(b, text, x, y, size=1.0):
    t = pcb.PCB_TEXT(b)
    t.SetText(text); t.SetLayer(pcb.F_SilkS); t.SetPosition(P(x, y))
    t.SetTextSize(pcb.VECTOR2I(pcb.FromMM(size), pcb.FromMM(size))); t.SetTextThickness(pcb.FromMM(0.15))
    b.Add(t)
    _keep.append(t)


def drc(path):
    out = os.path.join(tempfile.mkdtemp(), 'drc.json')
    subprocess.run(['kicad-cli', 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', out, path], capture_output=True)
    d = json.load(open(out))
    kinds = {}
    for v in d.get('violations', []):
        if not v.get('excluded'):
            kinds[v['type']] = kinds.get(v['type'], 0) + 1
    return kinds
