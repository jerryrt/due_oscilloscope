#!/bin/bash
# Build the pinned image. Local only - there is no registry and nothing
# is pushed, so "same image" across benches is not a claim this makes;
# "same pinned inputs" is, and that is what the Dockerfile carries.
#
# The tag names the compiler, because the compiler is the thing an image
# is chosen for. A second xPack release is a second tag beside this one,
# not a rebuild of it.
#
# ANOTHER XPACK RELEASE MOVES TWO VALUES, NEVER ONE. The tarball and its
# sha256 travel together; xPack publishes the digest beside the asset as
# `<name>.tar.gz.sha`. Change the defaults in the Dockerfile, or pass
# both here:
#
#     DUE_XPACK_VERSION=14.2.1-1.1 \
#     DUE_XPACK_SHA256=ed8c...90a6 docker/build-image.sh
#
# Passing only the version is not a shortcut - the checksum then fails
# and the build stops, which is the pin doing its job.
set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
version=${DUE_XPACK_VERSION:-15.2.1-1.1}

args=(--build-arg "XPACK_VERSION=$version")
if [ -n "${DUE_XPACK_SHA256:-}" ]; then
    args+=(--build-arg "XPACK_SHA256=$DUE_XPACK_SHA256")
fi

docker build \
    "${args[@]}" \
    --tag "due-build:$version" \
    --file "$here/Dockerfile" \
    "$@" \
    "$here"

docker image inspect "due-build:$version" \
    --format '{{index .RepoTags 0}}  {{.Id}}  {{.Size}} bytes'
