#!/bin/bash
cd /work/hardware/afe-proto
export PYTHONPATH=. SLACKD=1.0 SLACKMAP=R302:100,R303:100,C301:100,R304:100,R305:100,R308:100,C304:100,R404:5.1,R403:3.8,R402:1.3,R406:4.0,R408:60,R410:60,R407:3.0,R409:2.6 ABSMAP=C401@3:3.0,C403@12:3.0 IGNORE=R402@1 LIM302=2.85
export EXTRACAPS='[["C305","1","R307","2",3.5],["C306","1","R307","2",3.5],["R304","1","J301","1",15.0],["R306","1","J301","1",15.0]]'
export OUTJ=whatif/_scratch/$3.json ANNEALSUB=$1 SEEDB=$2 SEEDS=6 ITERS=400000 WDISP=0.1 WALIGN=0.5 PSNAP=0.35 T0=0.4
python3 whatif/_scratch/fixpos.py > whatif/_scratch/$3.full 2>&1
grep "anneal seed\|ANNEALSUB\|Traceback\|Error" whatif/_scratch/$3.full > whatif/_scratch/$3.txt
