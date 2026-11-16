import json, sys, re, ast, shutil
ch = sys.argv[1]; k = int(sys.argv[2])
lines = [l for l in open(f'whatif/_scratch/tm_{ch}.txt') if l.startswith('RES ')]
l = lines[k]
m = re.match(r"RES (\S+) (\S+) (\S+) (\S+) (\[.*\])", l)
spec = ast.literal_eval(m.group(5))
pos = json.load(open('whatif/_scratch/relay_pos_base.json')); rotov = json.load(open('whatif/_scratch/rotov_base.json')); lab = json.load(open('whatif/_scratch/labmode_base.json'))
rot0 = json.load(open('whatif/_scratch/rot.json'))
for ref, x, y, d, mode in spec:
    pos[ref] = [x, y]
    if d: rotov[ref] = int((rotov.get(ref, rot0[ref]) + d) % 360)
    lab[ref] = 'W' if mode == 2 else 'E'
json.dump(pos, open('whatif/_scratch/relay_pos.json', 'w')); json.dump(rotov, open('whatif/_scratch/rotov.json', 'w'))
for f in ('labmode.json', 'labmode_E.json', 'labmode_W.json'): json.dump(lab, open('whatif/_scratch/' + f, 'w'))
print('applied', ch, k, [(r[0], r[1], r[2]) for r in spec][:2])
