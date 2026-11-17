"""python3 netdiff_board.py BOARD   (in the image, cwd hardware/afe-proto): hand/netdiff.py against v2/kicad/design.py for any board: the pads are dumped from the board, netdiff.py runs on them unchanged."""
import sys, json, runpy, os
sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew
b = pcbnew.LoadBoard(sys.argv[1]); mm = pcbnew.ToMM; out = []
for f in b.GetFootprints():
    for p in f.Pads():
        bb = p.GetBoundingBox()
        out.append(dict(ref=f.GetReference(), pin=p.GetNumber(), net=p.GetNetname(), x=mm(p.GetPosition().x) - 50, y=150 - mm(p.GetPosition().y), bb=[mm(bb.GetX()) - 50, 150 - mm(bb.GetBottom()), mm(bb.GetRight()) - 50, 150 - mm(bb.GetY())], smd=True))
tmp = '/tmp/pads_nd.json'; json.dump(out, open(tmp, 'w'))
src = open('v2/layout/scratch-outputs/relayout-mock/hand/netdiff.py').read().replace("'v2/layout/scratch-outputs/relayout-mock/hand/pads.json'", repr(tmp))
exec(compile(src, 'netdiff.py', 'exec'), {'__name__': '__main__'})
