"""Read the board with pcbnew for the relayout placer (relayout_place.py): parts (origin, rotation, courtyard, the extent of their own top silk, pads),
tracks and vias, and the board's own top-silk drawings (lines, arcs, rects, text) with their boxes. Due mm, y up (x - 50, 150 - y).
    python3 relayout_dump.py BOARD.kicad_pcb OUT.json        (in the PCB image)"""
import json, sys
import pcbnew
b = pcbnew.LoadBoard(sys.argv[1]); mm = pcbnew.ToMM
def X(v): return mm(v) - 50.0
def Y(v): return 150.0 - mm(v)
def box(bb): return [X(bb.GetLeft()), Y(bb.GetBottom()), X(bb.GetRight()), Y(bb.GetTop())]
parts = []
for f in b.GetFootprints():
    c = f.GetCourtyard(pcbnew.F_CrtYd)
    cy = box(c.BBox()) if c.OutlineCount() else None
    sx = None
    for g in f.GraphicalItems():
        if g.GetLayer() == pcbnew.F_SilkS and not hasattr(g, 'GetText'):
            bb = box(g.GetBoundingBox())
            sx = bb if sx is None else [min(sx[0], bb[0]), min(sx[1], bb[1]), max(sx[2], bb[2]), max(sx[3], bb[3])]
    t = f.Reference(); tp = t.GetPosition()
    pads = []
    for p in f.Pads():
        bb = box(p.GetBoundingBox())
        pads.append(dict(n=p.GetNumber(), net=p.GetNetname(), c=[X(p.GetPosition().x), Y(p.GetPosition().y)], bb=bb))
    parts.append(dict(ref=f.GetReference(), val=f.GetValue(), x=X(f.GetPosition().x), y=Y(f.GetPosition().y), rot=f.GetOrientationDegrees(),
                      side='B' if f.IsFlipped() else 'F', cy=cy, silk=sx, pads=pads, tx=X(tp.x), ty=Y(tp.y), tang=t.GetTextAngleDegrees(),
                      tlayer=b.GetLayerName(t.GetLayer()), tvis=t.IsVisible()))
trk = []
for t in b.GetTracks():
    if t.Type() == pcbnew.PCB_VIA_T:
        trk.append(dict(k='via', c=[X(t.GetPosition().x), Y(t.GetPosition().y)], net=t.GetNetname(), d=mm(t.GetWidth(pcbnew.F_Cu))))
    else:
        trk.append(dict(k='seg', a=[X(t.GetStart().x), Y(t.GetStart().y)], b=[X(t.GetEnd().x), Y(t.GetEnd().y)], net=t.GetNetname(), w=mm(t.GetWidth()), l=b.GetLayerName(t.GetLayer())))
draw = []
for d in b.GetDrawings():
    if d.GetLayer() not in (pcbnew.F_SilkS, pcbnew.B_SilkS):
        continue
    kind = 'text' if hasattr(d, 'GetText') else 'shape'
    e = dict(kind=kind, layer=b.GetLayerName(d.GetLayer()), bb=box(d.GetBoundingBox()))
    if kind == 'text':
        e['text'] = d.GetText(); e['at'] = [X(d.GetPosition().x), Y(d.GetPosition().y)]; e['ang'] = d.GetTextAngleDegrees()
    else:
        e['shape'] = d.GetShapeStr(); e['a'] = [X(d.GetStart().x), Y(d.GetStart().y)]; e['b'] = [X(d.GetEnd().x), Y(d.GetEnd().y)]
    draw.append(e)
json.dump(dict(parts=parts, trk=trk, draw=draw), open(sys.argv[2], 'w'))
print(len(parts), len(trk), len(draw))
