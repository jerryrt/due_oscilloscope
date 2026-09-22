#!/usr/bin/env bash
# Run from anywhere. The Python driver checks export and analysis results.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
exec python3 "$here/run.py"
