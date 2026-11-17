#!/bin/bash
cd /work/hardware/afe-proto && export PYTHONPATH=.
python3 kicad/relayout/variant_p33.py
bash kicad/relayout/regen_sch.sh 2>&1 | tail -1
printf 'p33|\n' > whatif/_scratch/cand_p33.txt
bash kicad/relayout/search.sh whatif/_scratch/cand_p33.txt 44,15,66,36 "/SDA1,/SCL1,/SNS_TAP,/SNS_B,/TAP3,/AWG_S,/P33_R,/P33_C,/VREF,/+3V3A,/VNEG,/SNS_TI,/SNS_BI,/SCL1_A,/SDA1_A,/AREF"
bash kicad/relayout/rows.sh p33full ""
