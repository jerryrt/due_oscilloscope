#!/bin/bash
cd /work/hardware/afe-proto && export PYTHONPATH=. SLACKD=1.0 LIM302=2.85 LABMODEFILE=whatif/_scratch/labmode_E.json SLACKMAP=R302:100,R303:100,C301:100,R304:100,R308:100 GRID=${GRID:-0.2} FENCEBOX=45.0,4.6,64.2,40.0
CSPSET=${CSPSET:-C501,C502,C503,C504,C505,D501,D502,R505,R509,R511,R512,R513,R514,R517} KMIN=0 KMAX=0 DEADLINE=${DEADLINE:-900} python3 whatif/_scratch/scan_ch1csp.py 2>&1 | grep -v "nets\|Debug\|^critical\|^caps\|^pin6"
