#!/bin/sh
# usage: run_base.sh BLK TAG XL YB NOFLOW CAP POOL
R=/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock
BLK=$1 XL=$3 YB=$4 POOL=$7 python3 -u $R/ch_tmpl_cands.py $2 > $R/ch_c_$2.txt 2>&1
BLK=$1 HN=8 HO=10 HNP=12 NOFLOW=$5 python3 -u $R/ch_milp.py 1 100 900 $6 '' $2 > $R/ch_d_$2.txt 2>&1
