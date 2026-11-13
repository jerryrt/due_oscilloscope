import sys, numpy as np
from pcbtools import boardio, rules
from pcbtools.boards import v1 as cfg
b = boardio.read_board(sys.argv[1])
pt = rules.pads(b); gnd = rules.nid(b, cfg.GND)
sel = sorted([j for j in range(len(pt.keys)) if pt.net[j]==gnd and b.p_smd[pt.rows[j]]], key=lambda j: pt.keys[j])
gv = np.column_stack([b.v_x,b.v_y])[b.v_net==gnd]; used=np.zeros(len(gv),bool); nov=[]
for j in sel:
    r=pt.rows[j]; d=np.hypot(gv[:,0]-b.p_x[r],gv[:,1]-b.p_y[r]); d=np.where(used,np.inf,d); i=int(np.argmin(d)) if len(d) else -1
    if i>=0 and d[i]<=3.0: used[i]=True; 
    else: nov.append('%s.%s'%pt.keys[j])
mine=[n for n in nov if n[0] in 'CRDUT' and n[1] in '12' and len(n.split('.')[0])==4]
print('GND pads w/o via, mine:', mine, ' total', len(nov))
for ch in cfg.CHANNELS:
    outl=sum(rules.length_of(b,n) for n in ch['out_nets']); hiz=sum(rules.length_of(b,n) for n in ch['hiz_nets'])
    print(ch['name'],'out %.1f hiz %.1f'%(outl,hiz), {n:round(rules.length_of(b,n),1) for n in ch['out_nets']+ch['hiz_nets']})
for r in (rules.lr2,rules.lr3,rules.lr4,rules.lr12):
    try:
        x=r(b,cfg); print(r.__name__, x.ok, x.detail[:300])
    except Exception as ex: print(r.__name__,'err',ex)
