#!/usr/bin/env bash
#
# Shim. tools/flash.py is the implementation and works on every host;
# this keeps the documented command and existing muscle memory working.
#
# Picks the repo venv, the same way CMakeLists.txt does, because
# flash.py needs pyserial and the system interpreter does not have it -
# requirements-dev.txt is explicit that the tools under host/ must run
# from the system interpreter during bring-up, and flash.py is the one
# that cannot. Falling back to python3 gives a clearer failure than a
# bare ImportError, but it is a fallback and not the intent.
#
# Override with PYTHON= for an interpreter of your own.
#
# usage: tools/flash.sh [BIN] [PORT]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/.." && pwd)"

if [ -z "${PYTHON:-}" ]; then
    for cand in "$repo/.venv/bin/python" "$repo/.venv/Scripts/python.exe"; do
        if [ -x "$cand" ]; then
            PYTHON="$cand"
            break
        fi
    done
fi
PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c 'import serial' 2>/dev/null; then
    echo "tools/flash.sh: $PYTHON has no pyserial." >&2
    echo "  build the venv:  python3 -m venv .venv &&" \
         ".venv/bin/pip install -r requirements-dev.txt" >&2
    echo "  or point at one: PYTHON=/path/to/python tools/flash.sh" >&2
    exit 1
fi

args=()
[ -n "${1:-}" ] && args+=(--bin "$1")
[ -n "${2:-}" ] && args+=(--port "$2")
exec "$PYTHON" "$here/flash.py" "${args[@]}"
