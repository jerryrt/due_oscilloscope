import pcbnew, sys, json
b = pcbnew.LoadBoard(sys.argv[1])
mm = pcbnew.ToMM
out = []
for f in b.GetFootprints():
    r = f.GetReference()
    p = f.GetPosition()
    cy = f.GetBoundingBox(False, False)
    try:
        c = f.GetCourtyard(pcbnew.F_CrtYd); bb = c.BBox()
        cyd = [mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())] if c.OutlineCount() else None
    except Exception as e:
        cyd = None
    t = f.Reference()
    tp = t.GetPosition()
    tb=t.GetBoundingBox(); tbb=[mm(tb.GetLeft()),mm(tb.GetTop()),mm(tb.GetRight()),mm(tb.GetBottom())]
    try:
        sh=t.GetEffectiveTextShape().BBox(); ink=[mm(sh.GetLeft()),mm(sh.GetTop()),mm(sh.GetRight()),mm(sh.GetBottom())]
    except Exception: ink=None
    out.append(dict(tbb=tbb,ink=ink,ref=r, val=f.GetValue(), x=mm(p.x), y=mm(p.y), rot=f.GetOrientationDegrees(), side='B' if f.IsFlipped() else 'F',
      cy=cyd, tx=mm(tp.x), ty=mm(tp.y), trot=t.GetTextAngleDegrees(), tvis=t.IsVisible(), tlayer=b.GetLayerName(t.GetLayer()),
      tsize=mm(t.GetTextWidth()), tth=mm(t.GetTextThickness()), fp=str(f.GetFPID().GetLibItemName())))
json.dump(out, open(sys.argv[2], 'w'), indent=0)
print(len(out))
