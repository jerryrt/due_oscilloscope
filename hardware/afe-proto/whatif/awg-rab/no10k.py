import itertools
T={'4.7k':4.7e3,'953':953.,'249':249.,'680':680.,'22':22.,'100k':100e3,'330k':330e3,'174k':174e3,'49.9':49.9}
par=lambda *r:1/sum(1/x for x in r)
nets={}
def add(n,v,k):
    key=round(v,2)
    if key not in nets or nets[key][1]>k: nets[key]=(n,k)
names=list(T)
for k in range(1,6):
    for c in itertools.combinations_with_replacement(names,k):
        add('+'.join(c),sum(T[x] for x in c),k)
        if 2<=k<=3: add('|'.join(c),par(*[T[x] for x in c]),k)
for a,b in itertools.combinations_with_replacement(names,2):
    for k in range(1,4):
        for c in itertools.combinations_with_replacement(names,k):
            add(f'({a}|{b})+'+'+'.join(c),par(T[a],T[b])+sum(T[x] for x in c),2+k)
items=list(nets.items())
res=[]
for (ra,(na,ka)),(rb,(nb,kb)) in itertools.product(items,repeat=2):
    if ka+kb>9: continue
    r=rb/ra
    if 1.125<=r<=1.160 and 30.5e3<=ra+rb<=40e3 and 13e3<ra<19e3:
        res.append((ka+kb,abs(r-1.1406),na,round(ra),nb,round(rb),round(r,4),round(ra+rb)))
res.sort()
for x in res[:15]: print(x)
