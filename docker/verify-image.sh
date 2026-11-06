#!/bin/bash
# Does the recipe still build, and does it build the same firmware?
#
#   docker/verify-image.sh [REFERENCE_IMAGE]
#
# Builds the Dockerfile from nothing under the tag due-build:<xpack>-rverify,
# then builds all three tracks with it and with the reference (default: the
# current revision in image-revisions.json) and compares the firmware
# bytes. Byte-identical firmware is the property the image exists to give;
# an image hash is reported but decides nothing, because two builds of one
# recipe need not agree on layer hashes.
#
# Run it monthly: the inputs that expire - the live archive the trust
# roots are fetched from, the snapshot, the compiler's release URL - fail
# here, weeks before anyone needs a rebuild.
#
# PASS, FAIL (bytes differ) or DID NOT RUN (the build itself failed).
set -uo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
manifest() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$here/image-revisions.json" "$1"; }
xpack=$(manifest xpack)
ref=${1:-due-build:$xpack-r$(manifest current)}
cand=due-build:$xpack-rverify
bins=(build/track_b_bringup.bin build-a/track_a_bringup.bin build-c/track_c_bringup.bin)

if ! docker image inspect "$ref" >/dev/null 2>&1; then
    echo "DID NOT RUN: reference image $ref is absent" >&2
    exit 2
fi
if ! DUE_IMAGE_REV=verify "$here/build-image.sh" --no-cache; then
    echo "DID NOT RUN: the from-scratch build failed" >&2
    exit 2
fi

sums() {
    DUE_BUILD_IMAGE=$1 "$here/run.sh" docker/build-firmware.sh >/dev/null || return 1
    for b in "${bins[@]}"; do sha256sum "$here/out/$b" | cut -d' ' -f1; done
}
a=$(sums "$ref") || { echo "DID NOT RUN: firmware build failed on $ref" >&2; exit 2; }
b=$(sums "$cand") || { echo "DID NOT RUN: firmware build failed on $cand" >&2; exit 2; }

echo "reference  content $("$here/image-id.sh" content "$ref")"
echo "candidate  content $("$here/image-id.sh" content "$cand")"
if [ "$a" = "$b" ] && [ "$(echo "$a" | wc -l)" -eq "${#bins[@]}" ]; then
    echo "PASS: ${#bins[@]} firmware images byte-identical"
else
    echo "FAIL: firmware differs"
    paste <(echo "$a") <(echo "$b")
    exit 1
fi
