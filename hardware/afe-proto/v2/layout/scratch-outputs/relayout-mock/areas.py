import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
import json, numpy as np
from scipy import ndimage
P=json.load(open('parts_cur.json'))
def cyd(p):
    c=p['cy']; return (c[0]-50,150-c[3],c[2]-50,150-c[1])
RECTS={'POWER': [(17.9, 4.6, 43.6, 26.0)],'REFCAL': [(44.2, 4.6, 64.4, 27.8), (64.6, 18.6, 70.2, 26.0)],'CH1': [(63.9, 33.0, 93.0, 50.0), (60.4, 34.6, 64.0, 36.8)],'CH2': [(69.0, 19.75, 93.0, 32.9)],'AWG': [(70.4, 4.55, 92.3, 19.25)]}
blk={'1':'CH1','2':'CH2','3':'AWG','4':'POWER','5':'REFCAL'}
tot={}
for k,v in RECTS.items(): print(k,'rect area',round(sum((r[2]-r[0])*(r[3]-r[1]) for r in v),1))
need={}
for p in P:
    r=p['ref']
    if r[0] in 'JM' : continue
    b='CH1' if r=='U101' else blk[r[-3] if r[0]!='B' and r[0]!='T' else r[-3]]
    c=cyd(p); a=(c[2]-c[0])*(c[3]-c[1]); n=len(r); L=0.95*n
    z=(L+0.6)*(1.2+0.6)
    need.setdefault(b,[0,0,0]); need[b][0]+=a; need[b][1]+=z; need[b][2]+=1
for b,(a,z,n) in need.items(): print(b,n,'parts courtyard',round(a),'label zones',round(z),'sum',round(a+z))
print('total',round(sum(a+z for a,z,n in need.values())))
