#!/bin/bash
cd /work/hardware/afe-proto && export PYTHONPATH=.
bash whatif/_scratch/run_rel.sh 300 > whatif/_scratch/ch1_sr.txt 2>&1
python3 -c "
from pcbtools import boardio, silkread
b=boardio.read_board('whatif/_scratch/relaid/afe-proto.kicad_pcb'); txt=open('whatif/_scratch/relaid/afe-proto.kicad_pcb').read()
f=silkread.findings(b, {'J101':'CH1 IN','J201':'CH2 IN','J301':'AWG OUT'}, edge_headers=('J601','J602','J603','J604','J605','J606','J607'), silk=silkread.read_silk(txt), east_end={'U301','U101'}, beside={'R302','R303','C301','R305','C302','C405','C401','C409','C402'})
print('ALL silkread', len(f)); [print(x[:200]) for x in f]"
echo '--- align (CH1 refs)'; python3 whatif/_scratch/ali.py whatif/_scratch/relaid/afe-proto.kicad_pcb | grep -E '[A-Z]2[0-9][0-9]'
echo '--- LR'; python3 -m pcbtools.check whatif/_scratch/relaid/afe-proto.kicad_pcb --config v1 2>&1 | grep 'LR-4\|LR-5\|LR-12\|LR-7\|LR-9'
