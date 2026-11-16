import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
import json
from PIL import Image, ImageDraw, ImageFont
BOARD=(17.0,-4.5,117.0,57.84); DUE=(17.0,0.0,117.0,53.34)
CUR={'POWER':[(17.9,4.6,43.6,26.0)],'REF/CAL':[(44.2,4.6,64.4,27.8),(64.6,18.6,70.2,26.0)],'CH1':[(63.9,33.0,93.0,50.0),(60.4,34.6,64.0,36.8)],'CH2':[(69.0,19.75,93.0,32.9)],'AWG':[(70.4,4.55,92.3,19.25)]}
NEW={'POWER':[(17.9,4.6,43.6,29.5)],'REF/CAL':[(44.2,4.6,62.0,27.8),(44.2,27.8,62.0,38.0),(44.2,38.0,58.0,48.9),(64.6,18.6,70.2,26.0)],'CH1':[(62.4,33.0,93.0,50.0),(58.0,38.0,62.4,50.0)],'CH2':[(69.0,19.75,93.0,32.9)],'AWG':[(70.4,4.55,92.3,19.25),(62.0,4.55,70.4,18.4)]}
NEED={'POWER':582,'CH1':509,'REF/CAL':776,'AWG':473,'CH2':322}     # (courtyards + label zones) / 0.55, areas.py
COL={'POWER':(200,60,60),'REF/CAL':(40,120,200),'CH1':(40,150,80),'CH2':(210,120,0),'AWG':(130,70,170)}
def area(rs): return sum((r[2]-r[0])*(r[3]-r[1]) for r in rs)
def overl(a,b): return min(a[2],b[2])-max(a[0],b[0])>1e-9 and min(a[3],b[3])-max(a[1],b[1])>1e-9
def check():
    rs=[(k,r) for k,v in NEW.items() for r in v]
    for i,(k,r) in enumerate(rs):
        for k2,r2 in rs[i+1:]:
            if k!=k2 and overl(r,r2): print('OVERLAP',k,r,k2,r2)
    for k,v in NEW.items():
        for r in v:
            if r[0]<17.9-1e-9 or r[2]>93.0+1e-9 or r[1]<4.55-1e-9 or r[3]>50+1e-9: print('outside interior',k,r)
if __name__=='__main__':
    check()
    S=14; W=int((BOARD[2]-BOARD[0]+4)*S); H=int((BOARD[3]-BOARD[1]+10)*S)
    im=Image.new('RGB',(W,H*1+0),'white'); d=ImageDraw.Draw(im)
    f=ImageFont.load_default()
    try: f=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',13)
    except Exception: pass
    def P(x,y): return ((x-BOARD[0]+2)*S,(BOARD[3]-y+4)*S)
    def R(r,**k):
        a=P(r[0],r[3]); b=P(r[2],r[1]); d.rectangle([a,b],**k)
    def dash(r,c):
        pts=[(r[0],r[1],r[2],r[1]),(r[2],r[1],r[2],r[3]),(r[2],r[3],r[0],r[3]),(r[0],r[3],r[0],r[1])]
        for x0,y0,x1,y1 in pts:
            n=int(max(abs(x1-x0),abs(y1-y0))/0.8)
            for i in range(0,n,2):
                a=(x0+(x1-x0)*i/n,y0+(y1-y0)*i/n); b=(x0+(x1-x0)*min(i+1,n)/n,y0+(y1-y0)*min(i+1,n)/n)
                d.line([P(*a),P(*b)],fill=c,width=2)
    R(BOARD,outline='black',width=3,fill=(246,246,240))
    R((17,-4.5,117,0),fill=(235,225,205)); R((17,53.34,117,57.84),fill=(235,225,205))
    d.text(P(18,-1.5),'analog edge band (top keep-out)',fill='gray',font=f); d.text(P(18,56.6),'far edge band',fill='gray',font=f)
    R((92.16,5.8,98.33,52.6),fill=(220,220,220),outline='gray'); d.text(P(92.4,30),'J605',fill='gray',font=f)
    R((98.5,0.75,116.4,50),fill=(232,232,232),outline='gray'); d.text(P(101,40),'BNC area',fill='gray',font=f)
    R((17.9,4.6,92.3,48.98),outline=(150,150,150))
    for k,rs in NEW.items():
        for r in rs: R(r,fill=tuple(int(0.35*c+0.65*255) for c in COL[k]),outline=COL[k],width=2)
    for k,rs in CUR.items():
        for r in rs: dash(r,(60,60,60))
    # labels
    for k,rs in NEW.items():
        r=max(rs,key=lambda r:(r[2]-r[0])*(r[3]-r[1])); cx=(r[0]+r[2])/2; cy=(r[1]+r[3])/2
        t1=k; t2='now %d  ->  new %d mm2'%(round(area(CUR[k])),round(area(rs))); t3='needed %d (at 55%%)'%NEED[k]
        for i,t in enumerate((t1,t2,t3)):
            x,y=P(cx,cy); d.text((x-len(t)*3.2,y-22+i*16),t,fill=(0,0,0),font=f)
    d.text((10,6),'AFE-2 floor plan, Due mm: proposed blocks (filled) against today (dashed). Board %.0f x %.2f mm.'%(BOARD[2]-BOARD[0],BOARD[3]-BOARD[1]),fill='black',font=f)
    tc=sum(area(v) for v in CUR.values()); tn=sum(area(v) for v in NEW.values()); nd=sum(NEED.values())
    d.text((10,H-18),'sum of blocks: now %d  new %d  needed %d  |  interior (x 17.9-92.3, y 4.55-48.98) %d mm2 | CH2 (mock-up): fits its present outline'%(tc,tn,nd,(92.3-17.9)*(48.98-4.55)),fill='black',font=f)
    im.save('floorplan_current_vs_proposed.png')
    print({k:(round(area(CUR[k]),1),round(area(NEW[k]),1),NEED[k]) for k in CUR}, tc, tn, nd)
