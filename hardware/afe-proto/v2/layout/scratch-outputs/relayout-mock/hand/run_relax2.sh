#!/bin/sh
# usage: run_relax2.sh TAG POOLTAG GENRELAX MODELRELAX NOFLOW CAP [skipgen]
R=/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock
[ -z "$7" ] && BLK=CH2 XL=83.1 YB=26.6 POOL=700 RELAX=$3 python3 -u $R/ch_tmpl_cands.py $2 > $R/ch_c_$2.txt 2>&1
BLK=CH2 HN=8 HO=10 HNP=12 NOFLOW=$5 RELAXM=$4 python3 -u $R/ch_milp.py 1 100 900 $6 '' $2 > $R/ch_d_$1.txt 2>&1
