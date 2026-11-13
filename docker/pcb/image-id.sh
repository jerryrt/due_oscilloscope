#!/bin/bash
# The hashes that identify the PCB image, in one place so build-image.sh,
# run.sh and the tests cannot disagree about them.
#
#   image-id.sh recipe        hash of the Dockerfile (comments and blank
#                             lines removed) and requirements-lock.txt
#   image-id.sh content IMAGE hash of an image's layer chain and config
#   image-id.sh installed IMAGE
#                             hash of what is INSTALLED in it: every dpkg package
#                             and version, and pip freeze. Two builds of the
#                             same recipe do not produce the same layers (apt and
#                             pip write timestamps and caches), so `content`
#                             differs between benches; this one does not, and
#                             "same pinned inputs" is checked by it.
#
# Same meaning as docker/image-id.sh: the recipe is the cross-bench
# identity, the content hash compares within a bench with certainty.
set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

case "${1:-}" in
recipe)
    python3 - "$here/Dockerfile" "$here/requirements-lock.txt" <<'PY'
import hashlib, sys
lines = [l.rstrip() for l in open(sys.argv[1], encoding="utf-8")]
body = "\n".join(l for l in lines if l.strip() and not l.lstrip().startswith("#"))
body += "\n--lock--\n" + open(sys.argv[2], encoding="utf-8").read()
print(hashlib.sha256(body.encode()).hexdigest())
PY
    ;;
content)
    docker image inspect "${2:?image}" \
        --format '{{range .RootFS.Layers}}{{println .}}{{end}}{{json .Config}}' |
        python3 -c 'import hashlib,sys
print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
    ;;
installed)
    docker run --rm --network none --user "$(id -u):$(id -g)" "${2:?image}" bash -c \
        'dpkg-query -W -f "dpkg \${Package} \${Version}\n" | LC_ALL=C sort; python3 -m pip freeze | LC_ALL=C sort | sed "s/^/pip /"' |
        python3 -c 'import hashlib,sys
print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
    ;;
*)
    echo "usage: image-id.sh recipe | content IMAGE | installed IMAGE" >&2
    exit 64
    ;;
esac
