import json,sys
d=json.load(open(sys.argv[1]))
for v in d.get('unconnected_items',[]):
    print('UNCON', ' | '.join(i.get('description','')[:60]+' %.2f,%.2f'%(i['pos']['x']-50,150-i['pos']['y']) for i in v['items']))
for v in d['violations']:
    if v['type'] not in ('courtyards_overlap',) or 'J607' not in str(v):
        print(v['type'], ' | '.join(i.get('description','')[:60]+' %.2f,%.2f'%(i['pos']['x']-50,150-i['pos']['y']) for i in v['items']))
