#!/bin/bash
cd /work/hardware/afe-proto && export PYTHONPATH=. SLACKD=1.0 LIM302=2.85 LABMODEFILE=whatif/_scratch/labmode_E.json SLACKMAP=R302:100,R303:100,C301:100,R304:100,R308:100 GRID=0.25 CHAN=$1
if [ "$1" = "1" ]; then SET=C101,C102,R101,R102,R103,R104,R105,R106,C105; FB=64.4,31.8,92.0,48.7; else SET=C201,C202,R201,R202,R203,R204,R205,R206,C203; FB=64.4,21.4,92.0,33.0; fi
FENCEBOX=$FB CSPSET=$SET KMIN=0 KMAX=0 python3 whatif/_scratch/scan_tmpl.py > whatif/_scratch/tm_$1.txt 2>&1; grep "^VARIANT\|^RESULTS\|^RES \|Error\|Trace\|File" whatif/_scratch/tm_$1.txt | cut -c1-420
