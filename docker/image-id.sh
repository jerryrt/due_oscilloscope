#!/bin/bash
# The two hashes that identify a build image, in one place so that
# build-image.sh, run.sh and verify-image.sh cannot disagree about them.
#
#   image-id.sh recipe        hash of the Dockerfile with comment and blank
#                             lines removed: a comment edit changes no
#                             image, any other edit may
#   image-id.sh content IMAGE hash of an image's layer chain and config
#
# The content hash covers what `docker image inspect` prints, so it
# compares within a bench with certainty and across benches only as far
# as their docker agrees. The recipe hash is the cross-bench identity.
set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

case "${1:-}" in
recipe)
    python3 - "$here/Dockerfile" <<'PY'
import hashlib, sys
lines = [l.rstrip() for l in open(sys.argv[1], encoding="utf-8")]
body = "\n".join(l for l in lines if l.strip() and not l.lstrip().startswith("#"))
print(hashlib.sha256(body.encode()).hexdigest())
PY
    ;;
content)
    docker image inspect "${2:?image}" \
        --format '{{range .RootFS.Layers}}{{println .}}{{end}}{{json .Config}}' |
        python3 -c 'import hashlib,sys
print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
    ;;
*)
    echo "usage: image-id.sh recipe | content IMAGE" >&2
    exit 64
    ;;
esac
