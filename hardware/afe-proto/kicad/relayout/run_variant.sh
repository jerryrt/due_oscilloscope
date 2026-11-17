#!/bin/bash
# run_variant.sh VARIANT: apply the R208 variant to design/floorplan, regenerate the schematic, then search the candidates
cd /work/hardware/afe-proto && export PYTHONPATH=.
python3 kicad/relayout/variant_r208.py $1
bash kicad/relayout/regen_sch.sh 2>&1 | tail -2
bash kicad/relayout/search.sh whatif/_scratch/cand_r208.txt 80,18,95,34 "/CH2_IN,/VREF_P,/VREF_T,/VREF,/CH2_OUT,/SC_VCC,/+3V3A,/VNEG"
