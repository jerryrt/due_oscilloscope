"""Run under the venv python: print the OLD lr_check loader's counts for one board as JSON (golden capture helper)."""
import json, math, os, sys
import os
V2 = os.environ['OLD_TOOLS_DIR']
sys.path.insert(0, V2)
sys.dont_write_bytecode = True
import lr_check as L  # noqa: E402
path = sys.argv[1]
m = L.load(path)
classes = {}
for t in m.board.GetTracks():
    classes[t.GetClass()] = classes.get(t.GetClass(), 0) + 1
netlen = {}
for s in m.segs:
    k = f'{s[0]}|{s[1]}'
    netlen[k] = netlen.get(k, 0.0) + math.dist(s[2], s[3])
out = dict(n_segs=len(m.segs), n_vias=len(m.vias), n_fps=len(m.fps), n_pads=len(m.pads),
           n_zones=len(m.zones), n_silk=len(m.silk), copper_layers=m.layers, track_classes=classes,
           netlen_by_net_layer={k: round(v, 6) for k, v in sorted(netlen.items())},
           total_len=round(sum(netlen.values()), 6),
           pads_per_net={}, )
pn = {}
for p in m.pads.values():
    pn[p['net']] = pn.get(p['net'], 0) + 1
out['pads_per_net'] = dict(sorted(pn.items()))
print(json.dumps(out))
