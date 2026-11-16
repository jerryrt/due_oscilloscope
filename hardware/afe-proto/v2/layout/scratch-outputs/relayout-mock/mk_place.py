import json, sys
st = json.load(open(sys.argv[1]))['st']
d = json.load(open('pads_cur.json'))
old = [p['c'] for p in d['pads'] if p['ref'] in st]
P={p['ref']:p for p in json.load(open('parts_cur.json'))}
rel={}
lab={r:[P[r]['x']-50,150-P[r]['y']] for r in ('BR501','BR504')}
for r in list(st)+list(lab):
    p=P[r]; c=p['cy']; x=p['x']-50; y=150-p['y']; rel[r]=[c[0]-50-x,150-c[3]-y,c[2]-50-x,150-c[1]-y]
json.dump(dict(st=st, old_pads=old, rel=rel, lab_only=lab), open('place.json', 'w'))
print(len(st), len(old))
