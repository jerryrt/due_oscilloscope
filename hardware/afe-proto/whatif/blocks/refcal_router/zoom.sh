#!/bin/bash
# zoom.sh out.png x0 y0 x1 y1 : crop of out/r.svg (last render), Due mm, 100 px/mm
cd /home/jerry/EE.Projects/due_oscilloscope_kvm01/hardware/afe-proto/whatif/blocks/refcal_router
python3 - "$@" <<'PY'
import sys,subprocess
o,x0,y0,x1,y1=sys.argv[1],*map(float,sys.argv[2:6])
s=100/ 1.0
px=lambda x:(x-17)*s; py=lambda y:(53.34-y)*s
subprocess.run(['magick','-density','2540','-background','white','out/r.svg','-crop','%dx%d+%d+%d'%((x1-x0)*s,(y1-y0)*s,px(x0),py(y1)),'+repage',o])
PY
