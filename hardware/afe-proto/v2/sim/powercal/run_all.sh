#!/bin/sh
# regenerate every result and report.md (about 20 s; lm_tran.py is separate: 3 to 10 minutes per case, python3 -I lm_tran.py <case>...)
cd "$(dirname "$0")" && for s in power refladder sense sc7 coupling wires parts pw1_awg; do python3 -I $s.py > /dev/null || exit 1; done && python3 -I report.py
