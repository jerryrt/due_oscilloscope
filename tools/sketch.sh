#!/usr/bin/env bash
#
# Shim. tools/sketch.py is the implementation and works on every host;
# this keeps the documented command working. It is still the only place
# that knows Track A's two build properties - see sketch.py for why each
# one is silent when missing.
#
# Picks the repo venv, because sketch.py needs pyserial to discover the
# upload port. Override with PYTHON=.
#
# usage: tools/sketch.sh [compile|upload] [PORT]
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"

if [ -z "${PYTHON:-}" ]; then
    for cand in "$repo/.venv/bin/python" "$repo/.venv/Scripts/python.exe"; do
        if [ -x "$cand" ]; then
            PYTHON="$cand"
            break
        fi
    done
fi
exec "${PYTHON:-python3}" "$here/sketch.py" "$@"
