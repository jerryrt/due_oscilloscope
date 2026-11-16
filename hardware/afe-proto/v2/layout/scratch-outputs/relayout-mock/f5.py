import json
D = json.load(open('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/dump_all.json'))
P = {p['ref']: p for p in D['parts']}
print('J601.5', [q['c'] for q in P['J601']['pads'] if q['n'] == '5'])
