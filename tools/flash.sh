#!/usr/bin/env bash
# Shim. tools/flash.py is the implementation and works on every host;
# this keeps the documented command and existing muscle memory working.
#
# usage: tools/flash.sh [BIN] [PORT]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
args=()
[ -n "${1:-}" ] && args+=(--bin "$1")
[ -n "${2:-}" ] && args+=(--port "$2")
exec "${PYTHON:-python3}" "$here/flash.py" "${args[@]}"
