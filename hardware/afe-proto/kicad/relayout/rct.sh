#!/bin/bash
cd /work/hardware/afe-proto && export PYTHONPATH=. SLACKD=1.0 LIM302=2.85 LABMODEFILE=whatif/_scratch/labmode_E.json SLACKMAP=R302:100,R303:100,C301:100,R304:100,R308:100
python3 whatif/_scratch/refcal_ties.py 2>&1 | grep "^TIE\|^SPAN\|^REFCAL\|Error\|Trace"
