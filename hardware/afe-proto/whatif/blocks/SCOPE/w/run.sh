#!/bin/bash
cd /home/jerry/EE.Projects/due_oscilloscope_kvm01
s=$1; shift
case $s in *.sh) I=bash;; *) I=python3;; esac
docker/pcb/run.sh -m 3G -c 2 -t 600 bash -c "cd /work/hardware/afe-proto && PYTHONPATH=/work/hardware/afe-proto $I whatif/blocks/SCOPE/w/$s $*"
