#!/bin/bash
# s2loop.sh CH N : try the first N template translations of channel CH with the remaining three parts as a CSP
cd /work/hardware/afe-proto && export PYTHONPATH=.
CH=$1; N=$2
if [ "$CH" = "1" ]; then REST=R101,R102,C105; else REST=R201,R202,C203; fi
for k in $(seq 0 $((N-1))); do
  python3 whatif/_scratch/stage2.py $CH $k 2>&1 | grep applied
  echo "TRY $k: $(CSPSET2=$REST WINC=84,41 UNTIEDW=0 DEADLINE=90 bash whatif/_scratch/div.sh $CH 2>&1 | grep 'BESIDE_BUDGET\|OVER' | head -1)"
  CSPSET2=$REST DEADLINE=90 bash whatif/_scratch/div.sh $CH 2>&1 | grep '^SOL' | head -1 | sed 's/, /,/g' | sed "s/^/SOL $k /"
done
