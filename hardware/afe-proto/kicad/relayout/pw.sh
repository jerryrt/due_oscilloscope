#!/bin/bash
# POWER charge-pump placement: pw.sh MODE [SUBSET SEEDBASE OUT]
cd /work/hardware/afe-proto
export PYTHONPATH=. SLACKD=1.0 LIM302=2.85 LABMODEFILE=whatif/_scratch/labmode_E.json
export SLACKMAP=R302:100,R303:100,C301:100,R304:100,R308:100,R404:5.1,R403:3.8,R402:1.3,R406:4.0,R408:60,R410:60,R407:3.0,R409:2.6,C404:100
export ABSMAP=C401@3:3.0,C403@12:3.0 IGNORE=R402@1
NEW='["C405","1","U401","5",3.0],["C406","1","U401","5",6.5],["C409","1","U401","6",4.5],["C410","1","U401","6",9.03],["C407","1","U401","11",4.5],["C408","1","U401","11",6.40]'
OLD='["C405","1","U401","5",12.3],["C406","1","U401","5",12.6],["C409","1","U401","6",6.3],["C410","1","U401","6",9.1],["C407","1","U401","11",6.5],["C408","1","U401","11",6.45]'
KEEP='["C404","1","U401","3",6.1],["C404","1","U401","8",8.15],["C404","1","U401","12",8.0]'
if [ "$1" = "old" ]; then export EXTRACAPS="[$OLD,$KEEP]"; else export EXTRACAPS="[$NEW,$KEEP]"; fi
if [ "$1" = "old" ] || [ "$1" = "new" ]; then EVAL=1 python3 whatif/_scratch/fixpos.py 2>&1 | grep -v nets | grep '^  [A-Z]\|cap C40\|EVALCAP C40' ; exit; fi
export ANNEALSUB=$2 SEEDB=$3 SEEDS=6 ITERS=400000 WDISP=0.1 WALIGN=0.5 PSNAP=0.35 T0=0.4 OUTJ=whatif/_scratch/$4.json
python3 whatif/_scratch/fixpos.py > whatif/_scratch/$4.full 2>&1
grep "anneal seed\|ANNEALSUB\|Traceback\|Error" whatif/_scratch/$4.full > whatif/_scratch/$4.txt
