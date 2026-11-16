import os, json; os.chdir(os.path.dirname(os.path.abspath(__file__)))
P=json.load(open('parts_mock.json'))
bx=[]
for p in P:
    c=p['cy']; bx.append((c[0]-50,150-c[3],c[2]-50,150-c[1]))
    if p['ink']: i=p['ink']; bx.append((i[0]-50,150-i[3],i[2]-50,150-i[1]))
w,h=2.7,1.0
best=[]
x=69.3
while x<92:
    y=20.1
    while y<32.4:
        b=(x,y,x+w,y+h)
        if all(min(b[2],c[2])-max(b[0],c[0])+0.5<=0 or min(b[3],c[3])-max(b[1],c[1])+0.5<=0 for c in bx):
            best.append((x,y))
        y+=0.1
    x+=0.1
print(len(best), best[:5], best[-5:])
