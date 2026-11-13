#!/bin/bash
# route.sh NAME  : w_NAME.kicad_pcb (hand board) -> keepouts+DSN -> freerouting -> SES -> NAME_r.kicad_pcb ; one container at a time
set -u
N=$1; PASSES=${2:-20}; TO=${3:-600}
D=/home/jerry/EE.Projects/due_oscilloscope_kvm01; R=hardware/afe-proto/whatif/blocks/refcal_router; RP=whatif/blocks/refcal_router
cd $D
PY="cd /work/hardware/afe-proto && export PYTHONPATH=/work/hardware/afe-proto PCBTOOLS_V1_SOURCE=/work/hardware/afe-proto/kicad"
docker/pcb/run.sh -m 2G -c 2 -t 300 bash -c "$PY && python3 $RP/rprep.py $RP/$N.kicad_pcb $RP/out/${N}_k.kicad_pcb $RP/out/$N.dsn" 2>&1 | grep -v Debug
docker/pcb/run.sh -m 2G -c 2 -t $((TO+120)) docker/pcb/freeroute.sh $R/out/$N.dsn $R/out/$N.ses --passes $PASSES --timeout $TO 2>&1 | tail -15
docker/pcb/run.sh -m 2G -c 2 -t 300 bash -c "$PY && python3 $RP/rpost.py $RP/out/${N}_k.kicad_pcb $RP/out/$N.ses $RP/out/${N}_r.kicad_pcb" 2>&1 | grep -v Debug
