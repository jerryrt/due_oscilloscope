#!/bin/bash
cd /work/hardware/afe-proto && export PYTHONPATH=. SLACKD=1.0 LIM302=2.85 LABMODEFILE=${LABMODEFILE:-whatif/_scratch/labmode_E.json} SLACKMAP=R302:100,R303:100,C301:100,R304:100,R308:100,R404:5.1,R403:3.8,R402:1.3,R406:4.0,R408:60,R410:60,R407:3.0,R409:2.6 ABSMAP=C401@3:3.0,C403@12:3.0 IGNORE=R402@1 GRID=${GRID:-0.2}
KMIN=0 KMAX=0 DEADLINE=${DEADLINE:-1500} python3 whatif/_scratch/scan_ch1csp.py 2>&1 | grep -v "nets\|Debug\|^critical\|^caps\|^pin6"
