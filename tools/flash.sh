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
BIN="${1:-}"
PORT="${2:-}"

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

# Pass only what was given, without an empty-array expansion: bash 3.2 -
# which is what /bin/bash still is on macOS - treats "${args[@]}" as an
# unbound variable under `set -u` when the array is empty, so calling
# this with no arguments aborted before running anything. It survived
# here only because /usr/bin/env finds a newer bash first.
exec "$PYTHON" "$here/flash.py" ${BIN:+--bin "$BIN"} ${PORT:+--port "$PORT"}
