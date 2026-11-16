"""draw parts (courtyards, pads), tracks and ref labels of a parts/pads dump region to a PNG (PIL). python3 viz.py parts.json pads.json out.png x0 y0 x1 y1 [scale]"""
import json, sys
from PIL import Image, ImageDraw, ImageFont
def cyd(p):
    c=p['cy']; return (c[0]-50,150-c[3],c[2]-50,150-c[1])
def draw(parts,pads,out,box,S=20,labels=None,extra=None):
    x0,y0,x1,y1=box
    W,H=int((x1-x0)*S),int((y1-y0)*S)
    im=Image.new('RGB',(W,H),'white'); d=ImageDraw.Draw(im)
    f=ImageFont.load_default()
    def P(x,y): return ((x-x0)*S,(y1-y)*S)
    def R(r,**k):
        a=P(r[0],r[3]); b=P(r[2],r[1]); d.rectangle([a,b],**k)
    for p in parts:
        R(cyd(p),outline=(0,120,0),fill=(235,250,235))
    for p in pads['pads']:
        R(p['bb'],fill=(200,130,130))
    for t in pads['trk']:
        if t['k']=='seg':
            d.line([P(*t['a']),P(*t['b'])],fill=(0,0,200) if t['l']=='F.Cu' else (200,0,200),width=max(1,int(t['w']*S)))
        else:
            c=P(*t['c']); r=t['d']/2*S; d.ellipse([c[0]-r,c[1]-r,c[0]+r,c[1]+r],outline=(0,0,0))
    for (r,k) in (extra or []): R(r,**k)
    for ref,(cx,cy,L,Hh) in (labels or {}).items():
        R((cx-L/2,cy-Hh/2,cx+L/2,cy+Hh/2),outline=(220,0,0))
        d.text(P(cx-L/2+0.1,cy+Hh/2),ref,fill=(220,0,0),font=f)
    for p in parts:
        c=cyd(p); d.text(P(c[0]+0.1,c[3]-0.1),p['ref'],fill=(0,80,0),font=f) if not labels else None
    im.save(out)
if __name__=='__main__':
    parts=json.load(open(sys.argv[1])); pads=json.load(open(sys.argv[2]))
    box=tuple(float(v) for v in sys.argv[4:8]); S=float(sys.argv[8]) if len(sys.argv)>8 else 20
    draw(parts,pads,sys.argv[3],box,S)
