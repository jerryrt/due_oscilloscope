import sys
sys.path.append('/usr/lib/python3/dist-packages'); import pcbnew
b = pcbnew.LoadBoard(sys.argv[1]); mm = pcbnew.ToMM
for r, lab in (('J101', 'CH1 IN'), ('J201', 'CH2 IN'), ('J301', 'AWG OUT')):
    f = b.FindFootprintByReference(r); rb = f.Reference().GetBoundingBox(); ox, oy = mm(f.GetPosition().x) - 50, 150 - mm(f.GetPosition().y)
    for d in b.GetDrawings():
        if d.GetClass() == 'PCB_TEXT' and d.GetText() == lab:
            tb = d.GetBoundingBox(); just = d.GetHorizJustify()
            print(r, 'designator right edge %.3f, function text left edge %.3f -> gap %.3f mm; function left edge offset from origin %.3f; designator offset (%.3f); justify=%s' % (mm(rb.GetRight()) - 50, mm(tb.GetX()) - 50, mm(tb.GetX()) - mm(rb.GetRight()), mm(tb.GetX()) - 50 - ox, (mm(rb.GetX()) + mm(rb.GetRight())) / 2 - 50 - ox, just))
