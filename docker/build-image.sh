#!/bin/bash
# Build the pinned image. Local only - there is no registry and nothing
# is pushed, so "same image" across benches is not a claim this makes;
# "same pinned inputs" is, and that is what the Dockerfile carries.
#
# The tag is <xpack>-r<revision>. The compiler is the thing an image is
# chosen for, and the revision says which build of the recipe around it:
# bump DUE_IMAGE_REV by hand whenever a Dockerfile change alters what is
# in the image, and add the row image-revisions.json asks for. The image
# carries its revision and its recipe hash as labels, and run.sh refuses
# one whose recipe is not the tree's.
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
#
# What the container is for, what it will not do, and what a bench
# gives up without it: docs/build-container.md
set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
manifest() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$here/image-revisions.json" "$1"; }
version=${DUE_XPACK_VERSION:-$(manifest xpack)}
rev=${DUE_IMAGE_REV:-$(manifest current)}
tag="due-build:$version-r$rev"
recipe=$("$here/image-id.sh" recipe)

args=(--build-arg "XPACK_VERSION=$version"
      --label "due.image.rev=$rev"
      --label "due.image.recipe=$recipe")
if [ -n "${DUE_XPACK_SHA256:-}" ]; then
    args+=(--build-arg "XPACK_SHA256=$DUE_XPACK_SHA256")
fi

docker build \
    "${args[@]}" \
    --tag "$tag" \
    --file "$here/Dockerfile" \
    "$@" \
    "$here"

docker image inspect "$tag" \
    --format '{{index .RepoTags 0}}  {{.Id}}  {{.Size}} bytes'
echo "recipe  $recipe"
echo "content $("$here/image-id.sh" content "$tag")"
