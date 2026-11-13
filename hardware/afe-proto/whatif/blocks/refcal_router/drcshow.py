import json,sys
d=json.load(open(sys.argv[1])); kinds=sys.argv[2:]
for v in d['violations']:
    if not kinds or v['type'] in kinds:
        print(v['type'], ' | '.join((i.get('description','')+' '+str(round(i['pos']['x']-50,2))+','+str(round(150-i['pos']['y'],2))) for i in v['items']))
