cd /work/hardware/afe-proto
PCBTOOLS_V1_SOURCE=kicad python3 -c '
import subprocess
from pcbtools import schematic as sch
from pcbtools.boards import v1
sch.write_all(v1.PARTS, v1.sch_cfg(), "kicad")
subprocess.run(["kicad-cli","sch","upgrade","kicad/afe-proto.kicad_sch"],capture_output=True,check=True)
print(len(v1.PARTS))
' 2>&1 | grep -v Debug
sh bom/v1/make_bom.sh 2>&1 | tail -2
