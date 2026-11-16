#!/bin/bash
cd /work/hardware/afe-proto && export PYTHONPATH=. SLACKD=1.0 LIM302=2.85 SLACKMAP=R302:100,R303:100,C301:100
export GRID=${GRID:-0.1} GT=${GT:-0.2} HW=${HW:-1.4} TMAX=${TMAX:-7.5}
python3 whatif/_scratch/scan_joint.py 2>&1 | grep -v "nets\|Debug"
