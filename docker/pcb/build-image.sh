#!/bin/bash
# Build the pinned PCB/simulation image. Local only, like docker/build-image.sh:
# no registry, so "same pinned inputs" is the claim, not "same image".
#
#     docker/pcb/build-image.sh                    # the image of record
#     DUE_PCB_WITHOUT_NGSPICE=1 docker/pcb/build-image.sh
#                                                  # the gate's control image (no ngspice)
#     DUE_PCB_WITHOUT_FREEROUTING=1 docker/pcb/build-image.sh
#                                                  # the control for the router (no Java, no jar)
#
# The tag is pcb-tools:<kicad>-r<revision>. Bump "current" in
# image-revisions.json whenever a change to the Dockerfile or the lock
# alters what is in the image. The control image carries the tag suffix
# -no-ngspice and is never what run.sh uses by default.
set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
manifest() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$here/image-revisions.json" "$1"; }
kicad=$(manifest kicad)
rev=${DUE_PCB_IMAGE_REV:-$(manifest current)}
tag="pcb-tools:$kicad-r$rev"
args=()
if [ "${DUE_PCB_WITHOUT_NGSPICE:-0}" = 1 ]; then
    tag="$tag-no-ngspice"
    args+=(--build-arg WITH_NGSPICE=0)
fi
if [ "${DUE_PCB_WITHOUT_FREEROUTING:-0}" = 1 ]; then
    tag="$tag-no-freerouting"
    args+=(--build-arg WITH_FREEROUTING=0)
fi
recipe=$("$here/image-id.sh" recipe)

docker build \
    "${args[@]}" \
    --label "due.image.rev=$rev" \
    --label "due.image.recipe=$recipe" \
    --tag "$tag" \
    --file "$here/Dockerfile" \
    "$@" \
    "$here"

docker image inspect "$tag" --format '{{index .RepoTags 0}}  {{.Id}}  {{.Size}} bytes'
echo "recipe  $recipe"
echo "content $("$here/image-id.sh" content "$tag")"
echo "installed $("$here/image-id.sh" installed "$tag")"
