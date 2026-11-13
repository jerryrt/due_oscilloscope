import numpy as np
from pcbtools import boardio
b=boardio.read_board('whatif/blocks/SCOPE/w/b1.kicad_pcb')
box=(79.69,33.64,83.79,34.94)
for j in range(len(b.p_x)):
    if b.p_bx0[j]-.25<box[2] and box[0]<b.p_bx1[j]+.25 and b.p_by0[j]-.25<box[3] and box[1]<b.p_by1[j]+.25: print(b.fp_ref[b.p_fp[j]],b.p_pin[j],b.p_bx0[j],b.p_by0[j],b.p_bx1[j],b.p_by1[j])
