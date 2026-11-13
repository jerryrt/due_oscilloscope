import json,sys
d=json.load(open('drc.json'))
X0,X1,Y0,Y1=(float(v) for v in sys.argv[1:5]) if len(sys.argv)>4 else (60,118,16,52)
def due(i): p=i['pos']; return p['x']-50, 150-p['y']
def inbox(it):
    x,y=due(it); return X0<=x<=X1 and Y0<=y<=Y1
for sect in ('violations','unconnected_items'):
    out={}
    for v in d.get(sect,[]):
        if not any(inbox(i) for i in v['items']): continue
        out.setdefault(v['type'],[]).append(v)
    for t,l in out.items():
        print(sect,t,len(l))
        for v in l[:30]:
            print('   ',v['description'][:60],'|',' ; '.join('%s@(%.2f,%.2f)'%((i['description'][:34],)+due(i)) for i in v['items']))
