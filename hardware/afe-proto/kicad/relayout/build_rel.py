import os, shutil, sys
from pcbtools import build as bd
from pcbtools.boards import v1
w = 'whatif/_scratch/relaid'
os.makedirs(w, exist_ok=True)
shutil.copy('kicad/afe-proto.kicad_sch', w)
nets = bd.schematic_nets(os.path.join(w, 'afe-proto.kicad_sch'))
info = bd.build_board(v1.PARTS, v1.pcb_cfg(), v1.pcb_place(), nets, os.path.join(w, 'afe-proto.kicad_pcb'), legalise_overlaps=False, anchors=v1.ANCHORS)
print(info)
