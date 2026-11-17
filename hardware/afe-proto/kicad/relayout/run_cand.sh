#!/bin/bash
# run_cand.sh LABEL SPEC: try a REFCAL spec on top of the live placement (pos_keep is restored afterwards): S run (bus A, kept partial wires) + hops
cd /work/hardware/afe-proto && export PYTHONPATH=. KEEPPARTIAL=1 BUS=A
L=$1; SP=$2
cp whatif/_scratch/pos_keep.json whatif/_scratch/pos_keep.bak; cp whatif/_scratch/rotov_keep2.json whatif/_scratch/rotov_keep2.bak
python3 kicad/relayout/apply_spec.py "$SP"
bash kicad/relayout/base_nopf.sh 2>&1 | grep -v Debug | tail -1
bash kicad/relayout/run_SR.sh S > whatif/_scratch/fr/log_$L.txt 2>&1
cp whatif/_scratch/fr/outS.kicad_pcb whatif/_scratch/fr/outS_$L.kicad_pcb
python3 kicad/relayout/hops.py whatif/_scratch/fr/outS_$L.kicad_pcb > whatif/_scratch/fr/hops_$L.txt 2>&1
cp whatif/_scratch/pos_keep.bak whatif/_scratch/pos_keep.json; cp whatif/_scratch/rotov_keep2.bak whatif/_scratch/rotov_keep2.json
echo "=== CAND $L"
grep -v Debug whatif/_scratch/fr/log_$L.txt | grep "LOCKS\|STAGE1B\|RUN S\|^\[FAIL\|^FAIL\|GAPS" | cut -c1-360
grep "^SUMMARY\|GAPS (spanning" whatif/_scratch/fr/hops_$L.txt
