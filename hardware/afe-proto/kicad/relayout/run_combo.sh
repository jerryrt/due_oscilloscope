#!/bin/bash
cd /work/hardware/afe-proto && export PYTHONPATH=.
python3 kicad/relayout/variant_combo.py
bash kicad/relayout/regen_sch.sh 2>&1 | tail -1
bash kicad/relayout/rows.sh combo "TP501:-1.5:0:-"
