#!/bin/bash
# ch1.sh SEEDBASE OUT : anneal the loose CH1 parts, labels above (U101 above)
cd /work/hardware/afe-proto
export PYTHONPATH=. SLACKD=1.0 LIM302=2.85 LABMODEFILE=whatif/_scratch/labmode_E.json
export SLACKMAP=R302:100,R303:100,C301:100,R304:100,R308:100,R404:5.1,R403:3.8,R402:1.3,R406:4.0,R408:60,R410:60,R407:3.0,R409:2.6
export ABSMAP=C401@3:3.0,C403@12:3.0 IGNORE=R402@1
export ANNEALSUB=C101,C102,C103,C104,C105,R101,R102,R103,R104,R105,R106,R107,R108,R110,R111,R112,R113,D101,TP101 SEEDB=$1 SEEDS=6 ITERS=400000 WDISP=0.1 WALIGN=0.5 PSNAP=0.35 T0=0.4 OUTJ=whatif/_scratch/$2.json
python3 whatif/_scratch/fixpos.py > whatif/_scratch/$2.full 2>&1
grep "anneal seed\|ANNEALSUB\|Traceback\|Error" whatif/_scratch/$2.full > whatif/_scratch/$2.txt
