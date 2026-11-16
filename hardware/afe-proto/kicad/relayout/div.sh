#!/bin/bash
# div.sh CH : CSP for the divider cluster of channel CH (1 or 2), HPWL limits as hard constraints
cd /work/hardware/afe-proto && export PYTHONPATH=. SLACKD=1.0 LIM302=2.85 LABMODEFILE=whatif/_scratch/labmode_E.json SLACKMAP=R302:100,R303:100,C301:100,R304:100,R308:100 GRID=${GRID:-0.25}
if [ "$1" = "1" ]; then SET=C101,C102,R101,R102,R103,R104,R105,R106,C105; FB=64.4,31.8,92.0,48.7; else SET=C201,C202,R201,R202,R203,R204,R205,R206,C203; FB=64.4,21.4,92.0,33.0; fi
FENCEBOX=$FB CSPSET=${CSPSET2:-$SET} UNTIEDW=${UNTIEDW:-0} KMIN=0 KMAX=0 DEADLINE=${DEADLINE:-1500} python3 whatif/_scratch/scan_div.py > /tmp/dv_$1.txt 2>&1; grep -v "Debug" /tmp/dv_$1.txt | grep -v "^critical\|^caps\|^pin6"
