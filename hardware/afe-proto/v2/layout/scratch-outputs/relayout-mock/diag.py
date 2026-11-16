import sys, json
sys.argv=[sys.argv[0]]+sys.argv[1:]
sys.argv=[sys.argv[0],sys.argv[1],'0','[[62.4,27.9,69.0,32.9]]']
import place_ch2 as M
sys.argv=[sys.argv[0],sys.argv[1]]
st={k:tuple(v) for k,v in json.load(open(__import__('os').path.basename(sys.argv[1])))['st'].items()}
cy,lb=M.geom(st)
for r in M.MOVE:
    a=M.inside(cy[r],M.REGION,M.INSET); b=M.inside(lb[r],M.REGION,M.INSET)
    if a or b: print(r,'outside region',round(a,2),round(b,2))
    for k,f in M.P.items():
        if k in M.MOVE: continue
        o=M.ov(cy[r],M.cyd(f),0.1); z=M.ov(lb[r],M.cyd(f),M.ZONE)
        if o or z: print(r,'cy/zone vs',k,round(o,2),round(z,2))
    for k,f in M.P.items():
        if k in M.MOVE or not f['tvis']: continue
        o=M.ov(lb[r],M.ink(f),M.LABEL_GAP)
        if o: print(r,'label vs label of',k,round(o,2))
for i,r in enumerate(M.MOVE):
    for s in M.MOVE[i+1:]:
        v=M.ov(cy[r],cy[s],0.1)+M.ov(lb[r],lb[s],M.LABEL_GAP)+M.ov(lb[r],cy[s],M.ZONE)+M.ov(lb[s],cy[r],M.ZONE)
        if v: print(r,s,round(v,2))
