"""Print the OLD lr_check loader's counts for one board as JSON (golden capture helper; run in a child process).

    python old_counts.py BOARD.kicad_pcb        (OLD_TOOLS_DIR, default: the frozen tools in the fixture folder)
"""
import json
import math
import os
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    sys.dont_write_bytecode = True
    sys.path.insert(0, os.environ.get('OLD_TOOLS_DIR') or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'fixtures', 'v2-8a1f7ac', 'tools'))
    import lr_check as L
    m = L.load(argv[0])
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
               total_len=round(sum(netlen.values()), 6), pads_per_net={})
    pn = {}
    for p in m.pads.values():
        pn[p['net']] = pn.get(p['net'], 0) + 1
    out['pads_per_net'] = dict(sorted(pn.items()))
    print(json.dumps(out))


if __name__ == '__main__':
    main()
