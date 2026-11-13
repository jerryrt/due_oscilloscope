#!/bin/sh
# Regenerate version 1's parts streams and bom.md with the version 2 engine. Run from hardware/afe-proto, inside the image:
#   docker/pcb/run.sh sh hardware/afe-proto/bom/v1/make_bom.sh        (from the worktree root)
set -e
cd "$(dirname "$0")/../.."
python3 -I bom/v1/make_parts.py
python3 -I v2/bom/bom.py --root bom/v1/data --model streams --name v1 --md bom/v1/bom.md \
  --path scope=bom/v1/data/scope_parts.csv --path awg=bom/v1/data/awg_parts.csv --path powercal=bom/v1/data/powercal_parts.csv \
  --path basic=v2/jlc-basic.csv
