import pcbnew, sys, json
b = pcbnew.LoadBoard(sys.argv[1]); mm = pcbnew.ToMM
def D(x,y): return [round(mm(x)-50,4), round(150-mm(y),4)]
pads=[]
for f in b.GetFootprints():
    for p in f.Pads():
        bb=p.GetBoundingBox()
        pads.append(dict(ref=f.GetReference(), n=p.GetNumber(), net=p.GetNetname(), c=D(p.GetPosition().x,p.GetPosition().y), bb=[mm(bb.GetLeft())-50,150-mm(bb.GetBottom()),mm(bb.GetRight())-50,150-mm(bb.GetTop())], th=p.GetAttribute()==pcbnew.PAD_ATTRIB_PTH))
trk=[]
for t in b.GetTracks():
    if t.Type()==pcbnew.PCB_VIA_T:
        trk.append(dict(k='via', c=D(t.GetPosition().x,t.GetPosition().y), net=t.GetNetname(), d=mm(t.GetWidth(pcbnew.F_Cu))))
    else:
        trk.append(dict(k='seg', a=D(t.GetStart().x,t.GetStart().y), b=D(t.GetEnd().x,t.GetEnd().y), net=t.GetNetname(), w=mm(t.GetWidth()), l=b.GetLayerName(t.GetLayer())))
json.dump(dict(pads=pads,trk=trk), open(sys.argv[2],'w'))
print(len(pads),len(trk))
