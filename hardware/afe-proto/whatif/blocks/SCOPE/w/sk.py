import sys, numpy as np
from pcbtools import boardio
b=boardio.read_board(sys.argv[1]); row={int(f):i for i,f in enumerate(b.r_fp)}
bad=[];n=0
for i,r in enumerate(b.fp_ref):
    d=''.join(c for c in r if c.isdigit())
    if len(d)>=3 and d[0] in '12':
        n+=1; k=row.get(i)
        if k is None or not b.r_on_silk[k] or b.r_h[k]<1.0 or b.r_t[k]<0.15-1e-9: bad.append((r, None if k is None else (b.r_on_silk[k], b.r_h[k], b.r_t[k])))
print('scope parts',n,'bad',bad,'words',[t for t in b.t_text if t in('CH1','CH2')],[ (t,h) for t,h in zip(b.t_text,b.t_h) if t in('CH1','CH2')])
